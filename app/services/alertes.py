from datetime import date, datetime, timezone

PEREMPTION_JOURS = 365

# Conditions idéales par pays (cahier des charges) : (idéal, tolérance).
SEUILS_PAYS: dict[str, dict[str, tuple[float, float]]] = {
    "bresil":   {"temperature": (29.0, 3.0), "humidity": (55.0, 2.0)},
    "equateur": {"temperature": (31.0, 3.0), "humidity": (60.0, 2.0)},
    "colombie": {"temperature": (26.0, 3.0), "humidity": (80.0, 2.0)},
}
PAYS_PAR_DEFAUT = "bresil"


def calculer_statut_lot(date_stockage: date) -> str:
    today = date.today()
    anciennete = (today - date_stockage).days
    if anciennete > PEREMPTION_JOURS:
        return "perime"
    return "conforme"


def est_mesure_hors_seuil(
    temperature: float, humidity: float, pays: str = PAYS_PAR_DEFAUT
) -> tuple[bool, str]:
    seuils = SEUILS_PAYS.get(pays, SEUILS_PAYS[PAYS_PAR_DEFAUT])
    temp_ideal, temp_tolerance = seuils["temperature"]
    hum_ideal, hum_tolerance = seuils["humidity"]
    temp_min, temp_max = temp_ideal - temp_tolerance, temp_ideal + temp_tolerance
    hum_min, hum_max = hum_ideal - hum_tolerance, hum_ideal + hum_tolerance

    raisons = []
    if temperature < temp_min or temperature > temp_max:
        raisons.append(f"température {temperature}°C hors seuil [{temp_min}-{temp_max}°C]")
    if humidity < hum_min or humidity > hum_max:
        raisons.append(f"humidité {humidity}% hors seuil [{hum_min}-{hum_max}%]")
    if raisons:
        return True, " / ".join(raisons)
    return False, ""


def raison_lot_problematique(date_stockage: date) -> tuple[bool, str]:
    statut = calculer_statut_lot(date_stockage)
    if statut == "perime":
        anciennete = (date.today() - date_stockage).days
        return True, f"lot périmé ({anciennete} jours de stockage)"
    return False, ""


def recuperer_alertes(db, pays: str | None = None):
    """Calcule les alertes (lots périmés, mesures hors seuil), filtrées par pays si fourni.

    Logique partagée entre le routeur /alertes (consultation) et le notifier email
    (déclenchement automatique) : retourne des tuples (objet, raison) bruts plutôt
    que des schémas Pydantic, pour rester réutilisable des deux côtés.
    """
    from app.models import Lot, Mesure

    tous_les_lots = db.query(Lot).all()
    pays_par_entrepot = {lot.entrepot_id: lot.pays for lot in tous_les_lots}

    lots = [l for l in tous_les_lots if not pays or l.pays == pays]
    entrepots_du_pays = {l.entrepot_id for l in lots} if pays else None

    lots_problematiques = []
    for lot in lots:
        est_pb, raison = raison_lot_problematique(lot.date_stockage)
        if est_pb:
            lot.statut = "perime"
            lots_problematiques.append((lot, raison))

    mesures = db.query(Mesure).all()
    mesures_hors_seuil = []
    for mesure in mesures:
        if entrepots_du_pays is not None and mesure.entrepot_id not in entrepots_du_pays:
            continue
        pays_mesure = pays_par_entrepot.get(mesure.entrepot_id, PAYS_PAR_DEFAUT)
        hors_seuil, raison = est_mesure_hors_seuil(mesure.temperature, mesure.humidity, pays_mesure)
        if hors_seuil:
            mesures_hors_seuil.append((mesure, raison))

    return lots_problematiques, mesures_hors_seuil
