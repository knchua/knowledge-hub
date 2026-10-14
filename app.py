"""Knowledge Hub Streamlit application entry point."""

import streamlit as st

from config.settings import ConfigurationError, get_settings
from database.health import check_database_connection
from services.auth_service import (
    AuthenticatedSession,
    AuthenticationError,
    sign_in,
    sign_out,
)
from services.authorization_service import (
    ApplicationAccessError,
    ApplicationUserContext,
    resolve_application_user,
)
from services.navigation_service import get_navigation_permissions
from services.session_service import (
    clear_session,
    get_stored_tokens,
    has_stored_session,
    store_session,
)


def render_login() -> None:
    """Render the Knowledge Hub login form."""

    st.title("📚 Knowledge Hub")
    st.caption("Phase 1 — Application Foundation")

    st.subheader("Sign in")

    with st.form("login_form"):
        email = st.text_input(
            "Email",
            autocomplete="email",
        )

        password = st.text_input(
            "Password",
            type="password",
            autocomplete="current-password",
        )

        submitted = st.form_submit_button(
            "Sign in",
            use_container_width=True,
        )

    if submitted:
        try:
            session = sign_in(email, password)

        except AuthenticationError:
            st.error("Invalid email or password.")
            return

        store_session(session)
        st.rerun()


def render_sidebar(
    user: ApplicationUserContext,
) -> None:
    """Render common authenticated-user controls."""

    with st.sidebar:
        st.divider()

        if user.display_name:
            st.write(f"Signed in as **{user.display_name}**")
        else:
            st.write(f"Signed in as **{user.email}**")

        st.caption(f"Role: {user.role}")

        if st.button(
            "Sign out",
            use_container_width=True,
        ):
            sign_out(
                user.access_token,
                user.refresh_token,
            )

            clear_session()
            st.rerun()


def build_navigation(
    user: ApplicationUserContext,
):
    """Build role-aware Streamlit navigation."""

    permissions = get_navigation_permissions(user)

    chatbot_page = st.Page(
        "pages/chatbot.py",
        title="Chatbot",
        icon="💬",
        url_path="chatbot",
        default=True,
    )

    document_analysis_page = st.Page(
        "pages/document_analysis.py",
        title="Document Analysis",
        icon="📄",
        url_path="document-analysis",
    )

    general_pages = [
        chatbot_page,
        document_analysis_page,
    ]

    if permissions.knowledge_management:
        knowledge_management_page = st.Page(
            "pages/knowledge_management.py",
            title="Knowledge Management",
            icon="📚",
            url_path="knowledge-management",
        )

    if permissions.user_management:
        user_management_page = st.Page(
            "pages/user_management.py",
            title="User Management",
            icon="👥",
            url_path="user-management",
        )

    if user.role == "admin":
        return st.navigation(
            {
                "Knowledge Hub": general_pages,
                "Administration": [
                    knowledge_management_page,
                    user_management_page,
                ],
            }
        )

    return st.navigation(
        {
            "Knowledge Hub": general_pages,
        }
    )


def resolve_current_user() -> ApplicationUserContext | None:
    """Resolve the current authenticated application user."""

    if not has_stored_session():
        return None

    access_token, refresh_token = get_stored_tokens()

    try:
        user = resolve_application_user(
            access_token or "",
            refresh_token or "",
        )

    except ApplicationAccessError:
        clear_session()

        st.error(
            "Your account does not currently have access "
            "to Knowledge Hub."
        )

        return None

    # Persist refreshed tokens returned during validation.
    store_session(
        AuthenticatedSession(
            user_id=user.user_id,
            email=user.email,
            access_token=user.access_token,
            refresh_token=user.refresh_token,
        )
    )

    return user


def main() -> None:
    """Run the Knowledge Hub application."""

    st.set_page_config(
        page_title="Knowledge Hub",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    try:
        get_settings()

    except ConfigurationError:
        st.error(
            "Application configuration is incomplete. "
            "Check the local Streamlit secrets configuration."
        )
        st.stop()

    if not check_database_connection():
        st.error(
            "Unable to connect to the application database. "
            "Check the Supabase configuration."
        )
        st.stop()

    user = resolve_current_user()

    if user is None:
        render_login()
        return

    render_sidebar(user)

    navigation = build_navigation(user)

    navigation.run()


if __name__ == "__main__":
    main()