"""Phase 3 retrieval-only service using Phase 1 Auth and Phase 2 pgvector RPC.

No privileged Supabase client, answer generation, or raw-document access.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from database.client import get_supabase_client
from services.authorization_service import resolve_application_user
from services.embedding_service import DIMENSIONS, embed_texts

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MAX_QUESTION_LENGTH = 2000


class RetrievalError(RuntimeError):
    """Safe error exposed to retrieval callers."""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    version_id: str
    document_name: str
    version_number: int
    chunk_index: int
    content: str
    page_number: int | None
    source_metadata: dict
    similarity: float


def _validate_question(question: str) -> str:
    if not isinstance(question, str):
        raise ValueError("Question must be text.")
    cleaned = question.strip()
    if not cleaned or len(cleaned) > MAX_QUESTION_LENGTH:
        raise ValueError(f"Question must be 1–{MAX_QUESTION_LENGTH} characters.")
    return cleaned


def _validate_options(top_k: int, min_similarity: float) -> None:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}.")
    if isinstance(min_similarity, bool) or not isinstance(min_similarity, (float, int)):
        raise ValueError("min_similarity must be a finite number between -1 and 1.")
    if not math.isfinite(min_similarity) or not -1 <= min_similarity <= 1:
        raise ValueError("min_similarity must be a finite number between -1 and 1.")


def _parse_row(row: dict) -> RetrievedChunk:
    if not isinstance(row, dict):
        raise ValueError("Invalid retrieval record.")
    required = ("chunk_id", "document_id", "version_id", "document_name",
                "version_number", "chunk_index", "content", "page_number",
                "source_metadata", "similarity")
    if any(field not in row for field in required):
        raise ValueError("Incomplete retrieval metadata.")
    if any(not isinstance(row[field], str) or not row[field].strip()
           for field in ("chunk_id", "document_id", "version_id", "document_name", "content")):
        raise ValueError("Invalid retrieval identifiers or content.")
    if not isinstance(row["version_number"], int) or isinstance(row["version_number"], bool):
        raise ValueError("Invalid version number.")
    if not isinstance(row["chunk_index"], int) or isinstance(row["chunk_index"], bool) or row["chunk_index"] < 0:
        raise ValueError("Invalid chunk index.")
    page = row["page_number"]
    if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
        raise ValueError("Invalid page number.")
    if not isinstance(row["source_metadata"], dict):
        raise ValueError("Invalid source metadata.")
    similarity = row["similarity"]
    if isinstance(similarity, bool) or not isinstance(similarity, (float, int)) or not math.isfinite(similarity) or not -1 <= similarity <= 1:
        raise ValueError("Invalid similarity score.")
    return RetrievedChunk(**{field: row[field] for field in required})


def retrieve_chunks(
    question: str,
    access_token: str,
    refresh_token: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = 0.0,
) -> list[RetrievedChunk]:
    """Retrieve ranked active-ready knowledge chunks for a verified active account.

    min_similarity=0.0 is a *starting retrieval floor*, not a calibrated
    relevance criterion; tune against a Phase 3 evaluation set in Step 2.
    """
    cleaned = _validate_question(question)
    _validate_options(top_k, min_similarity)

    # Authoritative server-side check; uses refreshed tokens from validated context.
    # Do not catch or obscure explicit application-access failures.
    user = resolve_application_user(access_token, refresh_token)

    try:
        vectors = embed_texts([cleaned])
        if len(vectors) != 1 or len(vectors[0]) != DIMENSIONS or not all(
            isinstance(v, (int, float)) and math.isfinite(v) for v in vectors[0]
        ):
            raise RetrievalError("Unable to prepare question embedding.")
        client = get_supabase_client()
        client.auth.set_session(user.access_token, user.refresh_token)
        response = client.rpc("match_knowledge_chunks", {
            "query_embedding": vectors[0],
            "match_count": top_k,
            "min_similarity": float(min_similarity),
        }).execute()
        rows = response.data or []
        if not isinstance(rows, list) or len(rows) > top_k:
            raise RetrievalError("Unexpected retrieval response.")
        chunks = [_parse_row(row) for row in rows]
        if any(chunk.similarity < min_similarity for chunk in chunks):
            raise RetrievalError("Retrieval returned results below the requested threshold.")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise RetrievalError("Retrieval returned duplicate chunk identifiers.")
        return chunks
    except RetrievalError:
        raise
    except Exception as exc:
        raise RetrievalError("Unable to retrieve knowledge documents. Please try again.") from exc
