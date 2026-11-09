"""Adaptive summary formatting tests; no OpenAI or Supabase calls."""
from types import SimpleNamespace
from unittest.mock import patch

from services.summary_section_service import prune_inapplicable_sections
from services.summarisation_service import MODE_TASKS, _verified_final
from services.structured_extraction_service import project_structured_summary


def test_removes_empty_sections_and_placeholder_sections():
    value = ("# Overview\nCPF LIFE provides lifelong payouts. [P1]\n"
             "# Decisions\nNot found in the document.\n"
             "# Action Items\n- Not found in the document.\n"
             "# Eligibility\nMembers can join from age 65. [P2]\n")
    actual = prune_inapplicable_sections(value)
    assert "# Decisions" not in actual
    assert "# Action Items" not in actual
    assert "# Eligibility" in actual
    assert "[P1]" in actual and "[P2]" in actual


def test_keeps_meaningful_sections_and_removes_only_placeholder_lines():
    source = "## Plans\n- Three plans are described. [P1]\n- Not found in the document.\n## Exceptions\nNo information provided."
    actual = prune_inapplicable_sections(source)
    assert "## Plans" in actual
    assert "Three plans" in actual
    assert "## Exceptions" not in actual
    assert "Not found" not in actual


def test_handles_empty_heading_and_not_applicable():
    assert prune_inapplicable_sections("# Objectives\n\n# Features\n- Capital guaranteed. [P1]\n# Risks\nNot applicable.") == "# Features\n\n- Capital guaranteed. [P1]"


def test_does_not_remove_real_information_or_currency():
    text = (
        "# Eligibility\n"
        "No minimum CPF savings is required. [P1]\n"
        "# Features\n"
        "Premium earns up to 6% per annum. [P2]"
    )

    result = prune_inapplicable_sections(text)

    # Valid sections must remain unchanged.
    assert result == text

    # Preserve factual information and citations.
    assert "No minimum CPF savings is required. [P1]" in result
    assert "Premium earns up to 6% per annum. [P2]" in result


def test_preserves_unstructured_summary_without_headings():
    text = "CPF LIFE is described as a longevity insurance annuity scheme. [P1]"
    assert prune_inapplicable_sections(text) == text


def test_model_tasks_are_document_adaptive():
    for mode in ("Structured", "Detailed"):
        prompt = MODE_TASKS[mode].lower()
        assert "omit" in prompt and "heading" in prompt
        assert "faq" in prompt
        assert "not found in the document" in prompt
    assert "at most 200 words" in MODE_TASKS["Concise"]


def test_final_validation_prunes_empty_structured_sections():
    source = SimpleNamespace(segments=(SimpleNamespace(index=0, text="CPF LIFE is lifelong income.", page_number=None),))
    draft = "# Overview\nCPF LIFE provides lifelong income. [P1]\n# Risks\nNot found in the document."
    with patch("services.summarisation_service._invoke_citation_checked", return_value=(draft, 1)):
        actual, consumed = _verified_final(object(), "Structured", "evidence", {"P1"}, 16000, source, "Structured", 2)
    assert consumed == 1 and "# Risks" not in actual
    assert "# Overview" in actual


def test_final_validation_prunes_empty_detailed_sections():
    source = SimpleNamespace(segments=(SimpleNamespace(index=0, text="Members can join from age 65.", page_number=None),))
    draft = "# Eligibility\nMembers can join from age 65. [P1]\n# Financial Position\nNot found in the document."
    with patch("services.summarisation_service._invoke_citation_checked", return_value=(draft, 1)):
        actual, consumed = _verified_final(object(), "Detailed", "evidence", {"P1"}, 16000, source, "Detailed", 2)
    assert consumed == 1 and "Financial Position" not in actual
    assert "Eligibility" in actual


def test_project_register_projection_omits_missing_section_when_none_unresolved():
    doc = SimpleNamespace(segments=(SimpleNamespace(index=0, text=(
        "A-01 — Marcus Lee to resolve defects.\n"
        "Risk R-01 — Identity integration failure: HIGH likelihood / HIGH impact."
    ), page_number=None),))
    projected = project_structured_summary("# Overview\nAMBER. [P1]", doc)
    assert "## Action Items" in projected
    assert "## Risks" in projected
    assert "## Missing/Unclear Information" not in projected


def test_project_register_projection_keeps_unresolved_when_present():
    doc = SimpleNamespace(segments=(SimpleNamespace(index=0, text=(
        "A-01 — Marcus Lee to resolve defects.\n"
        "Risk R-01 — Identity integration failure: HIGH likelihood / HIGH impact.\n"
        "Final UAT tester count remains unconfirmed."
    ), page_number=None),))
    projected = project_structured_summary("# Overview\nAMBER. [P1]", doc)
    assert "## Missing/Unclear Information" in projected
    assert "unconfirmed" in projected


def test_cited_placeholders_and_inline_label_removed():
    source = "# FAQ\nFacts [P1]\n# Decisions\n- **Decision:** Not found in the document. [P2]"
    actual = prune_inapplicable_sections(source)
    assert "Decisions" not in actual
    assert "Facts [P1]" in actual
