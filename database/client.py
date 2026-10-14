"""Supabase client factories for Knowledge Hub.

Security model:
- Normal application clients are created per use and may carry a user session.
- The privileged admin client is server-side only and may be cached because
  it must never carry an end-user session.
"""

from functools import lru_cache

from supabase import Client, create_client
from supabase.client import ClientOptions

from config.settings import get_settings


def get_supabase_client() -> Client:
    """Return a fresh normal application Supabase client.

    A fresh client is created for each use so authenticated user sessions
    are never shared through a process-wide cached client.
    """

    settings = get_settings()

    return create_client(
        settings.supabase_url,
        settings.supabase_publishable_key,
        options=ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
            postgrest_client_timeout=10,
            storage_client_timeout=10,
            schema="public",
        ),
    )


@lru_cache(maxsize=1)
def get_supabase_admin_client() -> Client:
    """Return the privileged server-side Supabase client."""

    settings = get_settings()

    return create_client(
        settings.supabase_url,
        settings.supabase_secret_key,
        options=ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
            postgrest_client_timeout=10,
            storage_client_timeout=10,
            schema="public",
        ),
    )


def verify_supabase_client_creation() -> dict[str, bool]:
    """Verify that both configured Supabase clients can be constructed."""

    app_client = get_supabase_client()
    admin_client = get_supabase_admin_client()

    return {
        "application_client_created": app_client is not None,
        "admin_client_created": admin_client is not None,
    }