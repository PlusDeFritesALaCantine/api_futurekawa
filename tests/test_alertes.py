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


def _mesure(db, mid, temp, hum, entrepot_id="entrepot-bresil-1", quand=None):
    m = Mesure(
        id=mid,
        entrepot_id=entrepot_id,
        temperature=temp,
        humidity=hum,
        timestamp=quand or datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()


# Brésil : idéal 29°C ±3 (tolérance), idéal 55% ±2.
# Tiers (sur la température, tolérance=3) : excellent <=0.75, bon <=1.8, correct <=3, bas <=6, critique >6.


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

    def test_mesure_critique_dans_alertes(self, client, db):
        # Écart de 11°C : > 2x la tolérance (3°C) -> critique.
        _mesure(db, "M-HOT", 40.0, 55.0)
        r = client.get("/alertes")
        mesures = r.json()["mesures_hors_seuil"]
        assert len(mesures) == 1
        assert mesures[0]["mesure"]["id"] == "M-HOT"
        assert mesures[0]["severite"] == "critique"
        assert "trop élevée" in mesures[0]["raison"]

    def test_mesure_bas_apparait_dans_alertes(self, client, db):
        # Écart de 4°C : hors tolérance (3°C) mais sous le seuil critique (6°C) -> "bas",
        # qui doit maintenant apparaître dans les alertes (pas seulement le critique).
        _mesure(db, "M-TIEDE", 33.0, 55.0)
        r = client.get("/alertes")
        mesures = r.json()["mesures_hors_seuil"]
        assert len(mesures) == 1
        assert mesures[0]["severite"] == "bas"

    def test_mesure_correcte_absente_des_alertes(self, client, db):
        # Écart de 2.5°C : dans la tolérance (3°C) -> tier "correct", pas une alerte.
        _mesure(db, "M-LIMITE", 31.5, 55.0)
        r = client.get("/alertes")
        assert r.json()["mesures_hors_seuil"] == []

    def test_mesure_conforme_absente_alertes(self, client, db):
        _mesure(db, "M-OK", 29.0, 55.0)
        r = client.get("/alertes")
        assert r.json()["mesures_hors_seuil"] == []

    def test_mix_alertes(self, client, db):
        _lot(db, "LOT-PERIME", 400)
        _lot(db, "LOT-CONFORME", 10)
        _mesure(db, "M-HORS", 40.0, 52.0, entrepot_id="entrepot-bresil-2")
        _mesure(db, "M-OK", 29.0, 55.0, entrepot_id="entrepot-bresil-1")
        r = client.get("/alertes")
        data = r.json()
        assert len(data["lots_problematiques"]) == 1
        assert len(data["mesures_hors_seuil"]) == 1

    def test_seul_le_dernier_releve_de_lentrepot_compte(self, client, db):
        # Un relevé critique ancien suivi d'un relevé revenu dans les clous : l'entrepôt
        # ne doit plus apparaître dans les alertes (sinon chaque dépassement passé
        # resterait signalé indéfiniment).
        _mesure(db, "M-ANCIEN-CRITIQUE", 45.0, 55.0, quand=datetime.now(timezone.utc) - timedelta(hours=2))
        _mesure(db, "M-RECENT-OK", 29.0, 55.0, quand=datetime.now(timezone.utc))
        r = client.get("/alertes")
        assert r.json()["mesures_hors_seuil"] == []

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
