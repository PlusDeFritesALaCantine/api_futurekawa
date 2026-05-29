from datetime import date, datetime, timezone

TEMP_MIN = 26.0
TEMP_MAX = 32.0
HUM_MIN = 53.0
HUM_MAX = 57.0
PEREMPTION_JOURS = 365


def calculer_statut_lot(date_stockage: date) -> str:
    today = date.today()
    anciennete = (today - date_stockage).days
    if anciennete > PEREMPTION_JOURS:
        return "perime"
    return "conforme"


def est_mesure_hors_seuil(temperature: float, humidity: float) -> tuple[bool, str]:
    raisons = []
    if temperature < TEMP_MIN or temperature > TEMP_MAX:
        raisons.append(f"température {temperature}°C hors seuil [{TEMP_MIN}-{TEMP_MAX}°C]")
    if humidity < HUM_MIN or humidity > HUM_MAX:
        raisons.append(f"humidité {humidity}% hors seuil [{HUM_MIN}-{HUM_MAX}%]")
    if raisons:
        return True, " / ".join(raisons)
    return False, ""


def raison_lot_problematique(date_stockage: date) -> tuple[bool, str]:
    statut = calculer_statut_lot(date_stockage)
    if statut == "perime":
        anciennete = (date.today() - date_stockage).days
        return True, f"lot périmé ({anciennete} jours de stockage)"
    return False, ""
