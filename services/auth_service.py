"""Authentication service for Knowledge Hub.

This module encapsulates Supabase Auth operations and prevents authentication
logic from being scattered through Streamlit pages.
"""

from dataclasses import dataclass
from typing import Optional

from database.client import get_supabase_client


class AuthenticationError(RuntimeError):
    """Raised when authentication cannot be completed."""


@dataclass(frozen=True)
class AuthenticatedSession:
    """Minimal authenticated session data required by the application."""

    user_id: str
    email: str
    access_token: str
    refresh_token: str


def sign_in(email: str, password: str) -> AuthenticatedSession:
    """Authenticate a user with Supabase Auth.

    Args:
        email: User email address.
        password: User password.

    Returns:
        AuthenticatedSession: Authenticated session details.

    Raises:
        AuthenticationError: If credentials are invalid or authentication
            fails.
    """

    if not email.strip() or not password:
        raise AuthenticationError("Email and password are required.")

    client = get_supabase_client()

    try:
        response = client.auth.sign_in_with_password(
            {
                "email": email.strip(),
                "password": password,
            }
        )
    except Exception as exc:
        raise AuthenticationError(
            "Unable to sign in with the supplied credentials."
        ) from exc

    session = response.session
    user = response.user

    if session is None or user is None:
        raise AuthenticationError(
            "Authentication did not return a valid session."
        )

    if not session.access_token or not session.refresh_token:
        raise AuthenticationError(
            "Authentication session is incomplete."
        )

    return AuthenticatedSession(
        user_id=str(user.id),
        email=user.email or email.strip(),
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def restore_session(
    access_token: str,
    refresh_token: str,
) -> Optional[AuthenticatedSession]:
    """Restore and validate a previously established session.

    A fresh Supabase client is created and the stored tokens are applied.
    Supabase may refresh the access token if required.

    The user is then fetched from Supabase Auth to validate the identity
    server-side rather than trusting local session contents.

    Args:
        access_token: Existing Supabase Auth access token.
        refresh_token: Existing Supabase Auth refresh token.

    Returns:
        AuthenticatedSession if valid; otherwise None.
    """

    if not access_token or not refresh_token:
        return None

    client = get_supabase_client()

    try:
        session_response = client.auth.set_session(
            access_token,
            refresh_token,
        )

        session = session_response.session

        if session is None:
            return None

        user_response = client.auth.get_user(
            session.access_token
        )

        user = user_response.user

        if user is None:
            return None

        return AuthenticatedSession(
            user_id=str(user.id),
            email=user.email or "",
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    except Exception:
        return None


def sign_out(
    access_token: str,
    refresh_token: str,
) -> None:
    """Sign the user out of Supabase Auth.

    Failure to contact Supabase should not prevent local session cleanup;
    the caller is responsible for clearing Streamlit session state.

    Args:
        access_token: Current access token.
        refresh_token: Current refresh token.
    """

    if not access_token or not refresh_token:
        return

    client = get_supabase_client()

    try:
        client.auth.set_session(
            access_token,
            refresh_token,
        )

        client.auth.sign_out()

    except Exception:
        # Local session cleanup still proceeds even if remote sign-out fails.
        pass