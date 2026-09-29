"""Business settings from the site: reading, PATCH merge, immediate effect."""

from datetime import date, timedelta

from app.models import Batch, Country, Measure
from app.services import parameters as svc

from tests.conftest import seed_countries


def _settings(db):
    """Persists the DEFAULTS constants, since the app no longer seeds by itself."""
    seed_countries(db)
    svc.reload(db)


def _batch(db, batch_id, days, country="brazil", warehouse="warehouse-brazil-1"):
    batch = Batch(
        id=batch_id,
        country=country,
        farm="Fazenda Test",
        warehouse_id=warehouse,
        storage_date=date.today() - timedelta(days=days),
    )
    db.add(batch)
    db.commit()
    return batch


class TestReadSettings:
    def test_reading_does_not_create_countries(self, client, db):
        """The API must never instantiate the DEFAULTS constants in the database."""
        assert client.get("/parameters/country").json() == []
        assert db.query(Country).count() == 0

    def test_unknown_country_is_not_seeded(self, client, db):
        assert client.get("/parameters/country/atlantis").status_code == 404
        assert db.query(Country).count() == 0

    def test_all_three_countries_are_seeded(self, client, db):
        _settings(db)
        body = client.get("/parameters/country").json()
        assert {c["slug"] for c in body} == {"brazil", "ecuador", "colombia"}

    def test_values_from_the_specification(self, client, db):
        _settings(db)
        brazil = client.get("/parameters/country/brazil").json()
        assert brazil["ideal_temperature"] == 29.0
        assert brazil["temperature_tolerance"] == 3.0
        assert brazil["ideal_humidity"] == 55.0
        assert brazil["shelf_life_days"] == 365


class TestUpdateSettings:
    def test_partial_patch_does_not_touch_other_fields(self, client, db):
        _settings(db)
        before = client.get("/parameters/country/brazil").json()

        after = client.patch(
            "/parameters/country/brazil", json={"shelf_life_days": 180}
        ).json()

        assert after["shelf_life_days"] == 180
        # Everything else must be intact: that is the regression this test locks down.
        for field in (
            "ideal_temperature", "temperature_tolerance",
            "ideal_humidity", "humidity_tolerance", "manager_email", "name",
        ):
            assert after[field] == before[field], f"{field} was overwritten by the PATCH"

    def test_empty_patch_rejected(self, client, db):
        _settings(db)
        assert client.patch("/parameters/country/brazil", json={}).status_code == 400

    def test_zero_tolerance_rejected(self, client, db):
        _settings(db)
        r = client.patch("/parameters/country/brazil", json={"temperature_tolerance": 0})
        assert r.status_code == 422

    def test_invalid_email_rejected(self, client, db):
        _settings(db)
        r = client.patch("/parameters/country/brazil", json={"manager_email": "not-an-address"})
        assert r.status_code == 422

    def test_unknown_country(self, client, db):
        _settings(db)
        r = client.patch("/parameters/country/atlantis", json={"shelf_life_days": 10})
        assert r.status_code == 404


class TestEffectOnBusinessLogic:
    """The settings must change the behaviour without a restart: that is the
    whole point of taking them out of the Python constants."""

    def test_shortening_shelf_life_expires_an_existing_batch(self, client, db):
        _settings(db)
        _batch(db, "LOT-200D", 200)
        assert client.get("/batches/LOT-200D").json()["status"] == "compliant"

        client.patch("/parameters/country/brazil", json={"shelf_life_days": 100})

        assert client.get("/batches/LOT-200D").json()["status"] == "expired"

    def test_tightening_tolerance_triggers_an_alert(self, client, db):
        _settings(db)
        _batch(db, "LOT-OK", 10)
        db.add(Measure(id="M1", warehouse_id="warehouse-brazil-1", temperature=31.0, humidity=55.0))
        db.commit()

        # 31 °C is within the ±3 tolerance: no alert.
        assert client.get("/alerts").json()["out_of_range_measures"] == []

        client.patch("/parameters/country/brazil", json={"temperature_tolerance": 1.0})

        alerts = client.get("/alerts").json()["out_of_range_measures"]
        assert len(alerts) == 1
        assert "temperature" in alerts[0]["reason"]

    def test_disabling_alerts_cuts_the_emails(self, client, db):
        from unittest.mock import patch

        from app.services import notifier

        _settings(db)
        _batch(db, "LOT-EXPIRED", 400)
        client.patch("/parameters/country/brazil", json={"alerts_enabled": False})

        with patch("app.services.notifier.send_email") as mock_send:
            sent = notifier.check_and_notify(["brazil"])

        assert sent == 0
        mock_send.assert_not_called()


class TestSettingsCache:
    def test_get_without_db_falls_back_to_defaults(self):
        svc.invalidate()
        assert svc.get("brazil").ideal_temperature == 29.0
        assert svc.get("colombia").ideal_humidity == 80.0
