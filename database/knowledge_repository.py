"""Privileged database actions for indexing an existing staged document version."""
from __future__ import annotations
from datetime import datetime, timezone


def fetch_pending_version(client, document_id: str, version_id: str) -> tuple[dict, dict]:
    d = (client.table("knowledge_documents").select("id,status,deleted_at,active_version_id")
         .eq("id", document_id).single().execute()).data
    v = (client.table("knowledge_document_versions")
         .select("id,document_id,original_filename,storage_path,status,chunk_count")
         .eq("id", version_id).eq("document_id", document_id).single().execute()).data
    if not d or d.get("deleted_at") is not None or d.get("status") != "processing" or d.get("active_version_id"):
        raise ValueError("Document is not awaiting its initial ingestion.")
    if not v or v.get("status") != "processing" or v.get("chunk_count") != 0:
        raise ValueError("Version is not awaiting its initial ingestion.")
    return d, v


def replace_chunks(client, document_id: str, version_id: str, chunks: list, vectors: list[list[float]]) -> None:
    """Store batches; failed writes are cleaned before a version is ever made ready."""
    client.table("knowledge_chunks").delete().eq("version_id", version_id).execute()
    for start in range(0, len(chunks), 50):
        rows = []
        for chunk, vector in zip(chunks[start:start+50], vectors[start:start+50]):
            rows.append({"document_id": document_id, "version_id": version_id,
                         "chunk_index": chunk.index, "content": chunk.content,
                         "page_number": chunk.page_number,
                         "source_metadata": chunk.source_metadata,
                         "embedding": vector, "embedding_model": "text-embedding-3-small"})
        client.table("knowledge_chunks").insert(rows).execute()


def activate(client, document_id: str, version_id: str, count: int) -> None:
    client.table("knowledge_document_versions").update({
        "status": "ready", "chunk_count": count,
        "error_summary": None, "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", version_id).execute()
    client.rpc("activate_knowledge_version", {
        "p_document_id": document_id, "p_version_id": version_id}).execute()


def fail(client, document_id: str, version_id: str, safe_summary: str) -> None:
    """Best-effort cleanup; never set a failed candidate active."""
    client.table("knowledge_chunks").delete().eq("version_id", version_id).execute()
    # Activation failure can occur after status was set to ready, but before
    # the active-version pointer changed. The candidate must not remain ready.
    client.table("knowledge_document_versions").update({
        "status": "failed", "chunk_count": 0, "error_summary": safe_summary[:300]
    }).eq("id", version_id).in_("status", ["processing", "ready"]).execute()
    client.table("knowledge_documents").update({"status": "failed"}).eq("id", document_id).eq("status", "processing").execute()


def claim_failed_version(client, document_id: str, version_id: str) -> dict:
    """Atomic failed->processing claim; a second concurrent claim must fail."""
    response = client.rpc("claim_failed_knowledge_version", {
        "p_document_id": document_id, "p_version_id": version_id,
    }).execute()
    rows = response.data or []
    if len(rows) != 1:
        raise ValueError("Failed version could not be claimed.")
    return rows[0]


def claim_replacement_version(client, document_id: str, version_id: str) -> dict:
    result = client.rpc("claim_knowledge_replacement", {
        "p_document_id": document_id, "p_version_id": version_id,
    }).execute()
    rows = result.data or []
    if len(rows) != 1:
        raise ValueError("Replacement cannot be claimed.")
    return rows[0]
