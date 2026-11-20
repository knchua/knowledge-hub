"""Phase 5 M3.2: deterministic source-aware evidence formatting, without model calls.

This service only formats already-authorised temporary evidence. It does NOT
perform retrieval, consent checks, session access, provider calls, or persistence.
Callers must obtain the current document using existing authorisation services.

All text and warnings from documents/providers are untrusted data. M3.3/M3.4
must explicitly instruct their models to treat these blocks as untrusted data.
"""
from __future__ import annotations

import re
from typing import Iterable


class SourceFormatError(ValueError):
    """Safe error message, without source content."""


ALLOWED_ORIGINS = frozenset({"native_text", "ocr_text", "vision_description"})
MAX_BLOCK_TEXT_CHARS = 12_000
MAX_WARNINGS = 12
MAX_WARNING_CHARS = 500
MAX_BLOCK_CHARS = 16_000
MAX_TOTAL_CHARS = 50_000

_ORIGIN_LABELS = {
    "native_text": "Native/selectable text",
    "ocr_text": "OCR-recognised text (may contain recognition errors)",
    "vision_description": "Model-generated visual interpretation (not a literal transcription)",
}


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _single_line(value: str) -> str:
    """Treat metadata as one line; remove controls, not printable content."""
    return re.sub(r"\s+", " ", "".join(c if c.isprintable() or c.isspace() else " " for c in value)).strip()


def _safe_metadata(value: object, *, maximum: int = MAX_WARNING_CHARS) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise SourceFormatError("Invalid source metadata.")
    return _single_line(value)


def format_source_block(item: object) -> str:
    """Format one ordered segment or selected EvidenceItem with its original [P#].

    `index` is the *original zero-based document segment index*; it must never
    be renumbered according to retrieval order. No source text is rewritten.
    Fail closed on invalid/oversized evidence rather than silently truncating.
    """
    index = getattr(item, "index", None)
    value = getattr(item, "text", None)
    page = getattr(item, "page_number", None)
    origin = getattr(item, "origin", "native_text")
    ordinal = getattr(item, "docx_image_ordinal", None)
    block = getattr(item, "docx_body_block", None)
    image_id = getattr(item, "image_id", None)
    warnings = getattr(item, "extraction_warnings", ())
    label = f"P{index + 1}" if type(index) is int and index >= 0 else None
    if label is None or not isinstance(value, str) or not value.strip() or len(value) > MAX_BLOCK_TEXT_CHARS:
        raise SourceFormatError("Invalid or oversized source evidence.")
    item_label = getattr(item, "label", label)
    if item_label != label:
        raise SourceFormatError("Evidence label does not match segment index.")
    if origin not in ALLOWED_ORIGINS:
        raise SourceFormatError("Invalid evidence extraction origin.")
    if page is not None and not _positive_int(page):
        raise SourceFormatError("Invalid PDF page location.")
    if ordinal is not None and not _positive_int(ordinal):
        raise SourceFormatError("Invalid Word image ordinal.")
    if block is not None and not _positive_int(block):
        raise SourceFormatError("Invalid Word body-block position.")
    if page is not None and (ordinal is not None or block is not None):
        raise SourceFormatError("Conflicting source locations.")
    if image_id is not None:
        if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", image_id):
            raise SourceFormatError("Invalid visual source identifier.")
    if not isinstance(warnings, tuple) or len(warnings) > MAX_WARNINGS:
        raise SourceFormatError("Invalid evidence warnings.")

    location = (f"PDF page {page}" if page is not None else
                f"Word image {ordinal}, body block {block}" if ordinal is not None and block is not None else
                f"Word image {ordinal}" if ordinal is not None else
                f"Word body block {block}" if block is not None else
                "Document segment (no physical page location)")
    lines = [f"[{label}]", f"Location: {location}", f"Extraction: {origin}",
             f"Evidence type: {_ORIGIN_LABELS[origin]}"]
    if image_id is not None:
        lines.append(f"Visual source ID: {image_id}")
    if warnings:
        clean = [_safe_metadata(w) for w in warnings]
        if any(not w for w in clean):
            raise SourceFormatError("Invalid evidence warnings.")
        lines.append("Extraction warnings (untrusted): " + " | ".join(clean))
    else:
        lines.append("Extraction warnings: None reported (not a confidence guarantee)")
    lines.extend(("UNTRUSTED SOURCE EVIDENCE:", value, f"[/{label}]"))
    result = "\n".join(lines)
    if len(result) > MAX_BLOCK_CHARS:
        raise SourceFormatError("Source evidence exceeds formatting limit.")
    return result


def format_source_blocks(items: Iterable[object], *, max_chars: int = MAX_TOTAL_CHARS) -> str:
    """Format a sequence without renumbering or silent context truncation."""
    if type(max_chars) is not int or not 500 <= max_chars <= MAX_TOTAL_CHARS:
        raise SourceFormatError("Invalid source context budget.")
    if not isinstance(items, (list, tuple)) or not items:
        raise SourceFormatError("No source evidence was supplied.")
    if len(items) > 2000:
        raise SourceFormatError("Too many source segments.")
    seen: set[int] = set()
    result: list[str] = []
    size = 0
    for item in items:
        index = getattr(item, "index", None)
        if type(index) is not int or index < 0 or index in seen:
            raise SourceFormatError("Invalid or duplicate source segment identifier.")
        seen.add(index)
        formatted = format_source_block(item)
        size += len(formatted) + (2 if result else 0)
        if size > max_chars:
            raise SourceFormatError("Source context exceeds formatting budget.")
        result.append(formatted)
    return "\n\n".join(result)
