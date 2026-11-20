"""Phase 5 M2.4 deterministic tests; no network, database, or Streamlit session."""
from dataclasses import replace

import pytest

from services.temporary_document_service import TemporarySegment
from services.visual_extraction_manifest_service import VisualCandidate, VisualManifest
from services.visual_provider_service import VisualEvidence
from services.visual_evidence_merge_service import (
    NativeEvidenceBlock, VisualMergeError, merge_visual_evidence,
)


def manifest(ext, candidates=(), pages=None, name=None, size=100):
    filename = name or f"fixture{ext}"
    return VisualManifest(filename, ext, size, pages, tuple(candidates))


def pdf_candidate(number, reason="image_only_or_visual_page"):
    return VisualCandidate(f"pdf_page_{number}", "pdf_page", reason, pdf_page=number)


def docx_candidate(number, block=1):
    return VisualCandidate(f"docx_image_{number}", "docx_image", "embedded_image",
                           docx_image_ordinal=number, docx_body_block=block)


def visual(source_id, text="", description="", warnings=(), unreadable=()):
    return VisualEvidence(source_id, text, description, tuple(unreadable), tuple(warnings),
                          1000, 100, 0.001, 0.4, 1024, 768)


def build(m, native=(), visions=(), owner="user-a"):
    return merge_visual_evidence(owner_user_id=owner, manifest=m,
                                 native_blocks=tuple(native), visual_evidence=tuple(visions))


def test_legacy_temporary_segment_constructor_is_compatible():
    segment = TemporarySegment(0, "Legacy evidence", None)
    assert segment.origin == "native_text"
    assert segment.image_id is None and segment.extraction_warnings == ()


def test_scanned_pdf_two_pages_keep_physical_locations():
    m = manifest(".pdf", [pdf_candidate(1), pdf_candidate(2)], pages=2)
    doc = build(m, visions=[
        visual("pdf_page_1", "Fire exits checked: 4"),
        visual("pdf_page_2", "Owner: Facilities Team"),
    ])
    assert [s.text for s in doc.segments] == ["Fire exits checked: 4", "Owner: Facilities Team"]
    assert [s.page_number for s in doc.segments] == [1, 2]
    assert [s.index for s in doc.segments] == [0, 1]
    assert [s.origin for s in doc.segments] == ["ocr_text", "ocr_text"]
    assert [s.image_id for s in doc.segments] == ["pdf_page_1", "pdf_page_2"]
    assert doc.page_count == 2 and doc.owner_user_id == "user-a"


def test_docx_infographic_no_fabricated_word_pages():
    m = manifest(".docx", [docx_candidate(1, block=2)])
    doc = build(m, [NativeEvidenceBlock("Introduction", docx_body_block=1)],
                [visual("docx_image_1", "Approve or reject", "Three boxes joined by arrows")])
    assert [s.origin for s in doc.segments] == ["native_text", "ocr_text", "vision_description"]
    assert all(s.page_number is None for s in doc.segments)
    assert doc.segments[1].docx_image_ordinal == 1
    assert doc.segments[1].docx_body_block == 2
    assert doc.segments[2].image_id == "docx_image_1"


def test_mixed_pdf_preserves_native_and_extra_ocr_without_duplicate_lines():
    m = manifest(".pdf", [pdf_candidate(1, "embedded_visual")], pages=1)
    native = [NativeEvidenceBlock("Owner: Facilities Team | Deadline: 21 October 2026", pdf_page=1)]
    doc = build(m, native, [visual("pdf_page_1",
        "Owner: Facilities Team\nDeadline: 21 October 2026\nRisk: Blocked access",
        "The page contains a workflow diagram")])
    assert doc.segments[0].origin == "native_text"
    assert "Owner:" not in "\n".join(s.text for s in doc.segments if s.origin == "ocr_text")
    assert "Deadline:" not in "\n".join(s.text for s in doc.segments if s.origin == "ocr_text")
    assert any(s.text == "Risk: Blocked access" and s.origin == "ocr_text" for s in doc.segments)
    assert any(s.origin == "vision_description" for s in doc.segments)


def test_same_ocr_content_on_another_page_is_not_suppressed():
    m = manifest(".pdf", [pdf_candidate(2)], pages=2)
    doc = build(m, [NativeEvidenceBlock("Owner: Facilities Team", pdf_page=1)],
                [visual("pdf_page_2", "Owner: Facilities Team")])
    assert len(doc.segments) == 2
    assert doc.segments[1].origin == "ocr_text" and doc.segments[1].page_number == 2


def test_docx_native_and_two_images_ordered_by_body_location():
    m = manifest(".docx", [docx_candidate(1, 1), docx_candidate(2, 3)])
    doc = build(m, [NativeEvidenceBlock("Before image", docx_body_block=1),
                    NativeEvidenceBlock("Between images", docx_body_block=2)],
                [visual("docx_image_2", "Second image"), visual("docx_image_1", "First image")])
    assert [s.text for s in doc.segments] == ["Before image", "First image", "Between images", "Second image"]
    assert [s.index for s in doc.segments] == [0, 1, 2, 3]


def test_description_exactly_repeating_ocr_is_removed():
    m = manifest(".pdf", [pdf_candidate(1)], pages=1)
    doc = build(m, visions=[visual("pdf_page_1", "Four exits", "Four exits.")])
    assert len(doc.segments) == 1
    assert doc.segments[0].origin == "ocr_text"


def test_empty_visual_regions_add_warning_and_no_fake_content():
    m = manifest(".pdf", [pdf_candidate(1), pdf_candidate(2)], pages=2)
    doc = build(m, visions=[visual("pdf_page_1", "Readable", unreadable=("bottom right",))])
    assert len(doc.segments) == 1
    assert any("incomplete" in w.lower() for w in doc.warnings)
    assert any("could not be read" in w.lower() for w in doc.segments[0].extraction_warnings)
    assert all("bottom right" not in s.text for s in doc.segments)


def test_unlocated_word_text_warns_of_uncertain_order():
    m = manifest(".docx", [docx_candidate(1)])
    doc = build(m, [NativeEvidenceBlock("Native but unlocated")], [visual("docx_image_1", "Image")])
    assert any("order is uncertain" in x for x in doc.warnings)


def test_native_only_txt_preserves_default_provenance():
    doc = build(manifest(".txt"), [NativeEvidenceBlock("Ordinary TXT")])
    assert doc.segments[0].origin == "native_text"
    assert doc.segments[0].page_number is None


def test_missing_source_id_rejected():
    m = manifest(".pdf", [pdf_candidate(1)], pages=1)
    with pytest.raises(VisualMergeError, match="trusted manifest"):
        build(m, visions=[visual("pdf_page_99", "Forged")])


def test_duplicate_visual_source_rejected():
    m = manifest(".pdf", [pdf_candidate(1), pdf_candidate(2)], pages=2)
    with pytest.raises(VisualMergeError, match="Duplicate"):
        build(m, visions=[visual("pdf_page_1", "A"), visual("pdf_page_1", "B")])


def test_invalid_source_page_rejected():
    m = manifest(".pdf", [pdf_candidate(1)], pages=1)
    with pytest.raises(VisualMergeError, match="PDF source"):
        build(m, [NativeEvidenceBlock("Fake page", pdf_page=5)])


def test_invalid_manifest_location_rejected():
    m = manifest(".docx", [replace(docx_candidate(1), pdf_page=2)])
    with pytest.raises(VisualMergeError, match="Word visual"):
        build(m, visions=[visual("docx_image_1", "Image")])


def test_unreadable_only_without_any_content_rejected():
    m = manifest(".pdf", [pdf_candidate(1)], pages=1)
    with pytest.raises(VisualMergeError, match="No usable"):
        build(m, visions=[visual("pdf_page_1", unreadable=("Unclear value",))])


def test_text_budget_failure_is_closed(monkeypatch):
    monkeypatch.setenv("KH_ANALYSIS_MAX_TEXT_CHARS", "1000")
    m = manifest(".txt")
    with pytest.raises(VisualMergeError, match="text limit"):
        build(m, [NativeEvidenceBlock("x" * 1001)])


def test_max_segments_rejects_without_partial_document(monkeypatch):
    monkeypatch.setenv("KH_ANALYSIS_MAX_SEGMENTS", "1")
    doc = build(manifest(".txt"), [NativeEvidenceBlock("One")])
    assert len(doc.segments) == 1
    with pytest.raises(VisualMergeError, match="segment count"):
        build(manifest(".txt"), [NativeEvidenceBlock("One"), NativeEvidenceBlock("Two")])


def test_long_evidence_chunking_preserves_indices_and_origin(monkeypatch):
    monkeypatch.setenv("KH_ANALYSIS_SEGMENT_CHARS", "500")
    monkeypatch.setenv("KH_ANALYSIS_SEGMENT_OVERLAP", "0")
    m = manifest(".pdf", [pdf_candidate(1)], pages=1)
    doc = build(m, visions=[visual("pdf_page_1", "x" * 1100)])
    assert len(doc.segments) >= 2
    assert [s.index for s in doc.segments] == list(range(len(doc.segments)))
    assert all(s.origin == "ocr_text" and s.page_number == 1 for s in doc.segments)


def test_existing_document_id_changes_each_merge():
    m = manifest(".txt")
    a = build(m, [NativeEvidenceBlock("Hello")])
    b = build(m, [NativeEvidenceBlock("Hello")])
    assert a.document_id != b.document_id


def test_invalid_configuration_is_safe(monkeypatch):
    monkeypatch.setenv("KH_ANALYSIS_SEGMENT_OVERLAP", "not-an-int")
    with pytest.raises(VisualMergeError, match="configuration"):
        build(manifest(".txt"), [NativeEvidenceBlock("Hello")])

# Real M2.2 synthetic fixtures, with M2.3-style provider responses mocked.
# These are integration-style *local* tests of manifest -> merge; no API calls.
def _fixture(name):
    from pathlib import Path
    return (Path(__file__).resolve().parent / "fixtures" / "phase5" / name).read_bytes()


def test_s1_real_scanned_pdf_manifest_merges_two_pages():
    from services.visual_extraction_manifest_service import inspect_visual_manifest
    filename = "S1_scanned_two_page.pdf"
    m = inspect_visual_manifest(filename, _fixture(filename))
    d = build(m, visions=[
        visual("pdf_page_1", "Fire exits checked: 4"),
        visual("pdf_page_2", "Deadline: 21 October 2026"),
    ])
    assert len(d.segments) == 2
    assert [s.page_number for s in d.segments] == [1, 2]


def test_s2_real_docx_manifest_merges_image_without_word_page():
    from services.visual_extraction_manifest_service import inspect_visual_manifest
    filename = "S2_image_only_infographic.docx"
    m = inspect_visual_manifest(filename, _fixture(filename))
    d = build(m, visions=[visual("docx_image_1", "Target turnaround: 3 working days",
                                 "Submit request -> Manager review -> Approve or reject")])
    assert d.segments and all(s.page_number is None for s in d.segments)
    assert all(s.docx_image_ordinal == 1 for s in d.segments)


def test_s3_real_mixed_pdf_manifest_preserves_chart_and_deduplicates_native():
    from services.visual_extraction_manifest_service import inspect_visual_manifest
    filename = "S3_mixed_chart_ocr_layer.pdf"
    m = inspect_visual_manifest(filename, _fixture(filename))
    d = build(m, native=[
        NativeEvidenceBlock("The chart below reports resolved cases per quarter.", pdf_page=1),
        NativeEvidenceBlock("Owner: Facilities Team | Deadline: 21 October 2026", pdf_page=2),
    ], visions=[
        visual("pdf_page_1", "The chart below reports resolved cases per quarter.",
               "Q1 40 cases, Q2 60 cases, Q3 55 cases"),
        visual("pdf_page_2", "Owner: Facilities Team\nDeadline: 21 October 2026\nRisk: Blocked access"),
    ])
    assert len([s for s in d.segments if s.origin == "ocr_text" and s.page_number == 1]) == 0
    assert any(s.origin == "vision_description" and "Q2 60" in s.text for s in d.segments)
    assert any(s.origin == "ocr_text" and "Risk: Blocked access" in s.text for s in d.segments)
    assert all("Owner: Facilities Team" not in s.text for s in d.segments if s.origin == "ocr_text")
