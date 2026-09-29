"""Business evaluation rules: measurement quality and batch shelf life.

The thresholds and the shelf life duration are no longer constants: they come
from the `countries` table via services/parameters.py, and are editable from the
site. The functions keep their signature — `country` stays a plain slug — so
they remain testable without a database: outside a database context,
parameters.get() falls back to the values from the specification.
"""

from datetime import date

from app.services.parameters import DEFAULT_COUNTRY, get as _params

# Measurement quality scale, from best to worst. The boundary between "fair"
# and "low" is the configured tolerance: beyond it, the measurement is out of
# range. Only the "low" and "critical" tiers raise an alert
# (Alerts page + e-mail) — cf. evaluate_measure().
QUALITY_ORDER = ["excellent", "good", "fair", "low", "critical"]
ALERTING_TIERS = {"low", "critical"}

# Beyond this multiple of the tolerance, the deviation goes from "low" to "critical".
CRITICAL_MULTIPLIER = 2.0

# Metric -> (label, unit, threshold attribute name in CountrySettings)
_METRICS = (
    ("temperature", "°C", "temperature"),
    ("humidity", "%", "humidity"),
)


def compute_batch_status(storage_date: date, country: str = DEFAULT_COUNTRY) -> str:
    if (date.today() - storage_date).days > _params(country).shelf_life_days:
        return "expired"
    return "compliant"


def _classify(deviation_abs: float, tolerance: float) -> str:
    if deviation_abs <= tolerance * 0.25:
        return "excellent"
    if deviation_abs <= tolerance * 0.6:
        return "good"
    if deviation_abs <= tolerance:
        return "fair"
    if deviation_abs <= tolerance * CRITICAL_MULTIPLIER:
        return "low"
    return "critical"


def evaluate_quality(temperature: float, humidity: float, country: str = DEFAULT_COUNTRY) -> list[dict]:
    """Classify temperature and humidity on the excellent/good/fair/low/critical scale.

    Always returns 2 entries (one per metric), even when everything is fine —
    unlike evaluate_measure() which only keeps the alerting metrics. Each entry
    is {"metric", "value", "tier", "direction", "reason"}; "direction" is None for
    excellent/good/fair (the measurement is within tolerance, there is no point
    flagging a direction).
    """
    params = _params(country)
    values = {"temperature": temperature, "humidity": humidity}
    results = []
    for label, unit, key in _METRICS:
        value = values[key]
        ideal, tolerance = params.threshold(key)
        deviation = value - ideal
        tier = _classify(abs(deviation), tolerance)
        if tier in ALERTING_TIERS:
            direction = "too high" if deviation > 0 else "too low"
            min_bound, max_bound = ideal - tolerance, ideal + tolerance
            reason = (
                f"{label} {direction}: {value:.1f}{unit} "
                f"(threshold {min_bound:.1f}–{max_bound:.1f}{unit})"
            )
        else:
            direction = None
            reason = (
                f"{label} {tier}: {value:.1f}{unit} "
                f"(ideal {ideal:.1f}{unit} ±{tolerance:.1f}{unit})"
            )
        results.append({
            "metric": label,
            "value": value,
            "tier": tier,
            "direction": direction,
            "reason": reason,
            # Technical type, used as a component of the dedup key of
            # persisted alerts (cf. services/alert_lifecycle.py).
            "type": key,
        })
    return results


def evaluate_measure(temperature: float, humidity: float, country: str = DEFAULT_COUNTRY) -> list[dict]:
    """Anomalies requiring an alert ("low" or "critical" tier), subset of evaluate_quality()."""
    return [a for a in evaluate_quality(temperature, humidity, country) if a["tier"] in ALERTING_TIERS]


def is_measure_out_of_range(
    temperature: float, humidity: float, country: str = DEFAULT_COUNTRY
) -> tuple[bool, str]:
    anomalies = evaluate_measure(temperature, humidity, country)
    if not anomalies:
        return False, ""
    return True, " / ".join(a["reason"] for a in anomalies)


def problematic_batch_reason(
    storage_date: date, country: str = DEFAULT_COUNTRY
) -> tuple[bool, str]:
    if compute_batch_status(storage_date, country) != "expired":
        return False, ""
    limit = _params(country).shelf_life_days
    age_days = (date.today() - storage_date).days
    reason = (
        f"Expired batch: stored for {age_days} days "
        f"(limit {limit} days, exceeded by {age_days - limit} days)"
    )
    return True, reason


def latest_measures_per_warehouse(db, warehouses: set[str] | None = None):
    """The latest reading of each warehouse, optionally restricted to a subset.

    Extracted here because three callers need it with exactly the same definition
    of "latest reading": the /alerts router, the e-mail notifier and the
    synchronisation of persisted alerts.
    """
    from sqlalchemy import func

    from app.models import Measure

    subquery = db.query(
        Measure.warehouse_id, func.max(Measure.timestamp).label("max_ts")
    )
    if warehouses is not None:
        if not warehouses:
            return []
        subquery = subquery.filter(Measure.warehouse_id.in_(warehouses))
    subquery = subquery.group_by(Measure.warehouse_id).subquery()

    return (
        db.query(Measure)
        .join(
            subquery,
            (Measure.warehouse_id == subquery.c.warehouse_id)
            & (Measure.timestamp == subquery.c.max_ts),
        )
        .all()
    )


def compute_alerts(db, country: str | None = None):
    """Computes the alerts (expired batches, "low"/"critical" out-of-range measurements), filtered by country if provided.

    Expired batches are never filtered: an expired batch is always reported.

    For measurements, only the LATEST reading of each warehouse is considered (at
    most one alert per warehouse): an alert reflects the current state, not every
    past breach — otherwise a warehouse with weeks of out-of-range readings would
    generate dozens of alerts for the same problem. The full history stays
    available through GET /measures.

    Logic shared between the /alerts router (read), the e-mail notifier
    (automatic trigger) and alert persistence: returns raw tuples rather than
    Pydantic schemas, to stay reusable from all three sides.
    """
    from app.models import Batch

    all_batches = db.query(Batch).all()
    country_by_warehouse = {b.warehouse_id: b.country for b in all_batches}

    batches = [b for b in all_batches if not country or b.country == country]
    country_warehouses = {b.warehouse_id for b in batches} if country else None

    problematic_batches = []
    for batch in batches:
        is_problematic, reason = problematic_batch_reason(batch.storage_date, batch.country)
        if is_problematic:
            batch.status = "expired"
            problematic_batches.append((batch, reason))

    out_of_range_measures = []
    for measure in latest_measures_per_warehouse(db, country_warehouses):
        measure_country = country_by_warehouse.get(measure.warehouse_id, DEFAULT_COUNTRY)
        anomalies = evaluate_measure(measure.temperature, measure.humidity, measure_country)
        if not anomalies:
            continue
        severity = "critical" if any(a["tier"] == "critical" for a in anomalies) else "low"
        reason = " / ".join(a["reason"] for a in anomalies)
        out_of_range_measures.append((measure, reason, severity))

    return problematic_batches, out_of_range_measures
