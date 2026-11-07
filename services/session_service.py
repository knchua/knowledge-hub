"""Streamlit session-state helpers for Knowledge Hub."""

import streamlit as st
from services.auth_service import AuthenticatedSession

SESSION_ACCESS_TOKEN = "auth_access_token"
SESSION_REFRESH_TOKEN = "auth_refresh_token"
SESSION_USER_ID = "auth_user_id"
SESSION_EMAIL = "auth_email"
SESSION_RECOVERY_MODE = "auth_recovery_mode"
SESSION_INVITE_MODE = "auth_invite_mode"


def store_session(session: AuthenticatedSession) -> None:
    """Store authenticated session values in Streamlit session state."""
    # A new authenticated identity must not inherit a prior user's Phase 4 data.
    if st.session_state.get(SESSION_USER_ID) not in (None, session.user_id):
        from services.document_analysis_service import clear_document
        clear_document(st.session_state, keep_owner=False)
    st.session_state[SESSION_ACCESS_TOKEN] = session.access_token
    st.session_state[SESSION_REFRESH_TOKEN] = session.refresh_token
    st.session_state[SESSION_USER_ID] = session.user_id
    st.session_state[SESSION_EMAIL] = session.email


def clear_session() -> None:
    """Remove authentication, Phase 3 chat and temporary Phase 4 state."""
    from services.document_analysis_service import clear_document
    clear_document(st.session_state, keep_owner=False)
    # Clear any Phase 4 state introduced in future milestones, without touching other features.
    for key in list(st.session_state.keys()):
        if key.startswith("phase4_"):
            st.session_state.pop(key, None)
    for key in (
        SESSION_ACCESS_TOKEN,
        SESSION_REFRESH_TOKEN,
        SESSION_USER_ID,
        SESSION_EMAIL,
        SESSION_RECOVERY_MODE,
        SESSION_INVITE_MODE,
        "phase3_chat_owner",
        "phase3_chat_turns",
    ):
        st.session_state.pop(key, None)


def get_stored_tokens() -> tuple[str | None, str | None]:
    return (
        st.session_state.get(SESSION_ACCESS_TOKEN),
        st.session_state.get(SESSION_REFRESH_TOKEN),
    )


def has_stored_session() -> bool:
    access_token, refresh_token = get_stored_tokens()
    return bool(access_token and refresh_token)


def set_recovery_mode(enabled: bool) -> None:
    st.session_state[SESSION_RECOVERY_MODE] = enabled


def is_recovery_mode() -> bool:
    return st.session_state.get(SESSION_RECOVERY_MODE, False)


def set_invite_mode(enabled: bool) -> None:
    st.session_state[SESSION_INVITE_MODE] = enabled


def is_invite_mode() -> bool:
    return st.session_state.get(SESSION_INVITE_MODE, False)
