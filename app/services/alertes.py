from datetime import date

PEREMPTION_JOURS = 365

# Conditions idéales par pays (cahier des charges) : (idéal, tolérance).
SEUILS_PAYS: dict[str, dict[str, tuple[float, float]]] = {
    "bresil":   {"temperature": (29.0, 3.0), "humidity": (55.0, 2.0)},
    "equateur": {"temperature": (31.0, 3.0), "humidity": (60.0, 2.0)},
    "colombie": {"temperature": (26.0, 3.0), "humidity": (80.0, 2.0)},
}
PAYS_PAR_DEFAUT = "bresil"

# Échelle de qualité d'une mesure, du meilleur au pire. La frontière entre
# "correct" et "bas" est la tolérance du cahier des charges (±3°C / ±2%) :
# au-delà, la mesure est hors seuil. Seuls les tiers "bas" et "critique"
# déclenchent une alerte (page Alertes + email) — cf. evaluer_mesure().
ORDRE_TIERS = ["excellent", "bon", "correct", "bas", "critique"]
TIERS_ALERTE = {"bas", "critique"}

# Au-delà de ce multiple de la tolérance, le dépassement passe de "bas" à "critique".
MULTIPLICATEUR_CRITIQUE = 2.0

_ADJECTIF_FEMININ = {"excellent": "excellente", "bon": "bonne", "correct": "correcte"}


def calculer_statut_lot(date_stockage: date) -> str:
    today = date.today()
    anciennete = (today - date_stockage).days
    if anciennete > PEREMPTION_JOURS:
        return "perime"
    return "conforme"


def _classer(deviation_abs: float, tolerance: float) -> str:
    if deviation_abs <= tolerance * 0.25:
        return "excellent"
    if deviation_abs <= tolerance * 0.6:
        return "bon"
    if deviation_abs <= tolerance:
        return "correct"
    if deviation_abs <= tolerance * MULTIPLICATEUR_CRITIQUE:
        return "bas"
    return "critique"


def evaluer_qualite(temperature: float, humidity: float, pays: str = PAYS_PAR_DEFAUT) -> list[dict]:
    """Classe température et humidité sur l'échelle excellent/bon/correct/bas/critique.

    Retourne toujours 2 entrées (une par grandeur), même quand tout va bien — contrairement
    à evaluer_mesure() qui ne garde que les grandeurs en alerte. Chaque entrée est
    {"grandeur", "valeur", "tier", "direction", "raison"} ; "direction" est None pour
    excellent/bon/correct (la mesure est dans la tolérance, pas de sens à signaler un sens).
    """
    seuils = SEUILS_PAYS.get(pays, SEUILS_PAYS[PAYS_PAR_DEFAUT])
    resultats = []
    for grandeur, valeur, unite, (ideal, tolerance) in (
        ("température", temperature, "°C", seuils["temperature"]),
        ("humidité", humidity, "%", seuils["humidity"]),
    ):
        deviation = valeur - ideal
        tier = _classer(abs(deviation), tolerance)
        if tier in TIERS_ALERTE:
            direction = "trop élevée" if deviation > 0 else "trop basse"
            borne_min, borne_max = ideal - tolerance, ideal + tolerance
            raison = (
                f"{grandeur} {direction} : {valeur:.1f}{unite} "
                f"(seuil {borne_min:.1f}–{borne_max:.1f}{unite})"
            )
        else:
            direction = None
            adjectif = _ADJECTIF_FEMININ[tier]
            raison = f"{grandeur} {adjectif} : {valeur:.1f}{unite} (idéal {ideal:.1f}{unite} ±{tolerance:.1f}{unite})"
        resultats.append({
            "grandeur": grandeur,
            "valeur": valeur,
            "tier": tier,
            "direction": direction,
            "raison": raison,
        })
    return resultats


def evaluer_mesure(temperature: float, humidity: float, pays: str = PAYS_PAR_DEFAUT) -> list[dict]:
    """Anomalies nécessitant une alerte (tier "bas" ou "critique"), sous-ensemble de evaluer_qualite()."""
    return [a for a in evaluer_qualite(temperature, humidity, pays) if a["tier"] in TIERS_ALERTE]


def est_mesure_hors_seuil(
    temperature: float, humidity: float, pays: str = PAYS_PAR_DEFAUT
) -> tuple[bool, str]:
    anomalies = evaluer_mesure(temperature, humidity, pays)
    if not anomalies:
        return False, ""
    return True, " / ".join(a["raison"] for a in anomalies)


def raison_lot_problematique(date_stockage: date) -> tuple[bool, str]:
    statut = calculer_statut_lot(date_stockage)
    if statut == "perime":
        anciennete = (date.today() - date_stockage).days
        depassement = anciennete - PEREMPTION_JOURS
        raison = (
            f"Lot périmé : stocké depuis {anciennete} jours "
            f"(limite {PEREMPTION_JOURS} jours, dépassement de {depassement} jours)"
        )
        return True, raison
    return False, ""


def recuperer_alertes(db, pays: str | None = None):
    """Calcule les alertes (lots périmés, mesures hors seuil "bas"/"critique"), filtrées par pays si fourni.

    Les lots périmés ne sont jamais filtrés : un lot périmé est toujours signalé.

    Pour les mesures, on ne regarde que le DERNIER relevé de chaque entrepôt (au plus
    une alerte par entrepôt) : une alerte reflète l'état actuel, pas chaque dépassement
    passé de l'historique — sinon un entrepôt avec des semaines de relevés hors seuil
    génèrerait des dizaines d'alertes pour le même problème. L'historique complet reste
    consultable via les courbes du lot (GET /mesures).

    Logique partagée entre le routeur /alertes (consultation) et le notifier email
    (déclenchement automatique) : retourne des tuples bruts plutôt que des schémas
    Pydantic, pour rester réutilisable des deux côtés.
    """
    from sqlalchemy import func

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

    sous_requete = (
        db.query(Mesure.entrepot_id, func.max(Mesure.timestamp).label("max_ts"))
        .group_by(Mesure.entrepot_id)
        .subquery()
    )
    q = db.query(Mesure).join(
        sous_requete,
        (Mesure.entrepot_id == sous_requete.c.entrepot_id)
        & (Mesure.timestamp == sous_requete.c.max_ts),
    )
    if entrepots_du_pays is not None:
        q = q.filter(Mesure.entrepot_id.in_(entrepots_du_pays))

    mesures_hors_seuil = []
    for mesure in q.all():
        pays_mesure = pays_par_entrepot.get(mesure.entrepot_id, PAYS_PAR_DEFAUT)
        anomalies = evaluer_mesure(mesure.temperature, mesure.humidity, pays_mesure)
        if not anomalies:
            continue
        severite = "critique" if any(a["tier"] == "critique" for a in anomalies) else "bas"
        raison = " / ".join(a["raison"] for a in anomalies)
        mesures_hors_seuil.append((mesure, raison, severite))

    return lots_problematiques, mesures_hors_seuil
