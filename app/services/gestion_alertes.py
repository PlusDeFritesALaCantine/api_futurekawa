"""Cycle de vie des alertes persistées : ouverture, acquittement, résolution.

Le calcul des anomalies reste dans services/alertes.py (fonctions pures,
testables sans base). Ce module fait le pont entre ce calcul, refait à chaque
cycle, et la table `alertes` qui garde une trace :

  état courant calculé  ->  synchroniser()  ->  table alertes

`synchroniser()` est idempotent. À chaque appel il compare les anomalies
constatées aux alertes ouvertes en base :

  - anomalie présente, pas d'alerte ouverte  -> ouverture
  - anomalie présente, alerte déjà ouverte   -> mise à jour (sévérité, message)
  - alerte ouverte, anomalie disparue        -> résolution automatique

L'unicité d'une alerte ouverte est garantie par l'index unique partiel sur
`cle_dedup` (cf. models.Alerte), pas par une structure en mémoire : deux
process, ou un redémarrage en plein cycle, ne peuvent pas créer de doublon.

Acquitter n'est pas résoudre. Un humain acquitte depuis le site pour dire
« je m'en occupe » ; l'alerte reste ouverte et continue d'être comptée tant que
l'anomalie physique n'a pas disparu des relevés.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models import Alerte
from app.services.alertes import recuperer_alertes

logger = logging.getLogger(__name__)

STATUTS = ("ouverte", "acquittee", "resolue")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def cle_mesure(type_alerte: str, entrepot_id: str) -> str:
    return f"{type_alerte}:{entrepot_id}"


def cle_peremption(entrepot_id: str, lot_id: str) -> str:
    return f"peremption:{entrepot_id}:{lot_id}"


def _attendues(db, pays: str | None) -> dict[str, dict]:
    """Les alertes qui *devraient* être ouvertes au vu de l'état courant.

    Une entrée par couple (anomalie, entrepôt) : un entrepôt dont la température
    et l'humidité dérivent toutes les deux produit deux alertes distinctes, pour
    qu'on puisse en résoudre une sans fermer l'autre.
    """
    from app.services.alertes import evaluer_mesure

    lots_problematiques, _ = recuperer_alertes(db, pays)
    attendues: dict[str, dict] = {}

    for lot, raison in lots_problematiques:
        cle = cle_peremption(lot.entrepot_id, lot.id)
        attendues[cle] = {
            "cle_dedup": cle,
            "pays": lot.pays,
            "entrepot_id": lot.entrepot_id,
            "lot_id": lot.id,
            "mesure_id": None,
            "type": "peremption",
            "severite": "critique",
            "message": raison[:255],
        }

    from app.models import Lot
    from app.services.alertes import dernieres_mesures_par_entrepot

    tous_les_lots = db.query(Lot).all()
    pays_par_entrepot = {l.entrepot_id: l.pays for l in tous_les_lots}
    entrepots = (
        {l.entrepot_id for l in tous_les_lots if l.pays == pays} if pays else None
    )

    for mesure in dernieres_mesures_par_entrepot(db, entrepots):
        pays_mesure = pays_par_entrepot.get(mesure.entrepot_id)
        if pays_mesure is None:
            # Entrepôt sans lot rattaché (sessions capteur) : pas de pays connu,
            # on ne devine pas — l'anomalie reste visible dans /alertes calculées.
            continue
        for anomalie in evaluer_mesure(mesure.temperature, mesure.humidity, pays_mesure):
            cle = cle_mesure(anomalie["type"], mesure.entrepot_id)
            attendues[cle] = {
                "cle_dedup": cle,
                "pays": pays_mesure,
                "entrepot_id": mesure.entrepot_id,
                "lot_id": None,
                "mesure_id": mesure.id,
                "type": anomalie["type"],
                "severite": "critique" if anomalie["tier"] == "critique" else "bas",
                "message": anomalie["raison"][:255],
            }

    return attendues


def synchroniser(db, pays: str | None = None) -> dict[str, int]:
    """Aligne la table `alertes` sur l'état courant. Retourne un compte-rendu."""
    attendues = _attendues(db, pays)

    q = db.query(Alerte).filter(Alerte.resolue_le.is_(None))
    if pays:
        q = q.filter(Alerte.pays == pays)
    ouvertes = {a.cle_dedup: a for a in q.all()}

    ouvertures = mises_a_jour = resolutions = 0

    for cle, champs in attendues.items():
        existante = ouvertes.get(cle)
        if existante is None:
            db.add(Alerte(id=str(uuid.uuid4()), declenchee_le=_maintenant(), **champs))
            ouvertures += 1
            continue
        if (
            existante.severite != champs["severite"]
            or existante.message != champs["message"]
            or existante.mesure_id != champs["mesure_id"]
        ):
            existante.severite = champs["severite"]
            existante.message = champs["message"]
            existante.mesure_id = champs["mesure_id"]
            mises_a_jour += 1

    for cle, alerte in ouvertes.items():
        if cle not in attendues:
            alerte.resolue_le = _maintenant()
            resolutions += 1

    try:
        db.commit()
    except IntegrityError:
        # Course avec un autre process sur l'index unique partiel : l'alerte a
        # déjà été ouverte à côté, il n'y a rien à réparer.
        db.rollback()
        logger.info("Synchronisation des alertes concurrente, cycle ignoré")
        return {"ouvertures": 0, "mises_a_jour": 0, "resolutions": 0}

    return {
        "ouvertures": ouvertures,
        "mises_a_jour": mises_a_jour,
        "resolutions": resolutions,
    }


def lister(
    db,
    pays: str | None = None,
    statut: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Alerte], int]:
    q = db.query(Alerte)
    if pays:
        q = q.filter(Alerte.pays == pays)
    if statut == "ouverte":
        q = q.filter(Alerte.resolue_le.is_(None), Alerte.acquittee_le.is_(None))
    elif statut == "acquittee":
        q = q.filter(Alerte.resolue_le.is_(None), Alerte.acquittee_le.isnot(None))
    elif statut == "resolue":
        q = q.filter(Alerte.resolue_le.isnot(None))

    total = q.count()
    lignes = (
        q.order_by(Alerte.declenchee_le.desc()).offset(offset).limit(limit).all()
    )
    return lignes, total


def acquitter(db, alerte_id: str, par: str | None = None) -> Alerte | None:
    alerte = db.get(Alerte, alerte_id)
    if alerte is None or alerte.resolue_le is not None:
        return None
    alerte.acquittee_le = _maintenant()
    alerte.acquittee_par = par
    db.commit()
    db.refresh(alerte)
    return alerte


def resoudre(db, alerte_id: str) -> Alerte | None:
    """Résolution manuelle depuis le site.

    Si l'anomalie est toujours présente dans les relevés, le prochain cycle de
    synchronisation rouvrira une alerte : c'est voulu, la base ne doit pas
    prétendre qu'un entrepôt va bien parce que quelqu'un a cliqué.
    """
    alerte = db.get(Alerte, alerte_id)
    if alerte is None or alerte.resolue_le is not None:
        return None
    alerte.resolue_le = _maintenant()
    db.commit()
    db.refresh(alerte)
    return alerte


def marquer_email_envoye(db, alertes: list[Alerte]) -> None:
    horodatage = _maintenant()
    for alerte in alertes:
        alerte.email_envoye_le = horodatage
    db.commit()


def alertes_sans_email(db, pays: str) -> list[Alerte]:
    """Alertes ouvertes pour lesquelles aucun e-mail n'est encore parti.

    C'est ce qui remplace le dict `_dernier_recap_envoye` en mémoire : la
    déduplication des envois est désormais portée par une colonne, donc elle
    survit au redémarrage de l'API.
    """
    return (
        db.query(Alerte)
        .filter(
            Alerte.pays == pays,
            Alerte.resolue_le.is_(None),
            Alerte.email_envoye_le.is_(None),
        )
        .order_by(Alerte.declenchee_le.asc())
        .all()
    )
