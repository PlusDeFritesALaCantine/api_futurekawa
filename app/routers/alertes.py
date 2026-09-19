from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AcquittementIn, AlerteMesure, AlerteOut, AlertesResponse, AlerteLot,
    PageAlertes, SynchroAlertesOut,
)
from app.services import gestion_alertes
from app.services.alertes import recuperer_alertes

router = APIRouter(prefix="/alertes", tags=["alertes"])


@router.get("", response_model=AlertesResponse)
def lister_alertes(pays: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Vue calculée de l'état courant — inchangée, c'est le contrat du front.

    Ne retourne que les anomalies actives : les mesures excellentes/bonnes/
    correctes ne sont pas des alertes. Pour l'historique, la prise en charge et
    la résolution, voir GET /alertes/journal.
    """
    lots_problematiques, mesures_hors_seuil = recuperer_alertes(db, pays)
    return AlertesResponse(
        lots_problematiques=[
            AlerteLot(lot=lot, raison=raison) for lot, raison in lots_problematiques
        ],
        mesures_hors_seuil=[
            AlerteMesure(mesure=mesure, raison=raison, severite=severite)
            for mesure, raison, severite in mesures_hors_seuil
        ],
    )


@router.get("/journal", response_model=PageAlertes)
def journal_alertes(
    pays: Optional[str] = Query(None),
    statut: Optional[str] = Query(None, pattern="^(ouverte|acquittee|resolue)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Alertes persistées, avec leur cycle de vie. Paginé."""
    items, total = gestion_alertes.lister(db, pays, statut, limit, offset)
    return PageAlertes(items=items, total=total, limit=limit, offset=offset)


@router.post("/synchroniser", response_model=SynchroAlertesOut)
def synchroniser_alertes(
    pays: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Aligne la table des alertes sur l'état courant des relevés.

    Appelée automatiquement par la boucle périodique ; exposée pour pouvoir la
    déclencher à la demande pendant une démonstration.
    """
    return SynchroAlertesOut(**gestion_alertes.synchroniser(db, pays))


@router.patch("/{alerte_id}/acquitter", response_model=AlerteOut)
def acquitter_alerte(
    alerte_id: str, corps: AcquittementIn | None = None, db: Session = Depends(get_db)
):
    """Prise en charge : l'alerte reste ouverte, mais on sait qui s'en occupe."""
    alerte = gestion_alertes.acquitter(db, alerte_id, (corps.par if corps else None))
    if alerte is None:
        raise HTTPException(status_code=404, detail="Alerte introuvable ou déjà résolue")
    return alerte


@router.patch("/{alerte_id}/resoudre", response_model=AlerteOut)
def resoudre_alerte(alerte_id: str, db: Session = Depends(get_db)):
    """Clôture manuelle. Si l'anomalie persiste, le cycle suivant rouvrira une alerte."""
    alerte = gestion_alertes.resoudre(db, alerte_id)
    if alerte is None:
        raise HTTPException(status_code=404, detail="Alerte introuvable ou déjà résolue")
    return alerte


@router.post("/notifier")
def notifier_maintenant():
    """Déclenche immédiatement une vérification + envoi d'emails (hors cycle périodique).

    Utile en démo pour ne pas attendre ALERT_CHECK_INTERVAL_SECONDS.
    """
    from app.services.notifier import verifier_et_notifier

    return {"emails_envoyes": verifier_et_notifier()}
