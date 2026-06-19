"""Seed de données de démo pour la base utilisée par start_all.sh (sqlite:///./futurekawa.db).

seed.sql est écrit en syntaxe PostgreSQL (INTERVAL, NOW()) et ne peut donc pas être
exécuté contre la base SQLite locale. Ce script remplit la même table via les modèles
SQLAlchemy de l'app, pour les 3 pays (bresil, equateur, colombie).

Usage : .venv/bin/python seed_sqlite.py
"""
import os
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./futurekawa.db")

from app.database import Base, SessionLocal, engine
from app.models import Lot, Mesure
from app.services.alertes import SEUILS_PAYS, calculer_statut_lot

Base.metadata.create_all(bind=engine)

PAYS_DATA = {
    "bresil": {
        "entrepot": "entrepot-bresil-1",
        "lots": [
            ("LOT-BR-001", "Fazenda Santa Clara", 10),
            ("LOT-BR-002", "Fazenda Rio Verde", 200),
            ("LOT-BR-003", "Fazenda Boa Esperança", 400),
        ],
    },
    "equateur": {
        "entrepot": "entrepot-equateur-1",
        "lots": [
            ("LOT-EQ-001", "Hacienda El Cafetal", 5),
            ("LOT-EQ-002", "Hacienda Los Andes", 150),
            ("LOT-EQ-003", "Hacienda Buena Vista", 380),
        ],
    },
    "colombie": {
        "entrepot": "entrepot-colombie-1",
        "lots": [
            ("LOT-CO-001", "Finca La Esperanza", 3),
            ("LOT-CO-002", "Finca El Paraiso", 120),
            ("LOT-CO-003", "Finca Las Nubes", 420),
        ],
    },
}

db = SessionLocal()
try:
    now = datetime.now(timezone.utc)

    for pays, data in PAYS_DATA.items():
        entrepot = data["entrepot"]
        temp_ideal, temp_tol = SEUILS_PAYS[pays]["temperature"]
        hum_ideal, hum_tol = SEUILS_PAYS[pays]["humidity"]

        for lot_id, exploitation, age_jours in data["lots"]:
            if db.get(Lot, lot_id):
                continue
            date_stockage = date.today() - timedelta(days=age_jours)
            db.add(Lot(
                id=lot_id,
                pays=pays,
                exploitation=exploitation,
                entrepot_id=entrepot,
                date_stockage=date_stockage,
                statut=calculer_statut_lot(date_stockage),
            ))

        # 7 jours de mesures, 4 par jour, dont quelques-unes hors seuil.
        for j in range(7, -1, -1):
            for h, offset_temp, offset_hum in [(2, 0, 0), (8, 0, 0), (14, 4.5, 0), (20, 0, -3)]:
                mesure_id = f"M-{pays[:2].upper()}-{j:02d}-{h:02d}"
                if db.get(Mesure, mesure_id):
                    continue
                timestamp = now - timedelta(days=j) + timedelta(hours=h)
                db.add(Mesure(
                    id=mesure_id,
                    entrepot_id=entrepot,
                    temperature=round(temp_ideal + offset_temp, 1),
                    humidity=round(hum_ideal + offset_hum, 1),
                    timestamp=timestamp,
                ))

    db.commit()
    print("Seed terminé :", db.query(Lot).count(), "lots,", db.query(Mesure).count(), "mesures.")
finally:
    db.close()
