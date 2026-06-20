"""Déclenchement des emails d'alerte (cahier des charges III.4).

Règles : un email est envoyé au responsable d'exploitation du pays concerné
dès qu'une NOUVELLE alerte apparaît :
  - un lot dépasse 365 jours de stockage (péremption) ;
  - une mesure température/humidité sort de la plage acceptable du pays.

Fréquence de vérification : appelée au démarrage de l'API puis toutes les
ALERT_CHECK_INTERVAL_SECONDS secondes (60s par défaut, voir app/main.py),
ainsi que manuellement via POST /alertes/notifier.

Dédoublonnage : chaque alerte (lot périmé ou mesure hors seuil) n'est notifiée
qu'une fois, via un ensemble de clés déjà notifiées gardé en mémoire du process.
Limite connue de ce prototype : cet état n'est pas persisté, il est donc remis
à zéro si l'API redémarre (un déploiement réel le stockerait en base, comme le
prévoit le champ `email_sent` du modèle Alerte de MQTT_Broker).
"""

import logging

from app.database import SessionLocal
from app.models import Lot
from app.services.alertes import recuperer_alertes
from app.services.email import MANAGER_EMAILS, construire_email_lot, construire_email_mesure, envoyer_email

logger = logging.getLogger(__name__)

_deja_notifies: set[str] = set()


def verifier_et_notifier(pays_liste: list[str] | None = None) -> int:
    """Vérifie les alertes et envoie un email pour toute alerte pas encore notifiée.

    Si pays_liste n'est pas fourni, vérifie tous les pays présents en base
    (fonctionne aussi bien en dev — un seul backend mutualisé pour 3 pays —
    qu'en architecture cible — un backend par pays, qui ne verra que les
    lots de son propre pays).

    Retourne le nombre d'emails effectivement envoyés.
    """
    db = SessionLocal()
    envoyes = 0
    try:
        if pays_liste is None:
            pays_liste = [row[0] for row in db.query(Lot.pays).distinct().all()]

        for pays in pays_liste:
            destinataire = MANAGER_EMAILS.get(pays)
            if not destinataire:
                logger.warning("Pas d'email de responsable configuré pour le pays %s", pays)
                continue

            lots_problematiques, mesures_hors_seuil = recuperer_alertes(db, pays)

            for lot, raison in lots_problematiques:
                cle = f"lot-{pays}-{lot.id}"
                if cle in _deja_notifies:
                    continue
                sujet, corps = construire_email_lot(pays, lot, raison)
                if _envoyer_si_possible(destinataire, sujet, corps, cle):
                    envoyes += 1

            for mesure, raison in mesures_hors_seuil:
                cle = f"mesure-{pays}-{mesure.id}"
                if cle in _deja_notifies:
                    continue
                sujet, corps = construire_email_mesure(pays, mesure, raison)
                if _envoyer_si_possible(destinataire, sujet, corps, cle):
                    envoyes += 1
    finally:
        db.close()
    return envoyes


def _envoyer_si_possible(destinataire: str, sujet: str, corps: str, cle: str) -> bool:
    try:
        envoyer_email(destinataire, sujet, corps)
    except Exception:
        logger.exception("Échec d'envoi de l'email d'alerte (%s)", cle)
        return False
    _deja_notifies.add(cle)
    logger.info("Email d'alerte envoyé pour %s à %s", cle, destinataire)
    return True
