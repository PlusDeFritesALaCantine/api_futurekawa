from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lot
from app.schemas import LotCreate, LotOut
from app.services.alertes import calculer_statut_lot

router = APIRouter(prefix="/lots", tags=["lots"])


@router.post("", response_model=LotOut, status_code=201)
def creer_lot(lot: LotCreate, db: Session = Depends(get_db)):
    if db.get(Lot, lot.id):
        raise HTTPException(status_code=409, detail="Lot déjà existant")
    db_lot = Lot(**lot.model_dump())
    db_lot.statut = calculer_statut_lot(lot.date_stockage)
    db.add(db_lot)
    db.commit()
    db.refresh(db_lot)
    return _enrichir(db_lot)


@router.get("", response_model=list[LotOut])
def lister_lots(pays: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Lot)
    if pays:
        q = q.filter(Lot.pays == pays)
    lots = q.order_by(Lot.date_stockage.asc()).all()
    return [_enrichir(l) for l in lots]


@router.get("/{lot_id}", response_model=LotOut)
def detail_lot(lot_id: str, db: Session = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot introuvable")
    return _enrichir(lot)


def _enrichir(lot: Lot) -> LotOut:
    statut = calculer_statut_lot(lot.date_stockage)
    lot.statut = statut
    return LotOut.model_validate(lot)
