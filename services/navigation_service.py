"""Role-based navigation policy for Knowledge Hub."""

from dataclasses import dataclass

from services.authorization_service import ApplicationUserContext


@dataclass(frozen=True)
class NavigationPermissions:
    """Pages available to the current application user."""

    chatbot: bool
    document_analysis: bool
    knowledge_management: bool
    user_management: bool


def get_navigation_permissions(
    user: ApplicationUserContext,
) -> NavigationPermissions:
    """Return the pages available to a validated application user."""

    is_admin = user.role == "admin"

    return NavigationPermissions(
        chatbot=True,
        document_analysis=True,
        knowledge_management=is_admin,
        user_management=is_admin,
    )