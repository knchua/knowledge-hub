"""M3.3 deterministic checks: no live provider calls or persistence."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from services.temporary_document_service import TemporaryDocument, TemporarySegment
from services.summarisation_service import (
    _batch_text, _group_segments, _extract_labels, _quality_issues,
    generate_summary, SummarisationError, SYSTEM,
)
from services.document_source_format_service import format_source_block


def document(*segments):
    return TemporaryDocument(
        document_id='m33', owner_user_id='test-user', filename='synthetic.pdf',
        extension='.pdf', size_bytes=100, character_count=sum(len(s.text) for s in segments),
        page_count=2, segments=tuple(segments), warnings=(),
    )


def seg(i, text, origin='native_text', page=None, warnings=(), ordinal=None, block=None):
    return TemporarySegment(
        i, text, page, origin=origin,
        docx_image_ordinal=ordinal, docx_body_block=block,
        extraction_warnings=warnings,
    )


class Pipeline:
    def __init__(self, replies, messages):
        self.replies = replies
        self.messages = messages

    def __or__(self, model):
        parent = self
        class Chain:
            def invoke(self, variables):
                parent.messages.append(variables)
                return SimpleNamespace(content=parent.replies.pop(0))
        return Chain()


def mocked_model(replies, messages):
    from langchain_core.prompts import ChatPromptTemplate
    return (
        patch('services.summarisation_service._model', return_value=object()),
        patch.object(ChatPromptTemplate, 'from_messages', return_value=Pipeline(replies, messages)),
    )


def test_page_and_origin_are_formatted():
    result = _batch_text([seg(0, 'Fire exits checked: 4', 'ocr_text', 1)])
    assert '[P1]' in result and 'PDF page 1' in result
    assert 'Extraction: ocr_text' in result and 'Fire exits checked: 4' in result


def test_visual_is_identified_as_model_interpretation():
    result = _batch_text([seg(1, 'Arrows run left to right', 'vision_description', 1)])
    assert '[P2]' in result and 'Model-generated visual interpretation' in result


def test_word_image_source_has_no_invented_page_number():
    result = _batch_text([seg(0,'Manager review then approve','vision_description',None,ordinal=1,block=2)])
    assert 'Word image 1, body block 2' in result and 'PDF page' not in result


def test_uncertainty_warning_reaches_prompt():
    result = _batch_text([seg(0,'Chart values are unclear','vision_description',1,('Q2 label unreadable',))])
    assert 'Q2 label unreadable' in result
    assert 'untrusted' in result.lower()


def test_no_warning_does_not_prove_confidence():
    assert 'not a confidence guarantee' in _batch_text([seg(0,'40 cases','ocr_text',1)])


def test_legacy_segment_constructor_remains_supported():
    item = TemporarySegment(0,'Plain text segment',None)
    result = _batch_text([item])
    assert 'native_text' in result and '[P1]' in result


def test_exact_formatted_size_can_fill_one_group():
    s1 = seg(0,'Alpha decision','native_text',1)
    s2 = seg(1,'Beta decision','native_text',2)
    doc = document(s1,s2)
    size = len(format_source_block(s1)) + len(format_source_block(s2)) + 2
    assert _group_segments(doc,size) == [[s1,s2]]


def test_one_char_short_forces_two_batches():
    s1 = seg(0,'Alpha decision','native_text',1)
    s2 = seg(1,'Beta decision','native_text',2)
    size = len(format_source_block(s1)) + len(format_source_block(s2)) + 2
    assert _group_segments(document(s1,s2),size - 1) == [[s1],[s2]]


def test_warning_metadata_is_included_in_actual_batch_size():
    s1=seg(0,'First','ocr_text',1)
    s2=seg(1,'Second','ocr_text',2,('Control characters replaced',))
    size = len(format_source_block(s1)) + len(format_source_block(s2)) + 2
    assert len(_group_segments(document(s1,s2),size - 1)) == 2


def test_oversized_segment_rejected_before_model_call():
    item=seg(0,'A'*12001,'ocr_text',1)
    with patch('services.summarisation_service._model') as model:
        with pytest.raises(SummarisationError, match='metadata'):
            generate_summary(document(item),'Concise')
        model.assert_not_called()


def test_oversized_warning_rejected_before_model_call():
    item=seg(0,'Valid content','vision_description',1,('X'*501,))
    with patch('services.summarisation_service._model') as model:
        with pytest.raises(SummarisationError, match='metadata'):
            generate_summary(document(item),'Detailed')
        model.assert_not_called()


def test_formatted_segment_too_large_for_summary_context(monkeypatch):
    monkeypatch.setenv('KH_SUMMARY_CONTEXT_CHARS','2000')
    item=seg(0,'A'*1900,'ocr_text',1)
    with patch('services.summarisation_service._model') as model:
        with pytest.raises(SummarisationError, match='context limit'):
            generate_summary(document(item),'Concise')
        model.assert_not_called()


@pytest.mark.parametrize('mode', ['Concise','Detailed','Structured'])
def test_all_three_modes_keep_citations_and_source_metadata(mode):
    d=document(seg(0,'Owner: Facilities Team','ocr_text',2))
    seen=[]
    a,b=mocked_model(['Owner: Facilities Team. [P1]'],seen)
    with a,b:
        result=generate_summary(d,mode)
    assert result.source_segments == (0,) and result.model_calls == 1
    assert 'Extraction: ocr_text' in seen[0]['content']


def test_invalid_citation_still_rejected():
    with pytest.raises(SummarisationError, match='source references'):
        _extract_labels('Invented [P99]',{'P1'})


def test_model_call_budget_still_applies(monkeypatch):
    monkeypatch.setenv('KH_SUMMARY_MAX_CALLS','1')
    first=seg(0,'Alpha','ocr_text',1)
    second=seg(1,'Beta','ocr_text',2)
    with patch('services.summarisation_service._group_segments',return_value=[[first],[second]]), \
         patch('services.summarisation_service._model') as model:
        with pytest.raises(SummarisationError, match='budget'):
            generate_summary(document(first,second),'Detailed')
        model.assert_not_called()


def test_multibatch_tasks_carry_uncertainty_and_labels():
    a=seg(0,'Q1=40','vision_description',1)
    b=seg(1,'Q2 unreadable','vision_description',2,('Q2 value unreadable',))
    messages=[]
    m,p=mocked_model(['Q1 40 [P1]','Q2 unclear [P2]','Q1 40; Q2 uncertain [P1] [P2]'],messages)
    with patch('services.summarisation_service._group_segments',return_value=[[a],[b]]),m,p:
        result=generate_summary(document(a,b),'Detailed')
    assert result.source_segments == (0,1) and result.model_calls == 3
    assert 'material extraction uncertainty' in messages[0]['task']
    assert 'material extraction uncertainty' in messages[2]['task']
    assert 'Q2 value unreadable' in messages[1]['content']


def test_prompt_prohibits_duplicate_confirmations_and_guessed_values():
    assert 'independent confirmation' in SYSTEM
    assert 'do not' in SYSTEM.lower()
    assert 'unreadable' in SYSTEM.lower()
    assert 'untrusted data' in SYSTEM.lower()


def test_visual_details_do_not_disable_legacy_currency_validator():
    d=document(seg(0,'Budget S$100,000','native_text',1))
    assert 'Financial amount not present in source' in _quality_issues('Budget S$200,000 [P1]', 'Detailed', d)


def test_duplicate_or_invalid_source_index_rejected():
    with pytest.raises(SummarisationError,match='metadata'):
        _batch_text([seg(0,'a'),seg(0,'b')])


def test_oversized_merged_context_is_rejected_without_truncation():
    with pytest.raises(SummarisationError,match='metadata'):
        _batch_text([seg(i, 'X'*1000) for i in range(50)])
