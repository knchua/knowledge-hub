"""Phase 5 M3.5-R1: session-only, immutable fact inventory contract.

Contract only; NOT connected to summarisation, extraction, databases or Streamlit.
No model calls and no assertion that textual overlap proves semantic truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

FactStatus = Literal["candidate", "uncertain", "conflicted", "rejected"]
SourceOrigin = Literal["native_text", "ocr_text", "vision_description", "unknown"]
FactKind = Literal["entity", "date", "quantity", "action", "status", "risk", "relationship", "metric", "process", "other"]
_LABEL = re.compile(r"P[1-9][0-9]*\Z")
_ID = re.compile(r"F-[0-9]{3,6}\Z")
_MAX_FACTS = 200
_MAX_ANCHORS = 12
_MAX_FACT_TEXT = 1000
_MAX_QUOTE = 1200
_MAX_SOURCE = 12000


class FactInventoryError(ValueError):
    """Content-free error indicating invalid fact inventory contract data."""


def _safe_string(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise FactInventoryError(f"Invalid {field}.")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise FactInventoryError(f"Invalid {field}.")
    return value


@dataclass(frozen=True)
class FactAnchor:
    """An exact supporting substring of a single labelled evidence segment."""
    label: str
    quote: str
    origin: SourceOrigin = "unknown"
    page_number: int | None = None
    image_ordinal: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not _LABEL.fullmatch(self.label):
            raise FactInventoryError("Invalid source label.")
        _safe_string(self.quote, "source quote", _MAX_QUOTE)
        if self.origin not in ("native_text", "ocr_text", "vision_description", "unknown"):
            raise FactInventoryError("Invalid evidence origin.")
        for name in ("page_number", "image_ordinal"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise FactInventoryError(f"Invalid {name}.")


@dataclass(frozen=True)
class FactRecord:
    """A source-linked claim candidate, never automatically designated verified."""
    fact_id: str
    kind: FactKind
    statement: str
    anchors: tuple[FactAnchor, ...]
    status: FactStatus = "candidate"
    # Relationships must be explicitly typed, not inferred from adjacent facts.
    relation: str | None = None
    related_fact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.fact_id, str) or not _ID.fullmatch(self.fact_id):
            raise FactInventoryError("Invalid fact identifier.")
        if self.kind not in ("entity", "date", "quantity", "action", "status", "risk", "relationship", "metric", "process", "other"):
            raise FactInventoryError("Invalid fact kind.")
        _safe_string(self.statement, "fact statement", _MAX_FACT_TEXT)
        if not isinstance(self.anchors, tuple) or not 1 <= len(self.anchors) <= _MAX_ANCHORS:
            raise FactInventoryError("Invalid fact anchors.")
        if not all(isinstance(a, FactAnchor) for a in self.anchors):
            raise FactInventoryError("Invalid fact anchors.")
        if self.status not in ("candidate", "uncertain", "conflicted", "rejected"):
            raise FactInventoryError("Invalid fact status.")
        if self.kind == "relationship":
            if not self.relation or not isinstance(self.relation, str):
                raise FactInventoryError("Relationships require explicit relation type.")
            _safe_string(self.relation, "relation type", 80)
            if not isinstance(self.related_fact_ids, tuple) or len(self.related_fact_ids) < 2:
                raise FactInventoryError("Relationships require two fact identifiers.")
        elif self.relation is not None or self.related_fact_ids:
            raise FactInventoryError("Non-relationship fact has relationship metadata.")
        if not isinstance(self.related_fact_ids, tuple) or any(
            not isinstance(r, str) or not _ID.fullmatch(r) for r in self.related_fact_ids
        ):
            raise FactInventoryError("Invalid related fact identifiers.")


@dataclass(frozen=True)
class FactInventory:
    """Document/owner-scoped transient contract; caller enforces fresh auth checks."""
    document_id: str
    owner_user_id: str
    facts: tuple[FactRecord, ...]
    source_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _safe_string(self.document_id, "document identity", 150)
        _safe_string(self.owner_user_id, "owner identity", 150)
        if not isinstance(self.facts, tuple) or len(self.facts) > _MAX_FACTS:
            raise FactInventoryError("Invalid fact count.")
        if not isinstance(self.source_labels, tuple) or any(
            not isinstance(label, str) or not _LABEL.fullmatch(label)
            for label in self.source_labels
        ):
            raise FactInventoryError("Invalid source labels.")
        if len(set(self.source_labels)) != len(self.source_labels):
            raise FactInventoryError("Duplicate source labels.")
        if any(not isinstance(fact, FactRecord) for fact in self.facts):
            raise FactInventoryError("Invalid fact record.")
        ids = [fact.fact_id for fact in self.facts]
        if len(set(ids)) != len(ids):
            raise FactInventoryError("Duplicate fact identifier.")
        allowed = set(self.source_labels)
        for fact in self.facts:
            if not isinstance(fact, FactRecord):
                raise FactInventoryError("Invalid fact record.")
            if any(anchor.label not in allowed for anchor in fact.anchors):
                raise FactInventoryError("Unknown source label.")
            if any(related not in ids or related == fact.fact_id for related in fact.related_fact_ids):
                raise FactInventoryError("Invalid relationship target.")
            if len(set(fact.related_fact_ids)) != len(fact.related_fact_ids):
                raise FactInventoryError("Duplicate relationship target.")


def bind_inventory(document: object, facts: tuple[FactRecord, ...]) -> FactInventory:
    """Check anchors against actual source segments; does NOT verify semantics.

    The caller must obtain the current document through the authorised session
    service before binding or reading facts. No state, network, DB or file I/O.
    """
    document_id = _safe_string(getattr(document, "document_id", None), "document identity", 150)
    owner = _safe_string(getattr(document, "owner_user_id", None), "owner identity", 150)
    segments = getattr(document, "segments", None)
    if not isinstance(segments, (list, tuple)) or not segments or len(segments) > 2000:
        raise FactInventoryError("Invalid source segments.")
    sources: dict[str, str] = {}
    for idx, segment in enumerate(segments):
        if getattr(segment, "index", None) != idx:
            raise FactInventoryError("Invalid segment index.")
        text = getattr(segment, "text", None)
        if not isinstance(text, str) or not text or len(text) > _MAX_SOURCE:
            raise FactInventoryError("Invalid segment text.")
        sources[f"P{idx + 1}"] = text
    inventory = FactInventory(document_id, owner, facts, tuple(sources))
    for fact in inventory.facts:
        for anchor in fact.anchors:
            if anchor.quote not in sources[anchor.label]:
                raise FactInventoryError("Source quote not found in labelled segment.")
    return inventory


def matches_document(inventory: FactInventory, document: object) -> bool:
    """Identity-only guard; NOT a substitute for current_document actor check."""
    return (isinstance(inventory, FactInventory)
            and inventory.document_id == getattr(document, "document_id", None)
            and inventory.owner_user_id == getattr(document, "owner_user_id", None))
