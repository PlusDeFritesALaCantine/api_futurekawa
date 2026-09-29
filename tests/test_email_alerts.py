from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models import Batch, Measure
from app.services import notifier
from app.services.alerts import evaluate_measure
from app.services.email import build_summary_email


def _batch(db, batch_id, age_days, country="brazil", warehouse_id="warehouse-brazil-1"):
    batch = Batch(
        id=batch_id,
        country=country,
        farm="Fazenda Test",
        warehouse_id=warehouse_id,
        storage_date=date.today() - timedelta(days=age_days),
        status="compliant",
    )
    db.add(batch)
    db.commit()
    return batch


def _measure(db, mid, temp, hum, warehouse_id="warehouse-brazil-1", when=None):
    m = Measure(
        id=mid,
        warehouse_id=warehouse_id,
        temperature=temp,
        humidity=hum,
        timestamp=when or datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    return m


class TestEvaluateMeasure:
    def test_direction_too_high(self, db):
        anomalies = evaluate_measure(40.0, 55.0, "brazil")
        assert len(anomalies) == 1
        assert anomalies[0]["direction"] == "too high"
        assert anomalies[0]["tier"] == "critical"

    def test_direction_too_low(self, db):
        anomalies = evaluate_measure(15.0, 55.0, "brazil")
        assert anomalies[0]["direction"] == "too low"

    def test_compliant_no_anomaly(self, db):
        assert evaluate_measure(29.0, 55.0, "brazil") == []


class TestSummaryEmail:
    def test_summary_lists_each_expired_batch(self, db):
        batch = _batch(db, "LOT-OLD", 400)
        subject, body = build_summary_email("brazil", [(batch, "Expired batch: stored for 400 days")], [])
        assert "1 expired batch(es)" in subject
        assert "LOT-OLD" in body

    def test_summary_lists_threshold_breaches_with_direction(self, db):
        measure = _measure(db, "M-HOT", 40.0, 55.0)
        anomaly = evaluate_measure(40.0, 55.0, "brazil")[0]
        subject, body = build_summary_email("brazil", [], [(measure, anomaly)])
        assert "1 threshold(s)" in subject
        assert "too high" in body
        assert measure.warehouse_id in body

    def test_summary_without_alert(self, db):
        subject, body = build_summary_email("brazil", [], [])
        assert "0 expired batch(es)" in subject
        assert "None." in body


class TestNotifier:
    # No more in-memory state reset: e-mail deduplication now lives in the
    # alerts.emailed_at column, and the setup_db fixture recreates the tables
    # before each test.

    def test_single_email_for_combined_expired_batch_and_threshold(self, db):
        _batch(db, "LOT-EXPIRED", 400)
        _measure(db, "M-HOT", 40.0, 55.0, warehouse_id="warehouse-brazil-2")
        _batch(db, "LOT-OTHER", 10, warehouse_id="warehouse-brazil-2")

        with patch("app.services.notifier.send_email") as mock_send:
            sent = notifier.check_and_notify(["brazil"])

        assert sent == 1
        mock_send.assert_called_once()
        recipient, subject, body = mock_send.call_args[0]
        assert recipient == notifier.MANAGER_EMAILS["brazil"]
        assert "LOT-EXPIRED" in body
        assert "warehouse-brazil-2" in body

    def test_no_alert_no_email(self, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-OK", 29.0, 55.0)

        with patch("app.services.notifier.send_email") as mock_send:
            sent = notifier.check_and_notify(["brazil"])

        assert sent == 0
        mock_send.assert_not_called()

    def test_no_resend_if_situation_unchanged(self, db):
        _batch(db, "LOT-EXPIRED", 400)

        with patch("app.services.notifier.send_email") as mock_send:
            notifier.check_and_notify(["brazil"])
            sent_second_pass = notifier.check_and_notify(["brazil"])

        assert sent_second_pass == 0
        assert mock_send.call_count == 1

    def test_resend_if_a_new_alert_appears(self, db):
        _batch(db, "LOT-EXPIRED-1", 400)

        with patch("app.services.notifier.send_email") as mock_send:
            notifier.check_and_notify(["brazil"])
            _batch(db, "LOT-EXPIRED-2", 410)
            sent_second_pass = notifier.check_and_notify(["brazil"])

        assert sent_second_pass == 1
        assert mock_send.call_count == 2

    def test_only_the_latest_reading_per_warehouse_counts(self, db):
        # Old critical reading, but the latest reading is back within range:
        # the summary must not flag this warehouse.
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-OLD-CRITICAL", 45.0, 55.0, when=datetime.now(timezone.utc) - timedelta(hours=2))
        _measure(db, "M-RECENT-OK", 29.0, 55.0, when=datetime.now(timezone.utc))

        with patch("app.services.notifier.send_email") as mock_send:
            sent = notifier.check_and_notify(["brazil"])

        assert sent == 0
        mock_send.assert_not_called()

    def test_send_failure_does_not_mark_as_notified(self, db):
        _batch(db, "LOT-EXPIRED", 400)

        with patch("app.services.notifier.send_email", side_effect=OSError("SMTP down")):
            sent = notifier.check_and_notify(["brazil"])
        assert sent == 0

        with patch("app.services.notifier.send_email") as mock_send:
            sent_retry = notifier.check_and_notify(["brazil"])
        assert sent_retry == 1
        mock_send.assert_called_once()

    def test_without_country_list_detects_countries_in_db(self, db):
        _batch(db, "LOT-BR", 400, country="brazil", warehouse_id="warehouse-brazil-1")
        _batch(db, "LOT-EQ", 400, country="ecuador", warehouse_id="warehouse-ecuador-1")

        with patch("app.services.notifier.send_email") as mock_send:
            sent = notifier.check_and_notify()

        assert sent == 2
        assert mock_send.call_count == 2


class TestNotifierEndpoint:
    def test_post_notify_sends_the_summary(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)

        with patch("app.services.notifier.send_email") as mock_send:
            r = client.post("/alerts/notify")

        assert r.status_code == 200
        assert r.json()["emails_sent"] == 1
        mock_send.assert_called_once()
