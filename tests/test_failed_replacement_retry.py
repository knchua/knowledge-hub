"""Failed replacement retry tests for the leased ingestion pipeline."""
from unittest.mock import Mock
import pytest
from services import knowledge_ingestion_service as svc
from services.knowledge_service import KnowledgeError

DOC = '11111111-1111-4111-8111-111111111111'
VER = '22222222-2222-4222-8222-222222222222'


def test_retry_replacement_denies_unprivileged_actor(monkeypatch):
    monkeypatch.setattr(svc, '_fresh_admin', Mock(side_effect=KnowledgeError('Denied')))
    client = Mock()
    monkeypatch.setattr(svc, 'get_supabase_admin_client', client)
    with pytest.raises(KnowledgeError, match='Denied'):
        svc.retry_failed_replacement(object(), DOC, VER)
    client.assert_not_called()


def test_retry_replacement_rejects_duplicate_claim(monkeypatch):
    monkeypatch.setattr(svc, '_fresh_admin', Mock(return_value=Mock(user_id=DOC)))
    client = Mock()
    monkeypatch.setattr(svc, 'get_supabase_admin_client', Mock(return_value=client))
    client.rpc.side_effect = ValueError('claimed')
    extract = Mock()
    monkeypatch.setattr(svc, 'extract_chunks', extract)
    with pytest.raises(KnowledgeError, match='Processing not available'):
        svc.retry_failed_replacement(object(), DOC, VER)
    extract.assert_not_called()


def test_retry_replacement_uses_fenced_mode(monkeypatch):
    run = Mock(return_value=2)
    monkeypatch.setattr(svc, '_process', run)
    actor = object()
    assert svc.retry_failed_replacement(actor, DOC, VER) == 2
    run.assert_called_once_with(actor, DOC, VER, mode='retry_replacement')
