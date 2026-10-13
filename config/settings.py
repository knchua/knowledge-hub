"""Application settings.

This module provides centralised application configuration.

Phase 1 Milestone 1 deliberately contains only non-sensitive
application settings. Supabase configuration will be introduced
during Milestone 2.
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppSettings:
    """Non-sensitive application settings."""

    app_name: str
    app_version: str
    environment: str
    phase: str


def get_settings() -> AppSettings:
    """Return application settings.

    Environment variables may override local defaults where appropriate.

    Returns:
        AppSettings: Immutable application configuration.
    """

    return AppSettings(
        app_name="Knowledge Hub",
        app_version="0.1.0",
        environment=os.getenv("KNOWLEDGE_HUB_ENV", "local"),
        phase="Phase 1 — Application Foundation",
    )