from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from services import knowledge_recovery_service as service


def fake_client(version, document):
    client = Mock()
    ver_query = client.table.return_value.select.return_value.eq.return_value
    ver_query.execute.return_value.data = [version]
    doc_query = client.table.return_value.select.return_value.eq.return_value.single.return_value
    doc_query.execute.return_value.data = document
    return client


def test_denied_actor_never_uses_privileged_client(monkeypatch):
    monkeypatch.setattr(service, '_fresh_admin', Mock(side_effect=PermissionError('denied')))
    admin_client = Mock()
    monkeypatch.setattr(service, 'get_supabase_admin_client', admin_client)
    with pytest.raises(PermissionError):
        service.list_stale_ingestion_candidates(object())
    admin_client.assert_not_called()


def test_old_unclaimed_version_is_detected(monkeypatch):
    monkeypatch.setattr(service, '_fresh_admin', Mock(return_value=SimpleNamespace(user_id='admin')))
    old = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    version = {'id':'v1','document_id':'d1','version_number':1,'status':'processing','created_at':old,'processing_claimed_at':None}
    doc = {'id':'d1','display_name':'example.txt','status':'processing','deleted_at':None,'active_version_id':None}
    monkeypatch.setattr(service, 'get_supabase_admin_client', lambda: fake_client(version,doc))
    got = service.list_stale_ingestion_candidates(object())
    assert len(got) == 1 and got[0]['was_claimed'] is False


def test_recent_claim_is_not_reported(monkeypatch):
    monkeypatch.setattr(service, '_fresh_admin', Mock(return_value=True))
    old = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    version = {'id':'v1','document_id':'d1','version_number':1,'status':'processing','created_at':old,'processing_claimed_at':recent}
    monkeypatch.setattr(service, 'get_supabase_admin_client', lambda: fake_client(version,{}))
    assert service.list_stale_ingestion_candidates(object()) == []


def test_threshold_validation(monkeypatch):
    monkeypatch.setattr(service, '_fresh_admin', Mock(return_value=True))
    monkeypatch.setattr(service, 'get_supabase_admin_client', Mock())
    with pytest.raises(ValueError):
        service.list_stale_ingestion_candidates(object(), older_than_minutes=0)
