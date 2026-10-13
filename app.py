"""Knowledge Hub Streamlit application entry point."""

import streamlit as st

from config.settings import ConfigurationError, get_settings
from database.health import check_database_connection


def main() -> None:
    """Render the Knowledge Hub application shell."""

    st.set_page_config(
        page_title="Knowledge Hub",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    try:
        settings = get_settings()
    except ConfigurationError:
        st.error(
            "Application configuration is incomplete. "
            "Check the local Streamlit secrets configuration."
        )
        st.stop()

    st.title("📚 Knowledge Hub")
    st.caption(settings.phase)

    st.success("Application configuration loaded successfully.")

    if check_database_connection():
        st.success("Supabase database connection verified.")
    else:
        st.error(
            "Unable to connect to the application database. "
            "Check the Supabase configuration."
        )
        st.stop()

    st.info(
        "Supabase credentials are configured. "
        "Database connectivity will be verified in the next checkpoint."
    )

    st.subheader("Phase 1")

    st.write(
        """
        This phase establishes the secure application foundation for the
        Knowledge Hub.
        """
    )

    st.markdown(
        """
        **Planned foundation capabilities**

        - Supabase authentication
        - Administrator and User roles
        - Role-based navigation
        - Secure user administration
        - Audit logging
        - Protected application pages
        """
    )

    st.divider()

    with st.expander("Application information"):
        st.write(f"**Application:** {settings.app_name}")
        st.write(f"**Version:** {settings.app_version}")
        st.write(f"**Environment:** {settings.environment}")
        st.write(f"**Phase:** {settings.phase}")


if __name__ == "__main__":
    main()



