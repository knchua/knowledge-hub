"""Knowledge Hub Streamlit application entry point."""

import streamlit as st

from config.settings import get_settings


def main() -> None:
    """Render the Knowledge Hub application shell."""

    settings = get_settings()

    st.set_page_config(
        page_title=settings.app_name,
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("📚 Knowledge Hub")
    st.caption(settings.phase)

    st.info(
        "Application foundation loaded successfully. "
        "Authentication has not yet been configured."
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