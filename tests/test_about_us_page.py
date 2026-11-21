"""S2 page access and content checks, using deterministic fake Streamlit modules."""

from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
import runpy
import sys
from unittest.mock import MagicMock

import pytest


PAGE = Path(__file__).resolve().parents[1] / "pages" / "about_us.py"


class PageStopped(Exception):
    pass


def run_page(monkeypatch, tokens, *, role="user", auth_exception=None):
    streamlit = ModuleType("streamlit")
    mock = MagicMock()
    mock.columns.return_value = [nullcontext(), nullcontext(), nullcontext()]
    mock.container.return_value = nullcontext()
    mock.expander.return_value = nullcontext()
    mock.stop.side_effect = PageStopped
    for attr in ("error", "stop", "title", "caption", "markdown", "subheader", "write", "columns", "container", "expander", "divider", "info"):
        setattr(streamlit, attr, getattr(mock, attr))

    auth_module = ModuleType("services.authorization_service")
    class ApplicationAccessError(RuntimeError):
        pass
    auth_module.ApplicationAccessError = ApplicationAccessError
    verify = MagicMock(return_value=SimpleNamespace(role=role, is_active=True))
    if auth_exception == "access":
        verify.side_effect = ApplicationAccessError("denied")
    elif auth_exception == "failure":
        verify.side_effect = RuntimeError("private provider detail")
    auth_module.resolve_application_user = verify

    session_module = ModuleType("services.session_service")
    session_module.get_stored_tokens = MagicMock(return_value=tokens)
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "services.authorization_service", auth_module)
    monkeypatch.setitem(sys.modules, "services.session_service", session_module)
    with pytest.raises(PageStopped) if (not all(tokens) or auth_exception) else nullcontext():
        runpy.run_path(str(PAGE))
    return mock, verify


@pytest.mark.parametrize("tokens", [(None, None), ("access", None), (None, "refresh")])
def test_missing_session_denied(monkeypatch, tokens):
    mock, verify = run_page(monkeypatch, tokens)
    verify.assert_not_called()
    mock.title.assert_not_called()


@pytest.mark.parametrize("failure", ["access", "failure"])
def test_rejected_or_unavailable_auth_denied_without_leaking_details(monkeypatch, failure):
    mock, verify = run_page(monkeypatch, ("access", "refresh"), auth_exception=failure)
    verify.assert_called_once_with("access", "refresh")
    mock.title.assert_not_called()
    assert "private provider detail" not in str(mock.error.call_args_list)


@pytest.mark.parametrize("role", ["admin", "user"])
def test_verified_active_roles_render_page(monkeypatch, role):
    # The real resolver validates role and active status; the UI does not require admin.
    mock, verify = run_page(monkeypatch, ("access", "refresh"), role=role)
    verify.assert_called_once_with("access", "refresh")
    mock.title.assert_called_once_with("ℹ️ About Knowledge Hub")
    mock.info.assert_called_once()
    assert mock.columns.call_args.args == (3,)
    body = " ".join(str(x) for x in mock.write.call_args_list + mock.markdown.call_args_list)
    for phrase in ("Knowledge Management", "RAG Chatbot", "Document Analysis", "administrators", "temporary"):
        assert phrase.lower() in body.lower()
