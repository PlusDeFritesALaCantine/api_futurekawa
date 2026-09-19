from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class LotCreate(BaseModel):
    id: str
    pays: str
    exploitation: str
    entrepot_id: str
    date_stockage: date


class LotUpdate(BaseModel):
    """Mise à jour partielle d'un lot. Utilisée par la synchronisation descendante
    depuis Odoo et par le siège. `statut` n'est volontairement pas modifiable :
    il est recalculé à partir de la date de stockage et de la péremption du pays."""

    pays: Optional[str] = Field(None, min_length=1, max_length=50)
    exploitation: Optional[str] = Field(None, min_length=1, max_length=100)
    entrepot_id: Optional[str] = Field(None, min_length=1, max_length=50)
    date_stockage: Optional[date] = None


class LotOut(BaseModel):
    id: str
    pays: str
    exploitation: str
    entrepot_id: str
    date_stockage: date
    statut: str

    model_config = {"from_attributes": True}


class MesureCreate(BaseModel):
    id: str
    entrepot_id: str
    temperature: float
    humidity: float
    lot_id: Optional[str] = None


class MesureOut(BaseModel):
    id: str
    entrepot_id: str
    temperature: float
    humidity: float
    timestamp: datetime
    lot_id: Optional[str] = None
    
    lot: Optional[LotOut] = None

    model_config = {"from_attributes": True}


class AlerteLot(BaseModel):
    lot: LotOut
    raison: str


class AlerteMesure(BaseModel):
    mesure: MesureOut
    raison: str
    severite: str


class AlertesResponse(BaseModel):
    lots_problematiques: list[AlerteLot]
    mesures_hors_seuil: list[AlerteMesure]

# --- Paramétrage par pays -------------------------------------------------

class ParametresPaysOut(BaseModel):
    slug: str
    nom: str
    temperature_ideale: float
    temperature_tolerance: float
    humidite_ideale: float
    humidite_tolerance: float
    peremption_jours: int
    email_responsable: str
    alertes_actives: bool

    model_config = {"from_attributes": True}


class ParametresPaysUpdate(BaseModel):
    """Mise à jour partielle : seuls les champs fournis sont écrasés.

    Tous les champs sont optionnels et le routeur applique model_dump(exclude_unset=True) :
    un PATCH qui ne porte que la péremption ne remet pas les seuils à zéro.
    """

    nom: Optional[str] = Field(None, min_length=1, max_length=60)
    temperature_ideale: Optional[float] = Field(None, ge=-50, le=80)
    temperature_tolerance: Optional[float] = Field(None, gt=0, le=50)
    humidite_ideale: Optional[float] = Field(None, ge=0, le=100)
    humidite_tolerance: Optional[float] = Field(None, gt=0, le=50)
    peremption_jours: Optional[int] = Field(None, gt=0, le=3650)
    email_responsable: Optional[str] = Field(None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    alertes_actives: Optional[bool] = None


# --- Alertes persistées ---------------------------------------------------

class AlerteOut(BaseModel):
    id: str
    pays: str
    entrepot_id: str
    lot_id: Optional[str] = None
    mesure_id: Optional[str] = None
    type: str
    severite: str
    message: str
    declenchee_le: Optional[datetime] = None
    email_envoye_le: Optional[datetime] = None
    acquittee_le: Optional[datetime] = None
    acquittee_par: Optional[str] = None
    resolue_le: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @property
    def statut(self) -> str:
        if self.resolue_le is not None:
            return "resolue"
        return "acquittee" if self.acquittee_le is not None else "ouverte"


class PageAlertes(BaseModel):
    items: list[AlerteOut]
    total: int
    limit: int
    offset: int


class AcquittementIn(BaseModel):
    par: Optional[str] = Field(None, max_length=120)


class SynchroAlertesOut(BaseModel):
    ouvertures: int
    mises_a_jour: int
    resolutions: int


# --- Pagination des mesures ----------------------------------------------

class PageMesures(BaseModel):
    items: list[MesureOut]
    total: int
    limit: int
    offset: int
