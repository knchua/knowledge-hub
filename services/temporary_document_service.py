"""Phase 4: bounded, in-memory parsing. Never stores files in Supabase."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from uuid import uuid4

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from services.knowledge_service import KnowledgeError, validate_file


class TemporaryDocumentError(RuntimeError):
    """Safe message for temporary document processing failures."""


def _limit(name: str, default: int, low: int, high: int) -> int:
    try:
        result = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise TemporaryDocumentError(f"Invalid processing configuration: {name}.") from exc
    if not low <= result <= high:
        raise TemporaryDocumentError(f"Invalid processing configuration: {name}.")
    return result


@dataclass(frozen=True)
class TemporarySegment:
    index: int
    text: str
    page_number: int | None


@dataclass(frozen=True)
class TemporaryDocument:
    document_id: str
    owner_user_id: str
    filename: str
    extension: str
    size_bytes: int
    character_count: int
    page_count: int | None
    segments: tuple[TemporarySegment, ...]
    warnings: tuple[str, ...]


def parse_temporary_document(owner_user_id: str, filename: str, data: bytes) -> TemporaryDocument:
    """Validate, extract and split only to bounded in-memory segments.

    No raw input bytes are returned or retained. The caller owns the resulting
    document and must enforce a fresh active-user check before further use.
    """
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise TemporaryDocumentError("An authenticated user is required.")
    if not isinstance(data, bytes):
        raise TemporaryDocumentError("Invalid uploaded file.")
    try:
        validated = validate_file(filename, data)
    except KnowledgeError as exc:
        raise TemporaryDocumentError(str(exc)) from exc

    max_chars = _limit("KH_ANALYSIS_MAX_TEXT_CHARS", 500_000, 1000, 2_000_000)
    max_segments = _limit("KH_ANALYSIS_MAX_SEGMENTS", 150, 1, 2000)
    segment_size = _limit("KH_ANALYSIS_SEGMENT_CHARS", 4000, 500, 12000)
    overlap = _limit("KH_ANALYSIS_SEGMENT_OVERLAP", 200, 0, 2000)
    if overlap >= segment_size:
        raise TemporaryDocumentError("Segment overlap must be smaller than segment size.")

    sources: list[Document] = []
    total = 0
    pages: int | None = None
    warnings: list[str] = []

    def append_text(text: str, page: int | None) -> None:
        nonlocal total
        text = text.strip()
        if not text:
            return
        total += len(text)
        if total > max_chars:
            raise TemporaryDocumentError("Extracted text exceeds the analysis limit.")
        sources.append(Document(page_content=text, metadata={"page_number": page}))

    try:
        if validated.extension == ".pdf":
            import fitz
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass:
                    raise TemporaryDocumentError("Password-protected PDFs are not supported.")
                pages = len(pdf)
                for i, page in enumerate(pdf):
                    # Limit runaway expansion before retaining page text.
                    append_text(page.get_text("text"), i + 1)
                if len(sources) < pages:
                    warnings.append("Some PDF pages contained no extractable text.")
        elif validated.extension == ".docx":
            from docx import Document as WordDocument
            doc = WordDocument(BytesIO(data))
            # Preserve source order for paragraph/table top-level elements.
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            for element in doc.element.body.iterchildren():
                if element.tag == qn("w:p"):
                    append_text(Paragraph(element, doc).text, None)
                elif element.tag == qn("w:tbl"):
                    table = Table(element, doc)
                    for row in table.rows:
                        append_text(" | ".join(cell.text.strip() for cell in row.cells), None)
        else:
            append_text(data.decode("utf-8-sig"), None)
    except TemporaryDocumentError:
        raise
    except Exception as exc:
        raise TemporaryDocumentError("Unable to extract text from this document.") from exc

    if not sources:
        raise TemporaryDocumentError("No readable text found. Scanned PDFs require OCR, which is not supported.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=segment_size, chunk_overlap=overlap)
    segments: list[TemporarySegment] = []
    for source in sources:
        for part in splitter.split_documents([source]):
            text = part.page_content.strip()
            if text:
                if len(segments) >= max_segments:
                    raise TemporaryDocumentError("Document exceeds the maximum analysis segment count.")
                segments.append(TemporarySegment(len(segments), text, part.metadata.get("page_number")))

    return TemporaryDocument(
        document_id=str(uuid4()), owner_user_id=owner_user_id,
        filename=validated.display_name, extension=validated.extension,
        size_bytes=len(data), character_count=total, page_count=pages,
        segments=tuple(segments), warnings=tuple(warnings),
    )
