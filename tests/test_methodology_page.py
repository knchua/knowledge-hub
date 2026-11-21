"""S3 Methodology page: deterministic no-network access and content checks."""
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
import runpy
import sys
from unittest.mock import MagicMock

import pytest

PAGE = Path(__file__).resolve().parents[1] / "pages" / "methodology.py"


class PageStopped(Exception):
    pass


def run_page(monkeypatch, tokens, *, role="user", failure=None):
    streamlit = ModuleType("streamlit")
    mock = MagicMock()
    mock.columns.return_value = [nullcontext(), nullcontext()]
    mock.container.return_value = nullcontext()
    mock.expander.return_value = nullcontext()
    mock.stop.side_effect = PageStopped
    for method in ("error", "stop", "title", "caption", "write", "markdown", "subheader", "columns", "container", "expander", "info"):
        setattr(streamlit, method, getattr(mock, method))
    auth = ModuleType("services.authorization_service")
    class ApplicationAccessError(RuntimeError):
        pass
    auth.ApplicationAccessError = ApplicationAccessError
    verify = MagicMock(return_value=SimpleNamespace(role=role, is_active=True))
    if failure == "access":
        verify.side_effect = ApplicationAccessError("inactive")
    elif failure == "provider":
        verify.side_effect = RuntimeError("secret internal text")
    auth.resolve_application_user = verify
    session = ModuleType("services.session_service")
    session.get_stored_tokens = MagicMock(return_value=tokens)
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "services.authorization_service", auth)
    monkeypatch.setitem(sys.modules, "services.session_service", session)
    with pytest.raises(PageStopped) if (not all(tokens) or failure) else nullcontext():
        runpy.run_path(str(PAGE))
    return mock, verify


@pytest.mark.parametrize("tokens", [(None, None), ("a", None), (None, "b")])
def test_missing_tokens_denied(monkeypatch, tokens):
    mock, verify = run_page(monkeypatch, tokens)
    verify.assert_not_called()
    mock.title.assert_not_called()


@pytest.mark.parametrize("failure", ["access", "provider"])
def test_invalid_or_unavailable_backend_denied(monkeypatch, failure):
    mock, verify = run_page(monkeypatch, ("a", "b"), failure=failure)
    verify.assert_called_once_with("a", "b")
    mock.title.assert_not_called()
    assert "secret internal text" not in str(mock.error.call_args_list)


@pytest.mark.parametrize("role", ["admin", "user"])
def test_both_valid_roles_see_methodology(monkeypatch, role):
    mock, verify = run_page(monkeypatch, ("a", "b"), role=role)
    verify.assert_called_once_with("a", "b")
    mock.title.assert_called_once_with("🧭 Methodology")
    assert mock.columns.call_args.args == (2,)
    assert mock.expander.called


def test_approved_methodology_topics_and_distinctions():
    text = PAGE.read_text(encoding="utf8")
    for phrase in ("Solution architecture", "Knowledge ingestion", "Retrieval-Augmented Generation", "Document summarisation", "OCR and multimodal", "Security and responsible AI", "Testing and evaluation", "Known limitations", "29c22b2", "2,932", "12 of 12"):
        assert phrase in text
    assert "not added to the shared knowledge repository" in text
    assert "do **not** independently prove" in text
    assert "require_admin" not in text
