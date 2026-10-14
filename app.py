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


def render_authenticated_app(
    user: ApplicationUserContext,
) -> None:
    """Render the temporary authenticated application shell."""

    st.title("📚 Knowledge Hub")
    st.caption("Phase 1 — Application Foundation")

    if user.display_name:
        st.write(f"Welcome, **{user.display_name}**.")
    else:
        st.write(f"Signed in as **{user.email}**")

    st.success("Application access validated.")

    st.write(f"Current role: **{user.role}**")

    st.info(
        "Authentication, profile validation and active-account "
        "enforcement are enabled. Role-based navigation will be "
        "implemented in the next milestone."
    )

    if st.button("Sign out"):
        sign_out(
            user.access_token,
            user.refresh_token,
        )

        clear_session()
        st.rerun()


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

    if not has_stored_session():
        render_login()
        return

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

        render_login()
        return


    store_session(
        AuthenticatedSession(
            user_id=user.user_id,
            email=user.email,
            access_token=user.access_token,
            refresh_token=user.refresh_token,
        )
    )

    render_authenticated_app(user)


if __name__ == "__main__":
    main()