"""Milestone 4D: bounded session-only history for one authorised temporary document.

No persistence, document storage, shared retrieval, or model calls except via the
existing Checkpoint 4C answer_document_question().
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import MutableMapping

from services.document_analysis_service import QA_HISTORY, current_document, DocumentAccessError
from services.document_qa_service import DocumentAnswer, DocumentQAError, answer_document_question

HISTORY_LIMIT = 8
_CONTEXT_ID = re.compile(r"\b(?:A|R|D)-\d{2,4}\b", re.IGNORECASE)
_FOLLOW_UP = re.compile(r"\b(?:it|its|that|this|they|their|them|he|she|his|her)\b", re.IGNORECASE)


@dataclass(frozen=True)
class QATurn:
    document_id: str
    owner_id: str
    question: str
    answer: DocumentAnswer


def _active(state: MutableMapping, actor):
    """Always recheck identity and ownership; discard mismatched history."""
    try:
        document = current_document(state, actor)
    except DocumentAccessError:
        state.pop(QA_HISTORY, None)
        raise
    if document is None:
        state.pop(QA_HISTORY, None)
    return document


def read_qa_history(state: MutableMapping, actor) -> tuple[QATurn, ...]:
    doc = _active(state, actor)
    if doc is None:
        return ()
    stored = state.get(QA_HISTORY, ())
    if not isinstance(stored, (tuple, list)) or any(
        not isinstance(turn, QATurn)
        or turn.document_id != doc.document_id
        or turn.owner_id != doc.owner_user_id
        or turn.answer.document_id != doc.document_id
        for turn in stored
    ):
        state.pop(QA_HISTORY, None)
        return ()
    return tuple(stored[-HISTORY_LIMIT:])


def clear_qa_history(state: MutableMapping, actor) -> None:
    _active(state, actor)
    state.pop(QA_HISTORY, None)


def _effective_question(question: str, history: tuple[QATurn, ...]) -> str:
    """Narrow follow-up resolution: carry one previously explicit record identifier.

    No previous answers are injected into the retrieval/model prompt. If the
    antecedent is ambiguous, do not guess: leave the question unchanged.
    """
    if not history or not _FOLLOW_UP.search(question) or _CONTEXT_ID.search(question):
        return question
    previous = history[-1].question
    ids = {x.upper() for x in _CONTEXT_ID.findall(previous)}
    if len(ids) != 1:
        return question
    return f"{question} (referring to {next(iter(ids))})"


def ask_and_record(state: MutableMapping, actor, question: str) -> DocumentAnswer:
    doc = _active(state, actor)
    if doc is None:
        raise DocumentQAError("Upload a document before asking a question.")
    history = read_qa_history(state, actor)
    if not isinstance(question, str) or not question.strip():
        raise DocumentQAError("Enter a question about the uploaded document.")
    normalized = question.strip()
    # The underlying selector remains the authority for the configured limit.
    effective = _effective_question(normalized, history)
    answer = answer_document_question(state, actor, effective)
    # Revalidate after network/model call: don't attach answer to a changed document.
    latest = _active(state, actor)
    if latest is None or latest.document_id != doc.document_id or answer.document_id != doc.document_id:
        state.pop(QA_HISTORY, None)
        raise DocumentQAError("The uploaded document changed. Ask your question again.")
    turn = QATurn(doc.document_id, doc.owner_user_id, normalized, answer)
    state[QA_HISTORY] = (*history, turn)[-HISTORY_LIMIT:]
    return answer
