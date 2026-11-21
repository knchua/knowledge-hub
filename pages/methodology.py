"""Authenticated information page describing the implemented Knowledge Hub methodology."""

import streamlit as st

from services.authorization_service import ApplicationAccessError, resolve_application_user
from services.session_service import get_stored_tokens


def _require_active_user() -> bool:
    """Check backend identity and active status even for direct page access."""
    access_token, refresh_token = get_stored_tokens()
    if not access_token or not refresh_token:
        st.error("Sign in is required to access Knowledge Hub.")
        st.stop()
        return False

    try:
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

    st.title("🧭 Methodology")
    st.caption("Knowledge Hub | Solution architecture, AI workflows and responsible use")
    st.write(
        "Knowledge Hub combines document processing, semantic retrieval and generative AI "
        "through two distinct workflows: a persistent administrator-managed shared knowledge "
        "repository and temporary, session-scoped document analysis."
    )

    st.subheader("1. Solution architecture")
    st.markdown(
        "**Application interface:** Streamlit  ·  **Application services:** Python and LangChain  ·  "
        "**Identity:** Supabase Auth  ·  **Shared data:** Supabase Storage and PostgreSQL/pgvector  ·  "
        "**AI processing:** OpenAI embeddings, language generation and supported vision processing"
    )
    shared, temporary = st.columns(2)
    with shared:
        with st.container(border=True):
            st.markdown("**Shared knowledge (persistent)**")
            st.markdown(
                "Administrator upload → validation and text extraction → LangChain chunking "
                "→ OpenAI embeddings → Supabase PostgreSQL/pgvector → authorised retrieval → RAG answer"
            )
    with temporary:
        with st.container(border=True):
            st.markdown("**Temporary document analysis (session-scoped)**")
            st.markdown(
                "User upload → native extraction and optional consented OCR/vision → "
                "source-attributed session evidence → OpenAI summary or document Q&A"
            )
    st.caption(
        "Temporary uploads are not added to the shared knowledge repository, Supabase Storage "
        "or persistent pgvector index by the Document Analysis workflow."
    )

    st.subheader("2. Knowledge ingestion")
    st.write(
        "Administrators upload supported PDF, DOCX or TXT documents to Knowledge Management. "
        "The ingestion pipeline validates each file, extracts text and source details, splits "
        "content into bounded chunks using LangChain, creates OpenAI embeddings, and stores "
        "versioned document metadata and vectors in Supabase PostgreSQL with pgvector. "
        "Original shared documents are kept in private Supabase Storage. Only eligible "
        "active, ready document versions are used for retrieval."
    )
    st.info(
        "OCR/visual analysis of temporary uploads does not automatically index visual content "
        "into the shared knowledge repository."
    )

    st.subheader("3. Retrieval-Augmented Generation (RAG)")
    st.markdown(
        "**Question → query embedding → authorised pgvector similarity retrieval → bounded "
        "supporting context → OpenAI grounded answer → validated citations and excerpts**"
    )
    st.write(
        "The chatbot searches relevant chunks of active shared knowledge, supplies selected "
        "evidence to the language model and asks it to answer from that context. The backend "
        "validates citation labels against retrieved sources before showing document names, "
        "available page references and excerpts. It can decline a question when sufficient "
        "supporting evidence cannot be found."
    )

    st.subheader("4. Document summarisation and Q&A")
    st.write(
        "Users can temporarily upload PDF, DOCX or TXT files for document-specific analysis. "
        "Concise summaries offer a shorter overview; Detailed summaries aim for wider "
        "coverage; Structured summaries organise supported findings into categories. "
        "Users can also ask questions about their current document, with available "
        "source-labelled evidence. Application-managed temporary content is session-scoped "
        "and is not persisted to the shared vector repository. Relevant source content "
        "is sent to OpenAI when AI analysis is requested."
    )

    st.subheader("5. OCR and multimodal processing")
    st.write(
        "Knowledge Hub extracts native document text first. For supported scanned PDF pages "
        "and embedded document images, optional AI vision can extract readable text and "
        "describe visual relationships. Document images are sent to OpenAI only after "
        "specific disclosure and consent. PDF page references and Word image locations "
        "are provided when determinable; visual interpretations and unreadable content "
        "may carry uncertainty warnings."
    )

    st.subheader("6. Security and responsible AI")
    st.markdown(
        "- **Access control:** Supabase authentication, active-account checks and "
        "server-side administrator authorisation.\n"
        "- **Evidence handling:** Retrieved and uploaded document material is treated as "
        "untrusted source data, not system instructions.\n"
        "- **Grounding:** Source-label validation and insufficient-evidence abstention "
        "reduce unsupported outputs without guaranteeing accuracy.\n"
        "- **Resource controls:** Configured processing limits, bounded model operations "
        "and explicit consent for visual processing.\n"
        "- **Privacy:** Temporary application state is cleared on supported lifecycle "
        "events; external provider processing and retention are separate considerations."
    )

    st.subheader("7. Testing and evaluation")
    st.write(
        "The latest reported local development working tree passed 2,932 automated tests. "
        "That total includes dormant experimental modules excluded from grading release "
        "commit 29c22b2, so it is not the measured test count of that exact release. "
        "The most recent controlled prompt-injection evaluation passed 12 of 12 scenarios. "
        "Representative checks also covered CPF LIFE summaries and document Q&A, "
        "image-based infographic analysis, and Streamlit Community Cloud smoke testing. "
        "Some summary omissions were observed during review. These tests demonstrate "
        "observed behaviour only for the evaluated cases."
    )

    with st.expander("8. Known limitations", expanded=True):
        st.markdown(
            "- Source citations identify evidence but do **not** independently prove "
            "that each generated claim is factually or semantically correct.\n"
            "- OCR, complex diagrams, charts and low-quality scans may produce incomplete "
            "or uncertain interpretations.\n"
            "- Session cleanup does not guarantee physical memory erasure or "
            "provider-side deletion.\n"
            "- Passing tests and controlled prompt-injection scenarios do not establish "
            "universal security, accuracy or production certification."
        )
    st.caption("Educational AI Bootcamp demonstration; verify important results against original sources.")


main()
