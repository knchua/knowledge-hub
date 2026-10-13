"""Tests for Supabase client creation."""

from unittest.mock import MagicMock, patch

import database.client as client_module


def setup_function():
    """Clear cached clients before each test."""

    client_module.get_supabase_client.cache_clear()
    client_module.get_supabase_admin_client.cache_clear()


@patch("database.client.create_client")
@patch("database.client.get_settings")
def test_application_client_uses_publishable_key(
    mock_get_settings,
    mock_create_client,
):
    """Normal application client must use the publishable key."""

    settings = MagicMock()
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_publishable_key = "publishable-key"
    settings.supabase_secret_key = "secret-key"

    mock_get_settings.return_value = settings
    mock_create_client.return_value = MagicMock()

    client_module.get_supabase_client()

    args, _ = mock_create_client.call_args

    assert args[0] == "https://example.supabase.co"
    assert args[1] == "publishable-key"


@patch("database.client.create_client")
@patch("database.client.get_settings")
def test_admin_client_uses_secret_key(
    mock_get_settings,
    mock_create_client,
):
    """Privileged client must use the secret key."""

    settings = MagicMock()
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_publishable_key = "publishable-key"
    settings.supabase_secret_key = "secret-key"

    mock_get_settings.return_value = settings
    mock_create_client.return_value = MagicMock()

    client_module.get_supabase_admin_client()

    args, _ = mock_create_client.call_args

    assert args[0] == "https://example.supabase.co"
    assert args[1] == "secret-key"