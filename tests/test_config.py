from app.config import _normalize_database_url, _normalize_usda_api_key, _to_bool


def test_normalize_database_url_postgres_scheme():
    value = _normalize_database_url("postgres://user:pass@localhost:5432/db")
    assert value.startswith("postgresql://")


def test_normalize_database_url_defaults_to_sqlite():
    assert _normalize_database_url(None) == "sqlite:///meal_autopilot.db"


def test_to_bool_parser():
    assert _to_bool("true") is True
    assert _to_bool("YES") is True
    assert _to_bool("0", default=True) is False
    assert _to_bool(None, default=True) is True


def test_normalize_usda_api_key_defaults_to_demo():
    assert _normalize_usda_api_key(None) == "DEMO_KEY"
    assert _normalize_usda_api_key("") == "DEMO_KEY"
    assert _normalize_usda_api_key("   ") == "DEMO_KEY"


def test_normalize_usda_api_key_keeps_explicit_value():
    assert _normalize_usda_api_key("abc123") == "abc123"
    assert _normalize_usda_api_key("  demo-key  ") == "demo-key"
