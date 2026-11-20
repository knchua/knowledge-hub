"""Phase 5 M3.5 Gate 1: local-only cross-service acceptance.

All evidence and model outputs are synthetic, scripted and in-memory. These tests
make no network/API/database calls. Passing them validates contracts and safeguards,
NOT independent live-model factual correctness or OpenAI charges.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import services.summarisation_service as summary
import services.document_qa_service as qa
import services.document_qa_history_service as history
from services.document_evidence_service import select_document_evidence, EvidenceSelectionError
from services.document_source_format_service import format_source_blocks
from services.temporary_document_service import TemporaryDocument, TemporarySegment


def segment(i, text, *, origin='native_text', page=None, image_id=None,
            ordinal=None, body_block=None, warnings=()):
    return TemporarySegment(
        i, text, page, origin=origin, image_id=image_id,
        docx_image_ordinal=ordinal, docx_body_block=body_block,
        extraction_warnings=tuple(warnings),
    )


def document(name, *parts, user='owner-a', doc_id=None):
    ext = '.docx' if name.endswith('.docx') else '.pdf' if name.endswith('.pdf') else '.txt'
    return TemporaryDocument(
        document_id=doc_id or name, owner_user_id=user, filename=name,
        extension=ext, size_bytes=100,
        character_count=sum(len(x.text) for x in parts),
        page_count=2 if ext == '.pdf' else None,
        segments=tuple(parts), warnings=(),
    )


@pytest.fixture
def s1():
    return document(
        'S1_scanned_two_page.pdf',
        segment(0, 'Site: North Annex. Inspection date: 14 October 2026. Fire exits checked: 4. Action: Replace 2 damaged exit signs.', origin='ocr_text', page=1, image_id='pdf_page_1'),
        segment(1, 'The scanned checklist contains site, date, exits and action fields.', origin='vision_description', page=1, image_id='pdf_page_1'),
        segment(2, 'Owner: Facilities Team. Deadline: 21 October 2026. Risk: Blocked access during delivery hours. Status: Pending replacement of 2 signs.', origin='ocr_text', page=2, image_id='pdf_page_2'),
        segment(3, 'The page depicts a maintenance checklist with risk and status fields.', origin='vision_description', page=2, image_id='pdf_page_2'),
    )


@pytest.fixture
def s2():
    return document(
        'S2_image_only_infographic.docx',
        segment(0, 'REQUEST APPROVAL WORKFLOW: Submit request -> Manager review -> Approve or reject. Target turnaround: 3 working days. Escalation only after review.', origin='ocr_text', image_id='docx_image_1', ordinal=1, body_block=2),
        segment(1, 'Three boxes connected left to right by arrows: Submit request, Manager review, then Approve or reject.', origin='vision_description', image_id='docx_image_1', ordinal=1, body_block=2),
    )


@pytest.fixture
def s3():
    return document(
        'S3_mixed_chart_ocr_layer.pdf',
        segment(0, 'Operations update: The support team reviewed quarterly resolution trends.', origin='native_text', page=1),
        segment(1, 'Quarterly cases resolved: Q1 40; Q2 60; Q3 55.', origin='ocr_text', page=1, image_id='pdf_page_1'),
        segment(2, 'Bar chart Q1 40, Q2 60, Q3 55. Q2 highest; Q3 below Q2 but above Q1.', origin='vision_description', page=1, image_id='pdf_page_1'),
        segment(3, 'Owner: Facilities Team. Deadline: 21 October 2026.', origin='native_text', page=2),
        segment(4, 'Risk: Blocked access during delivery hours. Status: Pending replacement of 2 signs.', origin='ocr_text', page=2, image_id='pdf_page_2'),
    )


class FakeLLM:
    def __init__(self, *answers, on_call=None):
        self._answers = iter(answers)
        self.messages = []
        self.on_call = on_call

    def invoke(self, messages):
        self.messages.append(messages)
        if self.on_call:
            self.on_call()
        return SimpleNamespace(content=next(self._answers))


def qa_session(monkeypatch, doc, *responses, on_call=None):
    active = {'doc': doc}
    state = {}
    monkeypatch.setattr(qa, 'current_document', lambda st, actor: active['doc'])
    monkeypatch.setattr(history, 'current_document', lambda st, actor: active['doc'])
    model = FakeLLM(*responses, on_call=on_call)
    monkeypatch.setattr(qa, '_model', lambda tokens: model)
    return state, active, model


def fake_summary(monkeypatch, *outputs):
    """Capture the real prompt-chain arguments while replacing the model.

    Fake chain works with both the full Phase 4+M3.3 summariser and the
    isolated contract shim. It never invokes ChatOpenAI.
    """
    from langchain_core.prompts import ChatPromptTemplate
    sent = []
    replies = iter(outputs)
    monkeypatch.setattr(summary, '_model', lambda tokens: object())

    class FakePrompt:
        def __or__(self, model):
            class FakeChain:
                def invoke(self, variables):
                    sent.append((variables['task'], variables['content'], None))
                    return SimpleNamespace(content=next(replies))
            return FakeChain()

    monkeypatch.setattr(ChatPromptTemplate, 'from_messages', lambda messages: FakePrompt())
    return sent


@pytest.mark.parametrize('mode', ['Concise', 'Detailed', 'Structured'])
def test_s1_summary_three_modes_preserve_citations_and_ocr(monkeypatch, s1, mode):
    sent = fake_summary(monkeypatch, 'North Annex checked 4 exits; replace 2 signs [P1]. Facilities Team owns the action, due 21 October 2026 [P3].')
    result = summary.generate_summary(s1, mode)
    assert result.mode == mode and result.model_calls == 1
    assert result.source_segments == (0, 2)
    assert 'Extraction: ocr_text' in sent[0][1]
    assert 'PDF page 2' in sent[0][1]
    assert '[P1]' in sent[0][1] and '[P3]' in sent[0][1]


def test_s2_summary_preserves_word_ordinal_and_workflow(monkeypatch, s2):
    sent = fake_summary(monkeypatch, 'Submit request, then manager review, then approve or reject. Target 3 working days; escalation after review [P1][P2].')
    result = summary.generate_summary(s2, 'Detailed')
    assert result.source_segments == (0, 1)
    assert 'Word image 1, body block 2' in sent[0][1]
    assert 'Extraction: vision_description' in sent[0][1]
    assert 'PDF page' not in sent[0][1]


def test_s3_summary_chart_numbers_and_native_context(monkeypatch, s3):
    sent = fake_summary(monkeypatch, 'Operations review shows Q1 40, Q2 60 and Q3 55, peaking in Q2 [P1][P2][P3].')
    result = summary.generate_summary(s3, 'Concise')
    assert result.source_segments == (0, 1, 2)
    assert 'Extraction: native_text' in sent[0][1]
    assert 'Extraction: vision_description' in sent[0][1]


def test_summary_warning_is_present_in_prompt(monkeypatch):
    d = document('ambiguous.pdf', segment(0, 'Q3 label unreadable on chart.', page=1, origin='vision_description', warnings=('Exact Q3 number cannot be read',)))
    sent = fake_summary(monkeypatch, 'The exact Q3 value is unreadable [P1].')
    result = summary.generate_summary(d, 'Concise')
    assert result.source_segments == (0,)
    assert 'Exact Q3 number cannot be read' in sent[0][1]
    assert 'untrusted' in sent[0][1].lower()


def test_summary_multi_batch_reduction_retains_source_labels_and_warnings(monkeypatch):
    d = document('uncertain.pdf', segment(0, 'Inspection complete.', page=1, origin='native_text'),
                 segment(1, 'Graph value not legible.', page=2, origin='vision_description', warnings=('Q4 unreadable',)))
    monkeypatch.setattr(summary, '_group_segments', lambda doc, budget: [[doc.segments[0]], [doc.segments[1]]])
    sent = fake_summary(monkeypatch, 'Inspection complete [P1].', 'Q4 unreadable [P2].',
                        'Inspection complete [P1]; Q4 remains unreadable [P2].')
    result = summary.generate_summary(d, 'Detailed')
    assert result.model_calls == 3 and result.source_segments == (0, 1)
    assert 'Q4 unreadable' in sent[1][1] and 'Q4 unreadable' in sent[2][1]
    assert '[P1]' in sent[0][1] and '[P2]' not in sent[0][1]
    assert '[P2]' in sent[1][1] and '[P1]' not in sent[1][1]


def test_summary_rejects_missing_citations_even_with_mock(monkeypatch, s1):
    fake_summary(monkeypatch, 'Unsupported claim without sources')
    # The application's actual citation repair/exception contract must fail closed.
    with pytest.raises(summary.SummarisationError):
        summary.generate_summary(s1, 'Concise')


def test_s1_qa_owner_and_deadline_with_original_segment(monkeypatch, s1):
    state, _, model = qa_session(monkeypatch, s1, 'Facilities Team, due 21 October 2026 [P3].')
    result = history.ask_and_record(state, object(), 'Who owns the action and when is the deadline?')
    assert [x.label for x in result.cited_evidence] == ['P3']
    assert result.cited_evidence[0].page_number == 2
    assert 'PDF page 2' in model.messages[0][1].content
    assert len(history.read_qa_history(state, object())) == 1


def test_s1_qa_fire_exit_count(monkeypatch, s1):
    state, _, _ = qa_session(monkeypatch, s1, 'Four exits were checked [P1].')
    result = history.ask_and_record(state, object(), 'How many fire exits were checked?')
    assert result.model_calls == 1 and result.cited_evidence[0].origin == 'ocr_text'


def test_s2_qa_word_image_location_and_flow(monkeypatch, s2):
    state, _, model = qa_session(monkeypatch, s2, 'Submit, review, then approve/reject; 3 working days [P1][P2].')
    result = history.ask_and_record(state, object(), 'What is the approval workflow and turnaround?')
    assert result.cited_evidence[1].docx_image_ordinal == 1
    assert 'Word image 1, body block 2' in model.messages[0][1].content


def test_s3_qa_chart_value_and_citation(monkeypatch, s3):
    state, _, _ = qa_session(monkeypatch, s3, 'Q2 is 60, compared to Q1 40 and Q3 55 [P2][P3].')
    result = history.ask_and_record(state, object(), 'What are the chart values by quarter?')
    assert [i.label for i in result.cited_evidence] == ['P2', 'P3']
    assert result.cited_evidence[0].page_number == 1


def test_ambiguous_visual_qa_abstains(monkeypatch):
    d = document('ambiguous.pdf', segment(0, 'One value is unreadable.', page=1, origin='vision_description', warnings=('Q3 exact number unreadable',)))
    state, _, model = qa_session(monkeypatch, d, qa.ABSTENTION)
    result = history.ask_and_record(state, object(), 'What is the exact Q3 value?')
    assert result.abstained and result.cited_evidence == ()
    assert 'Q3 exact number unreadable' in model.messages[0][1].content


def test_qa_foreign_citation_never_saved(monkeypatch, s1):
    state, _, model = qa_session(monkeypatch, s1, 'Wrong [P999].', 'Wrong [P999].')
    with pytest.raises(qa.DocumentQAError):
        history.ask_and_record(state, object(), 'Who owns the action?')
    assert history.read_qa_history(state, object()) == ()
    assert len(model.messages) <= 2


def test_qa_retry_budget_is_respected(monkeypatch, s1):
    state, _, model = qa_session(monkeypatch, s1, 'Invalid [P999].', 'Facilities Team [P3].')
    result = history.ask_and_record(state, object(), 'Who owns the action?')
    assert result.model_calls == 2 and len(model.messages) == 2


def test_retrieval_actual_formatted_budget(monkeypatch, s3):
    monkeypatch.setenv('KH_QA_MAX_EVIDENCE_CHARS', '500')
    monkeypatch.setenv('KH_QA_MAX_EVIDENCE_SEGMENTS', '2')
    selected = select_document_evidence(s3, 'What are the chart values?')
    if selected.items:
        complete = format_source_blocks(selected.items, max_chars=500)
        assert len(complete) == selected.total_evidence_chars <= 500


def test_duplicate_pair_does_not_consume_both_lexical_slots(monkeypatch):
    d = document('duplicate.pdf',
        segment(0, 'Site North Annex exits four', page=1, origin='ocr_text'),
        segment(1, 'Site North Annex exits four', page=1, origin='vision_description'),
        segment(2, 'Site North Annex replace signs', page=2, origin='ocr_text'))
    monkeypatch.setenv('KH_QA_MAX_EVIDENCE_SEGMENTS', '2')
    selected = select_document_evidence(d, 'Site North Annex exits?')
    assert not ({'P1', 'P2'} <= selected.allowed_labels)


def test_source_order_after_retrieval(monkeypatch, s3):
    monkeypatch.setenv('KH_QA_MAX_EVIDENCE_SEGMENTS', '2')
    selected = select_document_evidence(s3, 'Q1 Q2 Q3 chart?')
    assert [i.index for i in selected.items] == sorted(i.index for i in selected.items)
    assert all(i.label == f'P{i.index + 1}' for i in selected.items)


def test_invalid_metadata_fails_before_model(monkeypatch):
    d = document('invalid.pdf', segment(0, 'Q3 unreadable', page=1, origin='vision_description', warnings=('x'*501,)))
    state, _, _ = qa_session(monkeypatch, d, 'Claim [P1].')
    with pytest.raises((EvidenceSelectionError, qa.DocumentQAError)):
        history.ask_and_record(state, object(), 'What is Q3?')
    assert history.read_qa_history(state, object()) == ()


def test_document_swap_during_answer_discards_history(monkeypatch, s1, s2):
    state, active, model = qa_session(monkeypatch, s1, 'Facilities Team [P3].')
    model.on_call = lambda: active.__setitem__('doc', s2)
    with pytest.raises(qa.DocumentQAError, match='changed'):
        history.ask_and_record(state, object(), 'Who owns the action?')
    assert history.read_qa_history(state, object()) == ()


def test_identity_change_invalidates_history(monkeypatch, s1):
    state, active, _ = qa_session(monkeypatch, s1, 'Four [P1].')
    history.ask_and_record(state, object(), 'How many fire exits?')
    active['doc'] = replace(s1, owner_user_id='different-owner')
    assert history.read_qa_history(state, object()) == ()


def test_clear_history_does_not_delete_document(monkeypatch, s1):
    state, active, _ = qa_session(monkeypatch, s1, 'Four [P1].')
    history.ask_and_record(state, object(), 'How many fire exits?')
    history.clear_qa_history(state, object())
    assert history.read_qa_history(state, object()) == ()
    assert active['doc'] is s1


def test_legacy_plain_text_qa(monkeypatch):
    d = document('legacy.txt', segment(0, 'A-05 belongs to Farah Aziz.', origin='native_text'))
    state, _, model = qa_session(monkeypatch, d, 'Farah Aziz owns A-05 [P1].')
    result = history.ask_and_record(state, object(), 'Who owns A-05?')
    assert result.retrieval_strategy == 'full_context'
    assert 'Extraction: native_text' in model.messages[0][1].content


def test_summary_invalid_provenance_fails_before_model(monkeypatch):
    d = document('invalid.pdf', segment(0, 'Unclear diagram', page=1, origin='vision_description', warnings=('x'*501,)))
    monkeypatch.setattr(summary, '_model', lambda tokens: pytest.fail('No model call for invalid metadata'))
    with pytest.raises(summary.SummarisationError):
        summary.generate_summary(d, 'Concise')


def test_qa_no_retrieval_match_uses_zero_calls(monkeypatch):
    d = document('legacy.txt', segment(0, 'alpha orange'), segment(1, 'beta grape'))
    monkeypatch.setenv('KH_QA_MAX_EVIDENCE_SEGMENTS', '1')
    state, _, _ = qa_session(monkeypatch, d)
    result = history.ask_and_record(state, object(), 'zeppelin whereabouts?')
    assert result.abstained and result.model_calls == 0
    assert result.text == qa.ABSTENTION


def test_model_failure_does_not_expose_source_or_append_history(monkeypatch, s1):
    state, _, model = qa_session(monkeypatch, s1)
    def failure(messages):
        raise RuntimeError('SECRET_PRIVATE_DOCUMENT_TEXT')
    model.invoke = failure
    with pytest.raises(qa.DocumentQAError) as caught:
        history.ask_and_record(state, object(), 'Who owns the action?')
    assert 'SECRET_PRIVATE_DOCUMENT_TEXT' not in str(caught.value)
    assert history.read_qa_history(state, object()) == ()


def test_authorisation_rejection_clears_history(monkeypatch, s1):
    state, _, _ = qa_session(monkeypatch, s1, 'Four [P1].')
    history.ask_and_record(state, object(), 'How many fire exits?')
    from services.document_analysis_service import DocumentAccessError
    def denied(state, actor):
        raise DocumentAccessError('Expired login')
    monkeypatch.setattr(history, 'current_document', denied)
    with pytest.raises(DocumentAccessError):
        history.read_qa_history(state, object())
    assert not state.get(history.QA_HISTORY)
