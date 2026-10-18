"""Admin-only replacement, controlled delete, and idempotent cleanup.

This code extends the existing Milestone 4 services; no public storage access.
"""
from __future__ import annotations
import uuid
from database.client import get_supabase_admin_client
from services.knowledge_service import BUCKET, KnowledgeError, _fresh_admin, validate_file
from services.audit_service import write_audit_log


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise KnowledgeError("Invalid document identifier.") from exc


def stage_replacement(actor, document_id: str, filename: str, content: bytes) -> dict:
    admin = _fresh_admin(actor)
    document_id = _uuid(document_id)
    file = validate_file(filename, content)
    version_id = str(uuid.uuid4())
    path = f"documents/{document_id}/versions/{version_id}{file.extension}"
    db = get_supabase_admin_client()
    try:
        response = db.rpc("register_knowledge_replacement", {
            "p_document_id": document_id, "p_version_id": version_id,
            "p_name": file.display_name, "p_checksum": file.checksum,
            "p_mime": file.mime_type, "p_size": len(content),
            "p_storage_path": path, "p_actor": admin.user_id,
        }).execute()
        number = response.data
    except Exception as exc:
        raise KnowledgeError("Unable to stage replacement. Confirm the document is ready and no replacement is pending.") from exc
    try:
        db.storage.from_(BUCKET).upload(path, file.content, {"content-type": file.mime_type, "upsert": "false"})
    except Exception as exc:
        try:
            db.rpc("fail_knowledge_candidate", {"p_document_id": document_id,
                "p_version_id": version_id, "p_summary": "Replacement Storage upload failed"}).execute()
        except Exception:
            raise KnowledgeError("Storage upload and status recovery failed; administrator investigation required.") from exc
        raise KnowledgeError("Replacement upload failed. Active document remains available.") from exc
    try:
        write_audit_log(actor_user_id=admin.user_id, action="knowledge_replacement_staged",
                        details={"document_id": document_id, "version_id": version_id})
    except Exception as exc:
        raise KnowledgeError("Replacement was stored but its audit event failed; investigate before continuing.") from exc
    return {"document_id": document_id, "version_id": version_id,
            "version_number": number, "status": "processing"}


def _cleanup_one(db, document_id: str, version_id: str) -> None:
    """Keep records until both Storage and chunk cleanup succeed; safe to repeat."""
    paths = db.rpc("claim_knowledge_cleanup", {"p_document_id": document_id,
        "p_version_id": version_id}).execute().data or []
    if len(paths) != 1:
        raise KnowledgeError("Cleanup could not be claimed.")
    path = paths[0]["storage_path"]
    try:
        # Supabase removal of missing objects is idempotent; check SDK error paths.
        db.storage.from_(BUCKET).remove([path])
        db.table("knowledge_chunks").delete().eq("version_id", version_id).execute()
        db.table("knowledge_document_versions").update({
            "cleanup_status": "complete", "cleanup_error": None,
            "chunk_count": 0,
        }).eq("id", version_id).eq("cleanup_status", "pending").execute()
    except Exception as exc:
        try:
            db.table("knowledge_document_versions").update({
                "cleanup_status": "failed", "cleanup_error": "Cleanup incomplete; retry required",
            }).eq("id", version_id).execute()
        except Exception:
            pass
        raise KnowledgeError("Cleanup incomplete. Administrator can retry safely.") from exc


def cleanup_version(actor, document_id: str, version_id: str) -> None:
    admin = _fresh_admin(actor)
    document_id, version_id = _uuid(document_id), _uuid(version_id)
    db = get_supabase_admin_client()
    _cleanup_one(db, document_id, version_id)
    try:
        write_audit_log(actor_user_id=admin.user_id, action="knowledge_version_cleaned",
                        details={"document_id": document_id, "version_id": version_id})
    except Exception as exc:
        raise KnowledgeError("Cleanup completed, but audit logging failed; investigate.") from exc


def delete_document(actor, document_id: str, confirmation: str) -> None:
    admin = _fresh_admin(actor)
    document_id = _uuid(document_id)
    if confirmation != "DELETE":
        raise KnowledgeError("Type DELETE to confirm document deletion.")
    db = get_supabase_admin_client()
    try:
        db.rpc("mark_knowledge_document_deleting", {"p_document_id": document_id}).execute()
    except Exception as exc:
        raise KnowledgeError("Unable to begin deletion; no document content was removed.") from exc
    # Visibility was revoked in SQL before any remote Storage operation.
    try:
        write_audit_log(actor_user_id=admin.user_id, action="knowledge_document_delete_requested",
                        details={"document_id": document_id})
    except Exception as exc:
        raise KnowledgeError("Document is hidden from retrieval, but audit logging failed; investigate.") from exc
    finish_deletion(actor, document_id)


def finish_deletion(actor, document_id: str) -> None:
    """Continue deletion after an interrupted run; never makes document visible."""
    admin = _fresh_admin(actor)
    document_id = _uuid(document_id)
    db = get_supabase_admin_client()
    try:
        doc = db.table("knowledge_documents").select("status").eq("id", document_id).single().execute().data
        if not doc or doc["status"] != "deleting":
            raise KnowledgeError("Document is not awaiting deletion cleanup.")
        versions = db.table("knowledge_document_versions").select("id,cleanup_status").eq("document_id",document_id).execute().data or []
        for ver in versions:
            if ver["cleanup_status"] != "complete":
                _cleanup_one(db, document_id, ver["id"])
        db.rpc("finalize_knowledge_deletion", {"p_document_id":document_id}).execute()
    except KnowledgeError:
        raise
    except Exception as exc:
        raise KnowledgeError("Deletion cleanup is incomplete. Retry from the administrator cleanup panel.") from exc
    try:
        write_audit_log(actor_user_id=admin.user_id, action="knowledge_document_deleted",
                        details={"document_id":document_id})
    except Exception as exc:
        raise KnowledgeError("Document deleted; audit logging requires investigation.") from exc


def list_pending_cleanup(actor) -> list[dict]:
    _fresh_admin(actor)
    db = get_supabase_admin_client()
    docs = db.table("knowledge_documents").select("id,display_name,status").eq("status","deleting").execute().data or []
    return docs
