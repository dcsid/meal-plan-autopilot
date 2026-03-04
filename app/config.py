import os
from typing import Optional


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_database_url(value: Optional[str]) -> str:
    if not value:
        return "sqlite:///meal_autopilot.db"

    # Render/Heroku-style URLs may use postgres:// which SQLAlchemy 2 rejects.
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql://", 1)
    return value


def _normalize_usda_api_key(value: Optional[str]) -> str:
    if value is None:
        return "DEMO_KEY"
    normalized = value.strip()
    return normalized or "DEMO_KEY"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    USDA_API_KEY = _normalize_usda_api_key(os.getenv("USDA_API_KEY"))
    AUTO_CREATE_TABLES = _to_bool(os.getenv("AUTO_CREATE_TABLES"), default=True)
    AUTO_SEED_DATA = _to_bool(os.getenv("AUTO_SEED_DATA"), default=True)
    AUTO_SEED_DEMO_PANTRY = _to_bool(os.getenv("AUTO_SEED_DEMO_PANTRY"), default=False)
