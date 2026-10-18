"""Focused retry control-flow tests. Run alongside the existing regression suite."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from services import knowledge_ingestion_service as svc
from services.knowledge_service import KnowledgeError

DOC = "11111111-1111-4111-8111-111111111111"
VER = "22222222-2222-4222-8222-222222222222"


def test_retry_requires_fresh_admin(monkeypatch):
    monkeypatch.setattr(svc, "_fresh_admin", Mock(side_effect=KnowledgeError("Denied")))
    client = Mock()
    monkeypatch.setattr(svc, "get_supabase_admin_client", Mock(return_value=client))
    with pytest.raises(KnowledgeError, match="Denied"):
        svc.retry_failed_document(object(), DOC, VER)
    client.rpc.assert_not_called()


def test_second_claim_rejected_without_processing(monkeypatch):
    monkeypatch.setattr(svc, "_fresh_admin", Mock(return_value=SimpleNamespace(user_id=DOC)))
    monkeypatch.setattr(svc, "get_supabase_admin_client", Mock(return_value=Mock()))
    monkeypatch.setattr(svc, "claim_failed_version", Mock(side_effect=ValueError("already claimed")))
    work = Mock()
    monkeypatch.setattr(svc, "_run_ingestion", work)
    with pytest.raises(KnowledgeError, match="Retry unavailable"):
        svc.retry_failed_document(object(), DOC, VER)
    work.assert_not_called()


def test_retry_runs_claimed_version(monkeypatch):
    admin = SimpleNamespace(user_id=DOC)
    client = Mock()
    version = {"original_filename": "example.txt", "storage_path": "documents/test"}
    monkeypatch.setattr(svc, "_fresh_admin", Mock(return_value=admin))
    monkeypatch.setattr(svc, "get_supabase_admin_client", Mock(return_value=client))
    monkeypatch.setattr(svc, "claim_failed_version", Mock(return_value=version))
    run = Mock(return_value=3)
    monkeypatch.setattr(svc, "_run_ingestion", run)
    assert svc.retry_failed_document(object(), DOC, VER) == 3
    run.assert_called_once_with(client, admin, DOC, VER, version, is_retry=True)


def test_invalid_identifiers_rejected_before_client(monkeypatch):
    monkeypatch.setattr(svc, "_fresh_admin", Mock(return_value=SimpleNamespace(user_id=DOC)))
    client = Mock()
    monkeypatch.setattr(svc, "get_supabase_admin_client", client)
    with pytest.raises(KnowledgeError, match="Invalid document"):
        svc.retry_failed_document(object(), "bad-id", VER)
    client.assert_not_called()
