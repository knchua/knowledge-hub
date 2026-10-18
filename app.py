"""Knowledge Hub Streamlit application entry point."""

import streamlit as st

from config.settings import ConfigurationError, get_settings
from database.health import check_database_connection
from services.auth_service import (
    AuthenticatedSession,
    AuthenticationError,
    sign_in,
    sign_out,
    update_password,
    verify_recovery_token,
    verify_invite_token,
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
    is_recovery_mode,
    set_recovery_mode,
    store_session,
    is_invite_mode,
    set_invite_mode,
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

def handle_recovery_link() -> bool:
    """Process a Supabase password-recovery token from the URL."""

    token_hash = st.query_params.get("token_hash")
    recovery_type = st.query_params.get("type")

    if not token_hash or recovery_type != "recovery":
        return False

    try:
        session = verify_recovery_token(
            token_hash,
        )

    except AuthenticationError:
        st.error(
            "This password reset link is invalid or has expired. "
            "Please request a new password reset."
        )

        st.query_params.clear()
        return True

    store_session(session)
    set_recovery_mode(True)

    # Token hashes are one-time credentials.
    # Remove them from the browser URL immediately after verification.
    st.query_params.clear()

    st.rerun()

    return True

def render_password_recovery() -> None:
    """Render the password recovery form."""

    st.title("📚 Knowledge Hub")
    st.caption("Password Recovery")

    st.subheader("Set New Password")

    st.info(
        "Enter a new password for your Knowledge Hub account."
    )

    with st.form("password_recovery_form"):
        new_password = st.text_input(
            "New password",
            type="password",
            autocomplete="new-password",
        )

        confirm_password = st.text_input(
            "Confirm new password",
            type="password",
            autocomplete="new-password",
        )

        submitted = st.form_submit_button(
            "Update Password",
            use_container_width=True,
        )

    if submitted:
        if len(new_password) < 8:
            st.error(
                "Password must contain at least 8 characters."
            )
            return

        if new_password != confirm_password:
            st.error("Passwords do not match.")
            return

        access_token, refresh_token = get_stored_tokens()

        try:
            update_password(
                access_token or "",
                refresh_token or "",
                new_password,
            )

        except AuthenticationError:
            st.error(
                "Unable to update your password. "
                "Please request a new reset link."
            )
            return

        clear_session()

        st.success(
            "Password updated successfully. "
            "You can now sign in using your new password."
        )

        if st.button(
            "Return to Sign In",
            use_container_width=True,
        ):
            st.rerun()

def handle_invite_link() -> bool:
    """Process a Supabase invitation token from the URL."""

    token_hash = st.query_params.get("token_hash")
    auth_type = st.query_params.get("type")

    if not token_hash or auth_type != "invite":
        return False

    try:
        session = verify_invite_token(
            token_hash,
        )

    except AuthenticationError:
        st.error(
            "This invitation link is invalid or has expired. "
            "Please ask an administrator to send a new invitation."
        )

        st.query_params.clear()
        return True

    store_session(session)
    set_invite_mode(True)

    st.query_params.clear()
    st.rerun()

    return True

def render_invite_setup() -> None:
    """Render first-time account setup after accepting an invite."""

    st.title("📚 Knowledge Hub")
    st.caption("Account Setup")

    st.subheader("Create Your Password")

    st.info(
        "Your invitation has been verified. "
        "Choose a password to complete your Knowledge Hub account."
    )

    with st.form("invite_setup_form"):
        new_password = st.text_input(
            "Password",
            type="password",
            autocomplete="new-password",
        )

        confirm_password = st.text_input(
            "Confirm password",
            type="password",
            autocomplete="new-password",
        )

        submitted = st.form_submit_button(
            "Complete Account Setup",
            use_container_width=True,
        )

    if submitted:
        if len(new_password) < 8:
            st.error(
                "Password must contain at least 8 characters."
            )
            return

        if new_password != confirm_password:
            st.error("Passwords do not match.")
            return

        access_token, refresh_token = get_stored_tokens()

        try:
            update_password(
                access_token or "",
                refresh_token or "",
                new_password,
            )

        except AuthenticationError:
            st.error(
                "Unable to complete account setup. "
                "Please request a new invitation."
            )
            return

        clear_session()

        st.success(
            "Account setup completed successfully. "
            "You can now sign in."
        )

        if st.button(
            "Return to Sign In",
            use_container_width=True,
        ):
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

    if handle_recovery_link():
        return

    if handle_invite_link():
        return

    if is_recovery_mode():
        render_password_recovery()
        return

    if is_invite_mode():
        render_invite_setup()
        return

    user = resolve_current_user()

    if user is None:
        render_login()
        return

    render_sidebar(user)

    navigation = build_navigation(user)

    navigation.run()


if __name__ == "__main__":
    main()