"""Tests for database health checks."""

from unittest.mock import MagicMock, patch

from database.health import check_database_connection


@patch("database.health.get_supabase_admin_client")
def test_database_health_check_succeeds(mock_get_client):
    """Health check should return True when Supabase responds."""

    mock_response = MagicMock()

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = mock_response

    mock_client = MagicMock()
    mock_client.table.return_value = mock_query

    mock_get_client.return_value = mock_client

    assert check_database_connection() is True


@patch("database.health.get_supabase_admin_client")
def test_database_health_check_handles_failure(mock_get_client):
    """Health check should fail safely without leaking exceptions."""

    mock_get_client.side_effect = RuntimeError(
        "simulated database failure"
    )

    assert check_database_connection() is False