"""M3.5 local-only tests: no Streamlit, network, database or model calls."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.phase5_gate2_budget_service import (
    STATE_KEY, Gate2BudgetError, enabled, operation, record_usage,
    reserve_attempt, snapshot,
)
from services.summarisation_service import (
    SummarisationError, _unsupported_grounding_issues, _quality_issues,
    generate_summary,
)
from services.temporary_document_service import TemporaryDocument, TemporarySegment

S1_TEXT = (
    "SAFETY CHECKLIST PAGE ONE. Site: North Annex. "
    "Inspection date: 14 October 2026. Fire exits checked: 4. "
    "Action: Replace two damaged exit signs.\n"
    "SAFETY CHECKLIST PAGE TWO. Owner: Facilities Team. "
    "Deadline: 21 October 2026. Risk: Blocked access during delivery hours. "
    "Status: Pending replacement of 2 signs."
)
BAD = (
    "The inspection checked four fire exits and identified two damaged exit signs. "
    "The Facilities Team should prioritize replacement to ensure compliance "
    "with safety standards. [P1]"
)
GOOD = (
    "On 14 October 2026, four fire exits were checked at North Annex. "
    "Facilities Team owns replacement of two damaged signs, due 21 October 2026. "
    "The documented risk is blocked access during delivery hours. [P1]"
)


def doc(source=S1_TEXT):
    return TemporaryDocument(
        document_id="s1",owner_user_id="owner-a",filename="S1.txt",extension=".txt",
        size_bytes=len(source),character_count=len(source),page_count=None,
        segments=(TemporarySegment(0,source,None),),warnings=(),
    )


def test_original_s1_grounding_defect_detected():
    issues=_quality_issues(BAD,"Concise",doc())
    assert any("compliance" in s.lower() for s in issues)
    assert any("priority" in s.lower() for s in issues)


def test_clean_s1_summary_accepted():
    assert _quality_issues(GOOD,"Concise",doc())==[]


@pytest.mark.parametrize("sentence", [
    "Ensure compliance with safety standards. [P1]",
    "Achieve regulatory compliance. [P1]",
    "Maintain certification. [P1]",
    "Meet regulatory requirements. [P1]",
    "These changes are compliant with safety standards. [P1]",
])
def test_unsupported_positive_compliance_assertions(sentence):
    assert _unsupported_grounding_issues(sentence,doc())


def test_compliance_negative_statement_permitted():
    assert _unsupported_grounding_issues("No safety standard is specified. [P1]",doc())==[]


def test_explicit_source_compliance_permitted():
    source=S1_TEXT+" The checklist confirms compliance with Safety Standard ABC-123."
    assert _unsupported_grounding_issues("Compliance with Safety Standard ABC-123 is confirmed. [P1]",doc(source))==[]


def test_explicit_source_priority_permitted():
    assert _unsupported_grounding_issues("Replacement is high priority. [P1]",doc(S1_TEXT+" Priority: High."))==[]


def test_unsupported_priority_rejected():
    assert any("priority" in x.lower() for x in _unsupported_grounding_issues("Prioritizing replacement is necessary. [P1]",doc()))


def test_retry_once_with_corrected_response(monkeypatch):
    monkeypatch.setenv("KH_SUMMARY_MAX_CALLS","2")
    responses=iter([BAD,GOOD])
    def fake_invoke(_model,_task,_content,_allowed,_max_chars):
        return next(responses)
    with patch("services.summarisation_service._model",return_value=object()), patch("services.summarisation_service._invoke",side_effect=fake_invoke) as inv:
        result=generate_summary(doc(),"Concise")
    assert result.text==GOOD and result.model_calls==2 and inv.call_count==2


def test_failed_correction_does_not_return_summary(monkeypatch):
    monkeypatch.setenv("KH_SUMMARY_MAX_CALLS","2")
    with patch("services.summarisation_service._model",return_value=object()), patch("services.summarisation_service._invoke",return_value=BAD) as inv:
        with pytest.raises(SummarisationError):
            generate_summary(doc(),"Concise")
    assert inv.call_count==2


def test_one_call_limit_rejects_without_retry(monkeypatch):
    monkeypatch.setenv("KH_SUMMARY_MAX_CALLS","1")
    with patch("services.summarisation_service._model",return_value=object()), patch("services.summarisation_service._invoke",return_value=BAD) as inv:
        with pytest.raises(SummarisationError):generate_summary(doc(),"Concise")
    assert inv.call_count==1


@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setenv("KH_PHASE5_GATE2_BUDGET_ENABLED","1")
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_ESTIMATED_USD","0.10")
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_ATTEMPTS","12")
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_OPERATIONS","6")


def reserve(model="gpt-4o-mini",chars=1000,tokens=1200):
    reserve_attempt(model=model,prompt_chars=chars,max_output_tokens=tokens)


def test_budget_opt_in_default_off(monkeypatch):
    monkeypatch.delenv("KH_PHASE5_GATE2_BUDGET_ENABLED",raising=False)
    assert not enabled()
    reserve()


def test_enabled_requires_operation_scope(guarded):
    with pytest.raises(Gate2BudgetError,match="scope"):reserve()


def test_estimated_attempt_charged_before_invocation(guarded):
    state={}
    with operation(state,"a"):
        reserve()
        assert snapshot(state,"a")["attempts"]==1
        assert Decimal(snapshot(state,"a")["reserved_usd"])>0
    assert snapshot(state,"a")["operations"]==1


def test_failed_attempt_still_charged(guarded):
    state={}
    with pytest.raises(RuntimeError):
        with operation(state,"a"):
            reserve()
            raise RuntimeError("synthetic failure")
    assert snapshot(state,"a")["attempts"]==1


def test_shared_across_document_replacements(guarded):
    state={}
    with operation(state,"a"):reserve()
    # Document replacement does not clear the budget state.
    with operation(state,"a"):reserve()
    assert snapshot(state,"a")["operations"]==2
    assert snapshot(state,"a")["attempts"]==2


def test_max_provider_attempts(guarded,monkeypatch):
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_ATTEMPTS","2")
    state={}
    with operation(state,"a"):
        reserve();reserve()
        with pytest.raises(Gate2BudgetError,match="attempt"):reserve()
    assert snapshot(state,"a")["attempts"]==2


def test_max_operations(guarded,monkeypatch):
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_OPERATIONS","1")
    state={}
    with operation(state,"a"):pass
    with pytest.raises(Gate2BudgetError,match="limit"):
        with operation(state,"a"):pass


def test_estimate_exhausts_before_next_call(guarded,monkeypatch):
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_ESTIMATED_USD","0.00001")
    state={}
    with operation(state,"a"):
        with pytest.raises(Gate2BudgetError,match="spending"):
            reserve()
    assert snapshot(state,"a")["attempts"]==0


def test_unknown_model_price_fails_closed(guarded):
    with operation({},"a"):
        with pytest.raises(Gate2BudgetError,match="estimate"):reserve("unsupported-model")


def test_reported_usage_does_not_refund_reservation(guarded):
    state={}
    with operation(state,"a"):
        reserve()
        before=snapshot(state,"a")["reserved_usd"]
        record_usage(SimpleNamespace(usage_metadata={"input_tokens":100,"output_tokens":50}))
        after=snapshot(state,"a")
        assert before==after["reserved_usd"]
        assert after["reported_input_tokens"]==100 and after["reported_output_tokens"]==50
        assert after["unreported_attempts"]==0


def test_unknown_usage_is_not_treated_as_zero(guarded):
    state={}
    with operation(state,"a"):
        reserve();record_usage(SimpleNamespace())
    assert snapshot(state,"a")["unreported_attempts"]==1


def test_owner_switch_does_not_inherit_budget(guarded):
    state={}
    with operation(state,"alice"):reserve()
    with operation(state,"bob"):reserve()
    assert snapshot(state,"bob")["operations"]==1
    assert snapshot(state,"alice")["operations"]==0


def test_invalid_budget_config_fails_closed(guarded,monkeypatch):
    monkeypatch.setenv("KH_PHASE5_GATE2_MAX_ESTIMATED_USD","NaN")
    with pytest.raises(Gate2BudgetError):
        with operation({},"a"):pass


def test_budget_never_stores_document_text(guarded):
    state={}
    with operation(state,"a"):reserve(chars=250)
    assert set(state[STATE_KEY]) == {"owner","operations","attempts","reserved_usd","reported_input_tokens","reported_output_tokens","unreported_attempts"}
