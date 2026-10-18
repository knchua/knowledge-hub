"""Administrator User Management page."""

import streamlit as st

from services.authorization_service import (
    ApplicationAccessError,
    resolve_application_user,
    require_admin,
)
from services.session_service import get_stored_tokens
from services.user_service import (
    UserAdministrationError,
    change_user_role,
    delete_user,
    invite_user,
    list_users,
    send_password_reset,
    set_user_active_status,
)
from services.audit_service import (
    AuditLoggingError,
    list_audit_logs,
)


def get_current_admin():
    """Resolve and verify the current administrator."""

    access_token, refresh_token = get_stored_tokens()

    try:
        user = resolve_application_user(
            access_token or "",
            refresh_token or "",
        )
        require_admin(user)
        return user

    except ApplicationAccessError:
        st.error("Administrator access is required.")
        st.stop()


def render_user_table(users) -> None:
    """Display current Knowledge Hub users."""

    if not users:
        st.info("No application users were found.")
        return

    rows = []

    for user in users:
        rows.append(
            {
                "Email": user.email,
                "Display Name": user.display_name or "",
                "Role": user.role,
                "Active": user.is_active,
                "Created": user.created_at or "",
                "Last Sign In": user.last_sign_in_at or "",
            }
        )

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


def render_invite_section(admin) -> None:
    """Render user invitation controls."""

    st.subheader("Invite User")

    with st.form(
        "invite_user_form",
        clear_on_submit=True,
    ):
        email = st.text_input(
            "Email address",
            placeholder="user@example.com",
        )

        submitted = st.form_submit_button(
            "Send Invitation",
            use_container_width=True,
        )

    if submitted:
        try:
            invite_user(
                admin,
                email,
            )

        except UserAdministrationError:
            st.error(
                "Unable to invite the user. "
                "Check the email address and whether the account already exists."
            )
            return

        st.success("User invitation sent.")
        st.rerun()


def render_role_section(admin, users) -> None:
    """Render administrator role-management controls."""

    st.subheader("Change User Role")

    eligible_users = [
        user
        for user in users
        if user.user_id != admin.user_id
    ]

    if not eligible_users:
        st.info("There are no other users available for role changes.")
        return

    user_by_id = {
        user.user_id: user
        for user in eligible_users
    }

    selected_user_id = st.selectbox(
        "User",
        options=list(user_by_id.keys()),
        format_func=lambda user_id: (
            f"{user_by_id[user_id].email} "
            f"({user_by_id[user_id].role})"
        ),
        key="role_target_user",
    )

    selected_user = user_by_id[selected_user_id]

    available_roles = ["user", "admin"]

    selected_role = st.selectbox(
        "Role",
        options=available_roles,
        index=available_roles.index(selected_user.role),
        key="role_new_value",
    )

    if st.button(
        "Update Role",
        use_container_width=True,
    ):
        if selected_role == selected_user.role:
            st.info("The selected user already has this role.")
            return

        try:
            change_user_role(
                admin,
                selected_user.user_id,
                selected_role,
            )

        except UserAdministrationError:
            st.error("Unable to change the user's role.")
            return

        st.success("User role updated.")
        st.rerun()


def render_status_section(admin, users) -> None:
    """Render activation/deactivation controls."""

    st.subheader("Account Access")

    eligible_users = [
        user
        for user in users
        if user.user_id != admin.user_id
    ]

    if not eligible_users:
        st.info("There are no other users available.")
        return

    user_by_id = {
        user.user_id: user
        for user in eligible_users
    }

    selected_user_id = st.selectbox(
        "User",
        options=list(user_by_id.keys()),
        format_func=lambda user_id: (
            f"{user_by_id[user_id].email} — "
            f"{'Active' if user_by_id[user_id].is_active else 'Inactive'}"
        ),
        key="status_target_user",
    )

    selected_user = user_by_id[selected_user_id]

    if selected_user.is_active:
        st.warning(
            "Deactivating this account will block Knowledge Hub access "
            "and prevent new Supabase sign-ins."
        )

        confirmed = st.checkbox(
            "I confirm that I want to deactivate this user.",
            key="confirm_deactivation",
        )

        if st.button(
            "Deactivate User",
            type="primary",
            disabled=not confirmed,
            use_container_width=True,
        ):
            try:
                set_user_active_status(
                    admin,
                    selected_user.user_id,
                    is_active=False,
                )

            except UserAdministrationError:
                st.error("Unable to deactivate the user.")
                return

            st.success("User account deactivated.")
            st.rerun()

    else:
        st.info(
            "This account is currently inactive. "
            "Activation will restore application access and remove the Auth ban."
        )

        if st.button(
            "Activate User",
            use_container_width=True,
        ):
            try:
                set_user_active_status(
                    admin,
                    selected_user.user_id,
                    is_active=True,
                )

            except UserAdministrationError:
                st.error("Unable to activate the user.")
                return

            st.success("User account activated.")
            st.rerun()


def render_password_reset_section(admin, users) -> None:
    """Render administrator password-reset controls."""

    st.subheader("Reset User Password")

    eligible_users = [
        user
        for user in users
        if user.user_id != admin.user_id
        and user.is_active
    ]

    if not eligible_users:
        st.info(
            "There are no active users available "
            "for password reset."
        )
        return

    user_by_id = {
        user.user_id: user
        for user in eligible_users
    }

    selected_user_id = st.selectbox(
        "User",
        options=list(user_by_id.keys()),
        format_func=lambda user_id: user_by_id[user_id].email,
        key="password_reset_target",
    )

    selected_user = user_by_id[selected_user_id]

    st.info(
        "The user will receive a password reset email. "
        "Administrators do not set or view the user's password."
    )

    if st.button(
        "Send Password Reset",
        use_container_width=True,
    ):
        try:
            send_password_reset(
                admin,
                selected_user.user_id,
                selected_user.email,
            )

        except UserAdministrationError:
            st.error(
                "Unable to send the password reset email."
            )
            return

        st.success("Password reset email sent.")

def render_delete_section(admin, users) -> None:
    """Render permanent user deletion controls."""

    st.subheader("Delete User")

    eligible_users = [
        user
        for user in users
        if user.user_id != admin.user_id
    ]

    if not eligible_users:
        st.info("There are no other users available for deletion.")
        return

    user_by_id = {
        user.user_id: user
        for user in eligible_users
    }

    selected_user_id = st.selectbox(
        "User",
        options=list(user_by_id.keys()),
        format_func=lambda user_id: (
            f"{user_by_id[user_id].email} "
            f"({user_by_id[user_id].role})"
        ),
        key="delete_target_user",
    )

    selected_user = user_by_id[selected_user_id]

    st.error(
        "Deleting a user is permanent. "
        "The Supabase Auth identity and corresponding "
        "Knowledge Hub profile will be removed."
    )

    confirmation = st.text_input(
        "Type DELETE to confirm",
        key="delete_confirmation",
    )

    if st.button(
        "Delete User Permanently",
        type="primary",
        disabled=confirmation != "DELETE",
        use_container_width=True,
    ):
        try:
            delete_user(
                admin,
                selected_user.user_id,
            )

        except UserAdministrationError:
            st.error("Unable to delete the user.")
            return

        st.success("User deleted.")
        st.rerun()

def render_audit_section(admin) -> None:
    """Render recent administrative audit activity."""

    st.subheader("Administrative Audit Log")

    st.caption(
        "Recent privileged account-management activity. "
        "Audit records do not contain passwords or authentication tokens."
    )

    try:
        entries = list_audit_logs(
            admin,
            limit=100,
        )

    except AuditLoggingError:
        st.error("Unable to load administrative audit records.")
        return

    if not entries:
        st.info("No administrative audit records were found.")
        return

    rows = []

    for entry in entries:
        rows.append(
            {
                "Time": entry.created_at,
                "Action": entry.action,
                "Actor User ID": entry.actor_user_id or "",
                "Target User ID": entry.target_user_id or "",
                "Details": entry.details,
            }
        )

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )

def main() -> None:
    """Render administrator user management."""

    st.title("👥 User Management")
    st.caption("Administrator access only")

    admin = get_current_admin()

    try:
        users = list_users(admin)

    except UserAdministrationError:
        st.error("Unable to load application users.")
        st.stop()

    st.subheader("Application Users")
    render_user_table(users)

    st.divider()
    render_invite_section(admin)

    st.divider()
    render_role_section(admin, users)

    st.divider()
    render_password_reset_section(admin, users)

    st.divider()
    render_status_section(admin, users)

    st.divider()
    render_audit_section(admin)

    st.divider()
    render_delete_section(admin, users)

main()