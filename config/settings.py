"""Application settings.

Centralises application configuration and access to Streamlit secrets.
"""

from dataclasses import dataclass
import os

import streamlit as st


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True)
class AppSettings:
    """Application configuration."""

    app_name: str
    app_version: str
    environment: str
    phase: str
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    base_url: str


def _get_required_secret(section: str, key: str) -> str:
    """Read a required value from Streamlit secrets.

    Args:
        section: TOML section name.
        key: Secret key within the section.

    Returns:
        The configured secret value.

    Raises:
        ConfigurationError: If the secret is missing or blank.
    """

    try:
        value = st.secrets[section][key]
    except (KeyError, FileNotFoundError) as exc:
        raise ConfigurationError(
            f"Missing required configuration: {section}.{key}"
        ) from exc

    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Configuration value is empty: {section}.{key}"
        )

    return value.strip()


def get_settings() -> AppSettings:
    """Return validated application settings."""

    return AppSettings(
        app_name="Knowledge Hub",
        app_version="0.1.0",
        environment=os.getenv("KNOWLEDGE_HUB_ENV", "local"),
        phase="Phase 1 — Application Foundation",
        supabase_url=_get_required_secret("supabase", "url"),
        supabase_publishable_key=_get_required_secret(
            "supabase",
            "publishable_key",
        ),
        supabase_secret_key=_get_required_secret(
            "supabase",
            "secret_key",
        ),
        base_url=_get_required_secret(
            "app",
            "base_url",
        ),
    )