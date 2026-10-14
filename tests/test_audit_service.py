"""Tests for administrative audit logging."""

from unittest.mock import MagicMock, patch

import pytest

from services.audit_service import (
    AuditLoggingError,
    write_audit_log,
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