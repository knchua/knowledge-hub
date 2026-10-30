"""Leased, fenced ingestion for initial, replacement, retry and stale recovery.

This replaces the Milestone 5 / Recovery Step 1 ingestion orchestration.
All database mutations in this module use ownership-checked RPCs from migration 006.
"""
from __future__ import annotations

import logging
import uuid

from database.client import get_supabase_admin_client
from services.audit_service import write_audit_log
from services.embedding_service import embed_texts
from services.ingestion_service import extract_chunks
from services.knowledge_service import BUCKET, KnowledgeError, _fresh_admin

logger = logging.getLogger(__name__)


def _validate_ids(document_id: str, version_id: str) -> None:
    try:
        uuid.UUID(document_id)
        uuid.UUID(version_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise KnowledgeError("Invalid document or version identifier.") from exc


def _rpc_one(db, name: str, parameters: dict) -> dict:
    rows = db.rpc(name, parameters).execute().data or []
    if isinstance(rows, dict):
        return rows
    if len(rows) != 1:
        raise KnowledgeError("Processing claim was not granted.")
    return rows[0]


def _process(actor, document_id: str, version_id: str, *, mode: str, allow_stale: bool = False) -> int:
    admin = _fresh_admin(actor)
    _validate_ids(document_id, version_id)
    db = get_supabase_admin_client()
    try:
        claim = _rpc_one(db, "kh_claim_ingestion", {
            "p_document_id": document_id, "p_version_id": version_id,
            "p_mode": mode, "p_allow_stale": allow_stale,
        })
    except Exception as exc:
        raise KnowledgeError("Processing not available; another attempt may own this version.") from exc

    token = claim["attempt_token"]
    try:
        source = db.storage.from_(BUCKET).download(claim["storage_path"])
        chunks = extract_chunks(claim["original_filename"], bytes(source))
        if not chunks:
            raise KnowledgeError("The file contains no extractable text.")
        # Limit processing so a single unattended operation cannot grow without bound.
        if len(chunks) > 2000:
            raise KnowledgeError("Document exceeds the supported 2,000-chunk limit.")
        # Embed a batch just before persisting it, rather than waiting for the
        # entire document's embeddings and risking lease expiry.
        for offset in range(0, len(chunks), 50):
            group = chunks[offset:offset + 50]
            vectors = embed_texts([x.content for x in group])
            if len(vectors) != len(group) or any(len(v) != 1536 for v in vectors):
                raise KnowledgeError("Embedding dimensions or count do not match chunks.")
            rows = [{
                "chunk_index": x.index, "content": x.content,
                "page_number": x.page_number, "source_metadata": x.source_metadata,
                "embedding": v,
            } for x, v in zip(group, vectors)]
            db.rpc("kh_append_ingestion_chunks", {
                "p_document_id": document_id, "p_version_id": version_id,
                "p_token": token, "p_rows": rows,
            }).execute()
        db.rpc("kh_finish_ingestion", {
            "p_document_id": document_id, "p_version_id": version_id,
            "p_token": token, "p_expected_count": len(chunks),
        }).execute()
    except Exception as exc:
        logger.error("Ingestion attempt failed for version %s (%s)", version_id, type(exc).__name__)
        try:
            changed = db.rpc("kh_fail_ingestion", {
                "p_document_id": document_id, "p_version_id": version_id,
                "p_token": token, "p_summary": "Ingestion attempt failed; review server logs.",
            }).execute().data
        except Exception as cleanup_exc:
            raise KnowledgeError("Ingestion failed; cleanup status is uncertain. Investigate before retrying.") from cleanup_exc
        if changed is False:
            raise KnowledgeError("Ingestion ownership was lost. This attempt was prevented from updating the active version.") from exc
        raise KnowledgeError("Ingestion failed. Check server logs and provider configuration.") from exc

    try:
        write_audit_log(
            actor_user_id=admin.user_id,
            action="knowledge_ingestion_recovered" if mode == "recover" else
                   "knowledge_document_reprocessed" if mode.startswith("retry") else
                   "knowledge_document_ingested",
            details={"document_id": document_id, "version_id": version_id,
                     "chunk_count": len(chunks), "operation": mode},
        )
    except Exception as exc:
        raise KnowledgeError("Document is indexed, but its audit event failed. Investigate audit logging.") from exc
    return len(chunks)


def ingest_pending_document(actor, document_id: str, version_id: str) -> int:
    return _process(actor, document_id, version_id, mode="initial")


def retry_failed_document(actor, document_id: str, version_id: str) -> int:
    return _process(actor, document_id, version_id, mode="retry_initial")


def process_replacement(actor, document_id: str, version_id: str) -> int:
    return _process(actor, document_id, version_id, mode="replacement")


def retry_failed_replacement(actor, document_id: str, version_id: str) -> int:
    return _process(actor, document_id, version_id, mode="retry_replacement")


def recover_stale_ingestion(actor, document_id: str, version_id: str) -> int:
    """Admin-only: reclaim an expired fenced lease, never a merely old unclaimed upload."""
    return _process(actor, document_id, version_id, mode="recover", allow_stale=True)
