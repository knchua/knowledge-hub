"""No network calls: Phase 4 summarisation and privacy regressions."""
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from services.temporary_document_service import TemporaryDocument, TemporarySegment
from services.summarisation_service import (
    SummarisationError, generate_summary, _extract_labels,
)
from services.document_summary_service import summarise_current_document
from services.document_analysis_service import DOCUMENT, RESULTS, clear_document


def sample_document(n=2):
    return TemporaryDocument(
        document_id="doc-1", owner_user_id="user-a", filename="test.txt",
        extension=".txt", size_bytes=30, character_count=60, page_count=None,
        segments=tuple(TemporarySegment(i, f"Meeting outcome {i}: action assigned.", None)
                       for i in range(n)), warnings=(),
    )


class StubChain:
    def __init__(self, replies):
        self.replies = replies
    def invoke(self, variables):
        return SimpleNamespace(content=self.replies.pop(0))


class StubPrompt:
    def __init__(self, replies):
        self.replies = replies
    def __or__(self, _model):
        return StubChain(self.replies)


def mock_pipeline(replies):
    from langchain_core.prompts import ChatPromptTemplate
    return patch.object(ChatPromptTemplate, "from_messages", return_value=StubPrompt(replies))


def test_single_group_grounded_summary():
    with patch("services.summarisation_service._model", return_value=object()), mock_pipeline(["Outcome: action assigned. [P1]"]):
        result = generate_summary(sample_document(), "Concise")
    assert result.document_id == "doc-1"
    assert result.source_segments == (0,)
    assert result.model_calls == 1


def test_long_document_all_groups_processed():
    docs = sample_document(4)
    # Deterministically force one segment per batch.
    with patch("services.summarisation_service._group_segments", return_value=[[s] for s in docs.segments]), \
         patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Section 1 [P1]", "Section 2 [P2]", "Section 3 [P3]", "Section 4 [P4]", "Overall [P1] [P2] [P3] [P4]"]):
        result = generate_summary(docs, "Detailed")
    assert result.model_calls == 5
    assert result.source_segments == (0, 1, 2, 3)


def test_no_silent_omission_when_call_budget_exceeded(monkeypatch):
    monkeypatch.setenv("KH_SUMMARY_MAX_CALLS", "2")
    docs = sample_document(4)
    with patch("services.summarisation_service._group_segments", return_value=[[s] for s in docs.segments]), \
         patch("services.summarisation_service._model") as model:
        with pytest.raises(SummarisationError, match="processing budget"):
            generate_summary(docs, "Structured")
        model.assert_not_called()


def test_invalid_citation_rejected():
    with pytest.raises(SummarisationError, match="source references"):
        _extract_labels("Not supported [P99]", {"P1"})
    with pytest.raises(SummarisationError, match="source references"):
        _extract_labels("Unsupported without citations", {"P1"})


def test_api_failure_returns_safe_error():
    with patch("services.summarisation_service._model", return_value=object()), mock_pipeline(["temporary"]):
        # Prompt returns a response without evidence.
        with pytest.raises(SummarisationError):
            generate_summary(sample_document(), "Concise")


def test_authorization_before_model_and_no_persisted_result_on_denial():
    state = {DOCUMENT: sample_document()}
    with patch("services.document_summary_service.current_document", side_effect=RuntimeError("denied")), \
         patch("services.document_summary_service.generate_summary") as model:
        with pytest.raises(RuntimeError):
            summarise_current_document(state, None, "Concise")
        model.assert_not_called()
        assert RESULTS not in state


def test_document_clear_removes_summary_and_mode():
    state = {DOCUMENT: sample_document(), RESULTS: {("doc-1", "Concise"): "secret"},
             "phase4_summary_mode": "Concise"}
    clear_document(state)
    assert DOCUMENT not in state
    assert RESULTS not in state
    assert "phase4_summary_mode" not in state

# Milestone 3 accuracy-focused regression scenarios.
from services.summarisation_service import _quality_issues, _source_risks


def project_document():
    content = (
        "Budget S$480,000. Spent S$218,000. Forecast S$472,000. "
        "Risk R-01 — Identity-provider integration: testing delays. "
        "Likelihood: High. Impact: High. Mitigation: daily triage. "
        "Risk R-02 — Accessibility assessment: potential rework. "
        "Likelihood: Medium. Impact: Medium. Mitigation: engage assessor."
    )
    return TemporaryDocument(
        document_id="project-1", owner_user_id="user-a", filename="project.txt",
        extension=".txt", size_bytes=100, character_count=len(content),
        page_count=None, segments=(TemporarySegment(0, content, None),), warnings=(),
    )


def test_extract_ratings_from_original_evidence():
    assert _source_risks(project_document()) == {
        "R-01": ("High", "High"), "R-02": ("Medium", "Medium"),
    }


def test_reject_malformed_currency_and_invented_financial_numbers():
    doc = project_document()
    corrupt = "Spent S`218,000hasbeenspent, forecast S`472,000. [P1]"
    assert "Malformed currency notation" in _quality_issues(corrupt, "Detailed", doc)
    assert "Financial amount not present in source" in _quality_issues(
        "Projected cost S$999,000. [P1]", "Detailed", doc
    )


def test_reject_grouped_risk_ratings_and_accept_separate_ratings():
    doc = project_document()
    grouped = "High risks: R-01 and R-02 involve delays. [P1]"
    assert _quality_issues(grouped, "Concise", doc)
    valid = (
        "Risks: R-01 has High likelihood and High impact. "
        "R-02 has Medium likelihood and Medium impact. "
        "Forecast S$472,000. [P1]"
    )
    assert _quality_issues(valid, "Concise", doc) == []


def test_reject_detailed_report_returned_in_concise_mode():
    doc = sample_document()
    report = "\n".join(f"{i}. Extensive section [P1]" for i in range(1, 9))
    assert "Concise summary contains too many numbered sections" in _quality_issues(
        report, "Concise", doc
    )
    assert "Concise summary exceeds the word budget" in _quality_issues(
        "word " * 230 + "[P1]", "Concise", doc
    )


def test_invalid_response_is_regenerated_once_and_not_silently_persisted():
    doc = project_document()
    first = "High risks R-01 and R-02. Spent S`218,000hasbeenspent. [P1]"
    corrected = (
        "Risks: R-01 has High likelihood and High impact. "
        "R-02 has Medium likelihood and Medium impact. "
        "Spent S$218,000, forecast S$472,000. [P1]"
    )
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline([first, corrected]):
        result = generate_summary(doc, "Concise")
    assert result.model_calls == 2
    assert result.text == corrected


def test_repeated_invalid_response_never_accepted():
    doc = project_document()
    invalid = "Both R-01 and R-02 have High risk. S`218,000. [P1]"
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline([invalid, invalid]):
        with pytest.raises(SummarisationError, match="accuracy checks"):
            generate_summary(doc, "Concise")

# Milestone 3 citation repair regression scenarios.

def test_structured_summary_repairs_out_of_range_source_label():
    doc = sample_document(2)
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Decision approved [P999]", "Decision approved [P2]"]):
        result = generate_summary(doc, "Structured")
    assert result.text == "Decision approved [P2]"
    assert result.source_segments == (1,)
    assert result.model_calls == 2


def test_structured_summary_repeated_invalid_citation_fails_closed():
    doc = sample_document(2)
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Decision [P999]", "Decision [P999]"]):
        with pytest.raises(SummarisationError, match="invalid source references"):
            generate_summary(doc, "Structured")


def test_long_map_stage_repairs_only_within_batch_labels():
    doc = sample_document(3)
    with patch("services.summarisation_service._group_segments", return_value=[[s] for s in doc.segments]), \
         patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Section [P2]", "Section [P1]", "Section [P2]", "Section [P3]", "Final [P1][P2][P3]"]):
        result = generate_summary(doc, "Structured")
    assert result.model_calls == 5
    assert result.source_segments == (0, 1, 2)


def test_retry_not_attempted_when_call_budget_would_be_exceeded(monkeypatch):
    monkeypatch.setenv("KH_SUMMARY_MAX_CALLS", "1")
    doc = sample_document(1)
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Not grounded [P999]"]):
        with pytest.raises(SummarisationError, match="budget"):
            generate_summary(doc, "Structured")


def test_missing_citations_can_be_regenerated():
    doc = sample_document(1)
    with patch("services.summarisation_service._model", return_value=object()), \
         mock_pipeline(["Statement without a source", "Statement with source [P1]"]):
        result = generate_summary(doc, "Structured")
    assert result.model_calls == 2

# Milestone 3: structured-register integrity (deterministic, no model calls).
from services.summarisation_service import _structured_issues, _source_risk_ratings


def register_document():
    text = (
        "A-01 — Marcus Lee to resolve integration defects by 13 Nov 2026.\n"
        "A-02 — Priya Nair to appoint accessibility assessor by 17 Nov 2026.\n"
        "Risk R-01 — Identity-provider integration failure: HIGH likelihood / HIGH impact. "
        "Mitigation: daily triage.\n"
        "Risk R-02 — Accessibility rework: MEDIUM likelihood / MEDIUM impact. "
        "Mitigation: early assessment.\n"
        "UAT participant count not confirmed."
    )
    return TemporaryDocument(
        document_id="register-doc", owner_user_id="user-a", filename="register.txt",
        extension=".txt", size_bytes=len(text.encode()), character_count=len(text),
        page_count=None, segments=(TemporarySegment(0, text, None),), warnings=(),
    )


def test_structured_register_valid_ids_owners_topics_and_ratings():
    valid = """# Overview
Test programme. [P1]
# Action Items
- A-01: Marcus Lee resolves integration defects [P1]
- A-02: Priya Nair appoints assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Accessibility rework [P1]
  - Likelihood: Medium
  - Impact: Medium
# Missing/Unclear Information
- Final UAT participant count is not confirmed [P1]
"""
    assert _source_risk_ratings(register_document()) == {
        "R-01": ("high", "high"), "R-02": ("medium", "medium")
    }
    assert _structured_issues(valid, register_document()) == []


def test_structured_register_duplicate_actions_and_renumbering_rejected():
    invalid = """# Action Items
- A-01: Marcus Lee [P1]
- A-02: Priya Nair [P1]
- A-01: Marcus Lee repeated [P1]
- A-03: Marcus Lee invented [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Accessibility rework [P1]
  - Likelihood: Medium
  - Impact: Medium
"""
    issues = _structured_issues(invalid, register_document())
    assert any("duplicated" in issue for issue in issues)
    assert any("renumbered or invented" in issue for issue in issues)


def test_structured_register_wrong_action_owner_and_risk_topic_rejected():
    invalid = """# Action Items
- A-01: Priya Nair resolves defects [P1]
- A-02: Marcus Lee books assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Vendor defect ageing [P1]
  - Likelihood: Medium
  - Impact: Medium
"""
    issues = _structured_issues(invalid, register_document())
    assert any("owner" in issue for issue in issues)
    assert any("risk title" in issue for issue in issues)


def test_structured_register_incorrect_risk_ratings_rejected():
    invalid = """# Action Items
- A-01: Marcus Lee resolves defects [P1]
- A-02: Priya Nair books assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Accessibility rework [P1]
  - Likelihood: High
  - Impact: High
"""
    issues = _structured_issues(invalid, register_document())
    assert any("risk ratings" in issue for issue in issues)


def test_structured_missing_section_rejects_asserted_known_facts():
    invalid = """# Action Items
- A-01: Marcus Lee [P1]
- A-02: Priya Nair [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Accessibility rework [P1]
  - Likelihood: Medium
  - Impact: Medium
# Missing/Unclear Information
- Forecast headroom is S$40,000 [P1]
- UAT roster is not confirmed [P1]
"""
    assert any("Missing/Unclear" in issue for issue in _structured_issues(invalid, register_document()))


def test_structured_incorrect_register_retried_once_and_corrected():
    doc = register_document()
    invalid = "# Action Items\n- A-01: Marcus Lee [P1]\n- A-03: invented [P1]\n"
    valid = """# Action Items
- A-01: Marcus Lee resolves integration defects [P1]
- A-02: Priya Nair appoints accessibility assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  - Likelihood: High
  - Impact: High
- R-02: Accessibility rework [P1]
  - Likelihood: Medium
  - Impact: Medium
# Missing/Unclear Information
- UAT participant count not confirmed [P1]
"""
    with patch("services.summarisation_service._model", return_value=object()), mock_pipeline([invalid, valid]):
        result = generate_summary(doc, "Structured")
    assert result.model_calls == 2
    assert result.text == valid.strip()

# Milestone 3 diagnostic/formatting-tolerance regressions.
from services.summarisation_service import _diagnostic_categories, _diagnostic_error


def test_structured_action_owner_on_next_line_is_accepted():
    text = """# Action Items
- A-01: Resolve integration defects by 13 Nov 2026 [P1]
  Owner: Marcus Lee
- A-02: Appoint accessibility assessor by 17 Nov 2026 [P1]
  Owner: Priya Nair
# Risks
- R-01: Identity-provider integration failure, High likelihood and High impact [P1]
- R-02: Accessibility rework, Medium likelihood and Medium impact [P1]
# Missing/Unclear Information
- UAT participant count remains unconfirmed [P1]
"""
    assert _structured_issues(text, register_document()) == []


def test_structured_risk_natural_language_rating_accepted():
    text = """# Action Items
- A-01: Marcus Lee resolves integration defects [P1]
- A-02: Priya Nair appoints assessor [P1]
# Risks
- R-01: Identity-provider integration failure has High likelihood and High impact [P1]
- R-02: Accessibility rework has Medium likelihood and Medium impact [P1]
"""
    assert _structured_issues(text, register_document()) == []


def test_structured_wrong_rating_still_rejected_with_prose():
    text = """# Action Items
- A-01: Marcus Lee resolves integration defects [P1]
- A-02: Priya Nair appoints assessor [P1]
# Risks
- R-01: Identity-provider integration failure has High likelihood and High impact [P1]
- R-02: Accessibility rework has High likelihood and High impact [P1]
"""
    assert any("ratings" in x for x in _structured_issues(text, register_document()))


def test_missing_info_continuation_contains_uncertainty_is_accepted():
    text = """# Action Items
- A-01: Marcus Lee resolves defects [P1]
- A-02: Priya Nair appoints assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  Likelihood: High; Impact: High
- R-02: Accessibility rework [P1]
  Likelihood: Medium; Impact: Medium
# Missing/Unclear Information
- Final number of UAT participants:
  Not confirmed as of the report date. [P1]
"""
    assert _structured_issues(text, register_document()) == []


def test_failure_diagnostics_are_fixed_categories_without_source_text():
    issues = ["Structured action owner missing or mismatched", "Structured risk ratings missing or inconsistent"]
    assert _diagnostic_categories(issues) == ("action_ownership", "risk_ratings")
    error = str(_diagnostic_error(issues))
    assert "action_ownership" in error
    assert "risk_ratings" in error
    assert "Marcus Lee" not in error
    assert "source" not in error.casefold()


def test_repeated_failure_exposes_safe_category_only():
    doc = register_document()
    invalid = """# Action Items
- A-01: Priya Nair resolves defects [P1]
- A-02: Marcus Lee books assessor [P1]
# Risks
- R-01: Identity-provider integration failure [P1]
  Likelihood: High; Impact: High
- R-02: Accessibility rework [P1]
  Likelihood: Medium; Impact: Medium
"""
    with patch("services.summarisation_service._model", return_value=object()), mock_pipeline([invalid, invalid]):
        with pytest.raises(SummarisationError, match="action_ownership"):
            generate_summary(doc, "Structured")
