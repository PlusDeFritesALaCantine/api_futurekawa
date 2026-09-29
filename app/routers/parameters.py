"""Business settings editable from the site.

Exposes the `countries` table: storage thresholds, shelf life duration and alert
recipients. Every write invalidates the cache of services/parameters.py, so the
change is taken into account from the next evaluation cycle — without a restart.

These routes are strictly read/write on existing rows: they never create a
country. A GET on an unknown slug answers 404 rather than seeding it from the
DEFAULTS constants.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Country
from app.schemas import CountrySettingsOut, CountrySettingsUpdate
from app.services import parameters as svc

router = APIRouter(prefix="/parameters", tags=["parameters"])



@router.get("/country", response_model=list[CountrySettingsOut])
def list_country_settings(db: Session = Depends(get_db)):
    return db.query(Country).order_by(Country.slug).all()


@router.get("/country/{slug}", response_model=CountrySettingsOut)
def get_country_settings(slug: str, db: Session = Depends(get_db)):
    row = db.get(Country, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Country '{slug}' not found")
    return row


@router.patch("/country/{slug}", response_model=CountrySettingsOut)
def update_country_settings(
    slug: str, maj: CountrySettingsUpdate, db: Session = Depends(get_db)
):
    """Partial update: only the fields present in the request change.

    `exclude_unset=True` is what guarantees the merge. Without it, a PATCH only
    sending the shelf life would reset all the thresholds to their Pydantic
    default — a silent overwrite that is hard to diagnose.
    """
    row = db.get(Country, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Country '{slug}' not found")

    fields = maj.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No field to modify")

    for key, value in fields.items():
        setattr(row, key, value)

    db.commit()
    db.refresh(row)
    # reload(), not invalidate(): an emptied cache would silently fall back to
    # the default values until the next database read.
    svc.reload(db)
    return row
