from datetime import date, datetime, timedelta, timezone
from app.models import Batch, Measure


def _batch(db, batch_id, age_days):
    batch = Batch(
        id=batch_id,
        country="brazil",
        farm="Fazenda Test",
        warehouse_id="warehouse-brazil-1",
        storage_date=date.today() - timedelta(days=age_days),
        status="compliant",
    )
    db.add(batch)
    db.commit()


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


# Brazil: ideal 29 °C ±3 (tolerance), ideal 55 % ±2.
# Tiers (on temperature, tolerance=3): excellent <=0.75, good <=1.8, fair <=3, low <=6, critical >6.


class TestAlertsEndpoint:
    def test_alerts_empty(self, client):
        r = client.get("/alerts")
        assert r.status_code == 200
        data = r.json()
        assert data["problematic_batches"] == []
        assert data["out_of_range_measures"] == []

    def test_expired_batch_in_alerts(self, client, db):
        _batch(db, "LOT-OLD", 400)
        r = client.get("/alerts")
        assert r.status_code == 200
        batches = r.json()["problematic_batches"]
        assert len(batches) == 1
        assert batches[0]["batch"]["id"] == "LOT-OLD"
        assert "Expired" in batches[0]["reason"]

    def test_compliant_batch_absent_from_alerts(self, client, db):
        _batch(db, "LOT-OK", 10)
        r = client.get("/alerts")
        assert r.json()["problematic_batches"] == []

    def test_critical_measure_in_alerts(self, client, db):
        # 11 °C gap: > 2x the tolerance (3 °C) -> critical.
        _measure(db, "M-HOT", 40.0, 55.0)
        r = client.get("/alerts")
        measures = r.json()["out_of_range_measures"]
        assert len(measures) == 1
        assert measures[0]["measure"]["id"] == "M-HOT"
        assert measures[0]["severity"] == "critical"
        assert "too high" in measures[0]["reason"]

    def test_low_measure_appears_in_alerts(self, client, db):
        # 4 °C gap: out of tolerance (3 °C) but under the critical threshold (6 °C) -> "low",
        # which must now appear in the alerts (not only critical).
        _measure(db, "M-WARM", 33.0, 55.0)
        r = client.get("/alerts")
        measures = r.json()["out_of_range_measures"]
        assert len(measures) == 1
        assert measures[0]["severity"] == "low"

    def test_fair_measure_absent_from_alerts(self, client, db):
        # 2.5 °C gap: within tolerance (3 °C) -> tier "fair", not an alert.
        _measure(db, "M-LIMIT", 31.5, 55.0)
        r = client.get("/alerts")
        assert r.json()["out_of_range_measures"] == []

    def test_compliant_measure_absent_from_alerts(self, client, db):
        _measure(db, "M-OK", 29.0, 55.0)
        r = client.get("/alerts")
        assert r.json()["out_of_range_measures"] == []

    def test_mixed_alerts(self, client, db):
        _batch(db, "LOT-EXPIRED", 400)
        _batch(db, "LOT-COMPLIANT", 10)
        _measure(db, "M-OUT", 40.0, 52.0, warehouse_id="warehouse-brazil-2")
        _measure(db, "M-OK", 29.0, 55.0, warehouse_id="warehouse-brazil-1")
        r = client.get("/alerts")
        data = r.json()
        assert len(data["problematic_batches"]) == 1
        assert len(data["out_of_range_measures"]) == 1

    def test_only_the_latest_reading_per_warehouse_counts(self, client, db):
        # An old critical reading followed by one back within range: the warehouse
        # must no longer appear in the alerts (otherwise every past breach would
        # remain flagged indefinitely).
        _measure(db, "M-OLD-CRITICAL", 45.0, 55.0, when=datetime.now(timezone.utc) - timedelta(hours=2))
        _measure(db, "M-RECENT-OK", 29.0, 55.0, when=datetime.now(timezone.utc))
        r = client.get("/alerts")
        assert r.json()["out_of_range_measures"] == []

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
