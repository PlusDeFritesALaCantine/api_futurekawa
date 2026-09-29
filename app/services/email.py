"""Build and send the alert summary e-mail (specification III.4).

A single e-mail per country and per check cycle (not one e-mail per individual
alert): it lists each expired batch, then the state of the temperature/humidity
thresholds per warehouse (too high / too low) based on the latest reading.

In local/demo, the target SMTP server is Mailpit (see MQTT_Broker/docker-compose.yml):
e-mails never reach real addresses, they are visible in Mailpit's web UI
(http://localhost:8025). Just change SMTP_HOST/SMTP_PORT to point at a real SMTP
relay in production.
"""

import os
import smtplib
from email.message import EmailMessage

from app.models import Batch, Measure

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@futurekawa.local")

# Operations manager per country — alert recipient (specification III.4).
MANAGER_EMAILS: dict[str, str] = {
    "brazil": os.getenv("BRAZIL_MANAGER_EMAIL", "manager.brazil@futurekawa.local"),
    "ecuador": os.getenv("ECUADOR_MANAGER_EMAIL", "manager.ecuador@futurekawa.local"),
    "colombia": os.getenv("COLOMBIA_MANAGER_EMAIL", "manager.colombia@futurekawa.local"),
}


def build_summary_email(
    country: str,
    problematic_batches: list[tuple[Batch, str]],
    threshold_anomalies: list[tuple[Measure, dict]],
) -> tuple[str, str]:
    nb_batches = len(problematic_batches)
    nb_thresholds = len(threshold_anomalies)

    subject = (
        f"[FutureKawa] Alert summary {country} — {nb_batches} expired batch(es), "
        f"{nb_thresholds} threshold(s) exceeded"
    )

    lines = [
        "Hello,",
        "",
        f"Summary of active alerts for {country}:",
        "",
        f"Expired batches ({nb_batches}):",
    ]
    if not problematic_batches:
        lines.append("  - None.")
    else:
        for batch, reason in problematic_batches:
            lines.append(
                f"  - {batch.id} ({batch.farm}, warehouse {batch.warehouse_id}): {reason}"
            )

    lines += ["", f"Storage thresholds exceeded ({nb_thresholds}):"]
    if not threshold_anomalies:
        lines.append("  - None.")
    else:
        for measure, anomaly in threshold_anomalies:
            lines.append(
                f"  - Warehouse {measure.warehouse_id}: {anomaly['reason']} "
                f"(read on {measure.timestamp})"
            )

    lines += [
        "",
        "Please check these items as soon as possible.",
        "",
        "-- FutureKawa monitoring platform (periodic summary)",
    ]
    return subject, "\n".join(lines)


def send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
        smtp.send_message(message)
