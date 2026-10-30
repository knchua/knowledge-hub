"""Retry behavior for the fenced ingestion orchestration (migration 006)."""
from unittest.mock import Mock
import pytest
from services import knowledge_ingestion_service as svc
from services.knowledge_service import KnowledgeError

DOC = '11111111-1111-4111-8111-111111111111'
VER = '22222222-2222-4222-8222-222222222222'


def test_retry_requires_fresh_admin(monkeypatch):
    monkeypatch.setattr(svc, '_fresh_admin', Mock(side_effect=KnowledgeError('Denied')))
    client = Mock()
    monkeypatch.setattr(svc, 'get_supabase_admin_client', Mock(return_value=client))
    with pytest.raises(KnowledgeError, match='Denied'):
        svc.retry_failed_document(object(), DOC, VER)
    client.rpc.assert_not_called()


def test_second_claim_rejected_without_processing(monkeypatch):
    monkeypatch.setattr(svc, '_fresh_admin', Mock(return_value=Mock(user_id=DOC)))
    client = Mock()
    monkeypatch.setattr(svc, 'get_supabase_admin_client', Mock(return_value=client))
    client.rpc.side_effect = ValueError('already claimed')
    extract = Mock()
    monkeypatch.setattr(svc, 'extract_chunks', extract)
    with pytest.raises(KnowledgeError, match='Processing not available'):
        svc.retry_failed_document(object(), DOC, VER)
    client.rpc.assert_called_once()
    extract.assert_not_called()


def test_retry_claim_uses_retry_initial_mode(monkeypatch):
    run = Mock(return_value=3)
    monkeypatch.setattr(svc, '_process', run)
    actor = object()
    assert svc.retry_failed_document(actor, DOC, VER) == 3
    run.assert_called_once_with(actor, DOC, VER, mode='retry_initial')


def test_invalid_identifiers_rejected_before_client(monkeypatch):
    monkeypatch.setattr(svc, '_fresh_admin', Mock(return_value=Mock(user_id=DOC)))
    client = Mock()
    monkeypatch.setattr(svc, 'get_supabase_admin_client', client)
    with pytest.raises(KnowledgeError, match='Invalid document'):
        svc.retry_failed_document(object(), 'bad-id', VER)
    client.assert_not_called()
