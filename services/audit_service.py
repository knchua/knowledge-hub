"""Administrative audit logging for Knowledge Hub."""

from typing import Any

from database.client import get_supabase_admin_client


class AuditLoggingError(RuntimeError):
    """Raised when an administrative audit record cannot be written."""


def write_audit_log(
    *,
    actor_user_id: str,
    action: str,
    target_user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an administrative audit record.

    Never include passwords, access tokens, refresh tokens, API keys,
    or other secrets in ``details``.
    """

    if not actor_user_id:
        raise AuditLoggingError("Audit actor is required.")

    if not action.strip():
        raise AuditLoggingError("Audit action is required.")

    payload = {
        "actor_user_id": actor_user_id,
        "action": action.strip(),
        "target_user_id": target_user_id,
        "details": details or {},
    }

    try:
        (
            get_supabase_admin_client()
            .table("audit_logs")
            .insert(payload)
            .execute()
        )
    except Exception as exc:
        raise AuditLoggingError(
            "Unable to record administrative audit event."
        ) from exc