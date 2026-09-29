"""Per-country business settings, stored in the database and editable from the site.

The thresholds used to live in three files that contradicted each other: the
COUNTRY_THRESHOLDS constant in services/alerts.py, config/seuils.ts on the
front-end, and the MQTT broker seed (which announced 20 °C ± 5 for Brazil where
the other two said 29 °C ± 3). The `countries` table becomes the single source of
truth; the front-end reads these values through the API instead of keeping a copy.

An in-memory cache avoids hitting the database on every measurement evaluation
(the notifier runs every 60 s over all warehouses). It is loaded at startup and
invalidated on every write — see `invalidate()`.

The values in DEFAULTS come from the specification. They are NOT written to the
database by this module: they only act as a read-only fallback when a country has
no row in the `countries` table, which is what lets the pure functions be
evaluated outside a database context (unit tests, first call before any country
row exists). Persisting a country is the caller's job — see
`tests/conftest.py::seed_countries` for how tests do it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_COUNTRY = "brazil"

DEFAULTS: dict[str, dict] = {
    "brazil": {
        "name": "Brazil",
        "ideal_temperature": 29.0,
        "temperature_tolerance": 3.0,
        "ideal_humidity": 55.0,
        "humidity_tolerance": 2.0,
        "shelf_life_days": 365,
        "manager_email": os.getenv(
            "BRAZIL_MANAGER_EMAIL", "manager.brazil@futurekawa.local"
        ),
    },
    "ecuador": {
        "name": "Ecuador",
        "ideal_temperature": 31.0,
        "temperature_tolerance": 3.0,
        "ideal_humidity": 60.0,
        "humidity_tolerance": 2.0,
        "shelf_life_days": 365,
        "manager_email": os.getenv(
            "ECUADOR_MANAGER_EMAIL", "manager.ecuador@futurekawa.local"
        ),
    },
    "colombia": {
        "name": "Colombia",
        "ideal_temperature": 26.0,
        "temperature_tolerance": 3.0,
        "ideal_humidity": 80.0,
        "humidity_tolerance": 2.0,
        "shelf_life_days": 365,
        "manager_email": os.getenv(
            "COLOMBIA_MANAGER_EMAIL", "manager.colombia@futurekawa.local"
        ),
    },
}


@dataclass(frozen=True)
class CountrySettings:
    slug: str
    name: str
    ideal_temperature: float
    temperature_tolerance: float
    ideal_humidity: float
    humidity_tolerance: float
    shelf_life_days: int
    manager_email: str
    alerts_enabled: bool = True

    def threshold(self, metric: str) -> tuple[float, float]:
        """(ideal, tolerance) for 'temperature' or 'humidity'."""
        if metric == "temperature":
            return self.ideal_temperature, self.temperature_tolerance
        return self.ideal_humidity, self.humidity_tolerance


def _from_defaults(slug: str) -> CountrySettings:
    base = DEFAULTS.get(slug) or DEFAULTS[DEFAULT_COUNTRY]
    return CountrySettings(slug=slug, **base)


_cache: dict[str, CountrySettings] = {}


def invalidate() -> None:
    """To be called after any write to the countries table."""
    _cache.clear()


def reload(db) -> dict[str, CountrySettings]:
    from app.models import Country

    _cache.clear()
    for row in db.query(Country).all():
        _cache[row.slug] = CountrySettings(
            slug=row.slug,
            name=row.name,
            ideal_temperature=row.ideal_temperature,
            temperature_tolerance=row.temperature_tolerance,
            ideal_humidity=row.ideal_humidity,
            humidity_tolerance=row.humidity_tolerance,
            shelf_life_days=row.shelf_life_days,
            manager_email=row.manager_email,
            alerts_enabled=bool(row.alerts_enabled),
        )
    return dict(_cache)


def get(slug: str = DEFAULT_COUNTRY) -> CountrySettings:
    """Settings for a country: cache, then table, then default values.

    Never raises: an unknown country falls back to the default country, the way
    COUNTRY_THRESHOLDS.get(country, COUNTRY_THRESHOLDS[DEFAULT_COUNTRY]) did
    before.
    """
    if slug in _cache:
        return _cache[slug]
    return _from_defaults(slug)


def get_from_db(db, slug: str) -> CountrySettings:
    """Like get(), but guarantees that the cache has been loaded from `db`."""
    if not _cache:
        reload(db)
    return get(slug)


def all_countries(db) -> list[CountrySettings]:
    if not _cache:
        reload(db)
    if not _cache:
        return [_from_defaults(s) for s in DEFAULTS]
    return sorted(_cache.values(), key=lambda p: p.slug)
