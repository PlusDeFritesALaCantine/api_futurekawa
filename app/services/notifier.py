"""Déclenchement de l'email récapitulatif d'alertes (cahier des charges III.4).

Règles : un récapitulatif est envoyé au responsable d'exploitation du pays
concerné s'il existe au moins une alerte ouverte dont l'e-mail n'est pas encore
parti :
  - un lot dépasse la durée de péremption paramétrée pour son pays ;
  - le dernier relevé température/humidité d'un entrepôt est classé "bas" ou
    "critique" sur l'échelle de qualité (excellent/bon/correct/bas/critique,
    cf. app/services/alertes.py) — les tiers excellent/bon/correct ne
    déclenchent jamais d'email.

Contrairement à une notification par alerte individuelle, on ne regarde que
le DERNIER relevé de chaque entrepôt pour les seuils — les alertes reflètent
l'état courant ("les infos tous les X temps"), pas l'historique complet.

Fréquence de vérification : appelée au démarrage de l'API puis toutes les
ALERT_CHECK_INTERVAL_SECONDS secondes (60s par défaut, voir app/main.py),
ainsi que manuellement via POST /alertes/notifier.

Dédoublonnage : porté par la colonne `alertes.email_envoye_le`, pas par un
dictionnaire en mémoire. Tant qu'aucune alerte nouvelle n'apparaît, aucun
nouveau récap ne part ; et, contrairement à la version précédente, l'état
survit au redémarrage de l'API — un redémarrage ne provoque plus un second
envoi pour des alertes déjà notifiées.

Le destinataire et l'activation des e-mails viennent de la table `pays`
(modifiables depuis le site) ; MANAGER_EMAILS ne sert plus que de repli
lorsqu'aucun paramétrage n'existe encore.
"""

import logging

from app.database import SessionLocal
from app.models import Lot
from app.services import gestion_alertes, parametres
from app.services.alertes import (
    dernieres_mesures_par_entrepot, evaluer_mesure, recuperer_alertes,
)
from app.services.email import (
    MANAGER_EMAILS, SMTP_HOST, SMTP_PORT, construire_email_recap, envoyer_email,
)

logger = logging.getLogger(__name__)


def verifier_et_notifier(pays_liste: list[str] | None = None) -> int:
    """Vérifie l'état des alertes par pays et envoie un récap si besoin.

    Si pays_liste n'est pas fourni, vérifie tous les pays présents en base
    (fonctionne aussi bien en dev — un seul backend mutualisé pour 3 pays —
    qu'en architecture cible — un backend par pays, qui ne verra que les
    lots de son propre pays).

    Retourne le nombre de récaps effectivement envoyés.
    """
    db = SessionLocal()
    envoyes = 0
    try:
        if pays_liste is None:
            pays_liste = [row[0] for row in db.query(Lot.pays).distinct().all()]

        for pays in pays_liste:
            params = parametres.get_db(db, pays)
            if not params.alertes_actives:
                continue

            destinataire = params.email_responsable or MANAGER_EMAILS.get(pays)
            if not destinataire:
                logger.warning("Pas d'email de responsable configuré pour le pays %s", pays)
                continue

            # Aligne d'abord la table des alertes sur l'état courant : c'est elle
            # qui dit ensuite ce qui reste à notifier.
            gestion_alertes.synchroniser(db, pays)
            a_notifier = gestion_alertes.alertes_sans_email(db, pays)
            if not a_notifier:
                continue

            lots_problematiques, _ = recuperer_alertes(db, pays)
            anomalies_seuils = _anomalies_dernieres_mesures(db, pays)

            sujet, corps = construire_email_recap(pays, lots_problematiques, anomalies_seuils)
            resultat = _envoyer_si_possible(destinataire, sujet, corps, pays)
            if resultat is None:
                return envoyes  # serveur SMTP inatteignable : on retentera au prochain cycle.
            if resultat:
                envoyes += 1
                gestion_alertes.marquer_email_envoye(db, a_notifier)
    finally:
        db.close()
    return envoyes


def _anomalies_dernieres_mesures(db, pays: str) -> list[tuple]:
    """Anomalies (direction + sévérité) du DERNIER relevé de chaque entrepôt du pays."""
    entrepots = {l.entrepot_id for l in db.query(Lot).filter(Lot.pays == pays).all()}
    resultat = []
    for mesure in dernieres_mesures_par_entrepot(db, entrepots):
        for anomalie in evaluer_mesure(mesure.temperature, mesure.humidity, pays):
            resultat.append((mesure, anomalie))
    return resultat


def _envoyer_si_possible(destinataire: str, sujet: str, corps: str, pays: str) -> bool | None:
    """Envoie le récap. Retourne True (envoyé), False (échec ponctuel) ou None
    (serveur SMTP inatteignable — inutile de retenter les pays suivants ce cycle)."""
    try:
        envoyer_email(destinataire, sujet, corps)
    except OSError as exc:
        logger.warning(
            "Serveur SMTP inatteignable (%s:%s) — récap en attente, retenté au prochain cycle : %s",
            SMTP_HOST, SMTP_PORT, exc,
        )
        return None
    except Exception:
        logger.exception("Échec d'envoi du récap d'alertes pour %s", pays)
        return False
    logger.info("Récap d'alertes envoyé pour %s à %s", pays, destinataire)
    return True
