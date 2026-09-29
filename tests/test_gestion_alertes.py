"""Cycle de vie des alertes persistées : ouverture, déduplication, acquittement,
résolution automatique quand l'anomalie disparaît."""

from datetime import date, datetime, timedelta, timezone

from app.models import Alerte, Lot, Mesure
from app.services import gestion_alertes


def _lot(db, lot_id, jours, pays="bresil", entrepot="entrepot-bresil-1"):
    db.add(Lot(
        id=lot_id, pays=pays, exploitation="Fazenda Teste",
        entrepot_id=entrepot, date_stockage=date.today() - timedelta(days=jours),
    ))
    db.commit()


def _mesure(db, mid, temp, hum, entrepot="entrepot-bresil-1", quand=None):
    db.add(Mesure(
        id=mid, entrepot_id=entrepot, temperature=temp, humidity=hum,
        timestamp=quand or datetime.now(timezone.utc),
    ))
    db.commit()


class TestOuverture:
    def test_lot_perime_ouvre_une_alerte(self, client, db):
        _lot(db, "LOT-PERIME", 400)

        rapport = gestion_alertes.synchroniser(db)

        assert rapport["ouvertures"] == 1
        alerte = db.query(Alerte).one()
        assert alerte.type == "peremption"
        assert alerte.lot_id == "LOT-PERIME"
        assert alerte.resolue_le is None

    def test_deux_grandeurs_hors_seuil_ouvrent_deux_alertes(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-DOUBLE", 40.0, 40.0)

        gestion_alertes.synchroniser(db)

        types = sorted(a.type for a in db.query(Alerte).all())
        assert types == ["humidite", "temperature"]

    def test_mesure_conforme_n_ouvre_rien(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-OK", 29.0, 55.0)

        gestion_alertes.synchroniser(db)

        assert db.query(Alerte).count() == 0

    def test_severite_critique_au_dela_du_double_de_tolerance(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-CRITIQUE", 40.0, 55.0)

        gestion_alertes.synchroniser(db)

        assert db.query(Alerte).one().severite == "critique"


class TestDeduplication:
    def test_deux_cycles_n_ouvrent_qu_une_alerte(self, client, db):
        _lot(db, "LOT-PERIME", 400)

        gestion_alertes.synchroniser(db)
        second = gestion_alertes.synchroniser(db)

        assert second["ouvertures"] == 0
        assert db.query(Alerte).count() == 1

    def test_message_mis_a_jour_sans_doublon(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M1", 33.0, 55.0, quand=datetime.now(timezone.utc) - timedelta(hours=1))
        gestion_alertes.synchroniser(db)
        assert db.query(Alerte).one().severite == "bas"

        # Une mesure plus récente, plus grave, sur le même entrepôt.
        _mesure(db, "M2", 45.0, 55.0)
        rapport = gestion_alertes.synchroniser(db)

        assert rapport["ouvertures"] == 0
        assert rapport["mises_a_jour"] == 1
        alerte = db.query(Alerte).one()
        assert alerte.severite == "critique"
        assert alerte.mesure_id == "M2"


class TestResolution:
    def test_retour_a_la_normale_resout_automatiquement(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-CHAUD", 40.0, 55.0, quand=datetime.now(timezone.utc) - timedelta(hours=1))
        gestion_alertes.synchroniser(db)
        assert db.query(Alerte).one().resolue_le is None

        _mesure(db, "M-NORMAL", 29.0, 55.0)
        rapport = gestion_alertes.synchroniser(db)

        assert rapport["resolutions"] == 1
        assert db.query(Alerte).one().resolue_le is not None

    def test_une_anomalie_persistante_rouvre_apres_resolution_manuelle(self, client, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-CHAUD", 40.0, 55.0)
        gestion_alertes.synchroniser(db)
        alerte_id = db.query(Alerte).one().id

        gestion_alertes.resoudre(db, alerte_id)
        rapport = gestion_alertes.synchroniser(db)

        # La base ne doit pas prétendre que tout va bien parce qu'on a cliqué.
        assert rapport["ouvertures"] == 1
        assert db.query(Alerte).filter(Alerte.resolue_le.is_(None)).count() == 1


class TestAcquittement:
    def test_acquitter_ne_ferme_pas_l_alerte(self, client, db):
        _lot(db, "LOT-PERIME", 400)
        gestion_alertes.synchroniser(db)
        alerte_id = db.query(Alerte).one().id

        r = client.patch(f"/alertes/{alerte_id}/acquitter", json={"par": "noa"})

        assert r.status_code == 200
        corps = r.json()
        assert corps["acquittee_par"] == "noa"
        assert corps["acquittee_le"] is not None
        assert corps["resolue_le"] is None

    def test_acquitter_une_alerte_inconnue(self, client):
        assert client.patch("/alertes/inexistante/acquitter").status_code == 404

    def test_resoudre_deux_fois(self, client, db):
        _lot(db, "LOT-PERIME", 400)
        gestion_alertes.synchroniser(db)
        alerte_id = db.query(Alerte).one().id

        assert client.patch(f"/alertes/{alerte_id}/resoudre").status_code == 200
        assert client.patch(f"/alertes/{alerte_id}/resoudre").status_code == 404


class TestJournal:
    def test_filtrage_par_statut(self, client, db):
        _lot(db, "LOT-A", 400)
        _lot(db, "LOT-B", 500, entrepot="entrepot-bresil-2")
        gestion_alertes.synchroniser(db)
        premiere = db.query(Alerte).order_by(Alerte.lot_id).first()
        client.patch(f"/alertes/{premiere.id}/acquitter", json={"par": "noa"})

        ouvertes = client.get("/alertes/journal?statut=ouverte").json()
        acquittees = client.get("/alertes/journal?statut=acquittee").json()

        assert ouvertes["total"] == 1
        assert acquittees["total"] == 1
        assert acquittees["items"][0]["acquittee_par"] == "noa"

    def test_pagination(self, client, db):
        for i in range(5):
            _lot(db, f"LOT-{i}", 400 + i, entrepot=f"entrepot-bresil-{i}")
        gestion_alertes.synchroniser(db)

        page = client.get("/alertes/journal?limit=2").json()

        assert page["total"] == 5
        assert len(page["items"]) == 2

    def test_filtrage_par_pays(self, client, db):
        _lot(db, "LOT-BR", 400, pays="bresil", entrepot="entrepot-bresil-1")
        _lot(db, "LOT-CO", 400, pays="colombie", entrepot="entrepot-colombie-1")
        gestion_alertes.synchroniser(db)

        corps = client.get("/alertes/journal?pays=colombie").json()

        assert corps["total"] == 1
        assert corps["items"][0]["lot_id"] == "LOT-CO"

    def test_endpoint_synchroniser(self, client, db):
        _lot(db, "LOT-PERIME", 400)

        corps = client.post("/alertes/synchroniser").json()

        assert corps == {"ouvertures": 1, "mises_a_jour": 0, "resolutions": 0}


class TestDeduplicationEmail:
    def test_le_deuxieme_cycle_n_envoie_rien(self, client, db):
        from unittest.mock import patch

        from app.services import notifier

        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            notifier.verifier_et_notifier(["bresil"])
            notifier.verifier_et_notifier(["bresil"])

        assert mock_envoyer.call_count == 1

    def test_la_deduplication_survit_au_redemarrage(self, client, db):
        """Le vrai apport de la persistance : avant, le dict en mémoire était
        remis à zéro et un redémarrage renvoyait un e-mail déjà envoyé."""
        from unittest.mock import patch

        from app.services import notifier

        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            notifier.verifier_et_notifier(["bresil"])

        # Simule un redémarrage : aucun état en mémoire n'est conservé.
        import importlib
        importlib.reload(notifier)

        with patch("app.services.notifier.envoyer_email") as mock_apres:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 0
        mock_apres.assert_not_called()
