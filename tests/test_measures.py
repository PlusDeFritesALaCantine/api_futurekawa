from datetime import datetime, timedelta, timezone

from app.models import Batch, Measure
from app.services.alerts import is_measure_out_of_range


def _measure(db, mid, temp, hum, warehouse="warehouse-brazil-1", when=None, batch_id=None):
    m = Measure(
        id=mid,
        warehouse_id=warehouse,
        temperature=temp,
        humidity=hum,
        batch_id=batch_id,
        timestamp=when or datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    return m


def _batch(db, batch_id, country, warehouse):
    batch = Batch(
        id=batch_id,
        country=country,
        farm="Test farm",
        warehouse_id=warehouse,
        storage_date=datetime.now(timezone.utc).date(),
    )
    db.add(batch)
    db.commit()
    return batch


class TestMeasureThresholds:
    def test_compliant(self):
        out, _ = is_measure_out_of_range(29.0, 55.0)
        assert not out

    def test_temperature_too_high(self):
        out, reason = is_measure_out_of_range(33.0, 55.0)
        assert out
        assert "temperature" in reason

    def test_temperature_too_low(self):
        out, reason = is_measure_out_of_range(25.0, 55.0)
        assert out
        assert "temperature" in reason

    def test_humidity_too_high(self):
        out, reason = is_measure_out_of_range(29.0, 58.0)
        assert out
        assert "humidity" in reason

    def test_humidity_too_low(self):
        out, reason = is_measure_out_of_range(29.0, 52.0)
        assert out
        assert "humidity" in reason

    def test_double_alert(self):
        out, reason = is_measure_out_of_range(35.0, 50.0)
        assert out
        assert "temperature" in reason
        assert "humidity" in reason

    def test_exact_bounds_are_compliant(self):
        assert not is_measure_out_of_range(26.0, 53.0)[0]
        assert not is_measure_out_of_range(32.0, 57.0)[0]


class TestMeasureEndpoints:
    def test_get_measures_empty(self, client):
        r = client.get("/measures")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0, "limit": 100, "offset": 0}

    def test_filter_by_warehouse(self, client, db):
        _measure(db, "M1", 29.0, 55.0, "warehouse-1")
        _measure(db, "M2", 29.0, 55.0, "warehouse-2")
        r = client.get("/measures?warehouse_id=warehouse-1")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["warehouse_id"] == "warehouse-1"

    def test_latest_per_warehouse(self, client, db):
        _measure(db, "MA", 29.0, 55.0, "warehouse-1")
        _measure(db, "MB", 30.0, 54.0, "warehouse-1")
        r = client.get("/measures/latest")
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestMeasurePagination:
    """The endpoint must never dump the whole table: that is the regression
    these tests lock down."""

    def test_default_limit_and_total(self, client, db):
        base = datetime.now(timezone.utc)
        for i in range(120):
            _measure(db, f"M{i}", 29.0, 55.0, when=base - timedelta(minutes=i))

        r = client.get("/measures")
        body = r.json()
        assert body["total"] == 120        # the total stays exact...
        assert len(body["items"]) == 100   # ...but the page is bounded

    def test_limit_is_capped(self, client):
        assert client.get("/measures?limit=5000").status_code == 422

    def test_offset_pagination(self, client, db):
        base = datetime.now(timezone.utc)
        for i in range(5):
            _measure(db, f"M{i}", 29.0, 55.0, when=base - timedelta(minutes=i))

        page1 = client.get("/measures?limit=2&offset=0").json()["items"]
        page2 = client.get("/measures?limit=2&offset=2").json()["items"]
        assert [m["id"] for m in page1] == ["M0", "M1"]   # descending order
        assert [m["id"] for m in page2] == ["M2", "M3"]

    def test_filter_by_date_range(self, client, db):
        base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _measure(db, "OLD", 29.0, 55.0, when=base - timedelta(days=10))
        _measure(db, "IN", 29.0, 55.0, when=base)
        _measure(db, "RECENT", 29.0, 55.0, when=base + timedelta(days=10))

        # params= rather than an f-string: the "+00:00" of an ISO 8601 string would
        # become a space in an unencoded query string, and the API would answer 422.
        body = client.get("/measures", params={
            "start": (base - timedelta(days=1)).isoformat(),
            "end": (base + timedelta(days=1)).isoformat(),
        }).json()
        assert [m["id"] for m in body["items"]] == ["IN"]

    def test_filter_by_country(self, client, db):
        _batch(db, "L-BR", "brazil", "warehouse-brazil-1")
        _batch(db, "L-CO", "colombia", "warehouse-colombia-1")
        _measure(db, "M-BR", 29.0, 55.0, "warehouse-brazil-1")
        _measure(db, "M-CO", 26.0, 80.0, "warehouse-colombia-1")

        body = client.get("/measures?country=colombia").json()
        assert [m["id"] for m in body["items"]] == ["M-CO"]

    def test_filter_by_unknown_country_returns_nothing(self, client, db):
        _measure(db, "M1", 29.0, 55.0)
        body = client.get("/measures?country=atlantis").json()
        assert body == {"items": [], "total": 0, "limit": 100, "offset": 0}

    def test_filter_by_batch(self, client, db):
        _batch(db, "L1", "brazil", "warehouse-brazil-1")
        _measure(db, "M-WITH", 29.0, 55.0, batch_id="L1")
        _measure(db, "M-WITHOUT", 29.0, 55.0)

        body = client.get("/measures?batch_id=L1").json()
        assert [m["id"] for m in body["items"]] == ["M-WITH"]
