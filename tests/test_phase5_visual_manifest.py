"""Deterministic Phase 5 M2.2 tests: local only; no provider, DB, or network."""
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from docx import Document as WordDocument
from docx.shared import Inches

from services.visual_extraction_manifest_service import (
    VisualManifestError, inspect_visual_manifest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "phase5"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_scanned_pdf_finds_two_pages():
    result = inspect_visual_manifest("S1_scanned_two_page.pdf", fixture_bytes("S1_scanned_two_page.pdf"))
    assert result.pdf_page_count == 2
    assert [item.source_id for item in result.candidates] == ["pdf_page_1", "pdf_page_2"]
    assert [item.pdf_page for item in result.candidates] == [1, 2]
    assert all(item.reason == "image_only_or_visual_page" for item in result.candidates)
    assert all(item.native_text_chars == 0 for item in result.candidates)
    assert result.proposed_vision_calls == 2 and result.consent_required


def test_docx_infographic_has_media_ordinal_not_page_number():
    result = inspect_visual_manifest("S2_image_only_infographic.docx", fixture_bytes("S2_image_only_infographic.docx"))
    assert result.proposed_vision_calls == 1
    item = result.candidates[0]
    assert item.source_id == "docx_image_1"
    assert item.kind == "docx_image"
    assert item.pdf_page is None
    assert item.docx_image_ordinal == 1
    assert item.docx_body_block is not None
    assert item.media_path == "word/media/image1.png"


def test_mixed_pdf_chart_and_ocr_layer_are_distinguished():
    result = inspect_visual_manifest("S3_mixed_chart_ocr_layer.pdf", fixture_bytes("S3_mixed_chart_ocr_layer.pdf"))
    assert result.pdf_page_count == 2
    assert [item.source_id for item in result.candidates] == ["pdf_page_1", "pdf_page_2"]
    assert result.candidates[0].reason == "embedded_visual"
    assert result.candidates[0].native_text_chars > 100
    assert result.candidates[1].reason == "possible_ocr_layer"
    assert 0 < result.candidates[1].native_text_chars <= 100


def test_txt_and_native_text_only_pdf_have_no_visual_calls():
    txt = inspect_visual_manifest("notes.txt", b"A safe local note.")
    assert not txt.consent_required and not txt.candidates
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Selectable text only")
        result = inspect_visual_manifest("native.pdf", pdf.tobytes())
    assert result.pdf_page_count == 1
    assert result.proposed_vision_calls == 0


def test_blank_pdf_is_warning_not_unnecessary_vision_call():
    with pymupdf.open() as pdf:
        pdf.new_page()
        result = inspect_visual_manifest("blank.pdf", pdf.tobytes())
    assert not result.candidates
    assert "PDF page 1" in result.warnings[0]


def test_no_document_or_image_bytes_retained():
    raw = fixture_bytes("S2_image_only_infographic.docx")
    result = inspect_visual_manifest("infographic.docx", raw)
    assert not any(isinstance(x, bytes) for x in vars(result).values())
    assert not any(isinstance(x, bytes) for item in result.candidates for x in vars(item).values())
    assert not hasattr(result, "data") and not hasattr(result.candidates[0], "blob")


def test_pdf_visual_page_limit_rejects_without_partial_manifest():
    with pymupdf.open() as pdf:
        # Eleven image-only pages, using a tiny synthetic PNG kept local.
        png = fixture_bytes("infographic.png")
        for _ in range(11):
            page = pdf.new_page()
            page.insert_image(page.rect, stream=png)
        raw = pdf.tobytes()
    with pytest.raises(VisualManifestError, match="10 visual-page"):
        inspect_visual_manifest("eleven.pdf", raw)


def test_docx_image_occurrence_limit_rejects():
    doc = WordDocument()
    image = FIXTURES / "infographic.png"
    for _ in range(11):
        doc.add_picture(str(image), width=Inches(1.0))
    buffer = BytesIO()
    doc.save(buffer)
    with pytest.raises(VisualManifestError, match="10-image"):
        inspect_visual_manifest("many.docx", buffer.getvalue())


def test_docx_repeated_media_is_numbered_by_occurrence():
    doc = WordDocument()
    image = FIXTURES / "infographic.png"
    doc.add_picture(str(image), width=Inches(1))
    doc.add_picture(str(image), width=Inches(1))
    buf = BytesIO()
    doc.save(buf)
    result = inspect_visual_manifest("twice.docx", buf.getvalue())
    assert [i.docx_image_ordinal for i in result.candidates] == [1, 2]
    assert [i.source_id for i in result.candidates] == ["docx_image_1", "docx_image_2"]
    assert result.candidates[0].media_path == result.candidates[1].media_path


@pytest.mark.parametrize("filename,raw", [
    ("invalid.csv", b"x"), ("invalid.pdf", b"not a PDF"),
    ("bad.docx", b"not a ZIP"), ("blank.txt", b""),
])
def test_invalid_inputs_fail_closed(filename, raw):
    with pytest.raises(VisualManifestError):
        inspect_visual_manifest(filename, raw)


def test_upload_maximum_enforced():
    with pytest.raises(VisualManifestError, match="20 MB"):
        inspect_visual_manifest("big.txt", b"x" * (20 * 1024 * 1024 + 1))
