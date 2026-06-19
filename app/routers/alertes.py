from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lot, Mesure
from app.schemas import AlertesResponse, AlerteLot, AlerteMesure, LotOut, MesureOut
from app.services.alertes import (
    raison_lot_problematique,
    est_mesure_hors_seuil,
    PAYS_PAR_DEFAUT,
)

router = APIRouter(prefix="/alertes", tags=["alertes"])


@router.get("", response_model=AlertesResponse)
def lister_alertes(pays: Optional[str] = Query(None), db: Session = Depends(get_db)):
    tous_les_lots = db.query(Lot).all()
    pays_par_entrepot = {lot.entrepot_id: lot.pays for lot in tous_les_lots}

    lots = [l for l in tous_les_lots if not pays or l.pays == pays]
    entrepots_du_pays = {l.entrepot_id for l in lots} if pays else None

    lots_problematiques = []
    for lot in lots:
        est_pb, raison = raison_lot_problematique(lot.date_stockage)
        if est_pb:
            lot.statut = "perime"
            lots_problematiques.append(
                AlerteLot(lot=LotOut.model_validate(lot), raison=raison)
            )

    mesures = db.query(Mesure).all()
    mesures_hors_seuil = []
    for mesure in mesures:
        if entrepots_du_pays is not None and mesure.entrepot_id not in entrepots_du_pays:
            continue
        pays_mesure = pays_par_entrepot.get(mesure.entrepot_id, PAYS_PAR_DEFAUT)
        hors_seuil, raison = est_mesure_hors_seuil(mesure.temperature, mesure.humidity, pays_mesure)
        if hors_seuil:
            mesures_hors_seuil.append(
                AlerteMesure(mesure=MesureOut.model_validate(mesure), raison=raison)
            )

    return AlertesResponse(
        lots_problematiques=lots_problematiques,
        mesures_hors_seuil=mesures_hors_seuil,
    )
