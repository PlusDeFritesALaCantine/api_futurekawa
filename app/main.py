import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import lots, mesures, alertes
from app.database import engine
from app.migrations import synchroniser_schema
from app.models import Base
from app.services.notifier import verifier_et_notifier

Base.metadata.create_all(bind=engine)
synchroniser_schema(engine)

logger = logging.getLogger(__name__)

ALERT_CHECK_INTERVAL_SECONDS = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "60"))


async def _boucle_verification_alertes():
    while True:
        try:
            await asyncio.to_thread(verifier_et_notifier)
        except Exception:
            logger.exception("Erreur durant la vérification périodique des alertes")
        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tache = asyncio.create_task(_boucle_verification_alertes())
    yield
    tache.cancel()


app = FastAPI(title="FutureKawa API — Brésil", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lots.router)
app.include_router(mesures.router)
app.include_router(alertes.router)


@app.get("/health")
def health():
    return {"status": "ok"}
