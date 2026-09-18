"""Seed de données de démo réaliste pour la base utilisée par start_all.sh (sqlite:///./futurekawa.db).

seed.sql est écrit en syntaxe PostgreSQL (INTERVAL, NOW()) et ne peut donc pas être
exécuté contre la base SQLite locale. Ce script remplit la même table via les modèles
SQLAlchemy de l'app, avec un volume et un profil différents par pays/lot pour que la
démo (dashboard, courbes, alertes, emails) ne montre pas les 3 pays identiques :

- Chaque lot a son propre entrepôt (donc sa propre courbe température/humidité),
  pour bien distinguer un lot récent, un lot ancien conforme et un lot périmé.
- Les mesures combinent bruit gaussien + une oscillation lente (sinusoïde, période
  et déphasage propres à chaque lot) + une dérive linéaire optionnelle. L'oscillation
  évite l'effet "mur" d'une dérive purement linéaire (qui finirait par aligner tout
  l'historique récent sur la même valeur) : même un entrepôt "à risque" alterne des
  passages plus calmes et plus tendus, comme une vraie simulation.
- Le nombre de lots et la proportion de lots à risque varient par pays, mais aucun
  pays n'est totalement épargné : même l'Équateur (le plus calme) a un incident.

Usage : .venv/bin/python seed_sqlite.py
"""
import math
import os
import random
import zlib
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./futurekawa.db")

from app.database import Base, SessionLocal, engine
from app.migrations import synchroniser_schema
from app.models import Lot, Mesure
from app.services.alertes import SEUILS_PAYS, calculer_statut_lot

Base.metadata.create_all(bind=engine)
synchroniser_schema(engine)


def generer_mesures(seed: int, jours_historique: float, intervalle_heures: float,
                     ideal_temp: float, ideal_hum: float, bruit_temp: float, bruit_hum: float,
                     derive_temp: float = 0.0, derive_hum: float = 0.0,
                     amplitude_temp: float = 0.0, amplitude_hum: float = 0.0,
                     periode_jours: float = 6.0) -> list[tuple[datetime, float, float]]:
    """Série de mesures sur les `jours_historique` derniers jours :
    bruit gaussien + oscillation sinusoïdale (amplitude/période, déphasage aléatoire
    propre au seed) + dérive linéaire de 0 (début) à derive_temp/derive_hum (fin).
    """
    rng = random.Random(seed)
    phase = rng.uniform(0, 2 * math.pi)
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours_historique)
    duree_s = (fin - debut).total_seconds()

    mesures = []
    t = debut
    while t <= fin:
        progression = (t - debut).total_seconds() / duree_s if duree_s > 0 else 1.0
        jours_ecoules = (t - debut).total_seconds() / 86400
        oscillation = math.sin(2 * math.pi * jours_ecoules / periode_jours + phase)
        temp = ideal_temp + derive_temp * progression + amplitude_temp * oscillation + rng.gauss(0, bruit_temp)
        hum = ideal_hum + derive_hum * progression + amplitude_hum * oscillation + rng.gauss(0, bruit_hum)
        mesures.append((t, round(temp, 1), round(hum, 1)))
        t += timedelta(hours=intervalle_heures)
    return mesures


# Chaque lot a son propre entrepôt -> sa propre courbe. Champs :
# (lot_id, exploitation, age_jours, entrepot, jours_historique_mesures, intervalle_h,
#  bruit_temp, bruit_hum, derive_temp, derive_hum, amplitude_temp, amplitude_hum, periode_jours)
#
# Profils choisis à partir d'un climat réaliste par pays (cf. recherche climat régions
# caféières) :
#  - Brésil (Minas Gerais, ~29°C/55% visé) : climat le plus proche de la zone de confort
#    universelle du café vert (20-25°C/50-60%RH) -> globalement stable, un incident
#    (panne de ventilation -> dérive de température sur le lot périmé).
#  - Équateur (entrepôt supposé déshumidifié activement, le climat côtier ambiant étant
#    très humide ~90%RH) -> le plus calme des 3, mais pas épargné : un bref incident
#    d'humidité (maintenance du déshumidificateur) sur le lot ancien.
#  - Colombie (~26°C/80% visé, saisons des pluies/sécheresse marquées Eje Cafetero) ->
#    le plus exposé, mais volontairement contenu à 1 lot périmé + 1 lot à risque
#    (pas davantage, pour ne pas saturer les alertes).
PAYS_DATA = {
    "bresil": [
        # Récent : excellent, oscillation modeste.
        ("LOT-BR-001", "Fazenda Santa Clara", 6, "entrepot-bresil-1", 6, 4,
         0.25, 0.4, 0.0, 0.0, 0.4, 0.6, 3.0),
        # Ancien conforme : oscille entre bon et correct, jamais hors tolérance.
        ("LOT-BR-002", "Fazenda Rio Verde", 120, "entrepot-bresil-2", 30, 8,
         0.4, 0.5, 0.3, -0.3, 1.3, 1.1, 7.0),
        # Périmé : panne de ventilation -> oscillation marquée, dérive vers le critique.
        ("LOT-BR-003", "Fazenda Boa Esperança", 400, "entrepot-bresil-3", 45, 8,
         0.6, 0.7, 6.5, -1.0, 2.0, 1.2, 6.0),
    ],
    "equateur": [
        # Récent : excellent.
        ("LOT-EQ-001", "Hacienda El Cafetal", 4, "entrepot-equateur-1", 4, 4,
         0.2, 0.35, 0.0, 0.0, 0.3, 0.5, 3.5),
        # Ancien : incident de maintenance du déshumidificateur -> humidité oscille
        # jusqu'à "bas" par moments, sans devenir critique (le pays reste le plus calme).
        ("LOT-EQ-002", "Hacienda Los Andes", 90, "entrepot-equateur-2", 30, 8,
         0.4, 0.5, 0.5, 0.5, 1.2, 2.6, 6.0),
    ],
    "colombie": [
        # Récent : oscille autour de "bon", jamais hors tolérance.
        ("LOT-CO-001", "Finca La Esperanza", 3, "entrepot-colombie-1", 3, 4,
         0.4, 0.5, 0.5, 0.5, 0.9, 0.9, 2.5),
        # Ancien conforme : oscille vers "correct" à l'occasion, jamais hors tolérance.
        ("LOT-CO-002", "Finca El Paraiso", 60, "entrepot-colombie-2", 30, 8,
         0.5, 0.6, -0.8, 0.8, 1.6, 1.3, 8.0),
        # À risque (non périmé) : saison sèche -> humidité oscille autour de "bas".
        ("LOT-CO-003", "Finca Las Nubes", 200, "entrepot-colombie-3", 40, 6,
         0.4, 0.4, 0.5, -2.6, 1.0, 1.1, 6.0),
        # Périmé : panne de climatisation -> température oscille en zone critique.
        ("LOT-CO-004", "Finca Buenavista", 380, "entrepot-colombie-4", 50, 6,
         0.6, 0.6, 7.0, 0.8, 1.8, 0.9, 5.0),
        # Plus très récent mais pas périmé : conditions stables, juste pour varier l'âge.
        ("LOT-CO-005", "Finca El Mirador", 150, "entrepot-colombie-5", 30, 8,
         0.4, 0.5, -0.6, 0.6, 1.0, 1.0, 7.0),
    ],
}

db = SessionLocal()
try:
    total_lots = 0
    total_mesures = 0

    for pays, lots in PAYS_DATA.items():
        temp_ideal, _ = SEUILS_PAYS[pays]["temperature"]
        hum_ideal, _ = SEUILS_PAYS[pays]["humidity"]

        for (lot_id, exploitation, age_jours, entrepot, jours_hist, intervalle_h,
             bruit_temp, bruit_hum, derive_temp, derive_hum,
             amplitude_temp, amplitude_hum, periode_jours) in lots:
            if not db.get(Lot, lot_id):
                date_stockage = date.today() - timedelta(days=age_jours)
                db.add(Lot(
                    id=lot_id,
                    pays=pays,
                    exploitation=exploitation,
                    entrepot_id=entrepot,
                    date_stockage=date_stockage,
                    statut=calculer_statut_lot(date_stockage),
                ))
                total_lots += 1

            seed = zlib.crc32(lot_id.encode())  # déterministe (contrairement à hash() entre runs)
            for timestamp, temp, hum in generer_mesures(
                seed, jours_hist, intervalle_h,
                temp_ideal, hum_ideal, bruit_temp, bruit_hum, derive_temp, derive_hum,
                amplitude_temp, amplitude_hum, periode_jours,
            ):
                mesure_id = f"M-{entrepot}-{int(timestamp.timestamp())}"
                if db.get(Mesure, mesure_id):
                    continue
                db.add(Mesure(
                    id=mesure_id,
                    entrepot_id=entrepot,
                    temperature=temp,
                    humidity=hum,
                    timestamp=timestamp,
                ))
                total_mesures += 1

    db.commit()
    print(f"Seed terminé : {total_lots} lots, {total_mesures} mesures "
          f"({db.query(Lot).count()} lots et {db.query(Mesure).count()} mesures en base au total).")
finally:
    db.close()
