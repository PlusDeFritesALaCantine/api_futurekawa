"""Triggering of the alert summary e-mail (specification III.4).

Rules: a summary is sent to the operations manager of the country concerned if
there is at least one open alert whose e-mail has not been sent yet:
  - a batch exceeds the shelf life duration configured for its country;
  - the latest temperature/humidity reading of a warehouse is classified "low"
    or "critical" on the quality scale (excellent/good/fair/low/critical,
    cf. app/services/alerts.py) — the excellent/good/fair tiers never trigger an
    e-mail.

Unlike a notification per individual alert, only the LATEST reading of each
warehouse is considered for the thresholds — alerts reflect the current state
("the same info every X time"), not the full history.

Check frequency: called when the API starts then every
ALERT_CHECK_INTERVAL_SECONDS seconds (60 by default, see app/main.py), and
manually via POST /alerts/notify.

Deduplication: carried by the `alerts.emailed_at` column, not by an in-memory
dictionary. As long as no new alert appears, no new summary goes out; and,
unlike the previous version, the state survives an API restart — a restart no
longer triggers a second send for alerts already notified.

The recipient and the e-mail toggle come from the `countries` table (editable
from the site); MANAGER_EMAILS is only a fallback for when no settings exist yet.
"""

import logging

from app.database import SessionLocal
from app.models import Batch
from app.services import alert_lifecycle, parameters
from app.services.alerts import (
    latest_measures_per_warehouse, evaluate_measure, compute_alerts,
)
from app.services.email import (
    MANAGER_EMAILS, SMTP_HOST, SMTP_PORT, build_summary_email, send_email,
)

logger = logging.getLogger(__name__)


def check_and_notify(country_list: list[str] | None = None) -> int:
    """Checks the alert state per country and sends a summary if needed.

    If country_list is not provided, checks every country present in the database
    (works both in dev — a single shared backend for 3 countries — and in the
    target architecture — one backend per country, which only sees the batches of
    its own country).

    Returns the number of summaries actually sent.
    """
    db = SessionLocal()
    sent = 0
    try:
        if country_list is None:
            country_list = [row[0] for row in db.query(Batch.country).distinct().all()]

        for country in country_list:
            params = parameters.get_from_db(db, country)
            if not params.alerts_enabled:
                continue

            recipient = params.manager_email or MANAGER_EMAILS.get(country)
            if not recipient:
                logger.warning("No manager e-mail configured for country %s", country)
                continue

            # First aligns the alerts table with the current state: it is that
            # table which then says what is left to notify.
            alert_lifecycle.sync(db, country)
            to_notify = alert_lifecycle.alerts_pending_email(db, country)
            if not to_notify:
                continue

            problematic_batches, _ = compute_alerts(db, country)
            threshold_anomalies = _latest_measure_anomalies(db, country)

            subject, body = build_summary_email(country, problematic_batches, threshold_anomalies)
            result = _send_if_possible(recipient, subject, body, country)
            if result is None:
                return sent  # SMTP server unreachable: we will retry next cycle.
            if result:
                sent += 1
                alert_lifecycle.mark_emailed(db, to_notify)
    finally:
        db.close()
    return sent


def _latest_measure_anomalies(db, country: str) -> list[tuple]:
    """Anomalies (direction + severity) of the LATEST reading of each warehouse in the country."""
    warehouses = {b.warehouse_id for b in db.query(Batch).filter(Batch.country == country).all()}
    result = []
    for measure in latest_measures_per_warehouse(db, warehouses):
        for anomaly in evaluate_measure(measure.temperature, measure.humidity, country):
            result.append((measure, anomaly))
    return result


def _send_if_possible(recipient: str, subject: str, body: str, country: str) -> bool | None:
    """Sends the summary. Returns True (sent), False (one-off failure) or None
    (SMTP server unreachable — no point retrying the other countries this cycle)."""
    try:
        send_email(recipient, subject, body)
    except OSError as exc:
        logger.warning(
            "SMTP server unreachable (%s:%s) — summary pending, retried next cycle: %s",
            SMTP_HOST, SMTP_PORT, exc,
        )
        return None
    except Exception:
        logger.exception("Failed to send the alert summary for %s", country)
        return False
    logger.info("Alert summary sent for %s to %s", country, recipient)
    return True
