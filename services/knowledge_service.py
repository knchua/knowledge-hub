"""Phase 2 Milestone 3: verified-admin document upload and listing.

Files are staged for the Milestone 4 ingestion pipeline. They are NOT indexed
or searchable until ingestion sets the version ready and activates it.
"""
from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass

from database.client import get_supabase_admin_client
from services.authorization_service import (
    ApplicationAccessError, ApplicationUserContext, require_admin,
    resolve_application_user,
)
from services.audit_service import write_audit_log

BUCKET = "knowledge-documents"
MAX_FILE_BYTES = 20 * 1024 * 1024
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


class KnowledgeError(RuntimeError):
    """Expected document-management error safe to show in the UI."""


@dataclass(frozen=True)
class ValidatedFile:
    display_name: str
    extension: str
    mime_type: str
    content: bytes
    checksum: str


def validate_file(filename: str, content: bytes) -> ValidatedFile:
    """Validate bytes (not browser MIME type); Phase 4 handles text extraction."""
    if not isinstance(filename, str) or not filename.strip():
        raise KnowledgeError("Choose a file with a valid name.")
    name = filename.replace("\\", "/").split("/")[-1].strip()
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise KnowledgeError("Filename must be 1–255 characters without control characters.")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in MIME_BY_EXTENSION:
        raise KnowledgeError("Only PDF, DOCX and TXT files are supported.")
    if not isinstance(content, bytes) or not content:
        raise KnowledgeError("The uploaded file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise KnowledgeError("File exceeds the 20 MB upload limit.")
    if ext == ".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise KnowledgeError("File is not a valid supported PDF.")
    elif ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = set(archive.namelist())
                if "[Content_Types].xml" not in entries or "word/document.xml" not in entries:
                    raise ValueError("Missing Word document structure")
                if archive.testzip() is not None:
                    raise ValueError("Corrupted Word document")
        except (zipfile.BadZipFile, ValueError, RuntimeError, OSError) as exc:
            raise KnowledgeError("File is not a valid DOCX document.") from exc
    else:
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeError("TXT files must use UTF-8 encoding.") from exc
        if not decoded.strip() or "\x00" in decoded:
            raise KnowledgeError("TXT file must contain readable non-empty text.")
    return ValidatedFile(name, ext, MIME_BY_EXTENSION[ext], content, hashlib.sha256(content).hexdigest())


def _fresh_admin(actor: ApplicationUserContext) -> ApplicationUserContext:
    """Recheck actual Supabase session/profile before using service-role client."""
    if not isinstance(actor, ApplicationUserContext):
        raise KnowledgeError("Administrator sign-in is required.")
    try:
        refreshed = resolve_application_user(actor.access_token, actor.refresh_token)
        require_admin(refreshed)
        if refreshed.user_id != actor.user_id:
            raise ApplicationAccessError("Authenticated identity changed.")
        return refreshed
    except Exception as exc:
        raise KnowledgeError("Administrator session is invalid or no longer authorised.") from exc


def list_documents(actor: ApplicationUserContext, limit: int = 100) -> list[dict]:
    """Admin-only list; includes staging and failed versions, excludes deleted."""
    _fresh_admin(actor)
    if not 1 <= limit <= 500:
        raise KnowledgeError("Invalid list limit.")
    try:
        response = (get_supabase_admin_client().table("knowledge_documents")
                    .select("id,display_name,mime_type,size_bytes,status,created_at,updated_at,active_version_id")
                    .is_("deleted_at", "null")
                    .order("created_at", desc=True).limit(limit).execute())
        return response.data or []
    except Exception as exc:
        raise KnowledgeError("Unable to load knowledge documents.") from exc


def list_versions(actor: ApplicationUserContext, document_id: str) -> list[dict]:
    _fresh_admin(actor)
    try:
        uuid.UUID(document_id)
    except (ValueError, TypeError) as exc:
        raise KnowledgeError("Invalid document identifier.") from exc
    try:
        result = (get_supabase_admin_client().table("knowledge_document_versions")
                  .select("id,version_number,original_filename,size_bytes,status,chunk_count,error_summary,created_at,cleanup_status")
                  .eq("document_id", document_id).order("version_number", desc=True).execute())
        return result.data or []
    except Exception as exc:
        raise KnowledgeError("Unable to retrieve document versions.") from exc


def _check_duplicate(client, checksum: str) -> None:
    result = (client.table("knowledge_documents").select("id")
              .eq("checksum_sha256", checksum).is_("deleted_at", "null")
              .limit(1).execute())
    if result.data:
        raise KnowledgeError("An active document with identical content already exists.")


def upload_document(actor: ApplicationUserContext, filename: str, content: bytes) -> dict:
    """Register original file for later ingestion; never activate a pending version.

    Database uniqueness additionally protects against concurrent duplicate attempts.
    A failed Storage upload marks the candidate failed and preserves a safe error.
    """
    admin = _fresh_admin(actor)
    file = validate_file(filename, content)
    client = get_supabase_admin_client()
    try:
        _check_duplicate(client, file.checksum)
    except KnowledgeError:
        raise
    except Exception as exc:
        raise KnowledgeError("Unable to check existing documents.") from exc

    document_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    path = f"documents/{document_id}/versions/{version_id}{file.extension}"
    doc = {"id": document_id, "display_name": file.display_name,
           "mime_type": file.mime_type, "size_bytes": len(content),
           "checksum_sha256": file.checksum, "status": "processing",
           "created_by": admin.user_id}
    ver = {"id": version_id, "document_id": document_id,
           "version_number": 1, "storage_path": path,
           "original_filename": file.display_name, "checksum_sha256": file.checksum,
           "mime_type": file.mime_type, "size_bytes": len(content),
           "status": "processing", "created_by": admin.user_id}
    try:
        client.table("knowledge_documents").insert(doc).execute()
    except Exception as exc:
        # Do not report a concurrent unique checksum violation as success.
        raise KnowledgeError("Unable to register document; an identical file may already exist.") from exc
    try:
        client.table("knowledge_document_versions").insert(ver).execute()
    except Exception as exc:
        # No version exists: soft-deactivate the metadata record, so duplicate retries work.
        try:
            client.table("knowledge_documents").update({"status": "failed"}).eq("id", document_id).execute()
            client.rpc("mark_knowledge_document_deleting", {"p_document_id": document_id}).execute()
        except Exception:
            pass  # Requires administrator investigation if database is unavailable.
        raise KnowledgeError("Unable to register document version.") from exc

    try:
        client.storage.from_(BUCKET).upload(path, file.content, {
            "content-type": file.mime_type,
            "upsert": "false",
        })
    except Exception as exc:
        try:
            client.table("knowledge_document_versions").update({
                "status": "failed", "error_summary": "Storage upload failed",
            }).eq("id", version_id).execute()
            client.table("knowledge_documents").update({
                "status": "failed",
            }).eq("id", document_id).execute()
        except Exception:
            pass
        raise KnowledgeError("Unable to store original file. Document marked for investigation.") from exc

    try:
        write_audit_log(actor_user_id=admin.user_id, action="knowledge_document_uploaded",
                        details={"document_id": document_id, "version_id": version_id,
                                 "size_bytes": len(content), "mime_type": file.mime_type})
    except Exception as exc:
        # Original is stored and traceability failed: do not claim a fully audited success.
        raise KnowledgeError("File was stored, but its audit event failed. Contact an administrator before retrying.") from exc
    return {"id": document_id, "version_id": version_id, "status": "processing",
            "display_name": file.display_name}
