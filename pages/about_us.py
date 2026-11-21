"""Authenticated information page describing the Knowledge Hub project."""

import streamlit as st

from services.authorization_service import ApplicationAccessError, resolve_application_user
from services.session_service import get_stored_tokens


def _require_active_user() -> bool:
    """Independently protect direct-page access, not just sidebar navigation."""
    access_token, refresh_token = get_stored_tokens()
    if not access_token or not refresh_token:
        st.error("Sign in is required to access Knowledge Hub.")
        st.stop()
        return False

    try:
        # This verifies the backend identity, effective role and active profile.
        resolve_application_user(access_token, refresh_token)
    except ApplicationAccessError:
        st.error("Your account does not currently have access to Knowledge Hub.")
        st.stop()
        return False
    except Exception:
        st.error("Unable to verify your account right now. Please try again.")
        st.stop()
        return False
    return True


def main() -> None:
    if not _require_active_user():
        return

    st.title("ℹ️ About Knowledge Hub")
    st.caption("A document-grounded GenAI knowledge assistant | AI Bootcamp project")
    st.markdown(
        "Knowledge Hub is an authenticated web application designed to help users "
        "find, understand and analyse information from documents more efficiently. "
        "It connects AI-generated answers with supporting document evidence so "
        "users can inspect the sources behind a response."
    )

    st.subheader("The problem")
    st.write(
        "Useful information is often dispersed across different documents, making it "
        "time-consuming to locate and interpret. General-purpose AI assistants may "
        "respond without showing traceable supporting material."
    )

    st.subheader("Our approach")
    st.write(
        "Knowledge Hub combines an administrator-managed shared knowledge repository "
        "with retrieval-augmented generation (RAG) and a separate, temporary "
        "document-analysis workflow."
    )

    st.subheader("Three core features")
    knowledge, chatbot, analysis = st.columns(3)
    with knowledge:
        with st.container(border=True):
            st.markdown("**📚 Knowledge Management**")
            st.write(
                "Administrators upload and manage shared documents. Supported "
                "files are processed into indexed, searchable knowledge."
            )
    with chatbot:
        with st.container(border=True):
            st.markdown("**💬 RAG Chatbot**")
            st.write(
                "Authenticated users ask questions about shared knowledge. "
                "The chatbot retrieves relevant passages and returns "
                "answers with source citations and excerpts."
            )
    with analysis:
        with st.container(border=True):
            st.markdown("**📄 Document Analysis**")
            st.write(
                "Users temporarily upload documents for Concise, Detailed or "
                "Structured summaries and document-specific Q&A. Supported "
                "image-based content can be analysed with OCR and AI vision "
                "after disclosure and consent."
            )

    st.subheader("Who uses Knowledge Hub?")
    st.markdown(
        "**Administrators** manage shared knowledge documents and user accounts. "
        "**Regular users** query the shared knowledge repository and analyse "
        "their own temporary documents. Both roles can access the user-facing "
        "chatbot and document analysis features."
    )

    with st.expander("Technology used"):
        st.write(
            "Streamlit · Python · LangChain · OpenAI · Supabase Authentication · "
            "Supabase PostgreSQL · Supabase Storage · pgvector"
        )

    st.divider()
    st.subheader("About this AI Bootcamp project")
    st.write(
        "Knowledge Hub was developed as an educational demonstration of RAG, "
        "role-based access, document processing, summarisation and multimodal "
        "document understanding."
    )
    st.info(
        "This application is a bootcamp demonstration, not a production-certified "
        "information system. AI-generated answers, summaries and visual "
        "interpretations should be checked against their original documents. "
        "Citations show source references but do not guarantee that every claim "
        "is factually correct."
    )


main()
