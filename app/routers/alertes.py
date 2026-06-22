from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import AlertesResponse, AlerteLot, AlerteMesure, LotOut, MesureOut
from app.services.alertes import recuperer_alertes
from app.services.notifier import verifier_et_notifier

router = APIRouter(prefix="/alertes", tags=["alertes"])


@router.get("", response_model=AlertesResponse)
def lister_alertes(pays: Optional[str] = Query(None), db: Session = Depends(get_db)):
    # Les lots périmés sont toujours tous listés ; les mesures ne remontent ici
    # que si leur tier est "bas" ou "critique" (cf. evaluer_mesure) — les
    # mesures excellentes/bonnes/correctes ne sont pas des alertes.
    lots_problematiques, mesures_hors_seuil = recuperer_alertes(db, pays)
    return AlertesResponse(
        lots_problematiques=[
            AlerteLot(lot=LotOut.model_validate(lot), raison=raison)
            for lot, raison in lots_problematiques
        ],
        mesures_hors_seuil=[
            AlerteMesure(mesure=MesureOut.model_validate(mesure), raison=raison, severite=severite)
            for mesure, raison, severite in mesures_hors_seuil
        ],
    )


@router.post("/notifier")
def notifier_maintenant():
    """Déclenche immédiatement une vérification + envoi d'emails (hors cycle périodique).

    Utile en démo pour ne pas attendre ALERT_CHECK_INTERVAL_SECONDS.
    """
    emails_envoyes = verifier_et_notifier()
    return {"emails_envoyes": emails_envoyes}
