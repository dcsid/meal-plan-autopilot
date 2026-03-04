from pathlib import Path
import sys

import pytest
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
    AUTO_CREATE_TABLES = True
    AUTO_SEED_DATA = True
    USDA_API_KEY = None


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    return db.session
