"""Phase 5 M2.2: read-only, local manifest of visual extraction candidates.

No OpenAI calls, Supabase writes, image rendering or retained document/image
bytes. This module does NOT alter the Phase 4 upload/analysis flow.
Candidates are *heuristics* for consented downstream review, not assertions that
an image contains readable information. Resource caps fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES_INSPECTED = 250
MAX_VISUAL_PDF_PAGES = 10
MAX_DOCX_IMAGE_OCCURRENCES = 10
MAX_VISION_OPERATIONS = 10
MAX_DOCX_ZIP_ENTRIES = 3000
MAX_DOCX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 1000
MAX_DOCX_IMAGE_BYTES = 20 * 1024 * 1024
PDF_OCR_LAYER_IMAGE_COVERAGE = 0.60
PDF_OCR_LAYER_TEXT_CHARS = 100
PDF_MIN_MEANINGFUL_IMAGE_COVERAGE = 0.02
PDF_VECTOR_DRAWING_THRESHOLD = 6


class VisualManifestError(ValueError):
    """Safe local inspection failure; never includes document contents."""


@dataclass(frozen=True)
class VisualCandidate:
    source_id: str  # Deterministic within the inspected document, NOT a [P#] label.
    kind: str  # pdf_page or docx_image
    reason: str
    pdf_page: int | None = None  # 1-based physical PDF page, never DOCX page.
    docx_image_ordinal: int | None = None  # 1-based occurrence, not unique file.
    docx_body_block: int | None = None  # 1-based Word body block (approximate).
    docx_body_block_kind: str | None = None  # paragraph or table.
    media_path: str | None = None  # DOCX internal media path; not file bytes.
    native_text_chars: int | None = None
    image_coverage: float | None = None  # Largest PDF image's page area ratio.


@dataclass(frozen=True)
class VisualManifest:
    filename: str
    extension: str
    size_bytes: int
    pdf_page_count: int | None
    candidates: tuple[VisualCandidate, ...]
    warnings: tuple[str, ...] = ()

    @property
    def proposed_vision_calls(self) -> int:
        return len(self.candidates)

    @property
    def consent_required(self) -> bool:
        return bool(self.candidates)


def _validate_input(filename: str, data: bytes) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise VisualManifestError("A valid filename is required.")
    if not isinstance(data, bytes) or not data:
        raise VisualManifestError("A non-empty document is required.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise VisualManifestError("File exceeds the 20 MB upload limit.")
    suffix = PurePosixPath(filename.replace('\\', '/')).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise VisualManifestError("Supported formats are PDF, DOCX and TXT.")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise VisualManifestError("Invalid PDF document.")
    return suffix


def _pdf_manifest(filename: str, data: bytes) -> VisualManifest:
    import pymupdf

    candidates: list[VisualCandidate] = []
    warnings: list[str] = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise VisualManifestError("Password-protected PDFs are not supported.")
            page_count = len(pdf)
            if page_count > MAX_PDF_PAGES_INSPECTED:
                raise VisualManifestError("PDF exceeds the maximum inspection page count.")
            for page_no, page in enumerate(pdf, 1):
                # Avoid pixel decoding/rendering. Only consider images actually
                # placed on the page; unused resource images do not count.
                page_area = max(float((page.rect.width * page.rect.height)), 1.0)
                largest_coverage = 0.0
                has_visual_image = False
                for image in page.get_images(full=True):
                    for rect in page.get_image_rects(image[0]):
                        intersect = rect & page.rect
                        coverage = min(1.0, max(0.0, (intersect.width * intersect.height) / page_area))
                        largest_coverage = max(largest_coverage, coverage)
                        if coverage >= PDF_MIN_MEANINGFUL_IMAGE_COVERAGE:
                            has_visual_image = True
                native_chars = len(page.get_text("text").strip())
                # Vector drawings can represent diagrams/charts with no bitmap.
                # A small number of decorative lines should not trigger calls.
                vector_visual = len(page.get_drawings()) >= PDF_VECTOR_DRAWING_THRESHOLD
                reason: str | None = None
                if native_chars == 0 and (has_visual_image or vector_visual):
                    reason = "image_only_or_visual_page"
                elif has_visual_image and largest_coverage >= PDF_OCR_LAYER_IMAGE_COVERAGE and native_chars <= PDF_OCR_LAYER_TEXT_CHARS:
                    reason = "possible_ocr_layer"
                elif has_visual_image or vector_visual:
                    reason = "embedded_visual"
                elif native_chars == 0:
                    warnings.append(f"PDF page {page_no} has no selectable text or detected visual content.")
                if reason is not None:
                    candidates.append(VisualCandidate(
                        source_id=f"pdf_page_{page_no}", kind="pdf_page", reason=reason,
                        pdf_page=page_no, native_text_chars=native_chars,
                        image_coverage=round(largest_coverage, 4),
                    ))
                    if len(candidates) > MAX_VISUAL_PDF_PAGES:
                        raise VisualManifestError("PDF exceeds the 10 visual-page processing limit.")
    except VisualManifestError:
        raise
    except Exception as exc:
        raise VisualManifestError("Unable to inspect PDF document.") from exc
    return VisualManifest(filename, ".pdf", len(data), page_count, tuple(candidates), tuple(warnings))


def _check_docx_archive(data: bytes) -> None:
    """Inspect ZIP metadata before allowing python-docx to parse the archive."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_ZIP_ENTRIES:
                raise VisualManifestError("Word document has too many archive entries.")
            if not any(info.filename == "word/document.xml" for info in infos):
                raise VisualManifestError("Invalid Word document structure.")
            total = 0
            for info in infos:
                total += info.file_size
                if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise VisualManifestError("Word document exceeds the expanded-size inspection limit.")
                if info.file_size > MAX_DOCX_IMAGE_BYTES and info.filename.startswith("word/media/"):
                    raise VisualManifestError("Embedded Word image exceeds its size limit.")
                if info.file_size and info.file_size / max(1, info.compress_size) > MAX_DOCX_COMPRESSION_RATIO:
                    raise VisualManifestError("Word document contains excessive compression.")
    except VisualManifestError:
        raise
    except (BadZipFile, OSError, ValueError) as exc:
        raise VisualManifestError("Invalid Word document.") from exc


def _docx_manifest(filename: str, data: bytes) -> VisualManifest:
    from docx import Document
    from docx.oxml.ns import qn

    _check_docx_archive(data)
    candidates: list[VisualCandidate] = []
    warnings: list[str] = []
    try:
        doc = Document(BytesIO(data))
        # Inspect top-level paragraphs AND tables, preserving block order.
        # Both inline (wp:inline) and anchored (wp:anchor) pictures use a:blip.
        for block_no, block in enumerate(doc.element.body.iterchildren(), 1):
            if block.tag == qn("w:p"):
                block_kind = "paragraph"
            elif block.tag == qn("w:tbl"):
                block_kind = "table"
            else:
                continue
            for blip in block.iter(qn("a:blip")):
                embedded_id = blip.get(qn("r:embed"))
                linked_id = blip.get(qn("r:link"))
                if not embedded_id:
                    if linked_id:
                        warnings.append("A linked Word image cannot be inspected locally.")
                    continue
                part = doc.part.related_parts.get(embedded_id)
                if part is None or not str(part.content_type).startswith("image/"):
                    warnings.append("A Word image reference could not be resolved.")
                    continue
                ordinal = len(candidates) + 1
                if ordinal > MAX_DOCX_IMAGE_OCCURRENCES:
                    raise VisualManifestError("Word document exceeds the 10-image processing limit.")
                candidates.append(VisualCandidate(
                    source_id=f"docx_image_{ordinal}", kind="docx_image",
                    reason="embedded_image", docx_image_ordinal=ordinal,
                    docx_body_block=block_no, docx_body_block_kind=block_kind,
                    media_path=str(part.partname).lstrip("/"),
                ))
    except VisualManifestError:
        raise
    except Exception as exc:
        raise VisualManifestError("Unable to inspect Word document.") from exc
    return VisualManifest(filename, ".docx", len(data), None, tuple(candidates), tuple(warnings))


def inspect_visual_manifest(filename: str, data: bytes) -> VisualManifest:
    """Build an in-memory candidate manifest; never calls a network provider.

    Caller remains responsible for the application's authenticated owner check.
    This does not extract evidence, label [P#] segments, or retain image bytes.
    """
    extension = _validate_input(filename, data)
    if extension == ".pdf":
        manifest = _pdf_manifest(filename, data)
    elif extension == ".docx":
        manifest = _docx_manifest(filename, data)
    else:
        manifest = VisualManifest(filename, extension, len(data), None, ())
    if manifest.proposed_vision_calls > MAX_VISION_OPERATIONS:
        raise VisualManifestError("Document exceeds the 10-call visual processing limit.")
    return manifest
