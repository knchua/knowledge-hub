"""Phase 4: authenticated, single-document session lifecycle."""
from __future__ import annotations

from typing import MutableMapping
from services.authorization_service import ApplicationAccessError, ApplicationUserContext, resolve_application_user
from services.temporary_document_service import TemporaryDocument, parse_temporary_document

OWNER = "phase4_owner"
DOCUMENT = "phase4_document"
UPLOAD = "phase4_upload"
WIDGET_VERSION = "phase4_upload_generation"
RESULTS = "phase4_results"
QA_HISTORY = "phase4_qa_history"


class DocumentAccessError(RuntimeError):
    """Document operation is not authorised."""


def clear_document(state: MutableMapping, *, keep_owner: bool = True) -> None:
    """Drop document references, derived state and current uploader widget state."""
    for key in (DOCUMENT, RESULTS, QA_HISTORY, UPLOAD, "phase4_summary_mode"):
        state.pop(key, None)
    # Do not mutate an instantiated Streamlit uploader widget key here.
    # The version change below stops rendering it on the next rerun.
    # A fresh widget key prevents Streamlit from reusing the previous upload.
    state[WIDGET_VERSION] = int(state.get(WIDGET_VERSION, 0)) + 1
    if not keep_owner:
        state.pop(OWNER, None)


def bind_owner(state: MutableMapping, user_id: str) -> None:
    if not user_id:
        raise DocumentAccessError("Sign in is required.")
    if state.get(OWNER) != user_id:
        clear_document(state, keep_owner=False)
        state[OWNER] = user_id


def verify_actor(actor: ApplicationUserContext) -> ApplicationUserContext:
    """Authoritative check, independent of Streamlit navigation/session state."""
    if not isinstance(actor, ApplicationUserContext):
        raise DocumentAccessError("Sign in is required.")
    try:
        current = resolve_application_user(actor.access_token, actor.refresh_token)
    except ApplicationAccessError as exc:
        raise DocumentAccessError("Your account is no longer authorised.") from exc
    except Exception as exc:
        raise DocumentAccessError("Unable to verify your account.") from exc
    if current.user_id != actor.user_id or not current.is_active:
        raise DocumentAccessError("Your account is no longer authorised.")
    return current


def replace_document(state: MutableMapping, actor: ApplicationUserContext, filename: str, data: bytes) -> TemporaryDocument:
    """Authenticate first, then parse; commit replacement only on success.

    Rejected files leave the previous authorised document intact. Authentication
    failure still clears session document state through the existing handler.
    """
    try:
        current = verify_actor(actor)
    except DocumentAccessError:
        clear_document(state, keep_owner=False)
        raise
    bind_owner(state, current.user_id)
    document = parse_temporary_document(current.user_id, filename, data)
    clear_document(state)
    state[DOCUMENT] = document
    return document


def current_document(state: MutableMapping, actor: ApplicationUserContext) -> TemporaryDocument | None:
    try:
        current = verify_actor(actor)
    except DocumentAccessError:
        clear_document(state, keep_owner=False)
        raise
    bind_owner(state, current.user_id)
    doc = state.get(DOCUMENT)
    if doc is None:
        return None
    if not isinstance(doc, TemporaryDocument) or doc.owner_user_id != current.user_id:
        clear_document(state, keep_owner=False)
        raise DocumentAccessError("Temporary document ownership mismatch.")
    return doc
