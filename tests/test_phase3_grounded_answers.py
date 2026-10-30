"""Phase 3 answer and citation tests; no real OpenAI/Supabase calls."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from services.retrieval_service import RetrievedChunk
from services.rag_service import generate_grounded_answer, ABSTAIN, AnswerGenerationError
from services.citation_service import make_citations, cited_sources


def sample():
    return RetrievedChunk(chunk_id="c1", document_id="d1", version_id="v2",
        document_name="test_knowledge.txt", version_number=2, chunk_index=0,
        content="Knowledge Hub is a document-grounded question answering app.",
        page_number=None, source_metadata={}, similarity=.73)


def test_citation_comes_from_backend():
    refs = make_citations([sample()]); sources = cited_sources("It is a document app [S1].", refs)
    assert sources[0].document_name == "test_knowledge.txt"
    assert sources[0].chunk_id == "c1"
    assert sources[0].excerpt.startswith("Knowledge Hub")


def test_fabricated_reference_rejected():
    with pytest.raises(ValueError):
        cited_sources("Fabricated [S2]", make_citations([sample()]))


def test_no_retrieval_no_model_call():
    with patch("services.rag_service.retrieve_chunks", return_value=[]), patch("services.rag_service._model") as model:
        out = generate_grounded_answer("Question", "access", "refresh")
        assert out.abstained and out.answer == ABSTAIN and not out.citations
        model.assert_not_called()


class PromptStub:
    def __or__(self, model):
        return model


@pytest.mark.parametrize("content,abstained", [
    ("Knowledge Hub handles documents [S1].", False),
    ("INSUFFICIENT_EVIDENCE", True),
    ("Fake citation [S9]", True),
    ("Unsupported answer without any sources", True),
])
def test_generation_fail_closed(content, abstained):
    fake = SimpleNamespace(invoke=lambda args: SimpleNamespace(content=content))
    with patch("services.rag_service.retrieve_chunks", return_value=[sample()]), \
         patch("services.rag_service._model", return_value=fake), \
         patch("langchain_core.prompts.ChatPromptTemplate.from_messages", return_value=PromptStub()):
        out = generate_grounded_answer("What is it?", "access", "refresh")
    assert out.abstained is abstained
    assert (len(out.citations) == 0) if abstained else (out.citations[0].label == "S1")


def test_model_failure_safe():
    class FailingModel:
        def invoke(self, args):
            raise RuntimeError("provider secret error")
    with patch("services.rag_service.retrieve_chunks", return_value=[sample()]), \
         patch("services.rag_service._model", return_value=FailingModel()), \
         patch("langchain_core.prompts.ChatPromptTemplate.from_messages", return_value=PromptStub()):
        with pytest.raises(AnswerGenerationError) as exc:
            generate_grounded_answer("What?", "access", "refresh")
        assert "secret" not in str(exc.value)
