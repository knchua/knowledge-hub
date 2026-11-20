"""Phase 4 Milestone 4B: bounded, deterministic, in-memory evidence selection.

Pure selection only. The calling service MUST first obtain its TemporaryDocument
through document_analysis_service.current_document(state, actor), which performs
fresh active-user and document-ownership checks. No LLM, network, vector-store,
logging of document text, or persistent storage occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from services.document_source_format_service import (
    SourceFormatError, format_source_block, format_source_blocks,
)
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
    # Phase 5 M3.2: backward-compatible optional source provenance.
    origin: str = "native_text"
    image_id: str | None = None
    docx_image_ordinal: int | None = None
    docx_body_block: int | None = None
    extraction_warnings: tuple[str, ...] = ()


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


def _visual_question(question: str) -> bool:
    """Only a small, explicit set of visual-structure cues affects tie breaks."""
    return bool(re.search(
        r"\b(chart|graph|diagram|workflow|flowchart|arrow|sequence|step|trend|bar|axis|visual)\b",
        question, re.I,
    ))


def _near_duplicate(a, b) -> bool:
    """Suppress only nearly identical OCR/vision pairs at the same location.

    This is a ranking diversity safeguard, not an evidence-merging rule.
    It never modifies document segments or original citation numbering.
    """
    if {getattr(a, "origin", "native_text"), getattr(b, "origin", "native_text")} != {"ocr_text", "vision_description"}:
        return False
    if a.page_number is not None or b.page_number is not None:
        if a.page_number is None or a.page_number != b.page_number:
            return False
    else:
        ai = getattr(a, "docx_image_ordinal", None)
        bi = getattr(b, "docx_image_ordinal", None)
        if ai is None or ai != bi:
            return False
    a_tokens = re.findall(r"\w+", a.text.casefold())
    b_tokens = re.findall(r"\w+", b.text.casefold())
    if not a_tokens or not b_tokens:
        return False
    a_set, b_set = set(a_tokens), set(b_tokens)
    return len(a_set & b_set) / max(len(a_set | b_set), 1) >= 0.92


def _candidate_item(seg, excerpt: str) -> EvidenceItem:
    return EvidenceItem(
        seg.index, f"P{seg.index + 1}", excerpt, seg.page_number,
        getattr(seg, "origin", "native_text"),
        getattr(seg, "image_id", None),
        getattr(seg, "docx_image_ordinal", None),
        getattr(seg, "docx_body_block", None),
        getattr(seg, "extraction_warnings", ()),
    )


def _fit_item(seg, available: int) -> EvidenceItem | None:
    """Fit the complete formatted source, including warnings, with no metadata loss.

    Original evidence truncation policy is retained: prefer a nearby word,
    sentence or line boundary. No model calls or silent source renumbering.
    """
    if available <= 0:
        return None
    source = seg.text
    lo, hi = 1, min(len(source), 12_000)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            length = len(format_source_block(_candidate_item(seg, source[:mid])))
        except SourceFormatError as exc:
            # A too-long text may be reduced; malformed source metadata cannot.
            if mid > 1:
                try:
                    format_source_block(_candidate_item(seg, source[:1]))
                except SourceFormatError as inner:
                    raise EvidenceSelectionError("Invalid or oversized evidence metadata.") from inner
            hi = mid - 1
            continue
        if length <= available:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if not best:
        return None
    excerpt = source[:best]
    if best < len(source) and best >= 25:
        boundary = max(excerpt.rfind("\n"), excerpt.rfind(". "), excerpt.rfind(" "))
        if boundary >= max(20, best // 2):
            shortened = excerpt[:boundary + (1 if excerpt[boundary:boundary + 2] == ". " else 0)]
            if shortened.strip():
                excerpt = shortened
    if not excerpt.strip():
        return None
    candidate = _candidate_item(seg, excerpt)
    try:
        if len(format_source_block(candidate)) > available:
            return None
    except SourceFormatError as exc:
        raise EvidenceSelectionError("Invalid or oversized evidence metadata.") from exc
    return candidate


def select_document_evidence(document: "TemporaryDocument", question: str) -> EvidenceSelection:
    """Select bounded source-aware evidence from the current authorised document.

    Exact formatted evidence (including all metadata) fits KH_QA_MAX_EVIDENCE_CHARS.
    The full-context shortcut is only used if all formatted blocks fit.
    Longer selections use lexical relevance, with conservative provenance-aware
    tie breaks and diversity; original [P#] labels and source order are retained.
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
    if len(segments) <= max_segments:
        try:
            complete = format_source_blocks(segments, max_chars=max_evidence)
        except SourceFormatError:
            complete = None  # May simply exceed budget; lexical selection below.
        if complete is not None:
            evidence = tuple(_candidate_item(s, s.text) for s in segments)
            return EvidenceSelection(document.document_id, evidence, "full_context", len(segments), len(complete))

    q = _tokens(question)
    if not q:
        return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)
    docs = [_tokens(seg.text) for seg in segments]
    df = {term: sum(term in tokens for tokens in docs) for term in q}
    visual_question = _visual_question(question)
    scored = []
    normalized_question = " ".join(question.casefold().split())
    for idx, seg in enumerate(segments):
        overlap = q & docs[idx]
        if not overlap:
            continue
        score = sum(1.0 + math.log((len(segments) + 1) / (df[t] + 1)) for t in overlap)
        score += 6.0 * len({t for t in overlap if re.fullmatch(r"(?:[adr]|id)-\d{2,5}", t)})
        if len(normalized_question) >= 8 and normalized_question in seg.text.casefold():
            score += 8.0
        origin = getattr(seg, "origin", "native_text")
        if origin in ("native_text", "ocr_text") and not visual_question:
            score += 0.15
        elif origin == "vision_description" and visual_question:
            score += 0.15
        scored.append((-score, idx))
    if not scored:
        return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)

    ranked = [idx for _, idx in sorted(scored)]
    chosen: list[EvidenceItem] = []
    remaining = max_evidence
    for idx in ranked:
        if len(chosen) >= max_segments:
            break
        seg = segments[idx]
        if any(_near_duplicate(seg, segments[other.index]) for other in chosen):
            continue
        # Separator between rendered blocks is exactly two characters.
        available = remaining - (2 if chosen else 0)
        candidate = _fit_item(seg, available)
        if candidate is None:
            continue
        rendered_len = len(format_source_block(candidate))
        remaining -= rendered_len + (2 if chosen else 0)
        chosen.append(candidate)
    if not chosen:
        return EvidenceSelection(document.document_id, (), "no_match", len(segments), 0)
    chosen.sort(key=lambda item: item.index)
    try:
        exact = format_source_blocks(chosen, max_chars=max_evidence)
    except SourceFormatError as exc:
        raise EvidenceSelectionError("Unable to fit evidence into the configured limit.") from exc
    return EvidenceSelection(document.document_id, tuple(chosen), "lexical", len(segments), len(exact))
