"""Règles métier d'évaluation : qualité d'une mesure et péremption d'un lot.

Les seuils et la durée de péremption ne sont plus des constantes : ils viennent
de la table `pays` via services/parametres.py, et sont modifiables depuis le
site. Les fonctions gardent leur signature — `pays` reste un simple slug — donc
elles restent testables sans base : hors contexte base, parametres.get() retombe
sur les valeurs du cahier des charges.
"""

from datetime import date

from app.services.parametres import PAYS_PAR_DEFAUT, get as _params

# Échelle de qualité d'une mesure, du meilleur au pire. La frontière entre
# "correct" et "bas" est la tolérance paramétrée : au-delà, la mesure est hors
# seuil. Seuls les tiers "bas" et "critique" déclenchent une alerte
# (page Alertes + email) — cf. evaluer_mesure().
ORDRE_TIERS = ["excellent", "bon", "correct", "bas", "critique"]
TIERS_ALERTE = {"bas", "critique"}

# Au-delà de ce multiple de la tolérance, le dépassement passe de "bas" à "critique".
MULTIPLICATEUR_CRITIQUE = 2.0

_ADJECTIF_FEMININ = {"excellent": "excellente", "bon": "bonne", "correct": "correcte"}

# Grandeur -> (libellé, unité, nom du seuil dans ParametresPays)
_GRANDEURS = (
    ("température", "°C", "temperature"),
    ("humidité", "%", "humidity"),
)


def calculer_statut_lot(date_stockage: date, pays: str = PAYS_PAR_DEFAUT) -> str:
    if (date.today() - date_stockage).days > _params(pays).peremption_jours:
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
    params = _params(pays)
    valeurs = {"temperature": temperature, "humidity": humidity}
    resultats = []
    for libelle, unite, cle in _GRANDEURS:
        valeur = valeurs[cle]
        ideal, tolerance = params.seuil(cle)
        deviation = valeur - ideal
        tier = _classer(abs(deviation), tolerance)
        if tier in TIERS_ALERTE:
            direction = "trop élevée" if deviation > 0 else "trop basse"
            borne_min, borne_max = ideal - tolerance, ideal + tolerance
            raison = (
                f"{libelle} {direction} : {valeur:.1f}{unite} "
                f"(seuil {borne_min:.1f}–{borne_max:.1f}{unite})"
            )
        else:
            direction = None
            adjectif = _ADJECTIF_FEMININ[tier]
            raison = (
                f"{libelle} {adjectif} : {valeur:.1f}{unite} "
                f"(idéal {ideal:.1f}{unite} ±{tolerance:.1f}{unite})"
            )
        resultats.append({
            "grandeur": libelle,
            "valeur": valeur,
            "tier": tier,
            "direction": direction,
            "raison": raison,
            # Type technique, utilisé comme composant de la clé de déduplication
            # des alertes persistées (cf. services/gestion_alertes.py).
            "type": "temperature" if cle == "temperature" else "humidite",
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


def raison_lot_problematique(
    date_stockage: date, pays: str = PAYS_PAR_DEFAUT
) -> tuple[bool, str]:
    if calculer_statut_lot(date_stockage, pays) != "perime":
        return False, ""
    limite = _params(pays).peremption_jours
    anciennete = (date.today() - date_stockage).days
    raison = (
        f"Lot périmé : stocké depuis {anciennete} jours "
        f"(limite {limite} jours, dépassement de {anciennete - limite} jours)"
    )
    return True, raison


def dernieres_mesures_par_entrepot(db, entrepots: set[str] | None = None):
    """Le dernier relevé de chaque entrepôt, éventuellement restreint à un sous-ensemble.

    Extrait ici parce que trois appelants en ont besoin avec exactement la même
    définition de « dernier relevé » : le routeur /alertes, le notifier e-mail et
    la synchronisation des alertes persistées.
    """
    from sqlalchemy import func

    from app.models import Mesure

    sous_requete = db.query(
        Mesure.entrepot_id, func.max(Mesure.timestamp).label("max_ts")
    )
    if entrepots is not None:
        if not entrepots:
            return []
        sous_requete = sous_requete.filter(Mesure.entrepot_id.in_(entrepots))
    sous_requete = sous_requete.group_by(Mesure.entrepot_id).subquery()

    return (
        db.query(Mesure)
        .join(
            sous_requete,
            (Mesure.entrepot_id == sous_requete.c.entrepot_id)
            & (Mesure.timestamp == sous_requete.c.max_ts),
        )
        .all()
    )


def recuperer_alertes(db, pays: str | None = None):
    """Calcule les alertes (lots périmés, mesures hors seuil "bas"/"critique"), filtrées par pays si fourni.

    Les lots périmés ne sont jamais filtrés : un lot périmé est toujours signalé.

    Pour les mesures, on ne regarde que le DERNIER relevé de chaque entrepôt (au plus
    une alerte par entrepôt) : une alerte reflète l'état actuel, pas chaque dépassement
    passé de l'historique — sinon un entrepôt avec des semaines de relevés hors seuil
    génèrerait des dizaines d'alertes pour le même problème. L'historique complet reste
    consultable via GET /mesures.

    Logique partagée entre le routeur /alertes (consultation), le notifier email
    (déclenchement automatique) et la persistance des alertes : retourne des tuples
    bruts plutôt que des schémas Pydantic, pour rester réutilisable des trois côtés.
    """
    from app.models import Lot

    tous_les_lots = db.query(Lot).all()
    pays_par_entrepot = {lot.entrepot_id: lot.pays for lot in tous_les_lots}

    lots = [l for l in tous_les_lots if not pays or l.pays == pays]
    entrepots_du_pays = {l.entrepot_id for l in lots} if pays else None

    lots_problematiques = []
    for lot in lots:
        est_pb, raison = raison_lot_problematique(lot.date_stockage, lot.pays)
        if est_pb:
            lot.statut = "perime"
            lots_problematiques.append((lot, raison))

    mesures_hors_seuil = []
    for mesure in dernieres_mesures_par_entrepot(db, entrepots_du_pays):
        pays_mesure = pays_par_entrepot.get(mesure.entrepot_id, PAYS_PAR_DEFAUT)
        anomalies = evaluer_mesure(mesure.temperature, mesure.humidity, pays_mesure)
        if not anomalies:
            continue
        severite = "critique" if any(a["tier"] == "critique" for a in anomalies) else "bas"
        raison = " / ".join(a["raison"] for a in anomalies)
        mesures_hors_seuil.append((mesure, raison, severite))

    return lots_problematiques, mesures_hors_seuil
