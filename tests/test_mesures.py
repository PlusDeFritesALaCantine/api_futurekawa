from datetime import datetime, timedelta, timezone

from app.models import Lot, Mesure
from app.services.alertes import est_mesure_hors_seuil


def _mesure(db, mid, temp, hum, entrepot="entrepot-bresil-1", quand=None, lot_id=None):
    m = Mesure(
        id=mid,
        entrepot_id=entrepot,
        temperature=temp,
        humidity=hum,
        lot_id=lot_id,
        timestamp=quand or datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    return m


def _lot(db, lot_id, pays, entrepot):
    lot = Lot(
        id=lot_id,
        pays=pays,
        exploitation="Exploitation test",
        entrepot_id=entrepot,
        date_stockage=datetime.now(timezone.utc).date(),
    )
    db.add(lot)
    db.commit()
    return lot


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
        assert r.json() == {"items": [], "total": 0, "limit": 100, "offset": 0}

    def test_filtrage_par_entrepot(self, client, db):
        _mesure(db, "M1", 29.0, 55.0, "entrepot-1")
        _mesure(db, "M2", 29.0, 55.0, "entrepot-2")
        r = client.get("/mesures?entrepot_id=entrepot-1")
        assert r.status_code == 200
        corps = r.json()
        assert corps["total"] == 1
        assert len(corps["items"]) == 1
        assert corps["items"][0]["entrepot_id"] == "entrepot-1"

    def test_latest_par_entrepot(self, client, db):
        _mesure(db, "MA", 29.0, 55.0, "entrepot-1")
        _mesure(db, "MB", 30.0, 54.0, "entrepot-1")
        r = client.get("/mesures/latest")
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestPaginationMesures:
    """L'endpoint ne doit jamais déverser toute la table : c'est la régression
    que ces tests verrouillent."""

    def test_limite_par_defaut_et_total(self, client, db):
        base = datetime.now(timezone.utc)
        for i in range(120):
            _mesure(db, f"M{i}", 29.0, 55.0, quand=base - timedelta(minutes=i))

        r = client.get("/mesures")
        corps = r.json()
        assert corps["total"] == 120        # le total reste exact...
        assert len(corps["items"]) == 100   # ...mais la page est bornée

    def test_limite_plafonnee(self, client):
        assert client.get("/mesures?limit=5000").status_code == 422

    def test_pagination_offset(self, client, db):
        base = datetime.now(timezone.utc)
        for i in range(5):
            _mesure(db, f"M{i}", 29.0, 55.0, quand=base - timedelta(minutes=i))

        page1 = client.get("/mesures?limit=2&offset=0").json()["items"]
        page2 = client.get("/mesures?limit=2&offset=2").json()["items"]
        assert [m["id"] for m in page1] == ["M0", "M1"]   # tri décroissant
        assert [m["id"] for m in page2] == ["M2", "M3"]

    def test_filtrage_par_plage_de_dates(self, client, db):
        base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _mesure(db, "VIEILLE", 29.0, 55.0, quand=base - timedelta(days=10))
        _mesure(db, "DANS", 29.0, 55.0, quand=base)
        _mesure(db, "RECENTE", 29.0, 55.0, quand=base + timedelta(days=10))

        # params= plutôt qu'une f-string : le "+00:00" d'un ISO 8601 deviendrait
        # une espace dans une query string non encodée, et l'API répondrait 422.
        corps = client.get("/mesures", params={
            "debut": (base - timedelta(days=1)).isoformat(),
            "fin": (base + timedelta(days=1)).isoformat(),
        }).json()
        assert [m["id"] for m in corps["items"]] == ["DANS"]

    def test_filtrage_par_pays(self, client, db):
        _lot(db, "L-BR", "bresil", "entrepot-bresil-1")
        _lot(db, "L-CO", "colombie", "entrepot-colombie-1")
        _mesure(db, "M-BR", 29.0, 55.0, "entrepot-bresil-1")
        _mesure(db, "M-CO", 26.0, 80.0, "entrepot-colombie-1")

        corps = client.get("/mesures?pays=colombie").json()
        assert [m["id"] for m in corps["items"]] == ["M-CO"]

    def test_filtrage_par_pays_inconnu_ne_renvoie_rien(self, client, db):
        _mesure(db, "M1", 29.0, 55.0)
        corps = client.get("/mesures?pays=atlantide").json()
        assert corps == {"items": [], "total": 0, "limit": 100, "offset": 0}

    def test_filtrage_par_lot(self, client, db):
        _lot(db, "L1", "bresil", "entrepot-bresil-1")
        _mesure(db, "M-AVEC", 29.0, 55.0, lot_id="L1")
        _mesure(db, "M-SANS", 29.0, 55.0)

        corps = client.get("/mesures?lot_id=L1").json()
        assert [m["id"] for m in corps["items"]] == ["M-AVEC"]
