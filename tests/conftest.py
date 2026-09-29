import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ALERT_LOOP_ENABLED", "0")

from app.database import Base, get_db
from app.main import app

SQLALCHEMY_TEST_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def seed_countries(db) -> int:
    """Persists the DEFAULTS constants as real `countries` rows.

    Test-only. The application never does this: services/parameters.py keeps
    DEFAULTS as a read-only fallback and never writes. Tests that exercise the
    settings endpoints need actual rows, so the seeding is done here, explicitly.
    """
    from app.models import Country
    from app.services.parameters import DEFAULTS

    created = 0
    for slug, values in DEFAULTS.items():
        if db.get(Country, slug) is None:
            db.add(Country(slug=slug, alerts_enabled=True, **values))
            created += 1
    db.commit()
    return created


@pytest.fixture(autouse=True)
def setup_db():
    from app.services import parameters

    Base.metadata.create_all(bind=engine)
    parameters.invalidate()
    yield
    parameters.invalidate()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
