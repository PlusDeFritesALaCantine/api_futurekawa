from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class LotCreate(BaseModel):
    id: str
    pays: str
    exploitation: str
    entrepot_id: str
    date_stockage: date


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