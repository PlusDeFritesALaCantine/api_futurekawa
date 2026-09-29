from datetime import date, timedelta
from app.models import Lot
from app.services.alertes import calculer_statut_lot


def _lot(db, lot_id, delta_jours):
    lot = Lot(
        id=lot_id,
        pays="bresil",
        exploitation="Fazenda Teste",
        entrepot_id="entrepot-bresil-1",
        date_stockage=date.today() - timedelta(days=delta_jours),
        statut="conforme",
    )
    db.add(lot)
    db.commit()
    return lot


class TestStatutLot:
    def test_conforme(self):
        assert calculer_statut_lot(date.today() - timedelta(days=10)) == "conforme"

    def test_limite_peremption(self):
        assert calculer_statut_lot(date.today() - timedelta(days=365)) == "conforme"

    def test_perime(self):
        assert calculer_statut_lot(date.today() - timedelta(days=366)) == "perime"

    def test_tres_ancien(self):
        assert calculer_statut_lot(date.today() - timedelta(days=400)) == "perime"


class TestEndpointsLots:
    def test_get_lots_vide(self, client):
        r = client.get("/lots")
        assert r.status_code == 200
        assert r.json() == []

    def test_creer_lot(self, client):
        payload = {
            "id": "LOT-TEST-001",
            "pays": "bresil",
            "exploitation": "Fazenda A",
            "entrepot_id": "entrepot-bresil-1",
            "date_stockage": str(date.today() - timedelta(days=5)),
        }
        r = client.post("/lots", json=payload)
        assert r.status_code == 201
        assert r.json()["id"] == "LOT-TEST-001"
        assert r.json()["statut"] == "conforme"

    def test_lot_perime_statut(self, client):
        payload = {
            "id": "LOT-TEST-OLD",
            "pays": "bresil",
            "exploitation": "Fazenda B",
            "entrepot_id": "entrepot-bresil-1",
            "date_stockage": str(date.today() - timedelta(days=400)),
        }
        r = client.post("/lots", json=payload)
        assert r.status_code == 201
        assert r.json()["statut"] == "perime"

    def test_lots_tries_par_date_asc(self, client, db):
        _lot(db, "LOT-C", 300)
        _lot(db, "LOT-A", 10)
        _lot(db, "LOT-B", 150)
        r = client.get("/lots")
        assert r.status_code == 200
        dates = [l["date_stockage"] for l in r.json()]
        assert dates == sorted(dates)

    def test_detail_lot_introuvable(self, client):
        r = client.get("/lots/INEXISTANT")
        assert r.status_code == 404

    def test_creer_lot_doublon(self, client, db):
        _lot(db, "LOT-DUP", 10)
        payload = {
            "id": "LOT-DUP",
            "pays": "bresil",
            "exploitation": "X",
            "entrepot_id": "e1",
            "date_stockage": str(date.today()),
        }
        r = client.post("/lots", json=payload)
        assert r.status_code == 409

    def test_supprimer_lot(self, client, db):
        _lot(db, "LOT-DEL", 10)
        r = client.delete("/lots/LOT-DEL")
        assert r.status_code == 204
        assert db.get(Lot, "LOT-DEL") is None

    def test_supprimer_lot_introuvable(self, client):
        r = client.delete("/lots/INEXISTANT")
        assert r.status_code == 404


class TestModificationLot:
    def test_patch_partiel_ne_vide_pas_les_autres_champs(self, client):
        client.post("/lots", json={
            "id": "LOT-PATCH", "pays": "bresil", "exploitation": "Fazenda Origine",
            "entrepot_id": "entrepot-bresil-1", "date_stockage": "2026-01-10",
        })

        apres = client.patch("/lots/LOT-PATCH", json={"entrepot_id": "entrepot-bresil-2"}).json()

        assert apres["entrepot_id"] == "entrepot-bresil-2"
        assert apres["exploitation"] == "Fazenda Origine"
        assert apres["date_stockage"] == "2026-01-10"

    def test_patch_recalcule_le_statut(self, client):
        client.post("/lots", json={
            "id": "LOT-RECALC", "pays": "bresil", "exploitation": "F",
            "entrepot_id": "entrepot-bresil-1", "date_stockage": "2026-09-01",
        })
        assert client.get("/lots/LOT-RECALC").json()["statut"] == "conforme"

        apres = client.patch("/lots/LOT-RECALC", json={"date_stockage": "2020-01-01"}).json()

        assert apres["statut"] == "perime"

    def test_patch_vide_refuse(self, client):
        client.post("/lots", json={
            "id": "LOT-VIDE", "pays": "bresil", "exploitation": "F",
            "entrepot_id": "entrepot-bresil-1", "date_stockage": "2026-01-10",
        })
        assert client.patch("/lots/LOT-VIDE", json={}).status_code == 400

    def test_patch_lot_inconnu(self, client):
        assert client.patch("/lots/INEXISTANT", json={"exploitation": "X"}).status_code == 404
