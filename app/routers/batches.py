from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Batch, Measure
from app.schemas import BatchCreate, BatchOut, BatchUpdate, MeasureOut
from app.services.alerts import compute_batch_status

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(batch: BatchCreate, db: Session = Depends(get_db)):
    if db.get(Batch, batch.id):
        raise HTTPException(status_code=409, detail="Batch already exists")
    db_batch = Batch(**batch.model_dump())
    db_batch.status = compute_batch_status(batch.storage_date, batch.country)
    db.add(db_batch)
    db.commit()
    db.refresh(db_batch)
    return _enrich(db_batch)


@router.get("", response_model=list[BatchOut])
def list_batches(country: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Batch)
    if country:
        q = q.filter(Batch.country == country)
    batches = q.order_by(Batch.storage_date.asc()).all()
    return [_enrich(b) for b in batches]



@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _enrich(batch)


@router.get("/{batch_id}/measures", response_model=list[MeasureOut])
def list_batch_measures(batch_id: str, db: Session = Depends(get_db)):
    """Returns the full history of the measurements recorded for a specific batch."""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not batch.measures:
        raise HTTPException(status_code=404, detail="No measures found for this batch")
    return batch.measures


@router.patch("/{batch_id}", response_model=BatchOut)
def update_batch(batch_id: str, maj: BatchUpdate, db: Session = Depends(get_db)):
    """Partial update: only the supplied fields are overwritten.

    `exclude_unset=True` is what guarantees the merge — a PATCH that only carries
    the storage date must not blank out the farm.
    """
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    fields = maj.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No field to modify")

    for key, value in fields.items():
        setattr(batch, key, value)

    db.commit()
    db.refresh(batch)
    return _enrich(batch)



@router.delete("/{batch_id}", status_code=204)
def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    db.delete(batch)
    db.commit()


def _enrich(batch: Batch) -> BatchOut:
    # Shelf life is configured per country: a Colombian batch is not judged
    # against Brazil's duration.
    batch.status = compute_batch_status(batch.storage_date, batch.country)
    return BatchOut.model_validate(batch)
