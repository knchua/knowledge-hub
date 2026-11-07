"""Source-grounded hierarchical register projection: no OpenAI or network calls."""
from types import SimpleNamespace
import pytest

from services.structured_extraction_service import (
    extract_register, project_structured_summary, StructuredExtractionError,
)
from services.summarisation_service import _quality_issues, _extract_labels


def doc(*segments):
    return SimpleNamespace(segments=tuple(
        SimpleNamespace(index=i, text=part, page_number=None)
        for i, part in enumerate(segments)
    ))


SOURCE = (
    "A-01 — Marcus Lee to fix identity defects by 13 November 2026.\n"
    "A-02 — Priya Nair to appoint assessor by 17 November 2026.\n"
    "Risk R-01 — Identity-provider integration failure: HIGH likelihood / HIGH impact. Mitigation: triage.\n"
    "Risk R-02 — Accessibility rework: MEDIUM likelihood / MEDIUM impact. Mitigation: testing.\n"
    "Final UAT tester count remains unconfirmed."
)


def test_registers_preserve_source_ids_owners_risks_and_citations():
    original = doc(SOURCE)
    register = extract_register(original)
    assert [item[0] for item in register.actions] == ["A-01", "A-02"]
    assert [item[0] for item in register.risks] == ["R-01", "R-02"]
    assert register.actions[0][1].startswith("Marcus Lee")
    result = project_structured_summary(
        "# Overview\nAMBER [P1]\n# Action Items\n- A-01: wrong [P1]\n"
        "- A-03: invented [P1]\n# Risks\n- R-02: wrong High rating [P1]\n"
        "# Missing/Unclear Information\n- Known owner: Marcus Lee [P1]", original
    )
    assert "A-03" not in result
    assert result.count("A-01") == 1
    assert "R-02 — Accessibility rework: MEDIUM likelihood / MEDIUM impact" in result
    assert "Known owner:" not in result
    assert "Final UAT tester count remains unconfirmed" in result
    assert _quality_issues(result, "Structured", original) == []
    assert _extract_labels(result, {"P1"}) == (0,)


def test_no_projection_without_both_authoritative_registers():
    original = doc("A-01 — Marcus Lee to investigate.")
    draft = "# Overview\nSingle register [P1]"
    assert project_structured_summary(draft, original) == draft


def test_register_conflict_fails_closed():
    original = doc("A-01 — Marcus Lee resolves defects.\nA-01 — Priya Nair leads readiness.\n"
                   "Risk R-01 — Identity failure: HIGH likelihood / HIGH impact.")
    with pytest.raises(StructuredExtractionError):
        project_structured_summary("Overview [P1]", original)


def test_incomplete_risk_rating_fails_closed():
    with pytest.raises(StructuredExtractionError):
        extract_register(doc("Risk R-01 — Identity failure: High risk."))


def test_citation_points_to_actual_segment_not_page():
    original = doc("Background unrelated.",
                   "A-01 — Marcus Lee to resolve defects.\n"
                   "Risk R-01 — Identity failure: HIGH likelihood / HIGH impact.")
    output = project_structured_summary("# Overview\nBackground [P1]", original)
    assert "A-01 — Marcus Lee to resolve defects. [P2]" in output
    assert "R-01 — Identity failure: HIGH likelihood / HIGH impact. [P2]" in output


def test_source_register_repeated_in_table_is_not_assumed_authoritative():
    original = doc("Action register IDs A-01, A-02; Risk register IDs R-01, R-02.")
    assert not extract_register(original).actions
    assert not extract_register(original).risks


def test_finalise_hierarchical_summary_overlays_incorrect_model_registers(monkeypatch):
    from services import summarisation_service as ss
    original = doc(SOURCE)
    calls = []
    draft = (
        "# Overview\nThe project has a dependency [P1]\n"
        "# Action Items\n- A-01: wrong owner [P1]\n- A-03: invented [P1]\n"
        "# Risks\n- R-02: different risk and rating [P1]\n"
        "# Missing/Unclear Information\n- Known spending S$123 [P1]"
    )

    def invoke(*args, **kwargs):
        calls.append(True)
        return draft, 1

    monkeypatch.setattr(ss, "_invoke_citation_checked", invoke)
    output, count = ss._verified_final(
        object(), "Structured", "[P1] source", {"P1"}, 16000,
        original, "Structured", 2, source_projection=True,
    )
    assert len(calls) == 1
    assert count == 1
    assert _quality_issues(output, "Structured", original) == []
    assert "A-03" not in output
    assert "Known spending" not in output


def test_projection_rejects_result_exceeding_budget_without_returning_content(monkeypatch):
    from services import summarisation_service as ss
    original = doc(SOURCE)
    monkeypatch.setattr(ss, "_invoke_citation_checked", lambda *a, **k: ("Short [P1]", 1))
    with pytest.raises(ss.SummarisationError, match="output limit"):
        ss._verified_final(object(), "Structured", "[P1]", {"P1"}, 100,
                           original, "Structured", 2, source_projection=True)


def test_proposed_unassigned_action_reference_is_not_an_authoritative_id():
    original = doc(
        SOURCE + "\nA possible A-10 was discussed, but it was not assigned or approved."
    )
    output = project_structured_summary("# Overview\nProgramme update [P1]", original)
    assert "- A-10" not in output
    assert _quality_issues(output, "Structured", original) == []


def test_source_metric_evidence_is_quoted_with_original_thresholds_and_citations():
    original = doc(
        "System integration testing (SIT) started. As of today SIT is 55% complete against a planned 70%. "
        "The SIT completion forecast is 11 December 2026 rather than the original 4 December 2026 target.",
        "Migration rehearsal 1 included 145,000 active customer cases and yielded 98.9% reconciliation. "
        "This is below the 99.8% acceptance threshold.",
        "The estimate at completion (EAC) is S$2,360,000, giving forecast headroom of S$40,000 below the approved ceiling.",
        SOURCE,
    )
    rendered = project_structured_summary("# Overview\nAMBER [P1]", original)
    assert "## Delivery Metrics (Source Evidence)" in rendered
    assert "55% complete against a planned 70%" in rendered
    assert "11 December 2026" in rendered and "4 December 2026" in rendered
    assert "145,000" in rendered and "98.9%" in rendered and "99.8%" in rendered
    assert "S$40,000" in rendered
    assert "[P2]" in rendered and "[P3]" in rendered
    assert _quality_issues(rendered, "Structured", original) == []


def test_no_metric_creation_from_unrelated_numbers():
    original = doc(SOURCE, "The report contains 40 sections and 70 references.")
    assert extract_register(original).delivery_metrics == ()


def test_unresolved_proposal_is_specific_and_confirmed_meeting_not_missing():
    original = doc(
        SOURCE,
        "The provisional contingency proposal is to run one additional evening SIT cycle per week. "
        "This proposal will be evaluated on 12 November and is not yet approved.",
        "The next steering meeting is planned for 19 November 2026 and will review the identity remediation evidence and unresolved UAT roster.",
    )
    rendered = project_structured_summary("# Overview\nAMBER [P1]", original)
    missing = rendered.split("## Missing/Unclear Information", 1)[1]
    assert "one additional evening SIT cycle" in missing
    assert "19 November" not in missing
    assert "[P2]" in missing


def test_repeated_retention_issue_consolidated_by_topic():
    original = doc(
        SOURCE,
        "Unresolved: Legal has not confirmed specialist case archive retention treatment.",
        "An unresolved policy question concerns specialist case archive retention longer than seven years.",
    )
    register = extract_register(original)
    assert sum("retention" in entry[0].casefold() for entry in register.unresolved) == 1


def test_omnibus_unresolved_facts_do_not_repeat_covered_tester_count():
    original = doc(
        SOURCE,
        "The final number of testers is still unconfirmed.",
        "The final UAT tester count, exact rollback recovery-time objective and accessibility assessor name are not established.",
    )
    entries = [item[0] for item in extract_register(original).unresolved]
    assert sum("tester" in text.casefold() for text in entries) == 1


def test_delivery_metric_projection_refuses_output_beyond_budget(monkeypatch):
    from services import summarisation_service as ss
    original = doc(
        SOURCE,
        "The estimate at completion (EAC) is S$2,360,000, giving forecast headroom of S$40,000 below the approved ceiling.",
    )
    monkeypatch.setattr(ss, "_invoke_citation_checked", lambda *a, **kw: ("Short [P1]", 1))
    with pytest.raises(ss.SummarisationError, match="output limit"):
        ss._verified_final(object(), "Structured", "[P1]", {"P1", "P2"}, 120,
                           original, "Structured", 2, source_projection=True)
