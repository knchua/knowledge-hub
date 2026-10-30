
"""Phase 3 / Milestone 4: protected session-scoped Knowledge Hub chatbot."""

import logging

import streamlit as st

from services.authorization_service import (
    ApplicationAccessError,
    resolve_application_user,
)
from services.conversation_service import (
    ChatTurn,
    bounded_turns,
    standalone_retrieval_query,
)
from services.rag_service import (
    AnswerGenerationError,
    generate_grounded_answer,
)
from services.retrieval_service import (
    MAX_QUESTION_LENGTH,
    RetrievalError,
)
from services.session_service import get_stored_tokens


logger = logging.getLogger(__name__)

CHAT_OWNER_KEY = "phase3_chat_owner"
CHAT_TURNS_KEY = "phase3_chat_turns"


def _safe_failure_types(exc: Exception) -> str:
    """Return exception class names without exposing sensitive details."""
    names = []
    visited = set()
    current = exc

    while (
        current is not None
        and id(current) not in visited
        and len(names) < 5
    ):
        visited.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or current.__context__

    return " -> ".join(names)


def _require_current_user():
    """Revalidate the current authenticated application user."""
    access_token, refresh_token = get_stored_tokens()

    if not access_token or not refresh_token:
        raise ApplicationAccessError("Sign in is required.")

    return resolve_application_user(
        access_token,
        refresh_token,
    )


def _render_citations(citations):
    """Display validated source citations."""
    if not citations:
        return

    st.markdown("**Sources**")

    for citation in citations:
        page = (
            f" · Page {citation.page_number}"
            if citation.page_number is not None
            else ""
        )

        title = (
            f"[{citation.label}] {citation.document_name} · "
            f"Version {citation.version_number}{page}"
        )

        with st.expander(title):
            st.caption(f"Chunk {citation.chunk_index + 1}")
            st.write(citation.excerpt)


def _clear_chat():
    """Clear the current session's conversation history."""
    st.session_state[CHAT_TURNS_KEY] = []


def main():
    st.title("💬 Knowledge Hub Chatbot")

    st.caption(
        "Answers grounded in active knowledge documents, "
        "with source citations"
    )

    # --------------------------------------------------
    # 1. Validate the authenticated user
    # --------------------------------------------------
    try:
        user = _require_current_user()

    except ApplicationAccessError:
        _clear_chat()
        st.session_state.pop(CHAT_OWNER_KEY, None)

        st.error(
            "Your account does not currently have access "
            "to Knowledge Hub."
        )
        st.stop()

    except Exception:
        st.error(
            "Unable to verify your account right now. "
            "Please try again."
        )
        st.stop()

    # --------------------------------------------------
    # 2. Enforce user-specific conversation isolation
    # --------------------------------------------------
    if st.session_state.get(CHAT_OWNER_KEY) != user.user_id:
        _clear_chat()
        st.session_state[CHAT_OWNER_KEY] = user.user_id

    turns = bounded_turns(
        st.session_state.get(CHAT_TURNS_KEY, [])
    )

    st.session_state[CHAT_TURNS_KEY] = turns

    # --------------------------------------------------
    # 3. Clear Conversation button
    # --------------------------------------------------
    st.button(
        "Clear Conversation",
        on_click=_clear_chat,
        disabled=not turns,
    )

    # --------------------------------------------------
    # 4. Display existing conversation
    # --------------------------------------------------
    for turn in turns:

        with st.chat_message("user"):
            st.write(turn.question)

        with st.chat_message("assistant"):
            st.write(turn.answer)

            _render_citations(turn.citations)

            if turn.abstained:
                st.caption(
                    "No supporting citation was available "
                    "for this answer."
                )

    # --------------------------------------------------
    # 5. Accept a new question
    # --------------------------------------------------
    question = st.chat_input(
        "Ask a question about the knowledge documents",
        max_chars=MAX_QUESTION_LENGTH,
    )

    if question is None:
        return

    question = question.strip()

    if not question:
        st.warning("Enter a question.")
        return

    # --------------------------------------------------
    # 6. Generate grounded answer
    # --------------------------------------------------
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):

        try:
            with st.spinner(
                "Searching the knowledge repository "
                "and preparing an answer…"
            ):
                retrieval_query = standalone_retrieval_query(
                    question,
                    turns,
                )

                result = generate_grounded_answer(
                    retrieval_query,
                    user.access_token,
                    user.refresh_token,
                )

        except (
            ApplicationAccessError,
            RetrievalError,
            AnswerGenerationError,
            ValueError,
        ) as exc:

            logger.warning(
                "Phase3 chatbot failure "
                "(exception types only): %s",
                _safe_failure_types(exc),
            )

            st.error(
                "Unable to answer that question right now. "
                "Please try again."
            )
            return

        except Exception as exc:

            logger.warning(
                "Phase3 chatbot unexpected failure "
                "(exception types only): %s",
                _safe_failure_types(exc),
            )

            st.error(
                "An unexpected error occurred. "
                "Please try again."
            )
            return

        st.write(result.answer)

        _render_citations(result.citations)

        if result.abstained:
            st.caption(
                "No supporting citation was available "
                "for this answer."
            )

    # --------------------------------------------------
    # 7. Store completed conversation turn
    # --------------------------------------------------
    turns.append(
        ChatTurn(
            question,
            result.answer,
            tuple(result.citations),
            result.abstained,
        )
    )

    st.session_state[CHAT_TURNS_KEY] = bounded_turns(turns)

    # --------------------------------------------------
    # 8. IMPORTANT FIX
    #
    # Force Streamlit to rerun after saving the answer.
    # This refreshes the Clear Conversation button so
    # it becomes enabled after the first Q&A exchange.
    # --------------------------------------------------
    st.rerun()


main()
