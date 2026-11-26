import pytest
from pydantic import ValidationError

from app.core.config import Settings, normalize_database_url

DB = "postgresql://u:p@localhost:5432/db"


def make(**kw) -> Settings:
    return Settings(_env_file=None, database_url=kw.pop("database_url", DB), **kw)


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg2://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
    ],
)
def test_database_url_normalized_to_asyncpg(url):
    assert normalize_database_url(url) == "postgresql+asyncpg://u:p@h:5432/d"


def test_non_postgres_url_rejected():
    with pytest.raises(ValueError):
        normalize_database_url("mysql://u:p@h/d")


def test_cors_origins_from_comma_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test,")
    assert make().cors_origins == ["http://a.test", "http://b.test"]


def test_defaults_are_single_user_loopback():
    s = make()
    assert s.auth_mode == "none"
    assert s.backend_host == "127.0.0.1"
    assert s.api_v1_prefix == "/api/v1"


def test_no_auth_refuses_non_loopback_host():
    with pytest.raises(ValidationError, match="AUTH_MODE=none"):
        make(backend_host="0.0.0.0")


def test_api_key_mode_requires_long_key():
    with pytest.raises(ValidationError, match="API_KEY"):
        make(auth_mode="api_key", api_key="short")
    s = make(auth_mode="api_key", api_key="k" * 32, backend_host="0.0.0.0")
    assert s.api_key is not None and s.api_key.get_secret_value() == "k" * 32
    assert "k" * 32 not in repr(s)  # secret never printed


def test_supabase_pooler_detected():
    assert make(
        database_url="postgresql://u:p@pooler.supabase.com:6543/postgres"
    ).uses_transaction_pooler
    assert not make().uses_transaction_pooler


def test_json_logs_default_follows_environment():
    assert make(app_env="production").json_logs is True
    assert make(app_env="development").json_logs is False
    assert make(app_env="development", log_json=True).json_logs is True
