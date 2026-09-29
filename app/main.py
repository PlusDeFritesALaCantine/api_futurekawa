import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine
from app.migrations import synchroniser_schema
from app.models import Base
from app.routers import alertes, lots, mesures, parametres
from app.services import gestion_alertes
from app.services import parametres as svc_parametres
from app.services.notifier import verifier_et_notifier

Base.metadata.create_all(bind=engine)
synchroniser_schema(engine)

logger = logging.getLogger(__name__)

ALERT_CHECK_INTERVAL_SECONDS = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "60"))

# Boucle de fond désactivable. Utile sur un réplica en lecture seule, qui ne doit
# ni écrire d'alertes ni envoyer d'e-mails, et dans les tests : un ordonnanceur
# qui démarre en même temps que le client rend les assertions d'envoi d'e-mail
# dépendantes du hasard d'ordonnancement.
ALERT_LOOP_ENABLED = os.getenv("ALERT_LOOP_ENABLED", "1").lower() not in ("0", "false", "no")


def _amorcer_parametres() -> None:
    """Crée les lignes de la table `pays` manquantes, à partir du cahier des charges.

    Idempotent : un pays déjà paramétré depuis le site garde ses valeurs.
    """
    db = SessionLocal()
    try:
        crees = svc_parametres.initialiser(db)
        if crees:
            logger.info("Paramétrage initial créé pour %s pays", crees)
    except Exception:
        logger.exception("Impossible d'amorcer le paramétrage des pays")
    finally:
        db.close()


def _cycle_alertes() -> None:
    """Un tour complet : aligner la table des alertes, puis notifier.

    La synchronisation est faite pour tous les pays, y compris ceux dont les
    e-mails sont désactivés : couper les notifications ne doit pas aveugler la
    page Alertes du site.
    """
    db = SessionLocal()
    try:
        gestion_alertes.synchroniser(db)
    except Exception:
        logger.exception("Erreur durant la synchronisation des alertes")
    finally:
        db.close()
    verifier_et_notifier()


async def _boucle_verification_alertes():
    while True:
        try:
            await asyncio.to_thread(_cycle_alertes)
        except Exception:
            logger.exception("Erreur durant la vérification périodique des alertes")
        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _amorcer_parametres()
    if not ALERT_LOOP_ENABLED:
        logger.info("Boucle d'alertes désactivée (ALERT_LOOP_ENABLED)")
        yield
        return
    tache = asyncio.create_task(_boucle_verification_alertes())
    yield
    tache.cancel()


app = FastAPI(title="FutureKawa API", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lots.router)
app.include_router(mesures.router)
app.include_router(alertes.router)
app.include_router(parametres.router)


@app.get("/health")
def health():
    return {"status": "ok"}
