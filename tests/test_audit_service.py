"""Tests for administrative audit logging."""

from unittest.mock import MagicMock, patch

import pytest

from services.audit_service import (
    AuditLoggingError,
    list_audit_logs,
    write_audit_log,
)
from services.authorization_service import ApplicationUserContext


@patch("services.audit_service.get_supabase_admin_client")
def test_write_audit_log(mock_get_client):
    """Administrative audit records should be inserted."""

    query = MagicMock()
    query.insert.return_value = query
    query.execute.return_value = MagicMock()

    client = MagicMock()
    client.table.return_value = query

    mock_get_client.return_value = client

    write_audit_log(
        actor_user_id="admin-123",
        action="test_action",
        target_user_id="user-123",
        details={"value": "test"},
    )

    client.table.assert_called_once_with("audit_logs")

    query.insert.assert_called_once_with(
        {
            "actor_user_id": "admin-123",
            "action": "test_action",
            "target_user_id": "user-123",
            "details": {"value": "test"},
        }
    )


def test_audit_log_requires_actor():
    """Normal administrative audit records require an actor."""

    with pytest.raises(AuditLoggingError):
        write_audit_log(
            actor_user_id="",
            action="test",
        )


def make_actor(
    role: str = "admin",
) -> ApplicationUserContext:
    """Create a reusable audit test actor."""

    return ApplicationUserContext(
        user_id="admin-123",
        email="admin@example.com",
        display_name="Administrator",
        role=role,
        is_active=True,
        access_token="access-token",
        refresh_token="refresh-token",
    )


@patch("services.audit_service.get_supabase_admin_client")
def test_write_audit_log(mock_get_client):
    """Administrative audit records should be inserted."""

    query = MagicMock()
    query.insert.return_value = query
    query.execute.return_value = MagicMock()

    client = MagicMock()
    client.table.return_value = query

    mock_get_client.return_value = client

    write_audit_log(
        actor_user_id="admin-123",
        action="test_action",
        target_user_id="user-123",
        details={"value": "test"},
    )

    client.table.assert_called_once_with("audit_logs")

    query.insert.assert_called_once_with(
        {
            "actor_user_id": "admin-123",
            "action": "test_action",
            "target_user_id": "user-123",
            "details": {"value": "test"},
        }
    )


def test_audit_log_requires_actor():
    """Normal administrative audit records require an actor."""

    with pytest.raises(AuditLoggingError):
        write_audit_log(
            actor_user_id="",
            action="test",
        )


@patch("services.audit_service.get_supabase_admin_client")
def test_admin_can_list_audit_logs(mock_get_client):
    """Administrators should be able to review recent audit records."""

    query = MagicMock()
    query.select.return_value = query
    query.order.return_value = query
    query.limit.return_value = query

    response = MagicMock()
    response.data = [
        {
            "id": "audit-1",
            "actor_user_id": "admin-123",
            "action": "user_role_changed",
            "target_user_id": "user-123",
            "created_at": "2026-10-17T10:00:00+00:00",
            "details": {
                "previous_role": "user",
                "new_role": "admin",
            },
        }
    ]

    query.execute.return_value = response

    client = MagicMock()
    client.table.return_value = query

    mock_get_client.return_value = client

    results = list_audit_logs(
        make_actor(),
        limit=100,
    )

    assert len(results) == 1
    assert results[0].action == "user_role_changed"
    assert results[0].target_user_id == "user-123"


@patch("services.audit_service.get_supabase_admin_client")
def test_normal_user_cannot_list_audit_logs(
    mock_get_client,
):
    """Normal users must fail before privileged audit access."""

    with pytest.raises(Exception):
        list_audit_logs(
            make_actor(role="user"),
        )

    mock_get_client.assert_not_called()


def test_invalid_audit_limit_is_rejected():
    """Audit queries must use a positive limit."""

    with pytest.raises(AuditLoggingError):
        list_audit_logs(
            make_actor(),
            limit=0,
        )