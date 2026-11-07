"""Milestone 3 regression: failed regeneration cannot show cached summaries."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from services.document_analysis_service import DOCUMENT, RESULTS, DocumentAccessError
from services.document_summary_service import summarise_current_document
from services.summarisation_service import SummarisationError


def _document():
    return SimpleNamespace(document_id="doc-123", owner_user_id="user-a")


def test_failed_generation_drops_old_result_for_same_document_and_mode():
    doc = _document()
    state = {DOCUMENT: doc, RESULTS: {("doc-123", "Concise"): "OLD INVALID OUTPUT",
                                     ("doc-123", "Detailed"): "other mode remains"}}
    with patch("services.document_summary_service.current_document", return_value=doc), \
         patch("services.document_summary_service.verify_actor", return_value=SimpleNamespace(user_id="user-a")), \
         patch("services.document_summary_service.generate_summary", side_effect=SummarisationError("Rejected")):
        with pytest.raises(SummarisationError, match="Rejected"):
            summarise_current_document(state, object(), "Concise")
    assert ("doc-123", "Concise") not in state[RESULTS]
    assert state[RESULTS][("doc-123", "Detailed")] == "other mode remains"


def test_success_replaces_prior_result():
    doc = _document()
    summary = SimpleNamespace(text="New valid summary [P1]")
    state = {DOCUMENT: doc, RESULTS: {("doc-123", "Concise"): "OLD"}}
    with patch("services.document_summary_service.current_document", return_value=doc), \
         patch("services.document_summary_service.verify_actor", return_value=SimpleNamespace(user_id="user-a")), \
         patch("services.document_summary_service.generate_summary", return_value=summary):
        returned = summarise_current_document(state, object(), "Concise")
    assert returned is summary
    assert state[RESULTS][("doc-123", "Concise")] is summary


def test_denied_user_does_not_invoke_model():
    doc = _document()
    state = {DOCUMENT: doc}
    with patch("services.document_summary_service.current_document", side_effect=DocumentAccessError("Denied")), \
         patch("services.document_summary_service.generate_summary") as model:
        with pytest.raises(DocumentAccessError):
            summarise_current_document(state, object(), "Concise")
        model.assert_not_called()
