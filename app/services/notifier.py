"""Déclenchement de l'email récapitulatif d'alertes (cahier des charges III.4).

Règles : un récapitulatif est envoyé au responsable d'exploitation du pays
concerné s'il y a au moins une alerte active :
  - un lot dépasse 365 jours de stockage (péremption) ;
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

Dédoublonnage : un seul récap par pays est envoyé tant que la situation ne
change pas (même lots périmés, mêmes entrepôts en dépassement). Si une
nouvelle alerte apparaît ou qu'une alerte se résout, un nouveau récap reflète
l'état à jour. Cet état est gardé en mémoire du process (limite connue de ce
prototype : remis à zéro si l'API redémarre).
"""

import logging

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Lot, Mesure
from app.services.alertes import evaluer_mesure, recuperer_alertes
from app.services.email import MANAGER_EMAILS, SMTP_HOST, SMTP_PORT, construire_email_recap, envoyer_email

logger = logging.getLogger(__name__)

_dernier_recap_envoye: dict[str, frozenset[str]] = {}


def verifier_et_notifier(pays_liste: list[str] | None = None) -> int:
    """Vérifie l'état des alertes par pays et envoie un récap si la situation a changé.

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
            destinataire = MANAGER_EMAILS.get(pays)
            if not destinataire:
                logger.warning("Pas d'email de responsable configuré pour le pays %s", pays)
                continue

            lots_problematiques, _ = recuperer_alertes(db, pays)
            anomalies_seuils = _anomalies_dernieres_mesures(db, pays)

            if not lots_problematiques and not anomalies_seuils:
                _dernier_recap_envoye.pop(pays, None)
                continue

            signature = _signature(lots_problematiques, anomalies_seuils)
            if signature == _dernier_recap_envoye.get(pays):
                continue  # situation inchangée depuis le dernier récap envoyé

            sujet, corps = construire_email_recap(pays, lots_problematiques, anomalies_seuils)
            resultat = _envoyer_si_possible(destinataire, sujet, corps, pays)
            if resultat is None:
                return envoyes  # serveur SMTP inatteignable : on retentera au prochain cycle.
            if resultat:
                envoyes += 1
                _dernier_recap_envoye[pays] = signature
    finally:
        db.close()
    return envoyes


def _anomalies_dernieres_mesures(db, pays: str) -> list[tuple[Mesure, dict]]:
    """Anomalies (direction + sévérité) du DERNIER relevé de chaque entrepôt du pays."""
    entrepots = {l.entrepot_id for l in db.query(Lot).filter(Lot.pays == pays).all()}
    if not entrepots:
        return []

    sous_requete = (
        db.query(Mesure.entrepot_id, func.max(Mesure.timestamp).label("max_ts"))
        .filter(Mesure.entrepot_id.in_(entrepots))
        .group_by(Mesure.entrepot_id)
        .subquery()
    )
    dernieres_mesures = (
        db.query(Mesure)
        .join(
            sous_requete,
            (Mesure.entrepot_id == sous_requete.c.entrepot_id)
            & (Mesure.timestamp == sous_requete.c.max_ts),
        )
        .all()
    )

    resultat = []
    for mesure in dernieres_mesures:
        for anomalie in evaluer_mesure(mesure.temperature, mesure.humidity, pays):
            resultat.append((mesure, anomalie))
    return resultat


def _signature(lots_problematiques, anomalies_seuils) -> frozenset[str]:
    cles_lots = {f"lot-{lot.id}" for lot, _ in lots_problematiques}
    cles_seuils = {
        f"seuil-{mesure.entrepot_id}-{anomalie['grandeur']}-{anomalie['direction']}"
        for mesure, anomalie in anomalies_seuils
    }
    return frozenset(cles_lots | cles_seuils)


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
