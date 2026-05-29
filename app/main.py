from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import lots, mesures, alertes
from app.database import engine
from app.models import Base

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FutureKawa API — Brésil", version="1.0.0")

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
