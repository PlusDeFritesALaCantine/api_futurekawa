from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AcknowledgeIn, MeasureAlert, AlertOut, AlertsResponse, BatchAlert,
    AlertPage, AlertSyncOut,
)
from app.services import alert_lifecycle
from app.services.alerts import compute_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertsResponse)
def list_alerts(country: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Computed view of the current state — unchanged, it is the front-end's contract.

    Only returns active anomalies: excellent/good/fair measurements are not
    alerts. For the history, acknowledgement and resolution, see
    GET /alerts/journal.
    """
    problematic_batches, out_of_range_measures = compute_alerts(db, country)
    return AlertsResponse(
        problematic_batches=[
            BatchAlert(batch=batch, reason=reason) for batch, reason in problematic_batches
        ],
        out_of_range_measures=[
            MeasureAlert(measure=measure, reason=reason, severity=severity)
            for measure, reason, severity in out_of_range_measures
        ],
    )


@router.get("/journal", response_model=AlertPage)
def alert_journal(
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(open|acknowledged|resolved)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Persisted alerts, with their lifecycle. Paginated."""
    items, total = alert_lifecycle.list_alerts(db, country, status, limit, offset)
    return AlertPage(items=items, total=total, limit=limit, offset=offset)


@router.post("/sync", response_model=AlertSyncOut)
def sync_alerts(
    country: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Aligns the alerts table with the current state of the readings.

    Called automatically by the periodic loop; exposed so it can be triggered on
    demand during a demo.
    """
    return AlertSyncOut(**alert_lifecycle.sync(db, country))


@router.patch("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: str, body: AcknowledgeIn | None = None, db: Session = Depends(get_db)
):
    """Acknowledgement: the alert stays open, but we know who is on it."""
    alert = alert_lifecycle.acknowledge(db, alert_id, (body.by if body else None))
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    return alert


@router.patch("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: str, db: Session = Depends(get_db)):
    """Manual closure. If the anomaly persists, the next cycle will reopen an alert."""
    alert = alert_lifecycle.resolve(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    return alert


@router.post("/notify")
def notify_now():
    """Triggers an immediate check + e-mail send (outside the periodic cycle).

    Useful in a demo to avoid waiting for ALERT_CHECK_INTERVAL_SECONDS.
    """
    from app.services.notifier import check_and_notify

    return {"emails_sent": check_and_notify()}
