from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models import Lot, Mesure
from app.services import notifier
from app.services.email import construire_email_lot, construire_email_mesure


def _lot(db, lot_id, delta_jours, pays="bresil"):
    lot = Lot(
        id=lot_id,
        pays=pays,
        exploitation="Fazenda Teste",
        entrepot_id=f"entrepot-{pays}-1",
        date_stockage=date.today() - timedelta(days=delta_jours),
        statut="conforme",
    )
    db.add(lot)
    db.commit()
    return lot


def _mesure(db, mid, temp, hum, entrepot_id="entrepot-bresil-1"):
    m = Mesure(
        id=mid,
        entrepot_id=entrepot_id,
        temperature=temp,
        humidity=hum,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(m)
    db.commit()
    return m


class TestContenuEmail:
    def test_email_lot_contient_id_et_raison(self, db):
        lot = _lot(db, "LOT-OLD", 400)
        sujet, corps = construire_email_lot("bresil", lot, "lot périmé (400 jours de stockage)")
        assert "LOT-OLD" in sujet
        assert "périmé" in corps
        assert lot.exploitation in corps

    def test_email_mesure_contient_entrepot_et_valeurs(self, db):
        mesure = _mesure(db, "M-HOT", 35.0, 55.0)
        sujet, corps = construire_email_mesure(
            "bresil", mesure, "température 35.0°C hors seuil [26.0-32.0°C]"
        )
        assert "entrepot-bresil-1" in sujet
        assert "35.0" in corps


class TestNotifier:
    def setup_method(self):
        notifier._deja_notifies.clear()

    def test_envoie_un_email_pour_lot_perime(self, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 1
        mock_envoyer.assert_called_once()
        destinataire, sujet, _corps = mock_envoyer.call_args[0]
        assert destinataire == notifier.MANAGER_EMAILS["bresil"]
        assert "LOT-PERIME" in sujet

    def test_envoie_un_email_pour_mesure_hors_seuil(self, db):
        # L'entrepôt n'est rattaché à un pays qu'à travers un lot existant
        # (Mesure n'a pas de colonne pays propre) — cf. recuperer_alertes().
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-HOT", 35.0, 55.0)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 1
        mock_envoyer.assert_called_once()

    def test_aucune_alerte_aucun_email(self, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-OK", 29.0, 55.0)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 0
        mock_envoyer.assert_not_called()

    def test_ne_renvoie_pas_deux_fois_la_meme_alerte(self, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            notifier.verifier_et_notifier(["bresil"])
            envoyes_second_passage = notifier.verifier_et_notifier(["bresil"])

        assert envoyes_second_passage == 0
        assert mock_envoyer.call_count == 1

    def test_echec_envoi_ne_marque_pas_comme_notifie(self, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email", side_effect=OSError("SMTP down")):
            envoyes = notifier.verifier_et_notifier(["bresil"])
        assert envoyes == 0

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes_retry = notifier.verifier_et_notifier(["bresil"])
        assert envoyes_retry == 1
        mock_envoyer.assert_called_once()

    def test_sans_pays_liste_detecte_les_pays_presents_en_base(self, db):
        _lot(db, "LOT-BR", 400, pays="bresil")
        _lot(db, "LOT-EQ", 400, pays="equateur")

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier()

        assert envoyes == 2
        assert mock_envoyer.call_count == 2


class TestEndpointNotifier:
    def setup_method(self):
        notifier._deja_notifies.clear()

    def test_post_notifier_envoie_les_alertes_en_attente(self, client, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            r = client.post("/alertes/notifier")

        assert r.status_code == 200
        assert r.json()["emails_envoyes"] == 1
        mock_envoyer.assert_called_once()
