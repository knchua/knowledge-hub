"""P4 regression: existing logout/reset removes password-reauth UI state.
No global import replacement; monkeypatches restored automatically by pytest.
"""
from services import session_service as session
from services import document_analysis_service as analysis


def test_clear_session_removes_p3_flags_and_auth_state(monkeypatch):
    state = {
        session.SESSION_ACCESS_TOKEN: 'synthetic-access',
        session.SESSION_REFRESH_TOKEN: 'synthetic-refresh',
        session.SESSION_USER_ID: 'synthetic-user',
        session.SESSION_EMAIL: 'user@example.test',
        'p3_reauthentication_required': True,
        'p3_reauthentication_owner': 'synthetic-user',
        'phase3_chat_owner': 'synthetic-user',
        'phase3_chat_turns': [],
        'phase4_sample': 'temp',
        'phase5_sample': 'temp',
        'unrelated_setting': 'keep',
    }
    monkeypatch.setattr(session.st, 'session_state', state)
    monkeypatch.setattr(analysis, 'clear_document', lambda *args, **kwargs: None)
    session.clear_session()
    assert 'p3_reauthentication_required' not in state
    assert 'p3_reauthentication_owner' not in state
    for key in (session.SESSION_ACCESS_TOKEN, session.SESSION_REFRESH_TOKEN,
                session.SESSION_USER_ID, session.SESSION_EMAIL,
                'phase3_chat_owner', 'phase3_chat_turns',
                'phase4_sample', 'phase5_sample'):
        assert key not in state
    assert state['unrelated_setting'] == 'keep'
