from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.database import get_db
from app.models import Mesure
from app.schemas import MesureOut

router = APIRouter(prefix="/mesures", tags=["mesures"])


@router.get("", response_model=list[MesureOut])
def lister_mesures(
    entrepot_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Mesure).order_by(desc(Mesure.timestamp))
    if entrepot_id:
        q = q.filter(Mesure.entrepot_id == entrepot_id)
    return q.all()


@router.get("/latest", response_model=list[MesureOut])
def derniere_mesure_par_entrepot(db: Session = Depends(get_db)):
    from sqlalchemy import func

    sous_requete = (
        db.query(Mesure.entrepot_id, func.max(Mesure.timestamp).label("max_ts"))
        .group_by(Mesure.entrepot_id)
        .subquery()
    )
    mesures = (
        db.query(Mesure)
        .join(
            sous_requete,
            (Mesure.entrepot_id == sous_requete.c.entrepot_id)
            & (Mesure.timestamp == sous_requete.c.max_ts),
        )
        .all()
    )
    return mesures
