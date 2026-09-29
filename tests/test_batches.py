from datetime import date, timedelta
from app.models import Batch
from app.services.alerts import compute_batch_status


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
    return batch


class TestBatchStatus:
    def test_compliant(self):
        assert compute_batch_status(date.today() - timedelta(days=10)) == "compliant"

    def test_shelf_life_limit(self):
        assert compute_batch_status(date.today() - timedelta(days=365)) == "compliant"

    def test_expired(self):
        assert compute_batch_status(date.today() - timedelta(days=366)) == "expired"

    def test_very_old(self):
        assert compute_batch_status(date.today() - timedelta(days=400)) == "expired"


class TestBatchEndpoints:
    def test_get_batches_empty(self, client):
        r = client.get("/batches")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_batch(self, client):
        payload = {
            "id": "LOT-TEST-001",
            "country": "brazil",
            "farm": "Fazenda A",
            "warehouse_id": "warehouse-brazil-1",
            "storage_date": str(date.today() - timedelta(days=5)),
        }
        r = client.post("/batches", json=payload)
        assert r.status_code == 201
        assert r.json()["id"] == "LOT-TEST-001"
        assert r.json()["status"] == "compliant"

    def test_expired_batch_status(self, client):
        payload = {
            "id": "LOT-TEST-OLD",
            "country": "brazil",
            "farm": "Fazenda B",
            "warehouse_id": "warehouse-brazil-1",
            "storage_date": str(date.today() - timedelta(days=400)),
        }
        r = client.post("/batches", json=payload)
        assert r.status_code == 201
        assert r.json()["status"] == "expired"

    def test_batches_sorted_by_date_asc(self, client, db):
        _batch(db, "LOT-C", 300)
        _batch(db, "LOT-A", 10)
        _batch(db, "LOT-B", 150)
        r = client.get("/batches")
        assert r.status_code == 200
        dates = [b["storage_date"] for b in r.json()]
        assert dates == sorted(dates)

    def test_batch_not_found(self, client):
        r = client.get("/batches/NONEXISTENT")
        assert r.status_code == 404

    def test_create_batch_duplicate(self, client, db):
        _batch(db, "LOT-DUP", 10)
        payload = {
            "id": "LOT-DUP",
            "country": "brazil",
            "farm": "X",
            "warehouse_id": "e1",
            "storage_date": str(date.today()),
        }
        r = client.post("/batches", json=payload)
        assert r.status_code == 409

    def test_delete_batch(self, client, db):
        _batch(db, "LOT-DEL", 10)
        r = client.delete("/batches/LOT-DEL")
        assert r.status_code == 204
        assert db.get(Batch, "LOT-DEL") is None

    def test_delete_batch_not_found(self, client):
        r = client.delete("/batches/NONEXISTENT")
        assert r.status_code == 404


class TestBatchUpdate:
    def test_partial_patch_does_not_blank_other_fields(self, client):
        client.post("/batches", json={
            "id": "LOT-PATCH", "country": "brazil", "farm": "Fazenda Origin",
            "warehouse_id": "warehouse-brazil-1", "storage_date": "2026-01-10",
        })

        after = client.patch("/batches/LOT-PATCH", json={"warehouse_id": "warehouse-brazil-2"}).json()

        assert after["warehouse_id"] == "warehouse-brazil-2"
        assert after["farm"] == "Fazenda Origin"
        assert after["storage_date"] == "2026-01-10"

    def test_patch_recomputes_status(self, client):
        client.post("/batches", json={
            "id": "LOT-RECALC", "country": "brazil", "farm": "F",
            "warehouse_id": "warehouse-brazil-1", "storage_date": "2026-09-01",
        })
        assert client.get("/batches/LOT-RECALC").json()["status"] == "compliant"

        after = client.patch("/batches/LOT-RECALC", json={"storage_date": "2020-01-01"}).json()

        assert after["status"] == "expired"

    def test_empty_patch_rejected(self, client):
        client.post("/batches", json={
            "id": "LOT-EMPTY", "country": "brazil", "farm": "F",
            "warehouse_id": "warehouse-brazil-1", "storage_date": "2026-01-10",
        })
        assert client.patch("/batches/LOT-EMPTY", json={}).status_code == 400

    def test_patch_unknown_batch(self, client):
        assert client.patch("/batches/NONEXISTENT", json={"farm": "X"}).status_code == 404
