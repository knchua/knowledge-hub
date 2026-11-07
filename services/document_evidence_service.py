"""Phase 4 Milestone 4B: bounded, deterministic, in-memory evidence selection.

Pure selection only. The calling service MUST first obtain its TemporaryDocument
through document_analysis_service.current_document(state, actor), which performs
fresh active-user and document-ownership checks. No LLM, network, vector-store,
logging of document text, or persistent storage occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.temporary_document_service import TemporaryDocument, TemporarySegment


class EvidenceSelectionError(ValueError):
    """Safe error raised when a retrieval input/configuration is invalid."""


@dataclass(frozen=True)
class EvidenceItem:
    index: int                 # Zero-based original document segment index.
    label: str                 # P1 = index 0; never re-number by retrieval order.
    text: str                  # Verbatim, possibly truncated, selected evidence.
    page_number: int | None    # PDF page, otherwise None.


@dataclass(frozen=True)
class EvidenceSelection:
    document_id: str
    items: tuple[EvidenceItem, ...]
    strategy: str              # "full_context", "lexical", or "no_match"
    total_segments: int
    total_evidence_chars: int

    @property
    def allowed_labels(self) -> frozenset[str]:
        return frozenset(item.label for item in self.items)


_STOP = frozenset("a an the in on at to for by of is are was were be been being who whom whose what when where why how did do does and or with from this that these those about please could would should tell me give show explain project document report summary its it my our their we i you they he she which there here regarding details status".split())
_TOKEN = re.compile(r"(?i)\b(?:[ADR]-\d{2,4}|ID-\d{2,5}|[\w]+)\b", re.UNICODE)


def _setting(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise EvidenceSelectionError(f"Invalid configuration: {name}.") from exc
    if not low <= value <= high:
        raise EvidenceSelectionError(f"Invalid configuration: {name}.")
    return value


def _tokens(value: str) -> set[str]:
    return {part.casefold() for part in _TOKEN.findall(value) if part.casefold() not in _STOP and len(part) >= 2}


def _validate_document(document: "TemporaryDocument") -> None:
    if not isinstance(getattr(document, "document_id", None), str) or not document.document_id:
        raise EvidenceSelectionError("A valid temporary document is required.")
    segments = getattr(document, "segments", None)
    if not isinstance(segments, (list, tuple)) or not segments:
        raise EvidenceSelectionError("No readable document segments are available.")
    if not isinstance(getattr(document, "owner_user_id", None), str) or not document.owner_user_id:
        raise EvidenceSelectionError("A valid temporary document owner is required.")
    for n, seg in enumerate(segments):
        if getattr(seg, "index", None) != n or not isinstance(getattr(seg, "text", None), str):
            raise EvidenceSelectionError("The temporary document has invalid segment identifiers.")


def select_document_evidence(document: "TemporaryDocument", question: str) -> EvidenceSelection:
    """Select evidence solely from the given document, with stable source labels.

    Short documents fitting BOTH budgets return all segments. Longer documents
    use a conservative lexical scorer. A zero-overlap long-document question
    returns no evidence rather than inventing a match. Retrieval relevance is
    heuristic: the answering layer must still establish support or abstain.
    """
    _validate_document(document)
    max_question = _setting("KH_QA_MAX_QUESTION_CHARS", 1000, 50, 4000)
    max_evidence = _setting("KH_QA_MAX_EVIDENCE_CHARS", 12000, 500, 50000)
    max_segments = _setting("KH_QA_MAX_EVIDENCE_SEGMENTS", 10, 1, 100)
    if not isinstance(question, str) or not question.strip():
        raise EvidenceSelectionError("Enter a question about the uploaded document.")
    question = question.strip()
    if len(question) > max_question:
        raise EvidenceSelectionError("Question exceeds the maximum length.")

    segments = document.segments
    # Reserve room in the future generation prompt for label/page metadata.
    metadata_budget = 48 * len(segments)
    all_chars = sum(len(seg.text) for seg in segments)
    if len(segments) <= max_segments and all_chars + metadata_budget <= max_evidence:
        indexes = list(range(len(segments)))
        strategy = "full_context"
    else:
        q = _tokens(question)
        if not q:
            return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)
        docs = [_tokens(seg.text) for seg in segments]
        df = {term: sum(term in tokens for tokens in docs) for term in q}
        scored = []
        normalized_question = " ".join(question.casefold().split())
        for idx, seg in enumerate(segments):
            overlap = q & docs[idx]
            if not overlap:
                continue
            score = sum(1.0 + math.log((len(segments) + 1) / (df[t] + 1)) for t in overlap)
            # Stable action/risk/defect IDs are particularly discriminative.
            score += 6.0 * len({t for t in overlap if re.fullmatch(r"(?:[adr]|id)-\d{2,5}", t)})
            if len(normalized_question) >= 8 and normalized_question in seg.text.casefold():
                score += 8.0
            scored.append((-score, idx))
        if not scored:
            return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)
        # Retrieval by relevance; final presentation by original source order.
        ranked = [idx for _, idx in sorted(scored)]
        indexes = ranked[:max_segments]
        strategy = "lexical"

    remaining = max_evidence
    evidence = []
    for idx in indexes:
        seg = segments[idx]
        overhead = max(48, len(f"[P{idx + 1}] Page: {seg.page_number if seg.page_number is not None else 'N/A'}\n") + 12)
        if remaining <= overhead + 10:
            break
        available = min(len(seg.text), remaining - overhead)
        excerpt = seg.text[:available]
        # Do not cut halfway through a word unless the source is a single token.
        if available < len(seg.text):
            boundary = max(excerpt.rfind("\n"), excerpt.rfind(". "), excerpt.rfind(" "))
            if boundary >= max(20, available // 2):
                excerpt = excerpt[:boundary + (1 if excerpt[boundary:boundary + 2] == ". " else 0)]
        if not excerpt.strip():
            continue
        evidence.append(EvidenceItem(idx, f"P{idx + 1}", excerpt, seg.page_number))
        remaining -= overhead + len(excerpt)
    if not evidence:
        return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)
    evidence.sort(key=lambda item: item.index)
    return EvidenceSelection(document.document_id, tuple(evidence), strategy, len(segments), sum(len(item.text) for item in evidence))
