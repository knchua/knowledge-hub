"""Tests for application settings."""

from unittest.mock import patch

from config.settings import get_settings


TEST_SECRETS = {
    "supabase": {
        "url": "https://example.supabase.co",
        "publishable_key": "test-publishable-key",
        "secret_key": "test-secret-key",
    },
    "app": {
        "base_url": "http://localhost:8501",
    },
}


@patch("config.settings.st.secrets", TEST_SECRETS)
def test_default_settings(monkeypatch):
    """Application should use safe local defaults."""

    monkeypatch.delenv("KNOWLEDGE_HUB_ENV", raising=False)

    settings = get_settings()

    assert settings.app_name == "Knowledge Hub"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.phase == "Phase 1 — Application Foundation"

    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_publishable_key == "test-publishable-key"
    assert settings.supabase_secret_key == "test-secret-key"
    assert settings.base_url == "http://localhost:8501"


@patch("config.settings.st.secrets", TEST_SECRETS)
def test_environment_can_be_overridden(monkeypatch):
    """Application environment should support external configuration."""

    monkeypatch.setenv("KNOWLEDGE_HUB_ENV", "test")

    settings = get_settings()

    assert settings.environment == "test"

@patch("config.settings.st.secrets", {})
def test_missing_supabase_configuration_raises_error():
    """Missing Supabase configuration should fail clearly."""

    from config.settings import ConfigurationError

    try:
        get_settings()
    except ConfigurationError as exc:
        assert "Missing required configuration" in str(exc)
    else:
        raise AssertionError("ConfigurationError was not raised")