from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lot, Mesure
from app.schemas import AlertesResponse, AlerteLot, AlerteMesure, LotOut, MesureOut
from app.services.alertes import raison_lot_problematique, est_mesure_hors_seuil

router = APIRouter(prefix="/alertes", tags=["alertes"])


@router.get("", response_model=AlertesResponse)
def lister_alertes(db: Session = Depends(get_db)):
    lots = db.query(Lot).all()
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
        hors_seuil, raison = est_mesure_hors_seuil(mesure.temperature, mesure.humidity)
        if hors_seuil:
            mesures_hors_seuil.append(
                AlerteMesure(mesure=MesureOut.model_validate(mesure), raison=raison)
            )

    return AlertesResponse(
        lots_problematiques=lots_problematiques,
        mesures_hors_seuil=mesures_hors_seuil,
    )
