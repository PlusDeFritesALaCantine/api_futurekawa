"""Lifecycle of persisted alerts: opening, deduplication, acknowledgement,
automatic resolution when the anomaly disappears."""

from datetime import date, datetime, timedelta, timezone

from app.models import Alert, Batch, Measure
from app.services import alert_lifecycle


def _batch(db, batch_id, days, country="brazil", warehouse="warehouse-brazil-1"):
    db.add(Batch(
        id=batch_id, country=country, farm="Fazenda Test",
        warehouse_id=warehouse, storage_date=date.today() - timedelta(days=days),
    ))
    db.commit()


def _measure(db, mid, temp, hum, warehouse="warehouse-brazil-1", when=None):
    db.add(Measure(
        id=mid, warehouse_id=warehouse, temperature=temp, humidity=hum,
        timestamp=when or datetime.now(timezone.utc),
    ))
    db.commit()


class TestOpening:
    def test_expired_batch_opens_an_alert(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)

        report = alert_lifecycle.sync(db)

        assert report["opened"] == 1
        alert = db.query(Alert).one()
        assert alert.type == "expiration"
        assert alert.batch_id == "LOT-EXPIRED"
        assert alert.resolved_at is None

    def test_two_out_of_range_metrics_open_two_alerts(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-DOUBLE", 40.0, 40.0)

        alert_lifecycle.sync(db)

        types = sorted(a.type for a in db.query(Alert).all())
        assert types == ["humidity", "temperature"]

    def test_compliant_measure_opens_nothing(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-OK", 29.0, 55.0)

        alert_lifecycle.sync(db)

        assert db.query(Alert).count() == 0

    def test_critical_severity_beyond_double_tolerance(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-CRITICAL", 40.0, 55.0)

        alert_lifecycle.sync(db)

        assert db.query(Alert).one().severity == "critical"


class TestDeduplication:
    def test_two_cycles_open_only_one_alert(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)

        alert_lifecycle.sync(db)
        second = alert_lifecycle.sync(db)

        assert second["opened"] == 0
        assert db.query(Alert).count() == 1

    def test_message_updated_without_duplicate(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M1", 33.0, 55.0, when=datetime.now(timezone.utc) - timedelta(hours=1))
        alert_lifecycle.sync(db)
        assert db.query(Alert).one().severity == "low"

        # A more recent, more severe measure on the same warehouse.
        _measure(db, "M2", 45.0, 55.0)
        report = alert_lifecycle.sync(db)

        assert report["opened"] == 0
        assert report["updated"] == 1
        alert = db.query(Alert).one()
        assert alert.severity == "critical"
        assert alert.measure_id == "M2"


class TestResolution:
    def test_return_to_normal_resolves_automatically(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-HOT", 40.0, 55.0, when=datetime.now(timezone.utc) - timedelta(hours=1))
        alert_lifecycle.sync(db)
        assert db.query(Alert).one().resolved_at is None

        _measure(db, "M-NORMAL", 29.0, 55.0)
        report = alert_lifecycle.sync(db)

        assert report["resolved"] == 1
        assert db.query(Alert).one().resolved_at is not None

    def test_a_persistent_anomaly_reopens_after_manual_resolution(self, client, db):
        _batch(db, "LOT-OK", 10)
        _measure(db, "M-HOT", 40.0, 55.0)
        alert_lifecycle.sync(db)
        alert_id = db.query(Alert).one().id

        alert_lifecycle.resolve(db, alert_id)
        report = alert_lifecycle.sync(db)

        # The database must not claim everything is fine because someone clicked.
        assert report["opened"] == 1
        assert db.query(Alert).filter(Alert.resolved_at.is_(None)).count() == 1


class TestAcknowledgement:
    def test_acknowledge_does_not_close_the_alert(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)
        alert_lifecycle.sync(db)
        alert_id = db.query(Alert).one().id

        r = client.patch(f"/alerts/{alert_id}/acknowledge", json={"by": "noa"})

        assert r.status_code == 200
        body = r.json()
        assert body["acknowledged_by"] == "noa"
        assert body["acknowledged_at"] is not None
        assert body["resolved_at"] is None

    def test_acknowledge_unknown_alert(self, client):
        assert client.patch("/alerts/nonexistent/acknowledge").status_code == 404

    def test_resolve_twice(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)
        alert_lifecycle.sync(db)
        alert_id = db.query(Alert).one().id

        assert client.patch(f"/alerts/{alert_id}/resolve").status_code == 200
        assert client.patch(f"/alerts/{alert_id}/resolve").status_code == 404


class TestJournal:
    def test_filter_by_status(self, client, db):
        _batch(db, "LOT-A", 400)
        _batch(db, "LOT-B", 500, warehouse="warehouse-brazil-2")
        alert_lifecycle.sync(db)
        first = db.query(Alert).order_by(Alert.batch_id).first()
        client.patch(f"/alerts/{first.id}/acknowledge", json={"by": "noa"})

        open_alerts = client.get("/alerts/journal?status=open").json()
        acknowledged = client.get("/alerts/journal?status=acknowledged").json()

        assert open_alerts["total"] == 1
        assert acknowledged["total"] == 1
        assert acknowledged["items"][0]["acknowledged_by"] == "noa"

    def test_pagination(self, client, db):
        for i in range(5):
            _batch(db, f"LOT-{i}", 400 + i, warehouse=f"warehouse-brazil-{i}")
        alert_lifecycle.sync(db)

        page = client.get("/alerts/journal?limit=2").json()

        assert page["total"] == 5
        assert len(page["items"]) == 2

    def test_filter_by_country(self, client, db):
        _batch(db, "LOT-BR", 400, country="brazil", warehouse="warehouse-brazil-1")
        _batch(db, "LOT-CO", 400, country="colombia", warehouse="warehouse-colombia-1")
        alert_lifecycle.sync(db)

        body = client.get("/alerts/journal?country=colombia").json()

        assert body["total"] == 1
        assert body["items"][0]["batch_id"] == "LOT-CO"

    def test_sync_endpoint(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)

        body = client.post("/alerts/sync").json()

        assert body == {"opened": 1, "updated": 0, "resolved": 0}


class TestEmailDeduplication:
    def test_the_second_cycle_sends_nothing(self, client, db):
        from unittest.mock import patch

        from app.services import notifier

        _batch(db, "LOT-EXPIRED", 400)

        with patch("app.services.notifier.send_email") as mock_send:
            notifier.check_and_notify(["brazil"])
            notifier.check_and_notify(["brazil"])

        assert mock_send.call_count == 1

    def test_deduplication_survives_restart(self, client, db):
        """The real contribution of persistence: before, the in-memory dict was
        reset and a restart re-sent an already sent e-mail."""
        from unittest.mock import patch

        from app.services import notifier

        _batch(db, "LOT-EXPIRED", 400)

        with patch("app.services.notifier.send_email") as mock_send:
            notifier.check_and_notify(["brazil"])

        # Simulates a restart: no in-memory state is kept.
        import importlib
        importlib.reload(notifier)

        with patch("app.services.notifier.send_email") as mock_after:
            sent = notifier.check_and_notify(["brazil"])

        assert sent == 0
        mock_after.assert_not_called()
