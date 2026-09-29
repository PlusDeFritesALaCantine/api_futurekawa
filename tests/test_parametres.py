"""Paramétrage métier depuis le site : lecture, fusion du PATCH, effet immédiat."""

from datetime import date, timedelta

from app.models import Lot, Mesure
from app.services import parametres as svc


def _lot(db, lot_id, jours, pays="bresil", entrepot="entrepot-bresil-1"):
    lot = Lot(
        id=lot_id,
        pays=pays,
        exploitation="Fazenda Teste",
        entrepot_id=entrepot,
        date_stockage=date.today() - timedelta(days=jours),
    )
    db.add(lot)
    db.commit()
    return lot


class TestLectureParametres:
    def test_les_trois_pays_sont_amorces(self, client):
        corps = client.get("/parametres/pays").json()
        assert {p["slug"] for p in corps} == {"bresil", "equateur", "colombie"}

    def test_valeurs_du_cahier_des_charges(self, client):
        bresil = client.get("/parametres/pays/bresil").json()
        assert bresil["temperature_ideale"] == 29.0
        assert bresil["temperature_tolerance"] == 3.0
        assert bresil["humidite_ideale"] == 55.0
        assert bresil["peremption_jours"] == 365

    def test_pays_inconnu(self, client):
        assert client.get("/parametres/pays/atlantide").status_code == 404


class TestModificationParametres:
    def test_patch_partiel_ne_touche_pas_aux_autres_champs(self, client):
        avant = client.get("/parametres/pays/bresil").json()

        apres = client.patch(
            "/parametres/pays/bresil", json={"peremption_jours": 180}
        ).json()

        assert apres["peremption_jours"] == 180
        # Tout le reste doit être intact : c'est la régression que ce test verrouille.
        for champ in (
            "temperature_ideale", "temperature_tolerance",
            "humidite_ideale", "humidite_tolerance", "email_responsable", "nom",
        ):
            assert apres[champ] == avant[champ], f"{champ} a été écrasé par le PATCH"

    def test_patch_vide_refuse(self, client):
        assert client.patch("/parametres/pays/bresil", json={}).status_code == 400

    def test_tolerance_nulle_refusee(self, client):
        r = client.patch("/parametres/pays/bresil", json={"temperature_tolerance": 0})
        assert r.status_code == 422

    def test_email_invalide_refuse(self, client):
        r = client.patch("/parametres/pays/bresil", json={"email_responsable": "pas-une-adresse"})
        assert r.status_code == 422

    def test_pays_inconnu(self, client):
        r = client.patch("/parametres/pays/atlantide", json={"peremption_jours": 10})
        assert r.status_code == 404


class TestEffetSurLeMetier:
    """Le paramétrage doit changer le comportement sans redémarrage : c'est tout
    l'intérêt de le sortir des constantes Python."""

    def test_reduire_la_peremption_perime_un_lot_existant(self, client, db):
        _lot(db, "LOT-200J", 200)
        assert client.get("/lots/LOT-200J").json()["statut"] == "conforme"

        client.patch("/parametres/pays/bresil", json={"peremption_jours": 100})

        assert client.get("/lots/LOT-200J").json()["statut"] == "perime"

    def test_resserrer_la_tolerance_declenche_une_alerte(self, client, db):
        _lot(db, "LOT-OK", 10)
        db.add(Mesure(id="M1", entrepot_id="entrepot-bresil-1", temperature=31.0, humidity=55.0))
        db.commit()

        # 31 °C est dans la tolérance de ±3 : aucune alerte.
        assert client.get("/alertes").json()["mesures_hors_seuil"] == []

        client.patch("/parametres/pays/bresil", json={"temperature_tolerance": 1.0})

        alertes = client.get("/alertes").json()["mesures_hors_seuil"]
        assert len(alertes) == 1
        assert "température" in alertes[0]["raison"]

    def test_desactiver_les_alertes_coupe_les_emails(self, client, db):
        from unittest.mock import patch

        from app.services import notifier

        _lot(db, "LOT-PERIME", 400)
        client.patch("/parametres/pays/bresil", json={"alertes_actives": False})

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 0
        mock_envoyer.assert_not_called()


class TestCacheParametres:
    def test_get_sans_base_retombe_sur_les_defauts(self):
        svc.invalider()
        assert svc.get("bresil").temperature_ideale == 29.0
        assert svc.get("colombie").humidite_ideale == 80.0
