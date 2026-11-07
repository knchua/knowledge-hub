"""Milestone 2 deterministic tests; no network calls or persisted documents."""
from io import BytesIO
from unittest.mock import patch

import pytest
from docx import Document

from services.document_analysis_service import (
    DocumentAccessError, OWNER, DOCUMENT, RESULTS, QA_HISTORY,
    bind_owner, clear_document, current_document, replace_document,
)
from services.temporary_document_service import TemporaryDocumentError, parse_temporary_document
from services.authorization_service import ApplicationUserContext
from services import session_service


def actor(user_id="user-a"):
    return ApplicationUserContext(user_id, "a@example.invalid", None, "user", True, "access", "refresh")


def test_txt_parse_no_original_bytes_retained():
    doc = parse_temporary_document("user-a", "hello.txt", b"Decision: ship on Monday.")
    assert doc.owner_user_id == "user-a"
    assert doc.extension == ".txt"
    assert doc.segments[0].text == "Decision: ship on Monday."
    assert doc.segments[0].page_number is None
    assert not hasattr(doc, "content")


def test_docx_parse():
    out = BytesIO()
    doc = Document()
    doc.add_paragraph("Meeting decision: approved")
    doc.save(out)
    parsed = parse_temporary_document("user-a", "notes.docx", out.getvalue())
    assert "approved" in " ".join(x.text for x in parsed.segments)


def test_pdf_page_references():
    import fitz
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page one decision")
    page = pdf.new_page()
    page.insert_text((72, 72), "Page two action")
    raw = pdf.tobytes()
    pdf.close()
    doc = parse_temporary_document("user-a", "report.pdf", raw)
    assert doc.page_count == 2
    assert {s.page_number for s in doc.segments} == {1, 2}


@pytest.mark.parametrize("name,raw", [
    ("bad.csv", b"a,b"), ("empty.txt", b""), ("binary.txt", b"\x00garbage"),
    ("bad.pdf", b"not a pdf"),
])
def test_invalid_document(name, raw):
    with pytest.raises(TemporaryDocumentError):
        parse_temporary_document("user-a", name, raw)


def test_text_budget(monkeypatch):
    monkeypatch.setenv("KH_ANALYSIS_MAX_TEXT_CHARS", "1000")
    with pytest.raises(TemporaryDocumentError, match="analysis limit"):
        parse_temporary_document("user-a", "long.txt", b"A" * 1100)


def test_replace_and_identity_change():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", side_effect=lambda a, r: actor()):
        one = replace_document(state, actor(), "first.txt", b"First")
        state[RESULTS] = "old summary"
        state[QA_HISTORY] = ["old answer"]
        two = replace_document(state, actor(), "second.txt", b"Second")
        assert one.document_id != two.document_id
        assert RESULTS not in state and QA_HISTORY not in state
        assert current_document(state, actor()) == two
    bind_owner(state, "user-b")
    assert DOCUMENT not in state
    assert state[OWNER] == "user-b"


def test_unauthorized_does_not_process():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", side_effect=Exception("denied")):
        with patch("services.document_analysis_service.parse_temporary_document") as parse:
            with pytest.raises(DocumentAccessError):
                replace_document(state, actor(), "a.txt", b"Secret")
            parse.assert_not_called()


def test_cross_user_document_rejected():
    state = {}
    with patch("services.document_analysis_service.resolve_application_user", return_value=actor("user-b")):
        bind_owner(state, "user-b")
        state[DOCUMENT] = parse_temporary_document("user-a", "a.txt", b"private")
        with pytest.raises(DocumentAccessError):
            current_document(state, actor("user-b"))
        assert DOCUMENT not in state


def test_logout_clears_phase4_and_preserves_phase3_behavior():
    state = {
        session_service.SESSION_ACCESS_TOKEN: "secret",
        "phase3_chat_turns": ["old"],
        OWNER: "user-a", DOCUMENT: object(), RESULTS: "result",
        "phase4_upload_0": object(), "unrelated_ui_preference": "keep",
    }
    with patch.object(session_service.st, "session_state", state):
        session_service.clear_session()
    assert not any(key.startswith("phase4_") for key in state)
    assert "phase3_chat_turns" not in state
    assert session_service.SESSION_ACCESS_TOKEN not in state
    assert state["unrelated_ui_preference"] == "keep"
