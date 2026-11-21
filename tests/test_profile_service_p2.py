"""P2 profile service tests with pytest-scoped mocks; safe for full suite collection."""
import types
from unittest.mock import MagicMock

import pytest

from services import profile_service as profile


class ApplicationUserContext:
    """Local test identity; does not replace the production identity type."""
    def __init__(self, role="user", is_active=True, user_id="u1"):
        self.user_id = user_id
        self.email = "person@example.test"
        self.role = role
        self.is_active = is_active
        self.access_token = "synthetic-access"
        self.refresh_token = "synthetic-refresh"
        self.display_name = "Before"


@pytest.fixture(autouse=True)
def mock_profile_identity(monkeypatch):
    """Never replace sys.modules or global authorization modules."""
    monkeypatch.setattr(
        profile, "resolve_application_user",
        lambda access, refresh: ApplicationUserContext(),
    )


ROW = {"user_id":"u1", "display_name":"Before", "role":"user", "is_active":True,
       "created_at":"2026-10-01T00:00:00Z"}

def fake_client(rows=None, updated_rows=None):
    client = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.update.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    read_resp = types.SimpleNamespace(data=rows if rows is not None else [ROW])
    update_resp = types.SimpleNamespace(data=updated_rows if updated_rows is not None else [{**ROW,"display_name":"After"}])
    query.execute.side_effect = [read_resp, update_resp]
    client.table.return_value = query
    client.auth.set_session.return_value = None
    client._query = query
    return client

@pytest.mark.parametrize("name,expected", [
    ("  Jo  ","Jo"), ("e\u0301", "é"), ("A"*100,"A"*100), ("李明", "李明")
])
def test_name_validation_valid(name, expected):
    assert profile.validate_display_name(name) == expected

@pytest.mark.parametrize("name", ["", "   ", "A"*101, "ok\nname", "bad\x00", "zero\u200bwidth", None])
def test_name_validation_invalid(name):
    with pytest.raises(profile.ProfileValidationError):
        profile.validate_display_name(name)

def test_load_self_profile_uses_user_session(monkeypatch):
    client = fake_client()
    client._query.execute.side_effect = [types.SimpleNamespace(data=[ROW])]
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    result = profile.load_own_profile(ApplicationUserContext())
    assert result.email == "person@example.test"
    assert result.created_at == ROW["created_at"]
    client.auth.set_session.assert_called_once_with("synthetic-access", "synthetic-refresh")
    client.table.assert_called_once_with("profiles")
    client._query.eq.assert_called_with("user_id", "u1")

def test_update_only_name_and_own_user_id(monkeypatch):
    client = fake_client()
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    updated = profile.update_own_display_name(ApplicationUserContext(), " After ")
    assert updated.display_name == "After"
    client._query.update.assert_called_once_with({"display_name":"After"})
    assert client._query.eq.call_args_list[-1].args == ("user_id", "u1")

def test_admin_can_edit_own_name(monkeypatch):
    client = fake_client()
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    assert profile.update_own_display_name(ApplicationUserContext(role="admin"), "After").display_name == "After"

def test_inactive_user_refused_without_client(monkeypatch):
    client_create = MagicMock()
    monkeypatch.setattr(profile, "get_supabase_client", client_create)
    with pytest.raises(profile.ProfileError):
        profile.update_own_display_name(ApplicationUserContext(is_active=False), "After")
    client_create.assert_not_called()

def test_revalidation_disallows_identity_switch(monkeypatch):
    monkeypatch.setattr(profile, "resolve_application_user", lambda a,b: ApplicationUserContext(user_id="different"))
    with pytest.raises(profile.ProfileError):
        profile.load_own_profile(ApplicationUserContext())

def test_revalidation_disallows_concurrent_disable(monkeypatch):
    monkeypatch.setattr(profile, "resolve_application_user", lambda a,b: ApplicationUserContext(is_active=False))
    with pytest.raises(profile.ProfileError):
        profile.update_own_display_name(ApplicationUserContext(), "After")

def test_other_user_row_denied(monkeypatch):
    client = fake_client(rows=[{**ROW,"user_id":"other"}])
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    with pytest.raises(profile.ProfileError):
        profile.update_own_display_name(ApplicationUserContext(), "After")
    client._query.update.assert_not_called()

def test_empty_update_result_fails_closed(monkeypatch):
    client = fake_client(updated_rows=[])
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    with pytest.raises(profile.ProfileError):
        profile.update_own_display_name(ApplicationUserContext(), "After")

def test_cross_user_update_response_fails_closed(monkeypatch):
    client = fake_client(updated_rows=[{**ROW,"user_id":"other","display_name":"After"}])
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    with pytest.raises(profile.ProfileError):
        profile.update_own_display_name(ApplicationUserContext(), "After")

def test_provider_error_sanitized(monkeypatch):
    client = MagicMock()
    client.table.side_effect = RuntimeError("SECRET_PRIVATE_TOKEN")
    monkeypatch.setattr(profile, "get_supabase_client", lambda: client)
    with pytest.raises(profile.ProfileError) as exc:
        profile.load_own_profile(ApplicationUserContext())
    assert "SECRET_PRIVATE_TOKEN" not in str(exc.value)
