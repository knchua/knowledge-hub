"""Read-only stale ingestion detection. No status resets or processing claims.

Recovery must not be enabled until ingestion writes and activation are fenced by
an attempt-specific ownership token. This module deliberately detects only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from database.client import get_supabase_admin_client
from services.knowledge_service import _fresh_admin

DEFAULT_STALE_MINUTES = 60


def list_stale_ingestion_candidates(actor, *, older_than_minutes: int = DEFAULT_STALE_MINUTES) -> list[dict]:
    """Return unready processing versions whose last known claim is old.

    This is an *investigation list*, not proof that a process has stopped.
    A candidate cannot safely be reset based on age alone.
    """
    _fresh_admin(actor)  # re-check server-side identity, active status, role
    if not isinstance(older_than_minutes, int) or isinstance(older_than_minutes, bool) or not 15 <= older_than_minutes <= 1440:
        raise ValueError("The stale threshold must be 15–1440 minutes.")

    client = get_supabase_admin_client()
    # Avoid querying content, embeddings or storage objects.
    res = (client.table("knowledge_document_versions")
           .select("id,document_id,version_number,status,created_at,processing_claimed_at")
           .eq("status", "processing").execute())
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=older_than_minutes)
    candidates: list[dict] = []
    for version in res.data or []:
        # If never claimed, use creation time (e.g., uploaded but not processed).
        ts = version.get("processing_claimed_at") or version.get("created_at")
        if not ts:
            continue
        try:
            stamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        if stamp > cutoff:
            continue
        # Check parent status; don't surface deleted or deleting documents.
        document = (client.table("knowledge_documents")
                    .select("id,display_name,status,deleted_at,active_version_id")
                    .eq("id", version["document_id"]).single().execute()).data
        if not document or document.get("deleted_at") is not None or document.get("status") not in ("ready", "processing"):
            continue
        if document.get("active_version_id") == version["id"]:
            continue
        candidates.append({
            "document_id": version["document_id"],
            "version_id": version["id"],
            "display_name": document["display_name"],
            "version_number": version["version_number"],
            "last_known_claim_at": stamp.isoformat(),
            "was_claimed": version.get("processing_claimed_at") is not None,
            "has_active_version": bool(document.get("active_version_id")),
        })
    return candidates
