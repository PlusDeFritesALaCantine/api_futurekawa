"""Paramétrage métier modifiable depuis le site.

Expose la table `pays` : seuils de conservation, durée de péremption et
destinataire des alertes. Toute écriture invalide le cache de
services/parametres.py, donc la modification est prise en compte dès le cycle
d'évaluation suivant — sans redémarrage.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pays
from app.schemas import ParametresPaysOut, ParametresPaysUpdate
from app.services import parametres as svc

router = APIRouter(prefix="/parametres", tags=["parametres"])


@router.get("/pays", response_model=list[ParametresPaysOut])
def lister_parametres(db: Session = Depends(get_db)):
    svc.initialiser(db)
    return db.query(Pays).order_by(Pays.slug).all()


@router.get("/pays/{slug}", response_model=ParametresPaysOut)
def detail_parametres(slug: str, db: Session = Depends(get_db)):
    svc.initialiser(db)
    ligne = db.get(Pays, slug)
    if ligne is None:
        raise HTTPException(status_code=404, detail=f"Pays '{slug}' inconnu")
    return ligne


@router.patch("/pays/{slug}", response_model=ParametresPaysOut)
def modifier_parametres(
    slug: str, maj: ParametresPaysUpdate, db: Session = Depends(get_db)
):
    """Mise à jour partielle : seuls les champs présents dans la requête changent.

    `exclude_unset=True` est ce qui garantit la fusion. Sans lui, un PATCH
    n'envoyant que la péremption remettrait tous les seuils à leur valeur par
    défaut Pydantic — un écrasement silencieux difficile à diagnostiquer.
    """
    svc.initialiser(db)
    ligne = db.get(Pays, slug)
    if ligne is None:
        raise HTTPException(status_code=404, detail=f"Pays '{slug}' inconnu")

    champs = maj.model_dump(exclude_unset=True)
    if not champs:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier")

    for cle, valeur in champs.items():
        setattr(ligne, cle, valeur)

    db.commit()
    db.refresh(ligne)
    # recharger(), pas invalider() : un cache vidé retomberait silencieusement
    # sur les valeurs par défaut jusqu'au prochain passage en base.
    svc.recharger(db)
    return ligne
