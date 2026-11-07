"""Standalone tests: model uses the same public TemporaryDocument/Segment fields.

The test intentionally avoids importing LangChain and Streamlit. Run in the real
project to verify integration against its existing TemporaryDocument contract.
"""
from dataclasses import dataclass
import pytest
from services.document_evidence_service import select_document_evidence, EvidenceSelectionError

@dataclass(frozen=True)
class Segment:
    index: int
    text: str
    page_number: int | None = None

@dataclass(frozen=True)
class Doc:
    document_id: str
    owner_user_id: str
    segments: tuple[Segment, ...]

def doc(*parts, page=None):
    return Doc("document-test", "owner-test", tuple(Segment(i, text, page) for i, text in enumerate(parts)))

def test_short_document_uses_bounded_full_context():
    result = select_document_evidence(doc("Alice owns A-01.", "Budget S$20,000."), "Who owns A-01?")
    assert result.strategy == "full_context"
    assert result.allowed_labels == {"P1", "P2"}

def test_original_labels_are_not_renumbered(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_SEGMENTS", "2")
    result = select_document_evidence(doc("foo one", "bar two", "unrelated", "A-05 belongs to Farah Aziz, due 18 December."), "Who owns A-05?")
    assert result.strategy == "lexical"
    assert [item.label for item in result.items] == ["P4"]

def test_pdf_page_metadata_survives():
    result = select_document_evidence(doc("Example content", page=7), "Example?")
    assert result.items[0].page_number == 7

def test_long_document_no_match_abstention(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_SEGMENTS", "1")
    result = select_document_evidence(doc("alpha", "beta"), "Zeppelin whereabouts?")
    assert result.strategy == "no_match" and not result.items

def test_retrieval_prefers_exact_action_identifier(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_SEGMENTS", "1")
    result = select_document_evidence(doc("Action A-01: due yesterday", "Action A-05: Farah Aziz by 18 December"), "Who owns A-05?")
    assert [item.label for item in result.items] == ["P2"]

def test_long_document_obeys_character_budget(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_SEGMENTS", "2")
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_CHARS", "500")
    result = select_document_evidence(doc("risk migration " * 150, "risk finance " * 150), "What are the risk issues?")
    assert sum(len(item.text) for item in result.items) + 48 * len(result.items) <= 500

def test_empty_question_rejected():
    with pytest.raises(EvidenceSelectionError, match="Enter a question"):
        select_document_evidence(doc("content"), "   ")

def test_overlong_question_rejected(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_QUESTION_CHARS", "50")
    with pytest.raises(EvidenceSelectionError, match="maximum length"):
        select_document_evidence(doc("content"), "a" * 51)

def test_invalid_config_fails_closed(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_CHARS", "bogus")
    with pytest.raises(EvidenceSelectionError, match="Invalid configuration"):
        select_document_evidence(doc("content"), "What is it?")

def test_invalid_indices_rejected():
    obj = Doc("doc", "owner", (Segment(5, "text"),))
    with pytest.raises(EvidenceSelectionError, match="segment identifiers"):
        select_document_evidence(obj, "What?")

def test_no_supabase_or_llm_imports():
    import inspect
    import services.document_evidence_service as service
    code = inspect.getsource(service)
    assert "supabase" not in code.casefold()
    assert "openai" not in code.casefold()


def test_source_order_preserved_after_scoring(monkeypatch):
    monkeypatch.setenv("KH_QA_MAX_EVIDENCE_SEGMENTS", "2")
    result = select_document_evidence(doc("Mars launch schedule", "ignore", "Mars launch Mars milestone"), "Mars launch?")
    assert [item.index for item in result.items] == [0, 2]
