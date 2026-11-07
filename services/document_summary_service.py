"""Authorize Phase 4 summary requests and keep results bound to the current file."""
from __future__ import annotations
from typing import MutableMapping

from services.document_analysis_service import (
    DOCUMENT, RESULTS, DocumentAccessError, current_document, verify_actor,
)
from services.authorization_service import ApplicationUserContext
from services.summarisation_service import DocumentSummary, generate_summary


def summarise_current_document(state: MutableMapping, actor: ApplicationUserContext,
                               mode: str) -> DocumentSummary:
    """Revalidate ownership and replace, never reuse, a requested summary.

    Crucial fail-closed behaviour: the previously displayed result for this
    document/mode is discarded BEFORE any external model operation. If the
    model fails validation, the UI must not redisplay a stale, invalid result.
    """
    document = current_document(state, actor)
    if document is None:
        raise DocumentAccessError("Upload a document before generating a summary.")
    user = verify_actor(actor)
    if user.user_id != document.owner_user_id or state.get(DOCUMENT) is not document:
        raise DocumentAccessError("Temporary document is no longer available.")

    # A failed retry must never leave the old summary looking like new output.
    prior = state.get(RESULTS)
    if isinstance(prior, dict):
        updated = dict(prior)
        updated.pop((document.document_id, mode), None)
        state[RESULTS] = updated
    else:
        state.pop(RESULTS, None)

    summary = generate_summary(document, mode)
    refreshed = current_document(state, actor)
    if refreshed is not document:
        raise DocumentAccessError("The document changed during processing. Discarding the result.")

    results = state.get(RESULTS)
    if not isinstance(results, dict):
        results = {}
    results[(document.document_id, mode)] = summary
    state[RESULTS] = results
    return summary
