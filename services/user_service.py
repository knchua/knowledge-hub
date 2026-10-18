"""Administrator-only user management services."""

from dataclasses import dataclass
from typing import Any

#from database.client import get_supabase_admin_client
from database.client import (
    get_supabase_admin_client,
    get_supabase_client,
)

from services.audit_service import write_audit_log
from services.authorization_service import (
    ApplicationUserContext,
    require_admin,
)
from config.settings import get_settings


VALID_ROLES = {"admin", "user"}

# Effectively disables sign-in without deleting the Auth identity.
ACCOUNT_BAN_DURATION = "876000h"


class UserAdministrationError(RuntimeError):
    """Raised when a user administration operation fails."""


@dataclass(frozen=True)
class ManagedUser:
    """Combined Supabase Auth and Knowledge Hub profile data."""

    user_id: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: str | None
    last_sign_in_at: str | None
    banned_until: str | None


def _admin_client():
    """Return the privileged Supabase client."""

    return get_supabase_admin_client()


def list_users(
    actor: ApplicationUserContext,
) -> list[ManagedUser]:
    """Return users visible to a validated administrator."""

    require_admin(actor)

    client = _admin_client()

    try:
        auth_response = client.auth.admin.list_users(
            page=1,
            per_page=1000,
        )

        profile_response = (
            client
            .table("profiles")
            .select(
                "user_id, display_name, role, is_active, created_at"
            )
            .execute()
        )

    except Exception as exc:
        raise UserAdministrationError(
            "Unable to retrieve users."
        ) from exc

    profiles = {
        str(row["user_id"]): row
        for row in (profile_response.data or [])
    }

    # supabase-py currently returns an iterable/list-like result here.
    auth_users = auth_response or []

    results: list[ManagedUser] = []

    for auth_user in auth_users:
        user_id = str(auth_user.id)
        profile = profiles.get(user_id)

        # Fail closed: an Auth identity without an application profile
        # is not silently treated as a valid Knowledge Hub user.
        if profile is None:
            continue

        results.append(
            ManagedUser(
                user_id=user_id,
                email=auth_user.email or "",
                display_name=profile.get("display_name"),
                role=profile.get("role", "user"),
                is_active=profile.get("is_active") is True,
                created_at=str(profile.get("created_at"))
                if profile.get("created_at")
                else None,
                last_sign_in_at=str(
                    getattr(auth_user, "last_sign_in_at", None)
                )
                if getattr(auth_user, "last_sign_in_at", None)
                else None,
                banned_until=str(
                    getattr(auth_user, "banned_until", None)
                )
                if getattr(auth_user, "banned_until", None)
                else None,
            )
        )

    return sorted(
        results,
        key=lambda user: user.email.lower(),
    )


def invite_user(
    actor: ApplicationUserContext,
    email: str,
) -> str:
    """Invite a new normal Knowledge Hub user.

    The Auth trigger creates the matching profile with role='user'.
    """

    require_admin(actor)

    email = email.strip().lower()

    if not email:
        raise UserAdministrationError("Email is required.")

    client = _admin_client()

    try:
        #response = client.auth.admin.invite_user_by_email(email)
        response = client.auth.admin.invite_user_by_email(
            email,
            {
                "redirect_to": get_settings().base_url,
            }
        )
        invited_user = response.user

        if invited_user is None:
            raise UserAdministrationError(
                "Supabase did not return an invited user."
            )

        user_id = str(invited_user.id)

        write_audit_log(
            actor_user_id=actor.user_id,
            action="user_invited",
            target_user_id=user_id,
            details={
                "initial_role": "user",
            },
        )

        return user_id

    except UserAdministrationError:
        raise
    except Exception as exc:
        raise UserAdministrationError(
            "Unable to invite user."
        ) from exc


def change_user_role(
    actor: ApplicationUserContext,
    target_user_id: str,
    new_role: str,
) -> None:
    """Change a Knowledge Hub user's role."""

    require_admin(actor)

    if new_role not in VALID_ROLES:
        raise UserAdministrationError("Invalid role.")

    if target_user_id == actor.user_id:
        raise UserAdministrationError(
            "Administrators cannot change their own role."
        )

    client = _admin_client()

    try:
        current = (
            client
            .table("profiles")
            .select("role, is_active")
            .eq("user_id", target_user_id)
            .limit(1)
            .execute()
        )

        rows = current.data or []

        if len(rows) != 1:
            raise UserAdministrationError(
                "Target user profile was not found."
            )

        previous_role = rows[0]["role"]

        if previous_role == new_role:
            return

        (
            client
            .table("profiles")
            .update({"role": new_role})
            .eq("user_id", target_user_id)
            .execute()
        )

        write_audit_log(
            actor_user_id=actor.user_id,
            action="user_role_changed",
            target_user_id=target_user_id,
            details={
                "previous_role": previous_role,
                "new_role": new_role,
            },
        )

    except UserAdministrationError:
        raise
    except Exception as exc:
        raise UserAdministrationError(
            "Unable to change user role."
        ) from exc


def set_user_active_status(
    actor: ApplicationUserContext,
    target_user_id: str,
    *,
    is_active: bool,
) -> None:
    """Activate or deactivate a Knowledge Hub user.

    Deactivation changes both:
    1. public.profiles.is_active
    2. Supabase Auth ban state

    This means the app rejects existing sessions immediately on the next
    authorization check, while Supabase Auth also prevents new sign-ins.
    """

    require_admin(actor)

    if target_user_id == actor.user_id and not is_active:
        raise UserAdministrationError(
            "Administrators cannot deactivate their own account."
        )

    client = _admin_client()

    try:
        current = (
            client
            .table("profiles")
            .select("is_active")
            .eq("user_id", target_user_id)
            .limit(1)
            .execute()
        )

        rows = current.data or []

        if len(rows) != 1:
            raise UserAdministrationError(
                "Target user profile was not found."
            )

        previous_status = rows[0]["is_active"] is True

        if previous_status == is_active:
            return

        if is_active:
            auth_attributes: dict[str, Any] = {
                "ban_duration": "none",
            }
        else:
            auth_attributes = {
                "ban_duration": ACCOUNT_BAN_DURATION,
            }

        # Update Auth state first.
        client.auth.admin.update_user_by_id(
            target_user_id,
            auth_attributes,
        )

        # Then update the application-level authorization state.
        (
            client
            .table("profiles")
            .update({"is_active": is_active})
            .eq("user_id", target_user_id)
            .execute()
        )

        write_audit_log(
            actor_user_id=actor.user_id,
            action=(
                "user_activated"
                if is_active
                else "user_deactivated"
            ),
            target_user_id=target_user_id,
            details={
                "previous_is_active": previous_status,
                "new_is_active": is_active,
            },
        )

    except UserAdministrationError:
        raise
    except Exception as exc:
        raise UserAdministrationError(
            "Unable to change user active status."
        ) from exc

###
def send_password_reset(
    actor: ApplicationUserContext,
    target_user_id: str,
    email: str,
) -> None:
    """Send a password reset email to a Knowledge Hub user."""

    require_admin(actor)

    email = email.strip().lower()

    if not email:
        raise UserAdministrationError(
            "Target user email is required."
        )

    client = get_supabase_client()

    try:
        client.auth.reset_password_for_email(
            email,
            {
                "redirect_to": get_settings().base_url,
            },
        )

        write_audit_log(
            actor_user_id=actor.user_id,
            action="user_password_reset_requested",
            target_user_id=target_user_id,
            details={
                "method": "recovery_email",
            },
        )

    except Exception as exc:
        raise UserAdministrationError(
            "Unable to send password reset email."
        ) from exc


def delete_user(
    actor: ApplicationUserContext,
    target_user_id: str,
) -> None:
    """Permanently delete a Knowledge Hub user.

    Deleting auth.users cascades to public.profiles according to the
    Phase 1 database schema.
    """

    require_admin(actor)

    if target_user_id == actor.user_id:
        raise UserAdministrationError(
            "Administrators cannot delete their own account."
        )

    client = _admin_client()

    try:
        current = (
            client
            .table("profiles")
            .select("role, is_active")
            .eq("user_id", target_user_id)
            .limit(1)
            .execute()
        )

        rows = current.data or []

        if len(rows) != 1:
            raise UserAdministrationError(
                "Target user profile was not found."
            )

        target_role = rows[0]["role"]
        target_is_active = rows[0]["is_active"] is True

        # Write before deletion. Because audit_logs.target_user_id uses
        # ON DELETE SET NULL, preserve the deleted UUID in details.
        write_audit_log(
            actor_user_id=actor.user_id,
            action="user_deleted",
            target_user_id=target_user_id,
            details={
                "deleted_user_id": target_user_id,
                "previous_role": target_role,
                "previous_is_active": target_is_active,
            },
        )

        client.auth.admin.delete_user(
            target_user_id,
        )

    except UserAdministrationError:
        raise
    except Exception as exc:
        raise UserAdministrationError(
            "Unable to delete user."
        ) from exc