"""Authenticated, self-service profile operations (P2 only).

Never use a privileged Supabase client for profile reads or writes.
"""

from dataclasses import dataclass
import unicodedata

from database.client import get_supabase_client
from services.authorization_service import (
    ApplicationAccessError,
    ApplicationUserContext,
    resolve_application_user,
)


class ProfileError(RuntimeError):
    """A profile operation could not be completed safely."""


class ProfileValidationError(ProfileError):
    """The requested display name is invalid."""


@dataclass(frozen=True)
class OwnProfile:
    email: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: str | None


def validate_display_name(value: str) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("Enter a valid display name.")
    name = unicodedata.normalize("NFC", value.strip())
    if not 1 <= len(name) <= 100:
        raise ProfileValidationError("Display name must contain 1 to 100 characters.")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        raise ProfileValidationError("Display name contains unsupported characters.")
    return name


def _validated_context(user: ApplicationUserContext) -> ApplicationUserContext:
    """Revalidate Auth, status, role and identity against live provider data."""
    if not user.is_active or user.role not in {"admin", "user"}:
        raise ProfileError("Your account does not currently have access.")
    if not user.access_token or not user.refresh_token or not user.user_id:
        raise ProfileError("Please sign in again.")
    try:
        current = resolve_application_user(user.access_token, user.refresh_token)
    except Exception as exc:
        raise ProfileError("Unable to verify your account right now.") from exc
    if (current.user_id != user.user_id or current.email != user.email
            or not current.is_active or current.role not in {"admin", "user"}):
        raise ProfileError("Your account has changed. Please sign in again.")
    return current


def _user_client(current: ApplicationUserContext):
    client = get_supabase_client()
    client.auth.set_session(current.access_token, current.refresh_token)
    return client


def _fetch_own_row(client, user_id: str) -> dict:
    response = (client.table("profiles")
                .select("user_id, display_name, role, is_active, created_at")
                .eq("user_id", user_id).limit(1).execute())
    rows = response.data or []
    if len(rows) != 1 or str(rows[0].get("user_id")) != user_id:
        raise ProfileError("Unable to retrieve your profile.")
    if rows[0].get("is_active") is not True or rows[0].get("role") not in {"user", "admin"}:
        raise ProfileError("Your account does not currently have access.")
    return rows[0]


def load_own_profile(user: ApplicationUserContext) -> OwnProfile:
    current = _validated_context(user)
    try:
        row = _fetch_own_row(_user_client(current), current.user_id)
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError("Unable to load your profile.") from exc
    return OwnProfile(
        email=current.email,
        display_name=row.get("display_name"),
        role=row["role"],
        is_active=True,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


def update_own_display_name(user: ApplicationUserContext, value: str) -> OwnProfile:
    name = validate_display_name(value)
    current = _validated_context(user)
    try:
        client = _user_client(current)
        before = _fetch_own_row(client, current.user_id)
        if before.get("display_name") == name:
            return OwnProfile(current.email, name, before["role"], True,
                              str(before["created_at"]) if before.get("created_at") else None)
        # Only the column explicitly granted to `authenticated` may be modified.
        response = (client.table("profiles")
                    .update({"display_name": name})
                    .eq("user_id", current.user_id)
                    .select("user_id, display_name, role, is_active, created_at")
                    .execute())
        rows = response.data or []
        if (len(rows) != 1 or str(rows[0].get("user_id")) != current.user_id
                or rows[0].get("display_name") != name
                or rows[0].get("is_active") is not True
                or rows[0].get("role") not in {"admin", "user"}):
            raise ProfileError("Unable to confirm that your profile was updated.")
        row = rows[0]
        return OwnProfile(current.email, name, row["role"], True,
                          str(row["created_at"]) if row.get("created_at") else None)
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError("Unable to update your profile.") from exc
