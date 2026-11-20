"""Phase 4 Milestone 2: protected temporary document upload and extraction."""

import streamlit as st

from services.authorization_service import ApplicationAccessError, resolve_application_user
from services.document_analysis_service import (
    DocumentAccessError, OWNER, WIDGET_VERSION, bind_owner,
    clear_document, current_document, replace_document,
)
from services.session_service import get_stored_tokens
from services.temporary_document_service import TemporaryDocumentError
from services.document_summary_service import summarise_current_document
from services.summarisation_service import SummarisationError
from services.summary_render_service import escape_markdown_currency
from services.document_analysis_service import RESULTS
from services.document_qa_history_service import ask_and_record, read_qa_history, clear_qa_history
from services.document_qa_service import DocumentQAError
from services.phase5_visual_session_service import (
    PENDING, discard_visual_attempt, prepare_visual_attempt,
    replace_visual_document, visual_attempt_matches, configured_vision_budget,
)
from services.visual_extraction_manifest_service import VisualManifestError
from services.visual_document_processing_service import VisualProcessingError


def _invalidate_visual_attempt() -> None:
    # A changed uploader selection revokes consent to the previous selected file.
    discard_visual_attempt(st.session_state)


def _render_document_controls(user, document) -> None:
    """Preserve the legacy native-text upload and add explicit visual consent."""
    generation = st.session_state.get(WIDGET_VERSION, 0)
    uploaded = st.file_uploader(
        "Choose document" if document is None else "Choose replacement document",
        type=["pdf", "docx", "txt"],
        key=f"phase4_upload_{generation}",
        on_change=_invalidate_visual_attempt,
    )
    submit = st.button("Upload Document" if document is None else "Replace Document")
    if submit:
        if uploaded is None:
            st.warning("Select a document first.")
            return
        try:
            if uploaded.size > 20 * 1024 * 1024:
                raise TemporaryDocumentError("File exceeds the 20 MB upload limit.")
            raw = uploaded.getvalue()
            with st.spinner("Inspecting document locally…"):
                manifest = prepare_visual_attempt(st.session_state, user, uploaded.name, raw)
            if not manifest.consent_required:
                # Preserve the Phase 4 service call and its static regression test.
                with st.spinner("Validating and extracting text…"):
                    result = replace_document(st.session_state, user, uploaded.name, uploaded.getvalue())
                st.success(f"Loaded {result.filename} ({len(result.segments)} segments).")
                st.rerun()
        except (TemporaryDocumentError, DocumentAccessError, VisualManifestError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Unable to inspect or process this document.")

    pending = st.session_state.get(PENDING)
    if uploaded is not None and pending is not None:
        try:
            raw = uploaded.getvalue()
            if not visual_attempt_matches(st.session_state, uploaded.name, raw):
                discard_visual_attempt(st.session_state)
                st.warning("Selected file changed. Inspect it again before consent.")
                return
            manifest = pending["manifest"]
            if pending.get("owner") != user.user_id:
                discard_visual_attempt(st.session_state)
                st.error("Visual processing consent has expired.")
                return
            try:
                budget_preview = configured_vision_budget(manifest.proposed_vision_calls)
            except DocumentAccessError as exc:
                st.error(str(exc))
                st.info("Configure and verify KH_VISION_MAX_ESTIMATED_USD and both price settings before processing.")
            else:
                reserved = budget_preview.next_reservation_usd * manifest.proposed_vision_calls
                st.info(f"Visual content detected: {manifest.proposed_vision_calls} image/page(s). "
                        f"Estimated preflight reservation: USD {reserved:.4f}; "
                        f"configured per-document estimate limit: USD {budget_preview.max_estimated_usd:.4f}. "
                        "Actual provider charges can exceed estimates.")
                for candidate in manifest.candidates:
                    location = (f"PDF page {candidate.pdf_page}" if candidate.pdf_page is not None
                                else f"Word image {candidate.docx_image_ordinal}, body block {candidate.docx_body_block}")
                    st.caption(f"{location} — {candidate.reason}")
                st.warning("Document images will be transmitted to OpenAI for OCR and visual description. "
                           "Provider retention is governed by OpenAI's terms; local clearing does not "
                           "guarantee provider-side deletion. Use synthetic/non-sensitive files.")
                consent = st.checkbox(
                    "I explicitly consent to send images from THIS selected document to OpenAI.",
                    value=False, key=f"phase5_consent_{pending['nonce']}",
                )
                if st.button("Process Document with AI Vision", disabled=not consent,
                             key=f"phase5_process_{pending['nonce']}"):
                    try:
                        with st.spinner("Extracting visual evidence securely…"):
                            result = replace_visual_document(
                                st.session_state, user, uploaded.name, raw, consent=consent)
                        st.success(f"Loaded {result.filename} ({len(result.segments)} segments).")
                        st.rerun()
                    except (DocumentAccessError, VisualProcessingError) as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error("Unable to complete visual processing safely.")
        except Exception:
            # Avoid displaying stale consent or leaking any uploaded data.
            discard_visual_attempt(st.session_state)
            st.error("Unable to display the visual processing preview safely.")

    if document is not None and st.button("Clear Document", type="secondary"):
        clear_document(st.session_state)
        st.rerun()


def main() -> None:
    st.title("📄 Document Analysis")
    st.caption("Phase 5 — Temporary document analysis with optional visual extraction")
    st.info("Native document excerpts are sent to OpenAI only for requested summary/Q&A. Document images are sent only after explicit consent. "
            "Use synthetic or non-sensitive documents for this bootcamp. Documents are not added to the shared knowledge repository.")

    access, refresh = get_stored_tokens()
    try:
        if not access or not refresh:
            raise ApplicationAccessError("Sign in required")
        user = resolve_application_user(access, refresh)
        bind_owner(st.session_state, user.user_id)
        document = current_document(st.session_state, user)
    except (ApplicationAccessError, DocumentAccessError):
        clear_document(st.session_state, keep_owner=False)
        st.error("Your session is no longer authorised. Please sign in again.")
        st.stop()
    except Exception:
        clear_document(st.session_state, keep_owner=False)
        st.error("Unable to verify your account right now.")
        st.stop()

    if document is None:
        st.write("Upload one readable PDF, DOCX or UTF-8 TXT file (maximum 20 MB).")
        _render_document_controls(user, document)
    else:
        st.success("Temporary document ready for analysis.")
        st.write(f"**Filename:** {document.filename}")
        st.write(f"**Format:** {document.extension.upper().lstrip('.')}  ·  **Bytes:** {document.size_bytes:,}")
        st.write(f"**Extracted characters:** {document.character_count:,}  ·  **Segments:** {len(document.segments)}")
        if document.page_count is not None:
            st.write(f"**PDF pages:** {document.page_count}")
        for warning in document.warnings:
            st.warning(warning)
        _render_document_controls(user, document)
        st.divider()
        st.subheader("Summarise this document")
        st.info("Document content is transmitted to OpenAI when you generate a summary. "
                "Only use synthetic or non-sensitive documents for the bootcamp.")
        mode = st.selectbox("Summary format", ["Concise", "Detailed", "Structured"], )
        if st.button("Generate Summary", type="primary"):
            try:
                with st.spinner("Preparing a document-grounded summary…"):
                    summarise_current_document(st.session_state, user, mode)
                st.success("A new summary was generated and validated.")
            except (SummarisationError, DocumentAccessError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Unable to generate the summary right now.")
        result = st.session_state.get(RESULTS, {}).get((document.document_id, mode))
        if result is not None:
            # Escape currency/math delimiters before Markdown rendering.
            # Do not modify the validated, stored result.text.
            st.markdown(escape_markdown_currency(result.text))
            with st.expander("Inspect raw generated summary (diagnostic)"):
                st.caption("Shows the stored text without Markdown rendering. "
                           "Use only with non-sensitive bootcamp documents.")
                st.text_area("Raw summary", value=result.text,
                             height=260, disabled=True,
                             key=f"phase4_raw_{document.document_id}_{mode}_{st.session_state.get(WIDGET_VERSION, 0)}")
            st.caption(f"Summary used {result.model_calls} model call(s). "
                       f"Source references refer to segments in the current document.")
            for idx in result.source_segments:
                segment = document.segments[idx]
                with st.expander(f"[P{idx + 1}] " +
                                 (f"PDF page {segment.page_number}" if segment.page_number else
                                  (f"Word image {segment.docx_image_ordinal} (block {segment.docx_body_block})"
                                   if segment.docx_image_ordinal else f"Segment {idx + 1}"))):
                    st.caption(f"Extraction source: {segment.origin}" + (f" · Word image {segment.docx_image_ordinal}" if segment.docx_image_ordinal else ""))
                    for warning in segment.extraction_warnings:
                        st.warning(warning)
                    st.text(segment.text[:500])
        st.divider()
        st.subheader("Chat with this document")
        st.caption("Ask questions about the uploaded document. Questions and selected excerpts are sent to OpenAI. "
                   "The conversation remains in this session and is never added to shared knowledge.")
        try:
            history = read_qa_history(st.session_state, user)
        except DocumentAccessError:
            st.error("Your document access has changed. Please sign in again.")
            st.stop()

        if not history:
            st.info("Ask a question below to start a document-grounded conversation. "
                    "For example: Who owns action A-05, and when is it due?")

        for turn in history:
            with st.chat_message("user"):
                # Plain text avoids interpreting user-controlled Markdown and currency symbols.
                st.text(turn.question)
            with st.chat_message("assistant"):
                st.markdown(escape_markdown_currency(turn.answer.text))
                if turn.answer.abstained:
                    st.caption("Insufficient evidence in this uploaded document.")
                else:
                    for item in turn.answer.cited_evidence:
                        source_segment = document.segments[item.index]
                        location = (f"PDF page {item.page_number}"
                                    if item.page_number is not None else
                                    (f"Word image {source_segment.docx_image_ordinal} "
                                     f"(block {source_segment.docx_body_block})"
                                     if source_segment.docx_image_ordinal else f"Segment {item.index + 1}"))
                        with st.expander(f"[{item.label}] — {location}"):
                            st.caption(f"Extraction source: {source_segment.origin}")
                            for warning in source_segment.extraction_warnings:
                                st.warning(warning)
                            st.text(item.text)

        # Give this widget a fresh identity when the uploaded document changes.
        question = st.chat_input(
            "Ask a question about this document…",
            key=f"phase4_chat_input_{document.document_id}_{st.session_state.get(WIDGET_VERSION, 0)}",
            max_chars=1000,
        )
        if question is not None:
            try:
                with st.spinner("Finding evidence and preparing a cited answer…"):
                    ask_and_record(st.session_state, user, question)
            except (DocumentQAError, DocumentAccessError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Unable to answer this question right now.")
            else:
                st.rerun()

        if st.button("Clear Chat History", type="secondary"):
            try:
                clear_qa_history(st.session_state, user)
            except DocumentAccessError:
                st.error("Your document access has changed. Please sign in again.")
                st.stop()
            st.rerun()



main()
