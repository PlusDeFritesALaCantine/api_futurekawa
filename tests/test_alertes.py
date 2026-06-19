from datetime import date, datetime, timedelta, timezone
from app.models import Lot, Mesure


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


def _mesure(db, mid, temp, hum):
    m = Mesure(
        id=mid,
        entrepot_id="entrepot-bresil-1",
        temperature=temp,
        humidity=hum,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()


class TestEndpointAlertes:
    def test_alertes_vides(self, client):
        r = client.get("/alertes")
        assert r.status_code == 200
        data = r.json()
        assert data["lots_problematiques"] == []
        assert data["mesures_hors_seuil"] == []

    def test_lot_perime_dans_alertes(self, client, db):
        _lot(db, "LOT-OLD", 400)
        r = client.get("/alertes")
        assert r.status_code == 200
        lots = r.json()["lots_problematiques"]
        assert len(lots) == 1
        assert lots[0]["lot"]["id"] == "LOT-OLD"
        assert "périmé" in lots[0]["raison"]

    def test_lot_conforme_absent_alertes(self, client, db):
        _lot(db, "LOT-OK", 10)
        r = client.get("/alertes")
        assert r.json()["lots_problematiques"] == []

    def test_mesure_hors_seuil_dans_alertes(self, client, db):
        _mesure(db, "M-HOT", 35.0, 55.0)
        r = client.get("/alertes")
        mesures = r.json()["mesures_hors_seuil"]
        assert len(mesures) == 1
        assert mesures[0]["mesure"]["id"] == "M-HOT"

    def test_mesure_conforme_absente_alertes(self, client, db):
        _mesure(db, "M-OK", 29.0, 55.0)
        r = client.get("/alertes")
        assert r.json()["mesures_hors_seuil"] == []

    def test_mix_alertes(self, client, db):
        _lot(db, "LOT-PERIME", 400)
        _lot(db, "LOT-CONFORME", 10)
        _mesure(db, "M-HORS", 33.0, 52.0)
        _mesure(db, "M-OK", 29.0, 55.0)
        r = client.get("/alertes")
        data = r.json()
        assert len(data["lots_problematiques"]) == 1
        assert len(data["mesures_hors_seuil"]) == 1

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
