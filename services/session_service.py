"""Streamlit session-state helpers for Knowledge Hub."""

import streamlit as st

from services.auth_service import AuthenticatedSession


SESSION_ACCESS_TOKEN = "auth_access_token"
SESSION_REFRESH_TOKEN = "auth_refresh_token"
SESSION_USER_ID = "auth_user_id"
SESSION_EMAIL = "auth_email"


def store_session(session: AuthenticatedSession) -> None:
    """Store authenticated session values in Streamlit session state."""

    st.session_state[SESSION_ACCESS_TOKEN] = session.access_token
    st.session_state[SESSION_REFRESH_TOKEN] = session.refresh_token
    st.session_state[SESSION_USER_ID] = session.user_id
    st.session_state[SESSION_EMAIL] = session.email


def clear_session() -> None:
    """Remove authentication values from Streamlit session state."""

    for key in (
        SESSION_ACCESS_TOKEN,
        SESSION_REFRESH_TOKEN,
        SESSION_USER_ID,
        SESSION_EMAIL,
    ):
        st.session_state.pop(key, None)


def get_stored_tokens() -> tuple[str | None, str | None]:
    """Return authentication tokens currently stored in session state."""

    return (
        st.session_state.get(SESSION_ACCESS_TOKEN),
        st.session_state.get(SESSION_REFRESH_TOKEN),
    )


def has_stored_session() -> bool:
    """Return whether authentication tokens exist locally."""

    access_token, refresh_token = get_stored_tokens()

    return bool(access_token and refresh_token)