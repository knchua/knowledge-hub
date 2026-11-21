"""P3: guarded self-service password change, never using service-role access.

Only password values passed as ephemeral function arguments.  No local persistence,
secret-bearing audit events, or logging. Supabase performs authoritative checks.
"""

from database.client import get_supabase_client
from services.authorization_service import ApplicationUserContext, resolve_application_user


class PasswordChangeError(RuntimeError):
    """Safe failure; original provider exceptions are deliberately not shown."""


class ReauthenticationRequired(PasswordChangeError):
    """Supabase requires an email nonce for this existing session."""


class InvalidReauthenticationCode(PasswordChangeError):
    """Supabase rejected the submitted email nonce."""


class PasswordValidationError(PasswordChangeError):
    """Client-side validation rejected the request before provider calls."""


def _validated_actor(actor: ApplicationUserContext) -> ApplicationUserContext:
    if (not actor.user_id or not actor.access_token or not actor.refresh_token
            or not actor.is_active or actor.role not in {"admin", "user"}):
        raise PasswordChangeError("Please sign in again before changing your password.")
    try:
        latest = resolve_application_user(actor.access_token, actor.refresh_token)
    except Exception as exc:
        raise PasswordChangeError("Unable to verify account access. Please sign in again.") from exc
    if (latest.user_id != actor.user_id or not latest.is_active
            or latest.role not in {"admin", "user"}
            or latest.email.casefold() != actor.email.casefold()):
        raise PasswordChangeError("Account access has changed. Please sign in again.")
    return latest


def _authenticated_client(actor: ApplicationUserContext):
    client = get_supabase_client()
    try:
        response = client.auth.set_session(actor.access_token, actor.refresh_token)
        session = getattr(response, "session", None)
        if session is None or not session.access_token:
            raise PasswordChangeError("Please sign in again before changing your password.")
        user_response = client.auth.get_user(session.access_token)
        user = getattr(user_response, "user", None)
        if user is None or str(user.id) != actor.user_id:
            raise PasswordChangeError("Authenticated identity has changed. Please sign in again.")
    except PasswordChangeError:
        raise
    except Exception as exc:
        raise PasswordChangeError("Unable to verify authentication. Please sign in again.") from exc
    return client


def validate_password_fields(current_password: str, new_password: str,
                             confirmation: str) -> None:
    if not all(isinstance(p, str) for p in (current_password, new_password, confirmation)):
        raise PasswordValidationError("Enter all password fields.")
    if not current_password:
        raise PasswordValidationError("Enter your current password.")
    if new_password != confirmation:
        raise PasswordValidationError("New passwords do not match.")
    if len(new_password) < 8:
        raise PasswordValidationError("New password must contain at least 8 characters.")
    if len(new_password) > 1024:
        raise PasswordValidationError("New password is too long.")
    if new_password == current_password:
        raise PasswordValidationError("Choose a different password.")


def request_reauthentication_code(actor: ApplicationUserContext) -> None:
    """Request email nonce on the user's existing session; never cache it."""
    latest = _validated_actor(actor)
    client = _authenticated_client(latest)
    try:
        client.auth.reauthenticate()
    except Exception as exc:
        raise PasswordChangeError(
            "Unable to request a security code right now. Please try again later."
        ) from exc


def change_own_password(actor: ApplicationUserContext,
                        current_password: str, new_password: str,
                        confirmation: str, nonce: str = "") -> None:
    """Change password on the original authenticated session.

    Do not sign in again: a newly created session could undermine the
    server-enforced reauthentication age check. Supabase validates the
    current password and, when necessary, the email nonce.
    """
    validate_password_fields(current_password, new_password, confirmation)
    if not isinstance(nonce, str) or len(nonce) > 32 or (nonce and not nonce.isascii()):
        raise PasswordValidationError("Invalid security code.")
    code = nonce.strip()
    if code and (not code.isascii() or not code.isdigit() or len(code) != 8):
        raise PasswordValidationError("Security code must contain eight digits.")

    latest = _validated_actor(actor)
    # Repeat the app authorization check as close as possible to the update.
    latest = _validated_actor(latest)
    client = _authenticated_client(latest)
    update = {"password": new_password, "current_password": current_password}
    if code:
        update["nonce"] = code
    try:
        result = client.auth.update_user(update)
        updated_user = getattr(result, "user", None)
        if updated_user is None or str(updated_user.id) != latest.user_id:
            raise PasswordChangeError("Password change could not be confirmed.")
    except PasswordChangeError:
        raise
    except Exception as exc:
        # Only inspect structured provider codes, never display provider messages.
        # Other failures remain a generic, non-secret-bearing error.
        code_value = getattr(exc, "code", None)
        if code_value == "reauthentication_needed":
            raise ReauthenticationRequired(
                "Email verification is required before changing your password."
            ) from None
        if code_value == "reauthentication_not_valid":
            raise InvalidReauthenticationCode(
                "The security code was rejected or expired. Request another code."
            ) from None
        raise PasswordChangeError(
            "Password change was not completed. Check your current password "
            "and the password requirements."
        ) from None
