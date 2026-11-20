"""M2.5 consent, actor, generation and transactional replacement tests; no APIs."""
from dataclasses import dataclass
from unittest.mock import patch, Mock

import pytest

from services.document_analysis_service import DOCUMENT, WIDGET_VERSION, DocumentAccessError
from services.phase5_visual_session_service import (
    PENDING, prepare_visual_attempt, visual_attempt_matches, replace_visual_document,
    discard_visual_attempt, configured_vision_budget,
)
from services.visual_document_processing_service import VisualProcessingError


@dataclass
class Actor:
    user_id: str = 'user-a'


def fixture():
    from pathlib import Path
    p = Path(__file__).parent / 'fixtures' / 'phase5' / 'S1_scanned_two_page.pdf'
    return p.name, p.read_bytes()


def verify(actor): return actor


def setup(monkeypatch):
    name, raw = fixture()
    state = {}
    monkeypatch.setattr('services.phase5_visual_session_service.verify_actor', verify)
    monkeypatch.setattr('services.phase5_visual_session_service.bind_owner', lambda state, uid: state.setdefault('phase4_owner', uid))
    manifest = prepare_visual_attempt(state, Actor(), name, raw)
    assert manifest.consent_required
    return state, name, raw


def test_prepare_is_local_only_and_stages_no_raw_bytes(monkeypatch):
    state, name, raw = setup(monkeypatch)
    assert visual_attempt_matches(state, name, raw)
    assert isinstance(state[PENDING]['fingerprint'], str)
    assert not any(isinstance(value, bytes) for value in state[PENDING].values())


def test_explicit_consent_required_before_provider(monkeypatch):
    state, name, raw = setup(monkeypatch)
    fake = Mock(side_effect=AssertionError('provider called'))
    with pytest.raises(DocumentAccessError, match='consent'):
        replace_visual_document(state, Actor(), name, raw, consent=False, vision_fn=fake)
    fake.assert_not_called()
    assert PENDING in state


def test_selected_file_changed_revokes_attempt(monkeypatch):
    state, name, raw = setup(monkeypatch)
    assert not visual_attempt_matches(state, name, raw + b'different')
    fake = Mock()
    with pytest.raises(DocumentAccessError, match='changed'):
        replace_visual_document(state, Actor(), name, raw + b'different', consent=True, vision_fn=fake)
    fake.assert_not_called()


def test_generation_change_rejects_old_consent(monkeypatch):
    state, name, raw = setup(monkeypatch)
    state[WIDGET_VERSION] = state.get(WIDGET_VERSION, 0) + 1
    with pytest.raises(DocumentAccessError, match='changed'):
        replace_visual_document(state, Actor(), name, raw, consent=True)


def test_cancel_without_document_clear(monkeypatch):
    state, name, raw = setup(monkeypatch)
    old = object()
    state[DOCUMENT] = old
    discard_visual_attempt(state)
    assert PENDING not in state and state[DOCUMENT] is old


def test_missing_configuration_fail_closed(monkeypatch):
    for key in ('KH_VISION_MAX_ESTIMATED_USD', 'KH_VISION_INPUT_PRICE_PER_MILLION_USD',
                'KH_VISION_OUTPUT_PRICE_PER_MILLION_USD'):
        monkeypatch.delenv(key, raising=False)
    with patch('services.phase5_visual_session_service._setting', return_value=''):
        with pytest.raises(DocumentAccessError, match='configured'):
            configured_vision_budget(2)


def configure(monkeypatch):
    monkeypatch.setenv('KH_VISION_MAX_ESTIMATED_USD', '.10')
    monkeypatch.setenv('KH_VISION_INPUT_PRICE_PER_MILLION_USD', '.40')
    monkeypatch.setenv('KH_VISION_OUTPUT_PRICE_PER_MILLION_USD', '1.60')


def test_success_commits_and_clears_old_analysis(monkeypatch):
    state, name, raw = setup(monkeypatch)
    configure(monkeypatch)
    old = object()
    state[DOCUMENT] = old
    state['phase4_results'] = {'old': 'summary'}
    state['phase4_qa_history'] = ('old',)
    new = object()
    def fake(**kwargs):
        kwargs['revalidate']()
        kwargs['revalidate']()
        return new
    with patch('services.phase5_visual_session_service.process_visual_document', side_effect=fake):
        result = replace_visual_document(state, Actor(), name, raw, consent=True)
    assert result is new and state[DOCUMENT] is new
    assert 'phase4_results' not in state and 'phase4_qa_history' not in state
    assert PENDING not in state


def test_failure_preserves_previous_document_but_expires_consent(monkeypatch):
    state, name, raw = setup(monkeypatch)
    configure(monkeypatch)
    old = object()
    state[DOCUMENT] = old
    with patch('services.phase5_visual_session_service.process_visual_document',
               side_effect=VisualProcessingError('provider failed')):
        with pytest.raises(VisualProcessingError):
            replace_visual_document(state, Actor(), name, raw, consent=True)
    assert state[DOCUMENT] is old
    assert PENDING not in state


def test_mid_call_generation_change_discard_without_overwrite(monkeypatch):
    state, name, raw = setup(monkeypatch)
    configure(monkeypatch)
    old = object()
    state[DOCUMENT] = old
    def fake(**kwargs):
        kwargs['revalidate']()
        state[WIDGET_VERSION] = state.get(WIDGET_VERSION, 0) + 1
        kwargs['revalidate']()
    with patch('services.phase5_visual_session_service.process_visual_document', side_effect=fake):
        with pytest.raises(DocumentAccessError, match='changed'):
            replace_visual_document(state, Actor(), name, raw, consent=True)
    assert state[DOCUMENT] is old


def test_user_switch_or_expired_token_clears_document(monkeypatch):
    state, name, raw = setup(monkeypatch)
    configure(monkeypatch)
    state[DOCUMENT] = object()
    def reject(actor): raise DocumentAccessError('unauthorised')
    monkeypatch.setattr('services.phase5_visual_session_service.verify_actor', reject)
    with pytest.raises(DocumentAccessError):
        replace_visual_document(state, Actor(), name, raw, consent=True)
    assert DOCUMENT not in state


def test_new_attempt_nonce_invalidates_old_consent(monkeypatch):
    state, name, raw = setup(monkeypatch)
    first = state[PENDING]['nonce']
    prepare_visual_attempt(state, Actor(), name, raw)
    assert first != state[PENDING]['nonce']
