"""No-OCR UX regression tests. No network, secrets, or external OCR required."""
from io import BytesIO

import pytest
from docx import Document as WordDocument

from services.temporary_document_service import (
    TemporaryDocumentError,
    parse_temporary_document,
)


def _empty_docx() -> bytes:
    out = BytesIO()
    doc = WordDocument()
    # A blank paragraph has no extractable text, like an image-only file.
    doc.add_paragraph('')
    doc.save(out)
    return out.getvalue()


def test_docx_without_extractable_text_reports_images_not_supported():
    with pytest.raises(TemporaryDocumentError) as exc:
        parse_temporary_document('test-user', 'infographic.docx', _empty_docx())
    message = str(exc.value)
    assert 'Word documents' in message
    assert 'images' in message
    assert 'text-based document' in message
    assert 'Scanned PDFs require OCR' not in message


def test_pdf_without_extractable_text_reports_scanned_pdf_limitation():
    import fitz
    pdf = fitz.open()
    pdf.new_page()
    raw = pdf.tobytes()
    pdf.close()
    with pytest.raises(TemporaryDocumentError) as exc:
        parse_temporary_document('test-user', 'scan.pdf', raw)
    assert 'Scanned PDFs' in str(exc.value)
    assert 'text-based document' in str(exc.value)


def test_regular_docx_still_parses_text():
    out = BytesIO()
    doc = WordDocument()
    doc.add_paragraph('Synthetic retirement FAQ: three available plans.')
    doc.save(out)
    result = parse_temporary_document('test-user', 'faq.docx', out.getvalue())
    assert 'three available plans' in result.segments[0].text
