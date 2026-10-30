"""Phase 3 retrieval-only tests. All remote clients are mocked."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from services.authorization_service import ApplicationAccessError
from services.retrieval_service import RetrievedChunk, RetrievalError, retrieve_chunks


@pytest.fixture
def valid_row():
    return dict(chunk_id="c", document_id="d", version_id="v",
                document_name="manual.txt", version_number=2, chunk_index=0,
                content="Knowledge Hub", page_number=None, source_metadata={},
                similarity=0.76)


@pytest.fixture
def mock_retrieval(valid_row):
    with patch("services.retrieval_service.resolve_application_user") as auth, \
         patch("services.retrieval_service.embed_texts") as embed, \
         patch("services.retrieval_service.get_supabase_client") as factory:
        auth.return_value = SimpleNamespace(access_token="validated-access", refresh_token="validated-refresh")
        embed.return_value = [[0.0] * 1536]
        client = factory.return_value
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=[valid_row])
        yield auth, embed, client, factory


def test_success_uses_user_client_and_rpc(mock_retrieval):
    auth, embed, client, factory = mock_retrieval
    chunks = retrieve_chunks("  What is Knowledge Hub?  ", "access", "refresh", top_k=5, min_similarity=0.2)
    assert len(chunks) == 1 and isinstance(chunks[0], RetrievedChunk)
    assert chunks[0].document_name == "manual.txt"
    auth.assert_called_once_with("access", "refresh")
    embed.assert_called_once_with(["What is Knowledge Hub?"])
    factory.assert_called_once_with()
    client.auth.set_session.assert_called_once_with("validated-access", "validated-refresh")
    assert client.rpc.call_args.args[0] == "match_knowledge_chunks"
    assert client.rpc.call_args.args[1]["match_count"] == 5
    assert client.rpc.call_args.args[1]["min_similarity"] == 0.2


def test_inactive_account_never_embeds_or_calls_rpc(mock_retrieval):
    auth, embed, client, _ = mock_retrieval
    auth.side_effect = ApplicationAccessError("Application account is inactive.")
    with pytest.raises(ApplicationAccessError):
        retrieve_chunks("Test", "access", "refresh")
    embed.assert_not_called()
    client.rpc.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"question": ""}, {"question": "x" * 2001},
    {"question": "Valid", "top_k": 0},
    {"question": "Valid", "top_k": 21},
    {"question": "Valid", "min_similarity": float("nan")},
])
def test_invalid_input_rejected_before_api(mock_retrieval, kwargs):
    auth, embed, client, _ = mock_retrieval
    with pytest.raises(ValueError):
        retrieve_chunks(kwargs.pop("question"), "access", "refresh", **kwargs)
    auth.assert_not_called()
    embed.assert_not_called()
    client.rpc.assert_not_called()


def test_missing_citation_metadata_rejected(mock_retrieval, valid_row):
    _, _, client, _ = mock_retrieval
    valid_row.pop("version_id")
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[valid_row])
    with pytest.raises(RetrievalError):
        retrieve_chunks("Test", "access", "refresh")


def test_low_relevance_row_rejected(mock_retrieval, valid_row):
    valid_row["similarity"] = 0.1
    with pytest.raises(RetrievalError):
        retrieve_chunks("Test", "access", "refresh", min_similarity=0.5)


def test_rpc_failure_safe_error(mock_retrieval):
    _, _, client, _ = mock_retrieval
    client.rpc.return_value.execute.side_effect = RuntimeError("sensitive backend info")
    with pytest.raises(RetrievalError) as caught:
        retrieve_chunks("Test", "access", "refresh")
    assert "sensitive" not in str(caught.value)


def test_empty_repository(mock_retrieval):
    _, _, client, _ = mock_retrieval
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[])
    assert retrieve_chunks("Test", "access", "refresh") == []
