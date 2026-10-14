"""Tests for Knowledge Hub navigation permissions."""

from services.authorization_service import ApplicationUserContext
from services.navigation_service import get_navigation_permissions


def make_user(role: str) -> ApplicationUserContext:
    """Create a test application user."""

    return ApplicationUserContext(
        user_id="user-123",
        email="user@example.com",
        display_name="Test User",
        role=role,
        is_active=True,
        access_token="access-token",
        refresh_token="refresh-token",
    )


def test_normal_user_navigation():
    """Normal users must receive only user-facing pages."""

    user = make_user("user")

    permissions = get_navigation_permissions(user)

    assert permissions.chatbot is True
    assert permissions.document_analysis is True

    assert permissions.knowledge_management is False
    assert permissions.user_management is False


def test_admin_navigation():
    """Administrators should receive user and admin pages."""

    admin = make_user("admin")

    permissions = get_navigation_permissions(admin)

    assert permissions.chatbot is True
    assert permissions.document_analysis is True
    assert permissions.knowledge_management is True
    assert permissions.user_management is True