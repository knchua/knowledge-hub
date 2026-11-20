"""Phase 5 M3.5-R2: deterministic, dormant source-quote fact candidates.

No LLM, filesystem, network, persistence, session management or UI integration.
All records remain `candidate`; literal matching is not semantic verification.
Callers MUST obtain the current authorised TemporaryDocument before invoking this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from services.fact_inventory_service import (
    FactAnchor, FactInventory, FactInventoryError, FactRecord, bind_inventory,
)


class FactExtractionError(ValueError):
    """Safe, content-free extraction failure."""


# Deliberately narrow phrase recognisers, not a general NLP extractor.
# A value must be present literally in the segment text; never normalise/guess.
_DATE = re.compile(r"\b(?:[1-9]|[12][0-9]|3[01])\s+"
                   r"(?:January|February|March|April|May|June|July|August|"
                   r"September|October|November|December)\s+\d{4}\b", re.I)
_CHART = re.compile(r"\bQ[1-4]\s*[:=]\s*\d+(?:\.\d+)?\b", re.I)
_DURATION = re.compile(r"\b\d+\s+(?:working|business|calendar)\s+days?\b", re.I)
_COUNT = re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                    r"(?:fire\s+exits?|(?:damaged\s+)?exit\s+signs?)\b", re.I)
_ACTION = re.compile(r"\b(?:replace|repair|inspect|review|submit|approve|reject)\s+"
                     r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)?\s*"
                     r"(?:damaged\s+)?(?:exit\s+signs?|fire\s+exits?|requests?|documents?)\b", re.I)
_OWNER = re.compile(r"\b(?:Owner|Responsible\s+team)\s*:\s*"
                    r"[A-Za-z][A-Za-z ]{1,65}\b", re.I)
_RISK = re.compile(r"\bRisk\s*:\s*[^.!?\n]{2,180}", re.I)
_STATUS = re.compile(r"\bStatus\s*:\s*[^.!?\n]{2,180}", re.I)
_CONDITION = re.compile(r"\bescalation\s+only\s+after\s+review\b", re.I)
_PROCESS = re.compile(r"\b[A-Za-z][A-Za-z ]{1,45}\s*(?:->|→)\s*"
                      r"[A-Za-z][A-Za-z ]{1,45}(?:\s*(?:->|→)\s*"
                      r"[A-Za-z][A-Za-z ]{1,45})*", re.I)

# Bounded input prevents runaway scanning; R1 limits individual source quotes.
_MAX_SEGMENTS = 2000
_MAX_SEGMENT_CHARS = 12000
_MAX_FACTS = 200
_MAX_MATCHES_PER_SEGMENT = 100
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date", _DATE), ("metric", _CHART), ("metric", _DURATION),
    ("quantity", _COUNT), ("action", _ACTION), ("entity", _OWNER),
    ("risk", _RISK), ("status", _STATUS), ("status", _CONDITION),
    ("process", _PROCESS),
)


@dataclass(frozen=True)
class ExtractionStats:
    total_segments: int
    candidates: int
    source_labels: tuple[str, ...]


def _origin(segment: object) -> str:
    """Return a provenance value ONLY if explicitly recorded on the segment."""
    for field in ("origin", "source_origin"):
        value = getattr(segment, field, None)
        if value in ("native_text", "ocr_text", "vision_description"):
            return value
    return "unknown"


def _metadata(segment: object, name: str) -> int | None:
    value = getattr(segment, name, None)
    # Avoid accepting booleans as ints or inferring DOCX pagination.
    return value if type(value) is int and value >= 1 else None


def extract_fact_candidates(document: object) -> FactInventory:
    """Extract exact source-substring candidates; bind through the R1 contract.

    This intentionally does NOT assert that a detected quote is true, and does
    NOT create any implied relationships, prioritisation or compliance claims.
    Fail closed if fact/segment budgets would require silent truncation.
    """
    segments = getattr(document, "segments", None)
    if not isinstance(segments, (list, tuple)) or not 1 <= len(segments) <= _MAX_SEGMENTS:
        raise FactExtractionError("Invalid source segment collection.")
    facts: list[FactRecord] = []
    for pos, segment in enumerate(segments):
        if getattr(segment, "index", None) != pos:
            raise FactExtractionError("Invalid source segment index.")
        text = getattr(segment, "text", None)
        if not isinstance(text, str) or not text or len(text) > _MAX_SEGMENT_CHARS:
            raise FactExtractionError("Invalid source segment text.")
        found: set[tuple[int, int, str]] = set()
        matches: list[tuple[int, int, str, str]] = []
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span()
                # Avoid double-counting identical quotes of the same kind.
                key = (start, end, kind)
                if key not in found:
                    found.add(key)
                    matches.append((start, end, kind, text[start:end]))
                if len(matches) > _MAX_MATCHES_PER_SEGMENT:
                    raise FactExtractionError("Candidate extraction limit exceeded.")
        matches.sort(key=lambda item: (item[0], item[1], item[2]))
        for _, _, kind, quote in matches:
            if len(facts) >= _MAX_FACTS:
                raise FactExtractionError("Candidate extraction limit exceeded.")
            # Always use original segment ordinal, never page or retrieval rank.
            anchor = FactAnchor(
                label=f"P{pos + 1}", quote=quote, origin=_origin(segment),
                page_number=_metadata(segment, "page_number"),
                image_ordinal=_metadata(segment, "image_ordinal"),
            )
            facts.append(FactRecord(
                fact_id=f"F-{len(facts) + 1:03d}", kind=kind,
                statement=quote, anchors=(anchor,), status="candidate",
            ))
    try:
        return bind_inventory(document, tuple(facts))
    except FactInventoryError as exc:
        raise FactExtractionError("Unable to bind candidates to document evidence.") from exc


def extraction_stats(inventory: FactInventory) -> ExtractionStats:
    """Content-free counters; no document text or quotes are logged."""
    if not isinstance(inventory, FactInventory):
        raise FactExtractionError("Invalid fact inventory.")
    return ExtractionStats(len(inventory.source_labels), len(inventory.facts), inventory.source_labels)
