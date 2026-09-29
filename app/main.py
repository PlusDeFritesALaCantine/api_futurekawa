import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine
from app.migrations import sync_schema
from app.models import Base
from app.routers import alerts, batches, measures, parameters
from app.services import alert_lifecycle, parameters as svc_parameters
from app.services.notifier import check_and_notify

Base.metadata.create_all(bind=engine)
sync_schema(engine)

logger = logging.getLogger(__name__)

ALERT_CHECK_INTERVAL_SECONDS = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "60"))
ALERT_LOOP_ENABLED = os.getenv("ALERT_LOOP_ENABLED", "1").lower() not in ("0", "false", "no")


def _load_parameters() -> None:
    """Warms the settings cache from the `countries` table.

    Read-only: nothing is created or written here. Until a country row exists,
    services/parameters.py falls back to its DEFAULTS constants.
    """
    db = SessionLocal()
    try:
        loaded = svc_parameters.reload(db)
        logger.info("Loaded settings for %s countries", len(loaded))
    except Exception:
        logger.exception("Could not load the country settings")
    finally:
        db.close()


def _alert_cycle() -> None:
    """A full cycle: align the alerts table, then notify.

    The synchronisation is done for every country, including those with e-mails
    disabled: turning notifications off must not blind the site's Alerts page.
    """
    db = SessionLocal()
    try:
        alert_lifecycle.sync(db)
    except Exception:
        logger.exception("Error during alert synchronisation")
    finally:
        db.close()
    check_and_notify()


async def _alert_check_loop():
    while True:
        try:
            await asyncio.to_thread(_alert_cycle)
        except Exception:
            logger.exception("Error during the periodic alert check")
        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_parameters()
    if not ALERT_LOOP_ENABLED:
        logger.info("Alert loop disabled (ALERT_LOOP_ENABLED)")
        yield
        return
    task = asyncio.create_task(_alert_check_loop())
    yield
    task.cancel()


app = FastAPI(title="FutureKawa API", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(batches.router)
app.include_router(measures.router)
app.include_router(alerts.router)
app.include_router(parameters.router)


@app.get("/health")
def health():
    return {"status": "ok"}
