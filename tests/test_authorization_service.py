"""Tests for application authorization."""

from unittest.mock import MagicMock, patch

import pytest

from services.auth_service import AuthenticatedSession
from services.authorization_service import (
    ApplicationAccessError,
    ApplicationUserContext,
    is_admin,
    require_admin,
    resolve_application_user,
)


def make_session() -> AuthenticatedSession:
    """Return a reusable authenticated test session."""

    return AuthenticatedSession(
        user_id="user-123",
        email="user@example.com",
        access_token="access-token",
        refresh_token="refresh-token",
    )


@patch("services.authorization_service.get_supabase_client")
@patch("services.authorization_service.restore_session")
def test_active_user_is_authorized(
    mock_restore_session,
    mock_get_client,
):
    """Active user with a valid profile should receive application access."""

    session = make_session()
    mock_restore_session.return_value = session

    mock_client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "user_id": "user-123",
            "display_name": "Test User",
            "role": "user",
            "is_active": True,
        }
    ]

    query.execute.return_value = response
    mock_client.table.return_value = query
    mock_get_client.return_value = mock_client

    result = resolve_application_user(
        "access-token",
        "refresh-token",
    )

    assert result.user_id == "user-123"
    assert result.email == "user@example.com"
    assert result.display_name == "Test User"
    assert result.role == "user"
    assert result.is_active is True


@patch("services.authorization_service.restore_session")
def test_invalid_authentication_session_is_denied(
    mock_restore_session,
):
    """Invalid Supabase sessions must not receive application access."""

    mock_restore_session.return_value = None

    with pytest.raises(ApplicationAccessError):
        resolve_application_user(
            "bad-token",
            "bad-refresh-token",
        )


@patch("services.authorization_service.get_supabase_client")
@patch("services.authorization_service.restore_session")
def test_missing_profile_is_denied(
    mock_restore_session,
    mock_get_client,
):
    """Authenticated identity without a profile must be denied."""

    mock_restore_session.return_value = make_session()

    mock_client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = []

    query.execute.return_value = response
    mock_client.table.return_value = query
    mock_get_client.return_value = mock_client

    with pytest.raises(ApplicationAccessError):
        resolve_application_user(
            "access-token",
            "refresh-token",
        )


@patch("services.authorization_service.get_supabase_client")
@patch("services.authorization_service.restore_session")
def test_inactive_user_is_denied(
    mock_restore_session,
    mock_get_client,
):
    """Inactive application profiles must be denied access."""

    mock_restore_session.return_value = make_session()

    mock_client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "user_id": "user-123",
            "display_name": "Inactive User",
            "role": "user",
            "is_active": False,
        }
    ]

    query.execute.return_value = response
    mock_client.table.return_value = query
    mock_get_client.return_value = mock_client

    with pytest.raises(ApplicationAccessError):
        resolve_application_user(
            "access-token",
            "refresh-token",
        )


@patch("services.authorization_service.get_supabase_client")
@patch("services.authorization_service.restore_session")
def test_mismatched_profile_identity_is_denied(
    mock_restore_session,
    mock_get_client,
):
    """A profile belonging to another identity must never be accepted."""

    mock_restore_session.return_value = make_session()

    mock_client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "user_id": "different-user",
            "display_name": "Wrong User",
            "role": "user",
            "is_active": True,
        }
    ]

    query.execute.return_value = response
    mock_client.table.return_value = query
    mock_get_client.return_value = mock_client

    with pytest.raises(ApplicationAccessError):
        resolve_application_user(
            "access-token",
            "refresh-token",
        )


@patch("services.authorization_service.get_supabase_client")
@patch("services.authorization_service.restore_session")
def test_invalid_role_is_denied(
    mock_restore_session,
    mock_get_client,
):
    """Unexpected role values must fail closed."""

    mock_restore_session.return_value = make_session()

    mock_client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "user_id": "user-123",
            "display_name": "Test User",
            "role": "superadmin",
            "is_active": True,
        }
    ]

    query.execute.return_value = response
    mock_client.table.return_value = query
    mock_get_client.return_value = mock_client

    with pytest.raises(ApplicationAccessError):
        resolve_application_user(
            "access-token",
            "refresh-token",
        )


def test_is_admin():
    """Only the admin role should satisfy the admin check."""

    user = MagicMock()
    user.role = "admin"

    assert is_admin(user) is True

    user.role = "user"

    assert is_admin(user) is False

def make_application_user(
    role: str = "user",
    is_active: bool = True,
) -> ApplicationUserContext:
    """Return a reusable application user context."""

    return ApplicationUserContext(
        user_id="user-123",
        email="user@example.com",
        display_name="Test User",
        role=role,
        is_active=is_active,
        access_token="access-token",
        refresh_token="refresh-token",
    )


def test_require_admin_accepts_admin():
    """Active administrators should pass the admin guard."""

    user = make_application_user(
        role="admin",
        is_active=True,
    )

    require_admin(user)


def test_require_admin_rejects_normal_user():
    """Normal users must not pass the administrator guard."""

    user = make_application_user(
        role="user",
        is_active=True,
    )

    with pytest.raises(ApplicationAccessError):
        require_admin(user)


def test_require_admin_rejects_inactive_admin():
    """Inactive administrators must not retain privileged access."""

    user = make_application_user(
        role="admin",
        is_active=False,
    )

    with pytest.raises(ApplicationAccessError):
        require_admin(user)