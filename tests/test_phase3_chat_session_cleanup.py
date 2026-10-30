"""Phase 3 / Milestone 4 logout and session isolation regression tests."""
from unittest.mock import patch

from services import session_service


def test_clear_session_removes_auth_and_chat_history():
    state = {
        session_service.SESSION_ACCESS_TOKEN: "test-access",
        session_service.SESSION_REFRESH_TOKEN: "test-refresh",
        session_service.SESSION_USER_ID: "user-a",
        session_service.SESSION_EMAIL: "test@example.invalid",
        "phase3_chat_owner": "user-a",
        "phase3_chat_turns": [object()],
        "unrelated_ui_preference": "preserve-me",
    }
    with patch.object(session_service.st, "session_state", state):
        session_service.clear_session()

    assert session_service.SESSION_ACCESS_TOKEN not in state
    assert session_service.SESSION_REFRESH_TOKEN not in state
    assert session_service.SESSION_USER_ID not in state
    assert session_service.SESSION_EMAIL not in state
    assert "phase3_chat_owner" not in state
    assert "phase3_chat_turns" not in state
    assert state["unrelated_ui_preference"] == "preserve-me"


def test_clear_session_accepts_missing_chat_state():
    state = {}
    with patch.object(session_service.st, "session_state", state):
        session_service.clear_session()
    assert state == {}
