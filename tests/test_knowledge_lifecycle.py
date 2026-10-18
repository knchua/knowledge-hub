from unittest.mock import Mock
from types import SimpleNamespace
import pytest
from services import knowledge_lifecycle_service as lifecycle
from services import knowledge_ingestion_service as ingestion
from services.knowledge_service import KnowledgeError

DOC='11111111-1111-4111-8111-111111111111'
VER='22222222-2222-4222-8222-222222222222'


def test_replacement_requires_fresh_admin(monkeypatch):
    monkeypatch.setattr(lifecycle,'_fresh_admin',Mock(side_effect=KnowledgeError('Denied')))
    client=Mock()
    monkeypatch.setattr(lifecycle,'get_supabase_admin_client',client)
    with pytest.raises(KnowledgeError,match='Denied'):
        lifecycle.stage_replacement(object(),DOC,'a.txt',b'text')
    client.assert_not_called()


def test_delete_requires_confirmation(monkeypatch):
    monkeypatch.setattr(lifecycle,'_fresh_admin',Mock(return_value=SimpleNamespace(user_id=DOC)))
    client=Mock()
    monkeypatch.setattr(lifecycle,'get_supabase_admin_client',client)
    with pytest.raises(KnowledgeError,match='DELETE'):
        lifecycle.delete_document(object(),DOC,'not confirmed')
    client.assert_not_called()


def test_replacement_claim_rejection_never_ingests(monkeypatch):
    monkeypatch.setattr(ingestion,'_fresh_admin',Mock(return_value=SimpleNamespace(user_id=DOC)))
    monkeypatch.setattr(ingestion,'get_supabase_admin_client',Mock(return_value=Mock()))
    monkeypatch.setattr(ingestion,'claim_replacement_version',Mock(side_effect=ValueError('claimed')))
    run=Mock()
    monkeypatch.setattr(ingestion,'_run_ingestion',run)
    with pytest.raises(KnowledgeError,match='unavailable'):
        ingestion.process_replacement(object(),DOC,VER)
    run.assert_not_called()


def test_deletion_marks_invisible_before_cleanup(monkeypatch):
    admin=SimpleNamespace(user_id=DOC)
    monkeypatch.setattr(lifecycle,'_fresh_admin',Mock(return_value=admin))
    client=Mock()
    monkeypatch.setattr(lifecycle,'get_supabase_admin_client',Mock(return_value=client))
    monkeypatch.setattr(lifecycle,'write_audit_log',Mock())
    finish=Mock()
    monkeypatch.setattr(lifecycle,'finish_deletion',finish)
    lifecycle.delete_document(object(),DOC,'DELETE')
    client.rpc.assert_called_once_with('mark_knowledge_document_deleting',{'p_document_id':DOC})
    finish.assert_called_once()


def test_cleanup_refuses_unclaimed_version(monkeypatch):
    client=Mock()
    client.rpc.return_value.execute.return_value.data=[]
    with pytest.raises(KnowledgeError,match='claimed'):
        lifecycle._cleanup_one(client,DOC,VER)
    client.storage.from_.assert_not_called()
