"""Phase 5 M2.4: pure, bounded merging of trusted native and visual evidence.

No external calls, session mutation, file I/O, persistent storage, or new consent.
M2.5 must revalidate actor/document generation and obtain explicit image consent.
The caller must supply native blocks from the same validated source and provide
only VisualEvidence from the consented M2.3 provider matched to the M2.2 manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
import re
from typing import Sequence
from uuid import uuid4

from services.visual_extraction_manifest_service import VisualManifest
from services.visual_provider_service import VisualEvidence
from services.temporary_document_service import (
    TemporaryDocument, TemporarySegment, TemporaryDocumentError, _limit,
)


class VisualMergeError(ValueError):
    """Safe error; never includes document text, generated OCR, or API output."""


@dataclass(frozen=True)
class NativeEvidenceBlock:
    """A source-ordered native extraction block, supplied by a trusted parser.

    `pdf_page` is the physical 1-based PDF page. Word body blocks are 1-based
    structural indices, *not* Word pages. A TXT block has neither location.
    """
    text: str
    pdf_page: int | None = None
    docx_body_block: int | None = None


def _normalise(value: str) -> str:
    """Comparison only. Never rewrite or fabricate the retained evidence."""
    return " ".join(re.findall(r"\w+", value.casefold(), re.UNICODE))


def _deduplicate_ocr(native_text: str, recognized_text: str) -> str:
    """Remove only OCR lines already represented in the same native page.

    This intentionally does not use fuzzy similarity: near matches can be
    materially different amounts, dates or identifiers. Text not confidently
    duplicated is retained and its provenance remains explicit.
    """
    native = _normalise(native_text)
    if not native:
        return recognized_text.strip()
    unique: list[str] = []
    seen: set[str] = set()
    for line in recognized_text.splitlines():
        stripped = line.strip()
        canonical = _normalise(stripped)
        if not canonical:
            continue
        if canonical in seen or f" {canonical} " in f" {native} ":
            continue
        unique.append(stripped)
        seen.add(canonical)
    return "\n".join(unique)


def _valid_positive(value: object) -> bool:
    return type(value) is int and value >= 1


def _validate_inputs(owner_user_id: str, filename: str, extension: str,
                     size_bytes: int, manifest: VisualManifest,
                     native_blocks: Sequence[NativeEvidenceBlock],
                     visual_evidence: Sequence[VisualEvidence]) -> None:
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise VisualMergeError("An authenticated document owner is required.")
    if not isinstance(manifest, VisualManifest):
        raise VisualMergeError("Trusted visual manifest is required.")
    if (filename != manifest.filename or extension != manifest.extension
            or type(size_bytes) is not int or size_bytes != manifest.size_bytes
            or size_bytes <= 0 or size_bytes > 20 * 1024 * 1024):
        raise VisualMergeError("Document and visual manifest do not match.")
    if extension not in (".pdf", ".docx", ".txt"):
        raise VisualMergeError("Unsupported document type.")
    if not isinstance(native_blocks, (tuple, list)) or not isinstance(visual_evidence, (tuple, list)):
        raise VisualMergeError("Invalid evidence collection.")
    if len(visual_evidence) > len(manifest.candidates) or len(visual_evidence) > 10:
        raise VisualMergeError("Visual evidence exceeds the trusted manifest.")
    if len(native_blocks) > 2000:
        raise VisualMergeError("Native evidence exceeds the processing limit.")
    trusted = {c.source_id: c for c in manifest.candidates}
    if len(trusted) != len(manifest.candidates):
        raise VisualMergeError("Visual manifest contains duplicate source identifiers.")
    seen: set[str] = set()
    for evidence in visual_evidence:
        if not isinstance(evidence, VisualEvidence) or evidence.source_id not in trusted:
            raise VisualMergeError("Visual evidence does not match the trusted manifest.")
        if evidence.source_id in seen:
            raise VisualMergeError("Duplicate visual evidence source identifier.")
        seen.add(evidence.source_id)
        if (not isinstance(evidence.recognized_text, str) or
                not isinstance(evidence.visual_description, str) or
                len(evidence.recognized_text) > 8000 or len(evidence.visual_description) > 8000 or
                not isinstance(evidence.warnings, tuple) or
                not isinstance(evidence.unreadable_regions, tuple) or
                any(not isinstance(x, str) or len(x) > 500 for x in (*evidence.warnings, *evidence.unreadable_regions))):
            raise VisualMergeError("Invalid visual evidence format.")
    for block in native_blocks:
        if not isinstance(block, NativeEvidenceBlock) or not isinstance(block.text, str):
            raise VisualMergeError("Invalid native evidence block.")
        if extension == ".pdf":
            if (not _valid_positive(block.pdf_page) or
                    manifest.pdf_page_count is None or block.pdf_page > manifest.pdf_page_count or
                    block.docx_body_block is not None):
                raise VisualMergeError("Invalid PDF source location.")
        elif extension == ".docx":
            if block.pdf_page is not None or (block.docx_body_block is not None and
                                              not _valid_positive(block.docx_body_block)):
                raise VisualMergeError("Invalid Word source location.")
        elif block.pdf_page is not None or block.docx_body_block is not None:
            raise VisualMergeError("TXT evidence cannot include PDF/Word locations.")
    for candidate in manifest.candidates:
        if extension == ".pdf":
            if (candidate.kind != "pdf_page" or not _valid_positive(candidate.pdf_page)
                    or manifest.pdf_page_count is None or candidate.pdf_page > manifest.pdf_page_count
                    or candidate.docx_image_ordinal is not None):
                raise VisualMergeError("Invalid PDF visual source location.")
        elif extension == ".docx":
            if (candidate.kind != "docx_image" or not _valid_positive(candidate.docx_image_ordinal)
                    or candidate.pdf_page is not None
                    or (candidate.docx_body_block is not None and not _valid_positive(candidate.docx_body_block))):
                raise VisualMergeError("Invalid Word visual source location.")
        else:
            raise VisualMergeError("TXT documents cannot contain visual candidates.")


def merge_visual_evidence(*, owner_user_id: str, manifest: VisualManifest,
                          native_blocks: Sequence[NativeEvidenceBlock],
                          visual_evidence: Sequence[VisualEvidence]) -> TemporaryDocument:
    """Create a NEW session-only TemporaryDocument from trusted extracted inputs.

    Caller must first validate original file and keep its bytes out of this API.
    No replacement/session mutation happens here. Citation labels derive solely
    from sequential segment indices after deterministic source ordering.
    Incomplete visual extraction is explicitly warned rather than silently
    treated as successful. Any invalid evidence fails the whole operation.
    """
    _validate_inputs(owner_user_id, manifest.filename, manifest.extension, manifest.size_bytes,
                     manifest, native_blocks, visual_evidence)
    try:
        max_chars = _limit("KH_ANALYSIS_MAX_TEXT_CHARS", 500_000, 1000, 2_000_000)
        max_segments = _limit("KH_ANALYSIS_MAX_SEGMENTS", 150, 1, 2000)
        segment_size = _limit("KH_ANALYSIS_SEGMENT_CHARS", 4000, 500, 12000)
        overlap = _limit("KH_ANALYSIS_SEGMENT_OVERLAP", 200, 0, 2000)
    except TemporaryDocumentError as exc:
        raise VisualMergeError("Invalid analysis processing configuration.") from exc
    if overlap >= segment_size:
        raise VisualMergeError("Segment overlap must be smaller than segment size.")

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=segment_size, chunk_overlap=overlap)
    extension = manifest.extension
    warnings = list(manifest.warnings)
    # tuple fields: (order, origin priority, text, pdf_page, image_id, ordinal, body_block, warnings)
    items: list[tuple[tuple[int, int, int], str, str, int | None,
                      str | None, int | None, int | None, tuple[str, ...]]] = []
    native_by_page: dict[int, list[str]] = defaultdict(list)
    has_unlocated_word_text = False
    for position, block in enumerate(native_blocks):
        text = block.text.strip()
        if not text:
            continue
        if extension == ".pdf":
            native_by_page[block.pdf_page].append(text)
            order = (block.pdf_page, 0, position)
        elif extension == ".docx":
            if block.docx_body_block is None:
                has_unlocated_word_text = True
                order = (0, 0, position)
            else:
                order = (block.docx_body_block, 0, position)
        else:
            order = (0, 0, position)
        items.append((order, "native_text", text, block.pdf_page, None, None,
                      block.docx_body_block, ()))
    if has_unlocated_word_text and manifest.candidates:
        warnings.append("Word reading order is uncertain where native text has no body-block location.")

    evidence_map = {v.source_id: v for v in visual_evidence}
    for position, candidate in enumerate(manifest.candidates):
        vision = evidence_map.get(candidate.source_id)
        if vision is None:
            warnings.append(f"Visual processing incomplete for {candidate.source_id}.")
            continue
        if vision.unreadable_regions:
            warnings.append(f"Visual content may be incomplete for {candidate.source_id}.")
        notes = tuple(vision.warnings)
        if vision.unreadable_regions:
            notes += ("Some regions could not be read reliably.",)
        page = candidate.pdf_page
        block = candidate.docx_body_block
        anchor = page if extension == ".pdf" else (block if block is not None else 10**9)
        if extension == ".docx" and block is None:
            warnings.append(f"Word image location uncertain for {candidate.source_id}.")
        # OCR is evidence text, not a source of instructions; compare to the
        # native text from this physical page only, never another page.
        ocr = vision.recognized_text.strip()
        if page is not None:
            ocr = _deduplicate_ocr("\n".join(native_by_page[page]), ocr)
        if ocr:
            items.append(((anchor, 1, position), "ocr_text", ocr, page,
                          candidate.source_id, candidate.docx_image_ordinal, block, notes))
        desc = vision.visual_description.strip()
        # Only remove exact repetition: a visual relationship may carry facts
        # missing from the printed words. Never claim that description is OCR.
        if desc and _normalise(desc) != _normalise(vision.recognized_text):
            items.append(((anchor, 2, position), "vision_description", desc, page,
                          candidate.source_id, candidate.docx_image_ordinal, block, notes))
        if not ocr and not desc:
            warnings.append(f"No usable visual evidence for {candidate.source_id}.")

    items.sort(key=lambda item: item[0])
    segments: list[TemporarySegment] = []
    total_chars = 0
    for _, origin, source_text, page, image_id, image_ordinal, body_block, notes in items:
        total_chars += len(source_text)
        if total_chars > max_chars:
            raise VisualMergeError("Extracted evidence exceeds the analysis text limit.")
        for part in splitter.split_text(source_text):
            text = part.strip()
            if not text:
                continue
            if len(segments) >= max_segments:
                raise VisualMergeError("Document exceeds the maximum analysis segment count.")
            segments.append(TemporarySegment(
                index=len(segments), text=text, page_number=page,
                origin=origin, image_id=image_id,
                docx_image_ordinal=image_ordinal, docx_body_block=body_block,
                extraction_warnings=notes,
            ))
    if not segments:
        raise VisualMergeError("No usable text or visual evidence was extracted.")
    return TemporaryDocument(
        document_id=str(uuid4()), owner_user_id=owner_user_id,
        filename=manifest.filename, extension=manifest.extension,
        size_bytes=manifest.size_bytes, character_count=total_chars,
        page_count=manifest.pdf_page_count, segments=tuple(segments),
        warnings=tuple(warnings),
    )
