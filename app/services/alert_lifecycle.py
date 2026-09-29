"""Lifecycle of persisted alerts: opening, acknowledgement, resolution.

The anomaly computation stays in services/alerts.py (pure functions, testable
without a database). This module bridges that computation, redone on every cycle,
and the `alerts` table that keeps a trace:

  current computed state  ->  sync()  ->  alerts table

`sync()` is idempotent. On each call it compares the observed anomalies to the
open alerts in the database:

  - anomaly present, no open alert  -> opening
  - anomaly present, alert already open -> update (severity, message)
  - open alert, anomaly gone        -> automatic resolution

The uniqueness of an open alert is guaranteed by the partial unique index on
`dedup_key` (cf. models.Alert), not by an in-memory structure: two processes, or
a restart mid-cycle, cannot create a duplicate.

Acknowledging is not resolving. A human acknowledges from the site to say "I'm
on it"; the alert stays open and keeps being counted as long as the physical
anomaly is still present in the readings.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models import Alert
from app.services.alerts import compute_alerts

logger = logging.getLogger(__name__)

STATUSES = ("open", "acknowledged", "resolved")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def measure_key(alert_type: str, warehouse_id: str) -> str:
    return f"{alert_type}:{warehouse_id}"


def expiration_key(warehouse_id: str, batch_id: str) -> str:
    return f"expiration:{warehouse_id}:{batch_id}"


def _expected(db, country: str | None) -> dict[str, dict]:
    """The alerts that *should* be open given the current state.

    One entry per (anomaly, warehouse) pair: a warehouse whose temperature and
    humidity both drift produces two distinct alerts, so that one can be resolved
    without closing the other.
    """
    from app.services.alerts import evaluate_measure

    problematic_batches, _ = compute_alerts(db, country)
    expected: dict[str, dict] = {}

    for batch, reason in problematic_batches:
        key = expiration_key(batch.warehouse_id, batch.id)
        expected[key] = {
            "dedup_key": key,
            "country": batch.country,
            "warehouse_id": batch.warehouse_id,
            "batch_id": batch.id,
            "measure_id": None,
            "type": "expiration",
            "severity": "critical",
            "message": reason[:255],
        }

    from app.models import Batch
    from app.services.alerts import latest_measures_per_warehouse

    all_batches = db.query(Batch).all()
    country_by_warehouse = {b.warehouse_id: b.country for b in all_batches}
    warehouses = (
        {b.warehouse_id for b in all_batches if b.country == country} if country else None
    )

    for measure in latest_measures_per_warehouse(db, warehouses):
        measure_country = country_by_warehouse.get(measure.warehouse_id)
        if measure_country is None:
            # Warehouse with no attached batch (sensor sessions): no known
            # country, we don't guess — the anomaly stays visible in the
            # computed /alerts.
            continue
        for anomaly in evaluate_measure(measure.temperature, measure.humidity, measure_country):
            key = measure_key(anomaly["type"], measure.warehouse_id)
            expected[key] = {
                "dedup_key": key,
                "country": measure_country,
                "warehouse_id": measure.warehouse_id,
                "batch_id": None,
                "measure_id": measure.id,
                "type": anomaly["type"],
                "severity": "critical" if anomaly["tier"] == "critical" else "low",
                "message": anomaly["reason"][:255],
            }

    return expected


def sync(db, country: str | None = None) -> dict[str, int]:
    """Aligns the `alerts` table with the current state. Returns a report."""
    expected = _expected(db, country)

    q = db.query(Alert).filter(Alert.resolved_at.is_(None))
    if country:
        q = q.filter(Alert.country == country)
    open_alerts = {a.dedup_key: a for a in q.all()}

    opened = updated = resolved = 0

    for key, fields in expected.items():
        existing = open_alerts.get(key)
        if existing is None:
            db.add(Alert(id=str(uuid.uuid4()), triggered_at=_now(), **fields))
            opened += 1
            continue
        if (
            existing.severity != fields["severity"]
            or existing.message != fields["message"]
            or existing.measure_id != fields["measure_id"]
        ):
            existing.severity = fields["severity"]
            existing.message = fields["message"]
            existing.measure_id = fields["measure_id"]
            updated += 1

    for key, alert in open_alerts.items():
        if key not in expected:
            alert.resolved_at = _now()
            resolved += 1

    try:
        db.commit()
    except IntegrityError:
        # Race with another process on the partial unique index: the alert was
        # already opened next to it, there is nothing to repair.
        db.rollback()
        logger.info("Concurrent alert sync, cycle skipped")
        return {"opened": 0, "updated": 0, "resolved": 0}

    return {
        "opened": opened,
        "updated": updated,
        "resolved": resolved,
    }


def list_alerts(
    db,
    country: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Alert], int]:
    q = db.query(Alert)
    if country:
        q = q.filter(Alert.country == country)
    if status == "open":
        q = q.filter(Alert.resolved_at.is_(None), Alert.acknowledged_at.is_(None))
    elif status == "acknowledged":
        q = q.filter(Alert.resolved_at.is_(None), Alert.acknowledged_at.isnot(None))
    elif status == "resolved":
        q = q.filter(Alert.resolved_at.isnot(None))

    total = q.count()
    rows = (
        q.order_by(Alert.triggered_at.desc()).offset(offset).limit(limit).all()
    )
    return rows, total


def acknowledge(db, alert_id: str, by: str | None = None) -> Alert | None:
    alert = db.get(Alert, alert_id)
    if alert is None or alert.resolved_at is not None:
        return None
    alert.acknowledged_at = _now()
    alert.acknowledged_by = by
    db.commit()
    db.refresh(alert)
    return alert


def resolve(db, alert_id: str) -> Alert | None:
    """Manual resolution from the site.

    If the anomaly is still present in the readings, the next synchronisation
    cycle will reopen an alert: this is intentional, the database must not claim
    a warehouse is fine because someone clicked.
    """
    alert = db.get(Alert, alert_id)
    if alert is None or alert.resolved_at is not None:
        return None
    alert.resolved_at = _now()
    db.commit()
    db.refresh(alert)
    return alert


def mark_emailed(db, alerts: list[Alert]) -> None:
    timestamp = _now()
    for alert in alerts:
        alert.emailed_at = timestamp
    db.commit()


def alerts_pending_email(db, country: str) -> list[Alert]:
    """Open alerts for which no e-mail has been sent yet.

    This is what replaces the in-memory `_last_summary_sent` dict: e-mail
    deduplication is now carried by a column, so it survives an API restart.
    """
    return (
        db.query(Alert)
        .filter(
            Alert.country == country,
            Alert.resolved_at.is_(None),
            Alert.emailed_at.is_(None),
        )
        .order_by(Alert.triggered_at.asc())
        .all()
    )
