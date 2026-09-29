"""Paramétrage métier par pays, stocké en base et modifiable depuis le site.

Avant, les seuils vivaient dans trois fichiers qui se contredisaient : la
constante SEUILS_PAYS de services/alertes.py, config/seuils.ts côté front, et
le seed du broker MQTT (qui annonçait 20 °C ± 5 pour le Brésil là où les deux
autres disaient 29 °C ± 3). La table `pays` devient la seule source de vérité ;
le front lit ces valeurs via l'API au lieu d'en garder une copie.

Un cache mémoire évite d'aller en base à chaque évaluation de mesure (le
notifier tourne toutes les 60 s sur tous les entrepôts). Il est rechargé au
démarrage et invalidé à chaque écriture — voir `invalider()`.

Les valeurs de DEFAUTS sont celles du cahier des charges. Elles servent à
amorcer la table au premier démarrage, et de repli quand le code est appelé
hors contexte base (tests unitaires des fonctions pures, par exemple).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PAYS_PAR_DEFAUT = "bresil"

DEFAUTS: dict[str, dict] = {
    "bresil": {
        "nom": "Brésil",
        "temperature_ideale": 29.0,
        "temperature_tolerance": 3.0,
        "humidite_ideale": 55.0,
        "humidite_tolerance": 2.0,
        "peremption_jours": 365,
        "email_responsable": os.getenv(
            "BRESIL_MANAGER_EMAIL", "responsable.bresil@futurekawa.local"
        ),
    },
    "equateur": {
        "nom": "Équateur",
        "temperature_ideale": 31.0,
        "temperature_tolerance": 3.0,
        "humidite_ideale": 60.0,
        "humidite_tolerance": 2.0,
        "peremption_jours": 365,
        "email_responsable": os.getenv(
            "EQUATEUR_MANAGER_EMAIL", "responsable.equateur@futurekawa.local"
        ),
    },
    "colombie": {
        "nom": "Colombie",
        "temperature_ideale": 26.0,
        "temperature_tolerance": 3.0,
        "humidite_ideale": 80.0,
        "humidite_tolerance": 2.0,
        "peremption_jours": 365,
        "email_responsable": os.getenv(
            "COLOMBIE_MANAGER_EMAIL", "responsable.colombie@futurekawa.local"
        ),
    },
}


@dataclass(frozen=True)
class ParametresPays:
    slug: str
    nom: str
    temperature_ideale: float
    temperature_tolerance: float
    humidite_ideale: float
    humidite_tolerance: float
    peremption_jours: int
    email_responsable: str
    alertes_actives: bool = True

    def seuil(self, grandeur: str) -> tuple[float, float]:
        """(idéal, tolérance) pour 'temperature' ou 'humidity'."""
        if grandeur == "temperature":
            return self.temperature_ideale, self.temperature_tolerance
        return self.humidite_ideale, self.humidite_tolerance


def _depuis_defauts(slug: str) -> ParametresPays:
    base = DEFAUTS.get(slug) or DEFAUTS[PAYS_PAR_DEFAUT]
    return ParametresPays(slug=slug, **base)


_cache: dict[str, ParametresPays] = {}


def invalider() -> None:
    """À appeler après toute écriture sur la table pays."""
    _cache.clear()


def recharger(db) -> dict[str, ParametresPays]:
    from app.models import Pays

    _cache.clear()
    for ligne in db.query(Pays).all():
        _cache[ligne.slug] = ParametresPays(
            slug=ligne.slug,
            nom=ligne.nom,
            temperature_ideale=ligne.temperature_ideale,
            temperature_tolerance=ligne.temperature_tolerance,
            humidite_ideale=ligne.humidite_ideale,
            humidite_tolerance=ligne.humidite_tolerance,
            peremption_jours=ligne.peremption_jours,
            email_responsable=ligne.email_responsable,
            alertes_actives=bool(ligne.alertes_actives),
        )
    return dict(_cache)


def get(slug: str = PAYS_PAR_DEFAUT) -> ParametresPays:
    """Paramètres d'un pays : cache, sinon table, sinon valeurs par défaut.

    Ne lève jamais : un pays inconnu retombe sur le pays par défaut, comme le
    faisait SEUILS_PAYS.get(pays, SEUILS_PAYS[PAYS_PAR_DEFAUT]) auparavant.
    """
    if slug in _cache:
        return _cache[slug]
    return _depuis_defauts(slug)


def get_db(db, slug: str) -> ParametresPays:
    """Comme get(), mais garantit que le cache est chargé depuis `db`."""
    if not _cache:
        recharger(db)
    return get(slug)


def tous(db) -> list[ParametresPays]:
    if not _cache:
        recharger(db)
    if not _cache:
        return [_depuis_defauts(s) for s in DEFAUTS]
    return sorted(_cache.values(), key=lambda p: p.slug)


def initialiser(db) -> int:
    """Crée les lignes manquantes à partir de DEFAUTS. Idempotent.

    Ne touche jamais à une ligne existante : un pays déjà paramétré depuis le
    site garde ses valeurs même si les constantes de DEFAUTS changent.
    """
    from app.models import Pays

    crees = 0
    for slug, valeurs in DEFAUTS.items():
        if db.get(Pays, slug) is None:
            db.add(Pays(slug=slug, alertes_actives=True, **valeurs))
            crees += 1
    if crees:
        db.commit()
    recharger(db)
    return crees
