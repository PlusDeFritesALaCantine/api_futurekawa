"""Consultation des relevés capteur.

`GET /mesures` ne déverse plus toute la table. Avant, l'endpoint renvoyait
l'intégralité des mesures (948 lignes en démo, sans borne en production) et le
front filtrait puis paginait côté navigateur : chaque changement de pays
transférait l'historique complet pour n'en afficher que 30 lignes.

L'endpoint est désormais borné et filtrant : `limit` est plafonné, et les
filtres entrepôt / lot / plage de dates sont appliqués en SQL. La réponse est
une enveloppe {items, total, limit, offset} — `total` permet au front de
paginer sans tout charger.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lot, Mesure
from app.schemas import MesureOut, PageMesures

router = APIRouter(prefix="/mesures", tags=["mesures"])

LIMITE_PAR_DEFAUT = 100
LIMITE_MAX = 1000


def _entrepots_du_pays(db: Session, pays: str) -> set[str]:
    return {l.entrepot_id for l in db.query(Lot).filter(Lot.pays == pays).all()}


@router.get("", response_model=PageMesures)
def lister_mesures(
    entrepot_id: Optional[str] = Query(None),
    lot_id: Optional[str] = Query(None),
    pays: Optional[str] = Query(None),
    debut: Optional[datetime] = Query(None, description="Borne basse sur timestamp (incluse)"),
    fin: Optional[datetime] = Query(None, description="Borne haute sur timestamp (incluse)"),
    limit: int = Query(LIMITE_PAR_DEFAUT, ge=1, le=LIMITE_MAX),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Mesure)

    if entrepot_id:
        q = q.filter(Mesure.entrepot_id == entrepot_id)
    if lot_id:
        q = q.filter(Mesure.lot_id == lot_id)
    if pays:
        entrepots = _entrepots_du_pays(db, pays)
        if not entrepots:
            return PageMesures(items=[], total=0, limit=limit, offset=offset)
        q = q.filter(Mesure.entrepot_id.in_(entrepots))
    if debut:
        q = q.filter(Mesure.timestamp >= debut)
    if fin:
        q = q.filter(Mesure.timestamp <= fin)

    total = q.count()
    items = q.order_by(desc(Mesure.timestamp)).offset(offset).limit(limit).all()
    return PageMesures(items=items, total=total, limit=limit, offset=offset)


@router.get("/latest", response_model=list[MesureOut])
def derniere_mesure_par_entrepot(pays: Optional[str] = Query(None), db: Session = Depends(get_db)):
    sous_requete = (
        db.query(Mesure.entrepot_id, func.max(Mesure.timestamp).label("max_ts"))
        .group_by(Mesure.entrepot_id)
        .subquery()
    )
    q = db.query(Mesure).join(
        sous_requete,
        (Mesure.entrepot_id == sous_requete.c.entrepot_id)
        & (Mesure.timestamp == sous_requete.c.max_ts),
    )
    if pays:
        q = q.filter(Mesure.entrepot_id.in_(_entrepots_du_pays(db, pays)))
    return q.all()
