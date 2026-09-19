from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models import Lot, Mesure
from app.services import notifier
from app.services.alertes import evaluer_mesure
from app.services.email import construire_email_recap


def _lot(db, lot_id, delta_jours, pays="bresil", entrepot_id="entrepot-bresil-1"):
    lot = Lot(
        id=lot_id,
        pays=pays,
        exploitation="Fazenda Teste",
        entrepot_id=entrepot_id,
        date_stockage=date.today() - timedelta(days=delta_jours),
        statut="conforme",
    )
    db.add(lot)
    db.commit()
    return lot


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
    return m


class TestEvaluerMesure:
    def test_direction_trop_elevee(self, db):
        anomalies = evaluer_mesure(40.0, 55.0, "bresil")
        assert len(anomalies) == 1
        assert anomalies[0]["direction"] == "trop élevée"
        assert anomalies[0]["tier"] == "critique"

    def test_direction_trop_basse(self, db):
        anomalies = evaluer_mesure(15.0, 55.0, "bresil")
        assert anomalies[0]["direction"] == "trop basse"

    def test_conforme_aucune_anomalie(self, db):
        assert evaluer_mesure(29.0, 55.0, "bresil") == []


class TestEmailRecap:
    def test_recap_liste_chaque_lot_perime(self, db):
        lot = _lot(db, "LOT-OLD", 400)
        sujet, corps = construire_email_recap("bresil", [(lot, "Lot périmé : stocké depuis 400 jours")], [])
        assert "1 lot(s) périmé(s)" in sujet
        assert "LOT-OLD" in corps

    def test_recap_liste_les_depassements_de_seuil_avec_direction(self, db):
        mesure = _mesure(db, "M-HOT", 40.0, 55.0)
        anomalie = evaluer_mesure(40.0, 55.0, "bresil")[0]
        sujet, corps = construire_email_recap("bresil", [], [(mesure, anomalie)])
        assert "1 seuil(s)" in sujet
        assert "trop élevée" in corps
        assert mesure.entrepot_id in corps

    def test_recap_sans_alerte(self, db):
        sujet, corps = construire_email_recap("bresil", [], [])
        assert "0 lot(s)" in sujet
        assert "Aucun." in corps


class TestNotifier:
    # Plus de reset d'état mémoire : la déduplication des envois vit désormais
    # dans la colonne alertes.email_envoye_le, et la fixture setup_db recrée
    # les tables avant chaque test.

    def test_un_seul_email_pour_lot_perime_et_seuil_combines(self, db):
        _lot(db, "LOT-PERIME", 400)
        _mesure(db, "M-HOT", 40.0, 55.0, entrepot_id="entrepot-bresil-2")
        _lot(db, "LOT-AUTRE", 10, entrepot_id="entrepot-bresil-2")

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 1
        mock_envoyer.assert_called_once()
        destinataire, sujet, corps = mock_envoyer.call_args[0]
        assert destinataire == notifier.MANAGER_EMAILS["bresil"]
        assert "LOT-PERIME" in corps
        assert "entrepot-bresil-2" in corps

    def test_aucune_alerte_aucun_email(self, db):
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-OK", 29.0, 55.0)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 0
        mock_envoyer.assert_not_called()

    def test_ne_renvoie_pas_si_situation_inchangee(self, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            notifier.verifier_et_notifier(["bresil"])
            envoyes_second_passage = notifier.verifier_et_notifier(["bresil"])

        assert envoyes_second_passage == 0
        assert mock_envoyer.call_count == 1

    def test_renvoie_si_une_nouvelle_alerte_apparait(self, db):
        _lot(db, "LOT-PERIME-1", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            notifier.verifier_et_notifier(["bresil"])
            _lot(db, "LOT-PERIME-2", 410)
            envoyes_second_passage = notifier.verifier_et_notifier(["bresil"])

        assert envoyes_second_passage == 1
        assert mock_envoyer.call_count == 2

    def test_seul_le_dernier_releve_de_chaque_entrepot_compte(self, db):
        # Relevé critique ancien, mais le dernier relevé est revenu dans les clous :
        # le récap ne doit pas signaler cet entrepôt.
        _lot(db, "LOT-OK", 10)
        _mesure(db, "M-ANCIEN-CRITIQUE", 45.0, 55.0, quand=datetime.now(timezone.utc) - timedelta(hours=2))
        _mesure(db, "M-RECENT-OK", 29.0, 55.0, quand=datetime.now(timezone.utc))

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier(["bresil"])

        assert envoyes == 0
        mock_envoyer.assert_not_called()

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
        _lot(db, "LOT-BR", 400, pays="bresil", entrepot_id="entrepot-bresil-1")
        _lot(db, "LOT-EQ", 400, pays="equateur", entrepot_id="entrepot-equateur-1")

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            envoyes = notifier.verifier_et_notifier()

        assert envoyes == 2
        assert mock_envoyer.call_count == 2


class TestEndpointNotifier:
    def test_post_notifier_envoie_le_recap(self, client, db):
        _lot(db, "LOT-PERIME", 400)

        with patch("app.services.notifier.envoyer_email") as mock_envoyer:
            r = client.post("/alertes/notifier")

        assert r.status_code == 200
        assert r.json()["emails_envoyes"] == 1
        mock_envoyer.assert_called_once()
