"""Pure conversation helper tests. No network or model calls."""
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from services.conversation_service import (
    ChatTurn, MAX_TURNS, MAX_HISTORY_CHARS, bounded_turns, standalone_retrieval_query,
)


def test_empty_history_keeps_original_query():
    assert standalone_retrieval_query("What is the project?", []) == "What is the project?"


def test_invalid_query_rejected():
    with pytest.raises(ValueError):
        standalone_retrieval_query("  ", [])


def test_bounded_turns_limits_history():
    history = [ChatTurn(f"Q{i}", f"A{i}") for i in range(30)]
    result = bounded_turns(history)
    assert len(result) == MAX_TURNS
    assert result[-1].question == "Q29"


def test_history_character_budget():
    history = [ChatTurn("Q" * 1000, "A" * 3500) for _ in range(6)]
    result = bounded_turns(history)
    assert sum(len(t.question) + len(t.answer) for t in result) <= MAX_HISTORY_CHARS


def test_rewrite_uses_model_output():
    with patch("services.conversation_service._model") as model, patch(
        "langchain_core.prompts.ChatPromptTemplate.from_messages"
    ) as from_messages:
        chain = SimpleNamespace(invoke=lambda values: SimpleNamespace(content="What is Knowledge Hub's purpose?"))
        class Prompt:
            def __or__(self, rhs):
                return chain
        from_messages.return_value = Prompt()
        result = standalone_retrieval_query("What is its purpose?", [ChatTurn("Tell me about Knowledge Hub", "It is a project")])
    assert result == "What is Knowledge Hub's purpose?"


def test_failed_rewrite_falls_back_to_original():
    with patch("services.conversation_service._model", side_effect=RuntimeError("provider")):
        assert standalone_retrieval_query("What about it?", [ChatTurn("Q", "A")]) == "What about it?"
