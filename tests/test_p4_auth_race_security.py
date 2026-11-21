"""P4: targeted fail-closed Auth operation tests; mocks, no external requests.

These tests DO NOT establish atomicity between a PostgreSQL profile check
and a subsequent Supabase Auth update. See P4_REMAINING_SECURITY_REVIEW.md.
"""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import pytest
from services import account_credentials_service as svc


def _user(active=True):
    return NS(user_id="disposable-A", email="a@example.test", role="user",
              is_active=active, access_token="synthetic-access",
              refresh_token="synthetic-refresh")


@pytest.fixture
def harness(monkeypatch):
    actor = _user()
    resolver = MagicMock(return_value=actor)
    client = MagicMock()
    client.auth.set_session.return_value = NS(session=NS(access_token="synthetic-current"))
    client.auth.get_user.return_value = NS(user=NS(id=actor.user_id))
    client.auth.update_user.return_value = NS(user=NS(id=actor.user_id))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(svc, "resolve_application_user", resolver)
    monkeypatch.setattr(svc, "get_supabase_client", factory)
    return NS(actor=actor, resolver=resolver, client=client, factory=factory)


def _change(h):
    svc.change_own_password(h.actor, "old-password", "NewPassword!123", "NewPassword!123")


def test_expired_session_denied_at_authorization_no_auth_update(harness):
    harness.resolver.side_effect = RuntimeError("private expired token")
    with pytest.raises(svc.PasswordChangeError) as result:
        _change(harness)
    assert "private expired token" not in str(result.value)
    harness.client.auth.update_user.assert_not_called()


def test_revoked_session_rejected_by_set_session_no_auth_update(harness):
    harness.client.auth.set_session.side_effect = RuntimeError("private revoked session")
    with pytest.raises(svc.PasswordChangeError) as result:
        _change(harness)
    assert "private revoked session" not in str(result.value)
    harness.client.auth.update_user.assert_not_called()


def test_identity_mismatch_after_session_restore_no_auth_update(harness):
    harness.client.auth.get_user.return_value = NS(user=NS(id="different-user"))
    with pytest.raises(svc.PasswordChangeError):
        _change(harness)
    harness.client.auth.update_user.assert_not_called()


def test_deactivation_observed_at_final_profile_check_blocks_auth_update(harness):
    harness.resolver.side_effect = [_user(active=True), _user(active=False)]
    with pytest.raises(svc.PasswordChangeError):
        _change(harness)
    harness.client.auth.update_user.assert_not_called()


def test_provider_rejects_update_after_final_check_fail_closed_no_retry(harness):
    # Auth refuses update after app's last profile check; simulates a revoked
    # session or an Auth-side ban that becomes effective in the race window.
    state = {"active": True}
    def reject_after_check(payload):
        state["active"] = False
        error = RuntimeError("private provider ban details")
        error.code = "session_not_found"
        raise error
    harness.client.auth.update_user.side_effect = reject_after_check
    with pytest.raises(svc.PasswordChangeError) as result:
        _change(harness)
    assert state["active"] is False
    assert "private provider ban details" not in str(result.value)
    harness.client.auth.update_user.assert_called_once()
    harness.client.auth.sign_in_with_password.assert_not_called()


def test_security_code_error_after_final_check_is_safe(harness):
    error = RuntimeError("private nonce content")
    error.code = "reauthentication_not_valid"
    harness.client.auth.update_user.side_effect = error
    with pytest.raises(svc.InvalidReauthenticationCode) as result:
        svc.change_own_password(harness.actor, "old-password", "NewPassword!123", "NewPassword!123", "12345678")
    assert "private nonce content" not in str(result.value)


def test_provider_success_after_app_check_cannot_prove_no_race(harness):
    # Characterization, NOT a security acceptance assertion: if an Auth update
    # succeeds following an app status check, this service cannot establish
    # whether an admin deactivated the user in between the two operations.
    _change(harness)
    harness.client.auth.update_user.assert_called_once()
    harness.client.auth.sign_in_with_password.assert_not_called()
