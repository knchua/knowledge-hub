"""Phase 5 M2.5 deterministic end-to-end orchestration tests; NO real API calls."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from docx import Document
from io import BytesIO

from services.visual_extraction_manifest_service import inspect_visual_manifest
from services.visual_provider_service import VisionBudget, VisualEvidence
from services.visual_document_processing_service import (
    VisualProcessingError, process_visual_document, _render_pdf,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'phase5'


def raw(name):
    return (FIXTURES / name).read_bytes()


def budget(count=10, cap=.10):
    return VisionBudget(cap, .4, 1.6, max_calls=count)


def fake_vision(*, source_id, image_bytes, consent, budget, client=None):
    assert consent is True
    assert image_bytes.startswith(b'\x89PNG')
    return VisualEvidence(source_id, 'Visible text', 'Diagram with arrows', (), (),
                          1000, 100, .00056, .01, 1024, 768)


def run(name, **overrides):
    data = raw(name)
    m = inspect_visual_manifest(name, data)
    options = dict(owner_user_id='user-a', filename=name, data=data, manifest=m,
                   consent=True, budget=budget(), revalidate=lambda: None,
                   vision_fn=fake_vision)
    options.update(overrides)
    return process_visual_document(**options)


def test_s1_scanned_pdf_produces_two_pages_and_visual_provenance():
    doc = run('S1_scanned_two_page.pdf')
    assert doc.page_count == 2 and len(doc.segments) >= 4
    assert {s.page_number for s in doc.segments} == {1, 2}
    assert all(s.origin in ('ocr_text', 'vision_description') for s in doc.segments)


def test_s2_image_only_word_has_image_location_not_word_page():
    doc = run('S2_image_only_infographic.docx')
    assert doc.page_count is None
    assert all(s.page_number is None for s in doc.segments)
    assert all(s.docx_image_ordinal == 1 for s in doc.segments)
    assert all(s.docx_body_block is not None for s in doc.segments)


def test_s3_mixed_pdf_retains_native_and_visual():
    doc = run('S3_mixed_chart_ocr_layer.pdf')
    assert {s.origin for s in doc.segments} >= {'native_text', 'vision_description'}
    assert any('quarter' in s.text.lower() for s in doc.segments if s.origin == 'native_text')
    assert {s.page_number for s in doc.segments} == {1, 2}
    assert [s.index for s in doc.segments] == list(range(len(doc.segments)))


def test_no_consent_means_no_vision_or_native_processing():
    fake = Mock(side_effect=AssertionError('must not be called'))
    with pytest.raises(VisualProcessingError, match='consent'):
        run('S1_scanned_two_page.pdf', consent=False, vision_fn=fake)
    fake.assert_not_called()


def test_mismatched_document_rejected_before_first_api_call():
    data = raw('S1_scanned_two_page.pdf')
    m = inspect_visual_manifest('S1_scanned_two_page.pdf', data)
    fake = Mock(side_effect=AssertionError('must not be called'))
    with pytest.raises(VisualProcessingError, match='manifest'):
        run('S2_image_only_infographic.docx', manifest=m, vision_fn=fake)
    fake.assert_not_called()


def test_preflight_budget_rejection_makes_no_calls():
    fake = Mock(side_effect=AssertionError('must not be called'))
    with pytest.raises(VisualProcessingError, match='budget'):
        run('S1_scanned_two_page.pdf', budget=budget(cap=.0001), vision_fn=fake)
    fake.assert_not_called()


def test_not_enough_call_capacity_rejected_before_calls():
    fake = Mock(side_effect=AssertionError('must not be called'))
    with pytest.raises(VisualProcessingError, match='call limit'):
        run('S1_scanned_two_page.pdf', budget=budget(count=1), vision_fn=fake)
    fake.assert_not_called()


def test_failed_second_image_returns_no_partial_document():
    fake = Mock(side_effect=[fake_vision(source_id='pdf_page_1', image_bytes=_render_pdf(raw('S1_scanned_two_page.pdf'), 1),consent=True,budget=budget()), RuntimeError('provider')])
    with pytest.raises(VisualProcessingError):
        run('S1_scanned_two_page.pdf', vision_fn=fake)
    assert fake.call_count == 2


def test_wrong_source_id_rejected_before_another_call():
    wrong = VisualEvidence('wrong_source', 'text', '', (), (), 1, 1, 0.1, 0.1, 500, 500)
    fake = Mock(return_value=wrong)
    with pytest.raises(VisualProcessingError, match='source'):
        run('S1_scanned_two_page.pdf', vision_fn=fake)
    assert fake.call_count == 1


def test_revalidation_occurs_before_and_after_each_call():
    count = [0]
    def validate(): count[0] += 1
    run('S1_scanned_two_page.pdf', revalidate=validate)
    assert count[0] >= 7


def test_revalidation_failure_between_calls_prevents_second_call():
    class Cancellation(Exception): pass
    call = [0]
    fake = Mock(side_effect=fake_vision)
    def validate():
        call[0] += 1
        if call[0] >= 4: raise Cancellation('cancelled')
    with pytest.raises(VisualProcessingError):
        run('S1_scanned_two_page.pdf', revalidate=validate, vision_fn=fake)
    assert fake.call_count == 1


def test_pdf_renderer_outputs_bounded_png():
    png = _render_pdf(raw('S1_scanned_two_page.pdf'), 1)
    assert png.startswith(b'\x89PNG')
    with pytest.raises(VisualProcessingError, match='location'):
        _render_pdf(raw('S1_scanned_two_page.pdf'), 999)


def test_docx_image_occurrences_include_duplicate_relationships():
    # One image resource reused at two positions must be two separate sources.
    stream = BytesIO()
    doc = Document()
    image = str(FIXTURES / 'infographic.png')
    doc.add_picture(image)
    doc.add_paragraph('Between the two image occurrences')
    doc.add_picture(image)
    doc.save(stream)
    data = stream.getvalue()
    manifest = inspect_visual_manifest('twice.docx', data)
    assert [c.docx_image_ordinal for c in manifest.candidates] == [1, 2]
    output = process_visual_document(
        owner_user_id='user-a', filename='twice.docx', data=data,
        manifest=manifest, consent=True, budget=budget(),
        revalidate=lambda: None, vision_fn=fake_vision,
    )
    visuals = [s for s in output.segments if s.origin == 'ocr_text']
    assert [s.docx_image_ordinal for s in visuals] == [1, 2]
    assert any(s.origin == 'native_text' for s in output.segments)


def test_visual_processing_does_not_write_to_disk_or_supabase(monkeypatch):
    # Service has no network dependency other than the injected image provider.
    doc = run('S1_scanned_two_page.pdf')
    assert not hasattr(doc, 'raw_file') and not hasattr(doc, 'image_bytes')
