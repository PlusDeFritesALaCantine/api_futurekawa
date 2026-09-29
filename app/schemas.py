from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class BatchCreate(BaseModel):
    id: str
    country: str
    farm: str
    warehouse_id: str
    storage_date: date


class BatchUpdate(BaseModel):
    """Partial update of a batch. Used by downstream synchronisation from Odoo
    and by the head office. `status` is deliberately not editable: it is
    recomputed from the storage date and the shelf life of the country."""

    country: Optional[str] = Field(None, min_length=1, max_length=50)
    farm: Optional[str] = Field(None, min_length=1, max_length=100)
    warehouse_id: Optional[str] = Field(None, min_length=1, max_length=50)
    storage_date: Optional[date] = None


class BatchOut(BaseModel):
    id: str
    country: str
    farm: str
    warehouse_id: str
    storage_date: date
    status: str

    model_config = {"from_attributes": True}


class MeasureCreate(BaseModel):
    id: str
    warehouse_id: str
    temperature: float
    humidity: float
    batch_id: Optional[str] = None



class MeasureOut(BaseModel):
    id: str
    warehouse_id: str
    temperature: float
    humidity: float
    timestamp: datetime
    batch_id: Optional[str] = None
    
    batch: Optional[BatchOut] = None

    model_config = {"from_attributes": True}


class BatchAlert(BaseModel):
    batch: BatchOut
    reason: str


class MeasureAlert(BaseModel):
    measure: MeasureOut
    reason: str
    severity: str


class AlertsResponse(BaseModel):
    problematic_batches: list[BatchAlert]
    out_of_range_measures: list[MeasureAlert]

class CountrySettingsOut(BaseModel):
    slug: str
    name: str
    ideal_temperature: float
    temperature_tolerance: float
    ideal_humidity: float
    humidity_tolerance: float
    shelf_life_days: int
    manager_email: str
    alerts_enabled: bool

    model_config = {"from_attributes": True}


class CountrySettingsUpdate(BaseModel):
    """Partial update: only the supplied fields are overwritten.

    Every field is optional and the router applies model_dump(exclude_unset=True):
    a PATCH that only carries the shelf life does not reset the thresholds to
    zero.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=60)
    ideal_temperature: Optional[float] = Field(None, ge=-50, le=80)
    temperature_tolerance: Optional[float] = Field(None, gt=0, le=50)
    ideal_humidity: Optional[float] = Field(None, ge=0, le=100)
    humidity_tolerance: Optional[float] = Field(None, gt=0, le=50)
    shelf_life_days: Optional[int] = Field(None, gt=0, le=3650)
    manager_email: Optional[str] = Field(None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    alerts_enabled: Optional[bool] = None

class AlertOut(BaseModel):
    id: str
    country: str
    warehouse_id: str
    batch_id: Optional[str] = None
    measure_id: Optional[str] = None
    type: str
    severity: str
    message: str
    triggered_at: Optional[datetime] = None
    emailed_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @property
    def status(self) -> str:
        if self.resolved_at is not None:
            return "resolved"
        return "acknowledged" if self.acknowledged_at is not None else "open"


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    limit: int
    offset: int


class AcknowledgeIn(BaseModel):
    by: Optional[str] = Field(None, max_length=120)


class AlertSyncOut(BaseModel):
    opened: int
    updated: int
    resolved: int

class MeasurePage(BaseModel):
    items: list[MeasureOut]
    total: int
    limit: int
    offset: int
