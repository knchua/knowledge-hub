"""Deterministic citations for retrieved Knowledge Hub chunks (Phase 3)."""
from __future__ import annotations
from dataclasses import dataclass
import re
from services.retrieval_service import RetrievedChunk

_LABEL = re.compile(r"\[S(\d+)\]")


@dataclass(frozen=True)
class Citation:
    label: str
    chunk_id: str
    document_id: str
    version_id: str
    document_name: str
    version_number: int
    chunk_index: int
    page_number: int | None
    excerpt: str
    similarity: float


def make_citations(chunks: list[RetrievedChunk], *, excerpt_chars: int = 250) -> dict[str, Citation]:
    if not 1 <= excerpt_chars <= 1000:
        raise ValueError("Invalid excerpt length.")
    result: dict[str, Citation] = {}
    for index, chunk in enumerate(chunks, 1):
        label = f"S{index}"
        result[label] = Citation(label, chunk.chunk_id, chunk.document_id,
                                 chunk.version_id, chunk.document_name,
                                 chunk.version_number, chunk.chunk_index,
                                 chunk.page_number, chunk.content[:excerpt_chars],
                                 chunk.similarity)
    return result


def cited_sources(answer: str, available: dict[str, Citation]) -> list[Citation]:
    """Reject unknown references; retain only sources actually referenced in answer."""
    labels = [f"S{n}" for n in _LABEL.findall(answer)]
    if not labels or any(label not in available for label in labels):
        raise ValueError("Answer contains missing or invalid citation references.")
    return [available[label] for label in dict.fromkeys(labels)]
