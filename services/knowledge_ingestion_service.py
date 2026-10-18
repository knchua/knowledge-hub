"""Administrator-initiated processing and safe failed-initial-version retry."""
from __future__ import annotations

import logging
import uuid

from database.client import get_supabase_admin_client
from database.knowledge_repository import (
    activate, claim_failed_version, claim_replacement_version, fail, fetch_pending_version, replace_chunks,
)
from services.audit_service import write_audit_log
from services.embedding_service import embed_texts
from services.ingestion_service import extract_chunks
from services.knowledge_service import BUCKET, KnowledgeError, _fresh_admin

logger = logging.getLogger(__name__)


def _ids(document_id: str, version_id: str) -> None:
    try:
        uuid.UUID(document_id)
        uuid.UUID(version_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise KnowledgeError("Invalid document or version identifier.") from exc


def _run_ingestion(client, admin, document_id: str, version_id: str,
                   version: dict, *, is_retry: bool) -> int:
    try:
        source = client.storage.from_(BUCKET).download(version["storage_path"])
        chunks = extract_chunks(version["original_filename"], bytes(source))
        embeddings = embed_texts([item.content for item in chunks])
        if len(embeddings) != len(chunks):
            raise KnowledgeError("Embedding count does not match extracted chunks.")
        replace_chunks(client, document_id, version_id, chunks, embeddings)
        activate(client, document_id, version_id, len(chunks))
    except Exception as exc:
        # Do not log raw provider payloads, request headers or document text.
        logger.error("Knowledge ingestion failed for version %s (%s)",
                     version_id, type(exc).__name__)
        summary = (str(exc) if isinstance(exc, KnowledgeError)
                   else "Ingestion failed. Check server logs and provider configuration.")
        try:
            fail(client, document_id, version_id, summary)
        except Exception as cleanup_exc:
            raise KnowledgeError(
                "Ingestion failed and cleanup could not be confirmed. "
                "Administrator investigation required."
            ) from cleanup_exc
        raise KnowledgeError(summary) from exc

    # An audit failure after activation must not cause the caller to retry a
    # successful ingestion. The user should investigate audit separately.
    try:
        write_audit_log(
            actor_user_id=admin.user_id,
            action="knowledge_document_reprocessed" if is_retry else "knowledge_document_ingested",
            details={"document_id": document_id, "version_id": version_id,
                     "chunk_count": len(chunks)},
        )
    except Exception as exc:
        raise KnowledgeError(
            "Document is indexed, but its audit event failed. Investigate audit logging."
        ) from exc
    return len(chunks)


def ingest_pending_document(actor, document_id: str, version_id: str) -> int:
    admin = _fresh_admin(actor)
    _ids(document_id, version_id)
    client = get_supabase_admin_client()
    try:
        _, version = fetch_pending_version(client, document_id, version_id)
    except Exception as exc:
        raise KnowledgeError("Only an unprocessed initial document version can be ingested.") from exc
    return _run_ingestion(client, admin, document_id, version_id, version, is_retry=False)


def retry_failed_document(actor, document_id: str, version_id: str) -> int:
    """Retry only a failed, non-active initial version; never reset DB manually."""
    admin = _fresh_admin(actor)
    _ids(document_id, version_id)
    client = get_supabase_admin_client()
    try:
        version = claim_failed_version(client, document_id, version_id)
    except Exception as exc:
        raise KnowledgeError(
            "Retry unavailable: document was deleted, activated, or already claimed."
        ) from exc
    return _run_ingestion(client, admin, document_id, version_id, version, is_retry=True)


def process_replacement(actor, document_id: str, version_id: str) -> int:
    """Process staged version 2+; prior active version remains readable until swap."""
    admin = _fresh_admin(actor)
    _ids(document_id, version_id)
    client = get_supabase_admin_client()
    try:
        version = claim_replacement_version(client, document_id, version_id)
    except Exception as exc:
        raise KnowledgeError("Replacement is unavailable or already being processed.") from exc
    # Existing run logic will preserve a ready document when candidate fails.
    return _run_ingestion(client, admin, document_id, version_id, version, is_retry=False)
