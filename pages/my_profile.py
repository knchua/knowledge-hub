"""P2: self-service profile page, independently protected against direct URLs."""

import streamlit as st

from services.authorization_service import ApplicationAccessError, resolve_application_user
from services.profile_service import (
    ProfileError,
    ProfileValidationError,
    load_own_profile,
    update_own_display_name,
)
from services.account_credentials_service import (
    PasswordChangeError,
    PasswordValidationError,
    ReauthenticationRequired,
    InvalidReauthenticationCode,
    change_own_password,
    request_reauthentication_code,
)
from services.session_service import clear_session, get_stored_tokens
from services.auth_service import sign_out


def _current_user():
    access_token, refresh_token = get_stored_tokens()
    if not access_token or not refresh_token:
        st.error("Sign in is required to access Knowledge Hub.")
        st.stop()
        return None
    try:
        return resolve_application_user(access_token, refresh_token)
    except ApplicationAccessError:
        clear_session()
        st.error("Your account does not currently have access to Knowledge Hub.")
        st.stop()
        return None
    except Exception:
        st.error("Unable to verify your account right now.")
        st.stop()
        return None


def main():
    user = _current_user()
    if user is None:
        return
    try:
        profile = load_own_profile(user)
    except ProfileError:
        st.error("Unable to load your profile right now.")
        st.stop()
        return

    st.title("👤 My Profile")
    st.caption("Manage your Knowledge Hub account")
    st.text_input("Email", value=profile.email, disabled=True)
    st.text_input("Role", value=profile.role.title(), disabled=True)
    st.text_input("Account status", value="Active", disabled=True)
    st.text_input("Account created", value=profile.created_at or "Not available", disabled=True)

    with st.form("own_profile_name_form"):
        new_name = st.text_input("Display name", value=profile.display_name or "", max_chars=200)
        submitted = st.form_submit_button("Save display name", use_container_width=True)
    if submitted:
        try:
            updated = update_own_display_name(user, new_name)
        except ProfileValidationError as exc:
            st.error(str(exc))
        except ProfileError:
            st.error("Unable to save your display name right now.")
        else:
            st.success("Display name saved.")
            # Refresh sidebar (and profile form) from the authoritative profile row.
            st.rerun()
    st.divider()
    st.subheader("Change password")
    st.caption(
        "Enter your current password and choose a new one. For older sessions, "
        "Supabase may require email verification. You will sign in again after updating."
    )

    # A boolean is safe to persist; never save passwords, OTPs or bearer tokens here.
    # Bound the flag to the authenticated identity to avoid cross-user UI leakage.
    flag = "p3_reauthentication_required"
    owner = "p3_reauthentication_owner"
    if st.session_state.get(owner) != user.user_id:
        st.session_state.pop(flag, None)
        st.session_state[owner] = user.user_id
    needs_code = bool(st.session_state.get(flag))

    if needs_code:
        st.info("Supabase requires email verification for this password change.")
        if st.button("Email me a security code", key="p3_send_code"):
            try:
                request_reauthentication_code(user)
            except PasswordChangeError:
                st.error("Unable to send a security code. Please try again later.")
            else:
                st.info("Check your account email for the eight-digit code.")

    with st.form("p3_change_password_form", clear_on_submit=True):
        current_password = st.text_input(
            "Current password", type="password", autocomplete="current-password"
        )
        new_password = st.text_input(
            "New password", type="password", autocomplete="new-password"
        )
        confirm_password = st.text_input(
            "Confirm new password", type="password", autocomplete="new-password"
        )
        nonce = ""
        if needs_code:
            nonce = st.text_input(
                "Email security code", max_chars=8,
                help="Enter the eight-digit code from the reauthentication email.",
            )
        password_submitted = st.form_submit_button(
            "Change password", use_container_width=True
        )

    if password_submitted:
        try:
            change_own_password(
                user, current_password, new_password, confirm_password, nonce
            )
        except PasswordValidationError as exc:
            st.error(str(exc))
        except ReauthenticationRequired:
            st.session_state[flag] = True
            st.warning("Email verification is required. Request a code and re-enter the password fields.")
            st.rerun()
        except InvalidReauthenticationCode:
            st.session_state[flag] = True
            st.error("Invalid or expired security code. Request another code and try again.")
        except PasswordChangeError:
            st.error("Password change was not completed. Check your current password and new password rules.")
        else:
            # Best-effort provider logout; never block local cleanup.
            try:
                sign_out(user.access_token, user.refresh_token)
            finally:
                clear_session()
                st.session_state.pop(flag, None)
                st.session_state.pop(owner, None)
            st.rerun()


main()
