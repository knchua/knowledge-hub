from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from services import knowledge_ingestion_service as svc
from services.knowledge_service import KnowledgeError

DOC="11111111-1111-4111-8111-111111111111"
VER="22222222-2222-4222-8222-222222222222"

def test_retry_replacement_denies_unprivileged_actor(monkeypatch):
    monkeypatch.setattr(svc,"_fresh_admin",Mock(side_effect=KnowledgeError("Denied")))
    get_client=Mock()
    monkeypatch.setattr(svc,"get_supabase_admin_client",get_client)
    with pytest.raises(KnowledgeError,match="Denied"):
        svc.retry_failed_replacement(object(),DOC,VER)
    get_client.assert_not_called()

def test_retry_replacement_rejects_duplicate_claim(monkeypatch):
    monkeypatch.setattr(svc,"_fresh_admin",Mock(return_value=SimpleNamespace(user_id=DOC)))
    monkeypatch.setattr(svc,"get_supabase_admin_client",Mock(return_value=Mock()))
    monkeypatch.setattr(svc,"claim_failed_replacement_version",Mock(side_effect=ValueError("claimed")))
    worker=Mock()
    monkeypatch.setattr(svc,"_run_ingestion",worker)
    with pytest.raises(KnowledgeError,match="unavailable"):
        svc.retry_failed_replacement(object(),DOC,VER)
    worker.assert_not_called()

def test_retry_replacement_reuses_pipeline(monkeypatch):
    admin=SimpleNamespace(user_id=DOC); client=Mock()
    version={"original_filename":"test.txt","storage_path":"documents/test"}
    monkeypatch.setattr(svc,"_fresh_admin",Mock(return_value=admin))
    monkeypatch.setattr(svc,"get_supabase_admin_client",Mock(return_value=client))
    monkeypatch.setattr(svc,"claim_failed_replacement_version",Mock(return_value=version))
    runner=Mock(return_value=2)
    monkeypatch.setattr(svc,"_run_ingestion",runner)
    assert svc.retry_failed_replacement(object(),DOC,VER)==2
    runner.assert_called_once_with(client,admin,DOC,VER,version,is_retry=True)
