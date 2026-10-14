"""Tests for Supabase client creation."""

from unittest.mock import MagicMock, patch

import database.client as client_module


def setup_function():
    """Clear the cached privileged client before each test."""

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
def test_application_client_is_not_shared(
    mock_get_settings,
    mock_create_client,
):
    """Application clients must be created independently."""

    settings = MagicMock()
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_publishable_key = "publishable-key"
    settings.supabase_secret_key = "secret-key"

    mock_get_settings.return_value = settings

    first_client = MagicMock()
    second_client = MagicMock()

    mock_create_client.side_effect = [
        first_client,
        second_client,
    ]

    result_one = client_module.get_supabase_client()
    result_two = client_module.get_supabase_client()

    assert result_one is first_client
    assert result_two is second_client
    assert mock_create_client.call_count == 2


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