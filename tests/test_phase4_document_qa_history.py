"""Checkpoint 4D session-only history contract tests."""
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
import services.document_qa_history_service as history


@dataclass(frozen=True)
class Doc:
    document_id: str = "doc-1"
    owner_user_id: str = "owner-1"


def answer(doc="doc-1", question="Who owns A-05?"):
    return SimpleNamespace(document_id=doc, question=question, text="Farah [P1]", cited_evidence=(), abstained=False)


@pytest.fixture
def setup(monkeypatch):
    state = {}
    active = {"doc": Doc()}
    monkeypatch.setattr(history, "current_document", lambda state, actor: active["doc"])
    monkeypatch.setattr(history, "answer_document_question", lambda state, actor, question: answer(question=question))
    return state, active, monkeypatch


def test_records_successful_turn(setup):
    state, _, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    turns = history.read_qa_history(state, object())
    assert len(turns) == 1 and turns[0].owner_id == "owner-1"
    assert turns[0].question == "Who owns A-05?"


def test_bounded_history(setup):
    state, _, _ = setup
    for i in range(15):
        history.ask_and_record(state, object(), f"Question {i} about A-05?")
    turns = history.read_qa_history(state, object())
    assert len(turns) == history.HISTORY_LIMIT
    assert turns[0].question == "Question 7 about A-05?"


def test_followup_carries_one_explicit_record_id(setup):
    state, _, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    result = history.ask_and_record(state, object(), "When is it due?")
    assert "A-05" in result.question
    assert history.read_qa_history(state, object())[-1].question == "When is it due?"


def test_followup_does_not_guess_ambiguous_reference(setup):
    state, _, _ = setup
    history.ask_and_record(state, object(), "Compare A-05 and A-06")
    assert history.ask_and_record(state, object(), "When is it due?").question == "When is it due?"


def test_followup_with_explicit_id_not_overridden(setup):
    state, _, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    assert history.ask_and_record(state, object(), "When is R-02 reviewed?").question == "When is R-02 reviewed?"


def test_replacement_clears_history(setup):
    state, active, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    active["doc"] = Doc("doc-2", "owner-1")
    assert history.read_qa_history(state, object()) == ()
    assert history.QA_HISTORY not in state


def test_identity_change_clears_history(setup):
    state, active, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    active["doc"] = Doc("doc-1", "other-owner")
    assert not history.read_qa_history(state, object())


def test_document_clear_clears_history(setup):
    state, active, _ = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    active["doc"] = None
    assert history.read_qa_history(state, object()) == ()


def test_clear_control_only_clears_chat(setup):
    state, active, _ = setup
    state["phase4_results"] = {"summary": "present"}
    history.ask_and_record(state, object(), "Who owns A-05?")
    history.clear_qa_history(state, object())
    assert history.QA_HISTORY not in state
    assert state["phase4_results"] == {"summary": "present"}


def test_failed_model_call_is_not_appended(setup):
    state, _, patch = setup
    history.ask_and_record(state, object(), "Who owns A-05?")
    def fail(*args):
        raise history.DocumentQAError("Invalid citations")
    patch.setattr(history, "answer_document_question", fail)
    with pytest.raises(history.DocumentQAError):
        history.ask_and_record(state, object(), "When is it due?")
    assert len(history.read_qa_history(state, object())) == 1


def test_changed_document_during_model_call_fails_closed(setup):
    state, active, patch = setup
    def change(state, actor, question):
        active["doc"] = Doc("doc-2", "owner-1")
        return answer()
    patch.setattr(history, "answer_document_question", change)
    with pytest.raises(history.DocumentQAError, match="changed"):
        history.ask_and_record(state, object(), "Who owns A-05?")
    assert history.QA_HISTORY not in state


def test_empty_question_does_not_call_model(setup):
    state, _, patch = setup
    def fail(*args):
        raise AssertionError("Should never call model")
    patch.setattr(history, "answer_document_question", fail)
    with pytest.raises(history.DocumentQAError, match="Enter a question"):
        history.ask_and_record(state, object(), "  ")


def test_invalid_history_type_fails_closed(setup):
    state, _, _ = setup
    state[history.QA_HISTORY] = "bad state"
    assert history.read_qa_history(state, object()) == ()
    assert history.QA_HISTORY not in state
