"""F-07 regressions: source money prefixes, safe replacement and uploader contract."""
from unittest.mock import patch

import pytest
from services.authorization_service import ApplicationUserContext
from services.document_analysis_service import (
    DOCUMENT, QA_HISTORY, RESULTS, WIDGET_VERSION, replace_document,
)
from services.summarisation_service import SYSTEM, _quality_issues
from services.temporary_document_service import (
    TemporaryDocument, TemporaryDocumentError, TemporarySegment,
)


def actor():
    return ApplicationUserContext("user-a", "a@example.invalid", None, "user", True, "access", "refresh")


def doc():
    text = (
        "CPF LIFE extra interest applies on the first $60,000. "
        "Escalating payouts rise by 2% per year."
    )
    return TemporaryDocument(
        document_id="cpf-fixture", owner_user_id="user-a", filename="cpf.txt",
        extension=".txt", size_bytes=len(text.encode()), character_count=len(text),
        page_count=None, segments=(TemporarySegment(0, text, None),), warnings=(),
    )


def test_source_currency_prefix_is_preserved_in_system_prompt():
    assert "if the source says $60,000, write $60,000 (not S$60,000)" in SYSTEM


def test_validator_allows_original_dollar_not_unfounded_sgd():
    assert _quality_issues("Interest applies on $60,000. [P1]", "Concise", doc()) == []
    assert "Financial amount not present in source" in _quality_issues(
        "Interest applies on S$60,000. [P1]", "Concise", doc()
    )


def test_valid_replacement_commits_and_discards_prior_results():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", return_value=actor()):
        old = replace_document(state, actor(), "first.txt", b"First knowledge")
        state[RESULTS] = {("old", "Concise"): "private summary"}
        state[QA_HISTORY] = ["private answer"]
        before = state[WIDGET_VERSION]
        new = replace_document(state, actor(), "second.txt", b"Second knowledge")
    assert new.document_id != old.document_id
    assert state[DOCUMENT] == new
    assert RESULTS not in state and QA_HISTORY not in state
    assert state[WIDGET_VERSION] == before + 1


def test_invalid_replacement_keeps_previous_valid_document_and_results():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", return_value=actor()):
        old = replace_document(state, actor(), "first.txt", b"First knowledge")
        state[RESULTS] = {("old", "Concise"): "private summary"}
        state[QA_HISTORY] = ["private answer"]
        before = state[WIDGET_VERSION]
        with pytest.raises(TemporaryDocumentError):
            replace_document(state, actor(), "empty.txt", b"")
    assert state[DOCUMENT] is old
    assert state[RESULTS] == {("old", "Concise"): "private summary"}
    assert state[QA_HISTORY] == ["private answer"]
    assert state[WIDGET_VERSION] == before


def test_auth_failure_clears_existing_document():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", return_value=actor()):
        replace_document(state, actor(), "first.txt", b"First knowledge")
    with patch("services.document_analysis_service.resolve_application_user", side_effect=Exception("denied")):
        with pytest.raises(Exception):
            replace_document(state, actor(), "second.txt", b"Second knowledge")
    assert DOCUMENT not in state
