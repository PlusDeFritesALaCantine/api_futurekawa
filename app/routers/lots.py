from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lot, Mesure
from app.schemas import LotCreate, LotOut, LotUpdate, MesureOut
from app.services.alertes import calculer_statut_lot

router = APIRouter(prefix="/lots", tags=["lots"])


@router.post("", response_model=LotOut, status_code=201)
def creer_lot(lot: LotCreate, db: Session = Depends(get_db)):
    if db.get(Lot, lot.id):
        raise HTTPException(status_code=409, detail="Lot déjà existant")
    db_lot = Lot(**lot.model_dump())
    db_lot.statut = calculer_statut_lot(lot.date_stockage, lot.pays)
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


@router.get("/{lot_id}/mesures", response_model=list[MesureOut])
def lister_mesures_par_lot(lot_id: str, db: Session = Depends(get_db)):
    """Récupère l'historique complet des mesures enregistrées pour un lot spécifique."""
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot introuvable")
    
    return lot.mesures


@router.patch("/{lot_id}", response_model=LotOut)
def modifier_lot(lot_id: str, maj: LotUpdate, db: Session = Depends(get_db)):
    """Mise à jour partielle : seuls les champs fournis sont écrasés.

    `exclude_unset=True` est ce qui garantit la fusion — un PATCH ne portant que
    la date de stockage ne doit pas vider l'exploitation.
    """
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot introuvable")

    champs = maj.model_dump(exclude_unset=True)
    if not champs:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier")

    for cle, valeur in champs.items():
        setattr(lot, cle, valeur)

    db.commit()
    db.refresh(lot)
    return _enrichir(lot)


@router.delete("/{lot_id}", status_code=204)
def supprimer_lot(lot_id: str, db: Session = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot introuvable")
    db.delete(lot)
    db.commit()


def _enrichir(lot: Lot) -> LotOut:
    # La péremption est paramétrée par pays : un lot colombien ne se juge pas
    # avec la durée du Brésil.
    lot.statut = calculer_statut_lot(lot.date_stockage, lot.pays)
    return LotOut.model_validate(lot)