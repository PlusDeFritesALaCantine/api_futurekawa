"""Sensor reading queries.

`GET /measures` no longer dumps the whole table. The endpoint used to return
every measurement (948 rows in the demo, unbounded in production) and the
front-end filtered and paginated in the browser: every country change
transferred the full history just to display 30 rows.

The endpoint is now bounded and filtered: `limit` is capped, and the
warehouse / batch / date range filters are applied in SQL. The response is a
{items, total, limit, offset} envelope — `total` lets the front-end paginate
without loading everything.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, Measure
from app.schemas import MeasureOut, MeasurePage

router = APIRouter(prefix="/measures", tags=["measures"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _warehouses_of_country(db: Session, country: str) -> set[str]:
    return {b.warehouse_id for b in db.query(Batch).filter(Batch.country == country).all()}


@router.get("", response_model=MeasurePage)
def list_measures(
    warehouse_id: Optional[str] = Query(None),
    batch_id: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None, description="Lower bound on timestamp (inclusive)"),
    end: Optional[datetime] = Query(None, description="Upper bound on timestamp (inclusive)"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Measure)

    if warehouse_id:
        q = q.filter(Measure.warehouse_id == warehouse_id)
    if batch_id:
        q = q.filter(Measure.batch_id == batch_id)
    if country:
        warehouses = _warehouses_of_country(db, country)
        if not warehouses:
            return MeasurePage(items=[], total=0, limit=limit, offset=offset)
        q = q.filter(Measure.warehouse_id.in_(warehouses))
    if start:
        q = q.filter(Measure.timestamp >= start)
    if end:
        q = q.filter(Measure.timestamp <= end)

    total = q.count()
    items = q.order_by(desc(Measure.timestamp)).offset(offset).limit(limit).all()
    return MeasurePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/latest", response_model=list[MeasureOut])
def latest_per_warehouse(country: Optional[str] = Query(None), db: Session = Depends(get_db)):
    subquery = (
        db.query(Measure.warehouse_id, func.max(Measure.timestamp).label("max_ts"))
        .group_by(Measure.warehouse_id)
        .subquery()
    )
    q = db.query(Measure).join(
        subquery,
        (Measure.warehouse_id == subquery.c.warehouse_id)
        & (Measure.timestamp == subquery.c.max_ts),
    )
    if country:
        q = q.filter(Measure.warehouse_id.in_(_warehouses_of_country(db, country)))
    return q.all()
