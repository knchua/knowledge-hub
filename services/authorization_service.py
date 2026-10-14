"""Application authorization and user-context resolution.

This module converts an authenticated Supabase identity into an
authoritative Knowledge Hub application user.

Authentication answers:
    "Who are you?"

Application authorization additionally answers:
    "Does this account exist in Knowledge Hub?"
    "Is this account active?"
    "What role does this account currently have?"
"""

from dataclasses import dataclass

from database.client import get_supabase_client
from services.auth_service import (
    AuthenticatedSession,
    restore_session,
)


VALID_ROLES = {"admin", "user"}


class ApplicationAccessError(RuntimeError):
    """Raised when an authenticated identity cannot access Knowledge Hub."""


@dataclass(frozen=True)
class ApplicationUserContext:
    """Authoritative application user context."""

    user_id: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    access_token: str
    refresh_token: str


def _load_profile(
    session: AuthenticatedSession,
) -> dict:
    """Load the authenticated user's own profile through RLS.

    The query uses a publishable-key client authenticated as the user.
    RLS therefore applies and permits access only to that user's profile.

    Args:
        session: Validated Supabase authentication session.

    Returns:
        dict: User profile row.

    Raises:
        ApplicationAccessError: If the profile cannot be loaded.
    """

    client = get_supabase_client()

    try:
        # Apply the authenticated user's Supabase session to this
        # fresh client so PostgreSQL sees the request as authenticated.
        client.auth.set_session(
            session.access_token,
            session.refresh_token,
        )

        response = (
            client
            .table("profiles")
            .select(
                "user_id, display_name, role, "
                "is_active, created_at, updated_at"
            )
            .eq("user_id", session.user_id)
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise ApplicationAccessError(
            "Unable to validate application access."
        ) from exc

    rows = response.data or []

    if len(rows) != 1:
        raise ApplicationAccessError(
            "A valid application profile could not be found."
        )

    return rows[0]


def resolve_application_user(
    access_token: str,
    refresh_token: str,
) -> ApplicationUserContext:
    """Validate identity, profile, status and effective application role.

    Args:
        access_token: Stored Supabase access token.
        refresh_token: Stored Supabase refresh token.

    Returns:
        ApplicationUserContext: Validated current application user.

    Raises:
        ApplicationAccessError: If any validation step fails.
    """

    session = restore_session(
        access_token,
        refresh_token,
    )

    if session is None:
        raise ApplicationAccessError(
            "Authentication session is invalid."
        )

    profile = _load_profile(session)

    profile_user_id = str(profile.get("user_id", ""))

    if profile_user_id != session.user_id:
        raise ApplicationAccessError(
            "Application profile does not match authenticated identity."
        )

    if profile.get("is_active") is not True:
        raise ApplicationAccessError(
            "Application account is inactive."
        )

    role = profile.get("role")

    if role not in VALID_ROLES:
        raise ApplicationAccessError(
            "Application role is invalid."
        )

    display_name = profile.get("display_name")

    if display_name is not None:
        display_name = str(display_name)

    return ApplicationUserContext(
        user_id=session.user_id,
        email=session.email,
        display_name=display_name,
        role=role,
        is_active=True,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def is_admin(user: ApplicationUserContext) -> bool:
    """Return whether the current application user is an administrator."""

    return user.role == "admin"