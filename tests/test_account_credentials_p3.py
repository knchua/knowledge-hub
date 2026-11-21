"""P3 corrective contract tests: no secondary sign-in and structured OTP errors."""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import pytest
from services import account_credentials_service as svc


def actor(uid="user-A", role="user", active=True):
    return NS(user_id=uid, email="user@example.test", role=role, is_active=active,
              access_token="synthetic-access", refresh_token="synthetic-refresh")


@pytest.fixture
def mocks(monkeypatch):
    current = actor()
    resolver = MagicMock(return_value=current)
    client = MagicMock()
    client.auth.set_session.return_value = NS(session=NS(access_token="current-access"))
    client.auth.get_user.return_value = NS(user=NS(id="user-A"))
    client.auth.update_user.return_value = NS(user=NS(id="user-A"))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(svc, "resolve_application_user", resolver)
    monkeypatch.setattr(svc, "get_supabase_client", factory)
    return NS(user=current, resolver=resolver, client=client, factory=factory)


@pytest.mark.parametrize("old,new,confirm", [
    ("", "NewPassword!1", "NewPassword!1"),
    ("old", "too", "too"),
    ("old", "NewPassword!1", "different"),
    ("samepassword", "samepassword", "samepassword"),
])
def test_invalid_fields_make_no_provider_calls(mocks, old, new, confirm):
    with pytest.raises(svc.PasswordValidationError):
        svc.change_own_password(mocks.user, old, new, confirm)
    mocks.factory.assert_not_called()


@pytest.mark.parametrize("nonce", ["abcdef", "123", "123456", "１２３４５６７８", "123456789", " 12 345678 "])
def test_bad_nonce_rejected_locally(mocks, nonce):
    with pytest.raises(svc.PasswordValidationError):
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1", nonce)
    mocks.factory.assert_not_called()


def test_password_update_uses_existing_session_and_current_password(mocks):
    svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")
    mocks.client.auth.set_session.assert_called_once_with("synthetic-access", "synthetic-refresh")
    mocks.client.auth.get_user.assert_called_once_with("current-access")
    mocks.client.auth.update_user.assert_called_once_with(
        {"password": "NewPassword!1", "current_password": "old"})
    assert mocks.resolver.call_count == 2
    mocks.client.auth.sign_in_with_password.assert_not_called()


def test_eight_digit_nonce_forwarded_only_when_provided(mocks):
    svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1", " 12345678 ")
    assert mocks.client.auth.update_user.call_args.args[0]["nonce"] == "12345678"


@pytest.mark.parametrize("code,etype", [
    ("reauthentication_needed", svc.ReauthenticationRequired),
    ("reauthentication_not_valid", svc.InvalidReauthenticationCode),
])
def test_structured_provider_error_codes(mocks, code, etype):
    err = RuntimeError("private provider detail")
    err.code = code
    mocks.client.auth.update_user.side_effect = err
    with pytest.raises(etype) as output:
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")
    assert "private provider detail" not in str(output.value)


def test_wrong_password_is_generic_and_safe(mocks):
    error = RuntimeError("private wrong-current-password detail")
    error.code = "same_password"
    mocks.client.auth.update_user.side_effect = error
    with pytest.raises(svc.PasswordChangeError) as result:
        svc.change_own_password(mocks.user, "bad", "NewPassword!1", "NewPassword!1")
    assert "private" not in str(result.value)


def test_concurrent_deactivation_before_update_denied(mocks):
    mocks.resolver.side_effect = [actor(), actor(active=False)]
    with pytest.raises(svc.PasswordChangeError, match="Account access has changed"):
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")
    mocks.client.auth.update_user.assert_not_called()


def test_identity_changed_on_client_denied(mocks):
    mocks.client.auth.get_user.return_value = NS(user=NS(id="user-B"))
    with pytest.raises(svc.PasswordChangeError, match="identity has changed"):
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")
    mocks.client.auth.update_user.assert_not_called()


def test_expired_session_denied(mocks):
    mocks.resolver.side_effect = RuntimeError("sensitive token")
    with pytest.raises(svc.PasswordChangeError, match="Unable to verify account"):
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")
    mocks.client.auth.update_user.assert_not_called()


def test_update_result_must_confirm_user(mocks):
    mocks.client.auth.update_user.return_value = NS(user=NS(id="user-B"))
    with pytest.raises(svc.PasswordChangeError, match="could not be confirmed"):
        svc.change_own_password(mocks.user, "old", "NewPassword!1", "NewPassword!1")


def test_request_nonce_uses_existing_session(mocks):
    svc.request_reauthentication_code(mocks.user)
    mocks.client.auth.reauthenticate.assert_called_once_with()
    mocks.client.auth.sign_in_with_password.assert_not_called()


def test_request_nonce_failure_sanitized(mocks):
    mocks.client.auth.reauthenticate.side_effect = RuntimeError("private code")
    with pytest.raises(svc.PasswordChangeError) as output:
        svc.request_reauthentication_code(mocks.user)
    assert "private" not in str(output.value)


def test_inactive_account_cannot_request_code(mocks):
    with pytest.raises(svc.PasswordChangeError):
        svc.request_reauthentication_code(actor(active=False))
    mocks.factory.assert_not_called()
