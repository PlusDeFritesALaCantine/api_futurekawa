from datetime import datetime, timezone
from app.models import Mesure
from app.services.alertes import est_mesure_hors_seuil


def _mesure(db, mid, temp, hum, entrepot="entrepot-bresil-1"):
    m = Mesure(
        id=mid,
        entrepot_id=entrepot,
        temperature=temp,
        humidity=hum,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    return m


class TestSeuilsMesures:
    def test_conforme(self):
        hors, _ = est_mesure_hors_seuil(29.0, 55.0)
        assert not hors

    def test_temperature_trop_haute(self):
        hors, raison = est_mesure_hors_seuil(33.0, 55.0)
        assert hors
        assert "température" in raison

    def test_temperature_trop_basse(self):
        hors, raison = est_mesure_hors_seuil(25.0, 55.0)
        assert hors
        assert "température" in raison

    def test_humidite_trop_haute(self):
        hors, raison = est_mesure_hors_seuil(29.0, 58.0)
        assert hors
        assert "humidité" in raison

    def test_humidite_trop_basse(self):
        hors, raison = est_mesure_hors_seuil(29.0, 52.0)
        assert hors
        assert "humidité" in raison

    def test_double_alerte(self):
        hors, raison = est_mesure_hors_seuil(35.0, 50.0)
        assert hors
        assert "température" in raison
        assert "humidité" in raison

    def test_limites_exactes_conformes(self):
        assert not est_mesure_hors_seuil(26.0, 53.0)[0]
        assert not est_mesure_hors_seuil(32.0, 57.0)[0]


class TestEndpointsMesures:
    def test_get_mesures_vide(self, client):
        r = client.get("/mesures")
        assert r.status_code == 200
        assert r.json() == []

    def test_filtrage_par_entrepot(self, client, db):
        _mesure(db, "M1", 29.0, 55.0, "entrepot-1")
        _mesure(db, "M2", 29.0, 55.0, "entrepot-2")
        r = client.get("/mesures?entrepot_id=entrepot-1")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["entrepot_id"] == "entrepot-1"

    def test_latest_par_entrepot(self, client, db):
        _mesure(db, "MA", 29.0, 55.0, "entrepot-1")
        _mesure(db, "MB", 30.0, 54.0, "entrepot-1")
        r = client.get("/mesures/latest")
        assert r.status_code == 200
        assert len(r.json()) == 1
