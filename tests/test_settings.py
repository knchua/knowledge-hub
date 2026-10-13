"""Tests for application settings."""

from config.settings import get_settings


def test_default_settings(monkeypatch):
    """Application should use safe local defaults."""

    monkeypatch.delenv("KNOWLEDGE_HUB_ENV", raising=False)

    settings = get_settings()

    assert settings.app_name == "Knowledge Hub"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.phase == "Phase 1 — Application Foundation"


def test_environment_can_be_overridden(monkeypatch):
    """Application environment should support external configuration."""

    monkeypatch.setenv("KNOWLEDGE_HUB_ENV", "test")

    settings = get_settings()

    assert settings.environment == "test"