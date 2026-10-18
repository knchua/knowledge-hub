from dataclasses import dataclass
from typing import Any

from database.client import get_supabase_admin_client
from services.authorization_service import (
    ApplicationUserContext,
    require_admin,
)


class AuditLoggingError(RuntimeError):
    """Raised when an audit operation fails."""


@dataclass(frozen=True)
class AuditLogEntry:
    """Administrative audit record."""

    id: str
    actor_user_id: str | None
    action: str
    target_user_id: str | None
    created_at: str
    details: dict[str, Any]


def write_audit_log(
    *,
    actor_user_id: str,
    action: str,
    target_user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an administrative audit record."""

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


def list_audit_logs(
    actor: ApplicationUserContext,
    *,
    limit: int = 100,
) -> list[AuditLogEntry]:
    """Return recent administrative audit records."""

    require_admin(actor)

    if limit < 1:
        raise AuditLoggingError(
            "Audit log limit must be greater than zero."
        )

    limit = min(limit, 500)

    try:
        response = (
            get_supabase_admin_client()
            .table("audit_logs")
            .select(
                "id, actor_user_id, action, "
                "target_user_id, created_at, details"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        raise AuditLoggingError(
            "Unable to retrieve audit records."
        ) from exc

    return [
        AuditLogEntry(
            id=str(row["id"]),
            actor_user_id=(
                str(row["actor_user_id"])
                if row.get("actor_user_id")
                else None
            ),
            action=str(row["action"]),
            target_user_id=(
                str(row["target_user_id"])
                if row.get("target_user_id")
                else None
            ),
            created_at=str(row["created_at"]),
            details=row.get("details") or {},
        )
        for row in (response.data or [])
    ]