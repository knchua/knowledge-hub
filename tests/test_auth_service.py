"""Tests for Knowledge Hub authentication service."""

from unittest.mock import MagicMock, patch

import pytest

from services.auth_service import (
    AuthenticationError,
    restore_session,
    sign_in,
    update_password,
    verify_recovery_token,
)


@patch("services.auth_service.get_supabase_client")
def test_sign_in_returns_authenticated_session(mock_get_client):
    """Successful Supabase authentication should return session data."""

    mock_client = MagicMock()

    mock_session = MagicMock()
    mock_session.access_token = "access-token"
    mock_session.refresh_token = "refresh-token"

    mock_user = MagicMock()
    mock_user.id = "user-123"
    mock_user.email = "user@example.com"

    mock_response = MagicMock()
    mock_response.session = mock_session
    mock_response.user = mock_user

    mock_client.auth.sign_in_with_password.return_value = mock_response
    mock_get_client.return_value = mock_client

    result = sign_in(
        "user@example.com",
        "password123",
    )

    assert result.user_id == "user-123"
    assert result.email == "user@example.com"
    assert result.access_token == "access-token"
    assert result.refresh_token == "refresh-token"


def test_sign_in_rejects_blank_credentials():
    """Blank credentials must fail before contacting Supabase."""

    with pytest.raises(AuthenticationError):
        sign_in("", "")


@patch("services.auth_service.get_supabase_client")
def test_sign_in_converts_supabase_failure(mock_get_client):
    """Authentication errors must not expose raw provider errors."""

    mock_client = MagicMock()

    mock_client.auth.sign_in_with_password.side_effect = RuntimeError(
        "provider-specific authentication error"
    )

    mock_get_client.return_value = mock_client

    with pytest.raises(AuthenticationError) as exc_info:
        sign_in(
            "user@example.com",
            "wrong-password",
        )

    assert "provider-specific" not in str(exc_info.value)


@patch("services.auth_service.get_supabase_client")
def test_restore_session_validates_user(mock_get_client):
    """Stored tokens should be validated against Supabase Auth."""

    mock_client = MagicMock()

    refreshed_session = MagicMock()
    refreshed_session.access_token = "new-access-token"
    refreshed_session.refresh_token = "new-refresh-token"

    set_session_response = MagicMock()
    set_session_response.session = refreshed_session

    verified_user = MagicMock()
    verified_user.id = "user-123"
    verified_user.email = "user@example.com"

    get_user_response = MagicMock()
    get_user_response.user = verified_user

    mock_client.auth.set_session.return_value = set_session_response
    mock_client.auth.get_user.return_value = get_user_response

    mock_get_client.return_value = mock_client

    result = restore_session(
        "old-access-token",
        "refresh-token",
    )

    assert result is not None
    assert result.user_id == "user-123"
    assert result.access_token == "new-access-token"


@patch("services.auth_service.get_supabase_client")
def test_restore_session_returns_none_when_invalid(mock_get_client):
    """Invalid or expired sessions should fail safely."""

    mock_client = MagicMock()

    mock_client.auth.set_session.side_effect = RuntimeError(
        "invalid refresh token"
    )

    mock_get_client.return_value = mock_client

    result = restore_session(
        "invalid-access-token",
        "invalid-refresh-token",
    )

    assert result is None

@patch("services.auth_service.get_supabase_client")
def test_verify_recovery_token_returns_session(mock_get_client):
    """Valid recovery token should establish an authenticated session."""

    client = MagicMock()

    session = MagicMock()
    session.access_token = "access-token"
    session.refresh_token = "refresh-token"

    user = MagicMock()
    user.id = "user-123"
    user.email = "user@example.com"

    response = MagicMock()
    response.session = session
    response.user = user

    client.auth.verify_otp.return_value = response
    mock_get_client.return_value = client

    result = verify_recovery_token("token-hash")

    assert result.user_id == "user-123"
    assert result.email == "user@example.com"
    assert result.access_token == "access-token"
    assert result.refresh_token == "refresh-token"

    client.auth.verify_otp.assert_called_once_with(
        {
            "token_hash": "token-hash",
            "type": "recovery",
        }
    )


@patch("services.auth_service.get_supabase_client")
def test_invalid_recovery_token_is_rejected(mock_get_client):
    """Invalid recovery links should fail safely."""

    client = MagicMock()

    client.auth.verify_otp.side_effect = RuntimeError(
        "invalid token"
    )

    mock_get_client.return_value = client

    with pytest.raises(AuthenticationError):
        verify_recovery_token("invalid-token")


@patch("services.auth_service.get_supabase_client")
def test_update_password(mock_get_client):
    """Password update should use the authenticated recovery session."""

    client = MagicMock()
    mock_get_client.return_value = client

    update_password(
        "access-token",
        "refresh-token",
        "new-password-123",
    )

    client.auth.set_session.assert_called_once_with(
        "access-token",
        "refresh-token",
    )

    client.auth.update_user.assert_called_once_with(
        {
            "password": "new-password-123",
        }
    )


def test_update_password_requires_value():
    """Blank password must be rejected."""

    with pytest.raises(AuthenticationError):
        update_password(
            "access-token",
            "refresh-token",
            "",
        )