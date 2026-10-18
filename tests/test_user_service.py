"""Tests for administrator user-management services."""

from unittest.mock import MagicMock, patch

import pytest

from services.authorization_service import ApplicationUserContext
from services.user_service import (
    UserAdministrationError,
    change_user_role,
    delete_user,
    invite_user,
    send_password_reset,
    set_user_active_status,
)


def make_actor(
    role: str = "admin",
) -> ApplicationUserContext:
    """Create a reusable test actor."""

    return ApplicationUserContext(
        user_id="admin-123",
        email="admin@example.com",
        display_name="Administrator",
        role=role,
        is_active=True,
        access_token="access-token",
        refresh_token="refresh-token",
    )


@patch("services.user_service.write_audit_log")
@patch("services.user_service.get_settings")
@patch("services.user_service.get_supabase_admin_client")
def test_admin_can_invite_user(
    mock_get_client,
    mock_get_settings,
    mock_audit,
):
    """Admin should be able to invite a normal user."""

    client = MagicMock()

    invited_user = MagicMock()
    invited_user.id = "new-user-123"

    response = MagicMock()
    response.user = invited_user

    client.auth.admin.invite_user_by_email.return_value = response
    mock_get_client.return_value = client

    settings = MagicMock()
    settings.base_url = "http://localhost:8501"
    mock_get_settings.return_value = settings

    user_id = invite_user(
        make_actor(),
        "NewUser@example.com",
    )

    assert user_id == "new-user-123"

    client.auth.admin.invite_user_by_email.assert_called_once_with(
        "newuser@example.com",
        {
            "redirect_to": "http://localhost:8501",
        },
    )

    mock_audit.assert_called_once()


@patch("services.user_service.get_supabase_admin_client")
def test_normal_user_cannot_invite_user(
    mock_get_client,
):
    """Normal users must fail before privileged Supabase access."""

    with pytest.raises(Exception):
        invite_user(
            make_actor(role="user"),
            "user@example.com",
        )

    mock_get_client.assert_not_called()


def test_admin_cannot_change_own_role():
    """An administrator must not demote themselves."""

    with pytest.raises(UserAdministrationError):
        change_user_role(
            make_actor(),
            "admin-123",
            "user",
        )


def test_invalid_role_is_rejected():
    """Only known application roles may be assigned."""

    with pytest.raises(UserAdministrationError):
        change_user_role(
            make_actor(),
            "user-123",
            "superadmin",
        )


def test_admin_cannot_deactivate_self():
    """An administrator must not deactivate their own account."""

    with pytest.raises(UserAdministrationError):
        set_user_active_status(
            make_actor(),
            "admin-123",
            is_active=False,
        )


@patch("services.user_service.write_audit_log")
@patch("services.user_service.get_supabase_admin_client")
def test_deactivation_bans_auth_user_and_profile(
    mock_get_client,
    mock_audit,
):
    """Deactivation should affect both Auth and application profile."""

    client = MagicMock()

    select_query = MagicMock()
    select_query.select.return_value = select_query
    select_query.eq.return_value = select_query
    select_query.limit.return_value = select_query

    select_response = MagicMock()
    select_response.data = [{"is_active": True}]
    select_query.execute.return_value = select_response

    update_query = MagicMock()
    update_query.update.return_value = update_query
    update_query.eq.return_value = update_query
    update_query.execute.return_value = MagicMock()

    client.table.side_effect = [
        select_query,
        update_query,
    ]

    mock_get_client.return_value = client

    set_user_active_status(
        make_actor(),
        "user-123",
        is_active=False,
    )

    client.auth.admin.update_user_by_id.assert_called_once()

    update_query.update.assert_called_once_with(
        {"is_active": False}
    )

    mock_audit.assert_called_once()

    @patch("services.user_service.write_audit_log")
    @patch("services.user_service.get_settings")
    @patch("services.user_service.get_supabase_client")
    def test_admin_can_request_password_reset(
        mock_get_client,
        mock_get_settings,
        mock_audit,
    ):
        """Admin should be able to send a user password reset email."""

        client = MagicMock()
        mock_get_client.return_value = client

        settings = MagicMock()
        settings.base_url = "http://localhost:8501"
        mock_get_settings.return_value = settings

        send_password_reset(
            make_actor(),
            "user-123",
            "User@example.com",
        )

        client.auth.reset_password_for_email.assert_called_once_with(
            "user@example.com",
            {
                "redirect_to": "http://localhost:8501",
            },
        )

    mock_audit.assert_called_once()


@patch("services.user_service.get_supabase_client")
def test_normal_user_cannot_request_password_reset(
    mock_get_client,
):
    """Normal users must not initiate admin password resets."""

    with pytest.raises(Exception):
        send_password_reset(
            make_actor(role="user"),
            "target-user",
            "target@example.com",
        )

    mock_get_client.assert_not_called()


def test_admin_cannot_delete_self():
    """Administrators must not delete themselves."""

    with pytest.raises(UserAdministrationError):
        delete_user(
            make_actor(),
            "admin-123",
        )


@patch("services.user_service.write_audit_log")
@patch("services.user_service.get_supabase_admin_client")
def test_admin_can_delete_other_user(
    mock_get_client,
    mock_audit,
):
    """Admin should be able to permanently delete another user."""

    client = MagicMock()

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "role": "user",
            "is_active": True,
        }
    ]

    query.execute.return_value = response
    client.table.return_value = query

    mock_get_client.return_value = client

    delete_user(
        make_actor(),
        "user-123",
    )

    mock_audit.assert_called_once()

    client.auth.admin.delete_user.assert_called_once_with(
        "user-123"
    )


@patch("services.user_service.get_supabase_admin_client")
def test_normal_user_cannot_delete_user(
    mock_get_client,
):
    """Normal users must never reach privileged deletion operations."""

    with pytest.raises(Exception):
        delete_user(
            make_actor(role="user"),
            "target-user",
        )

    mock_get_client.assert_not_called()