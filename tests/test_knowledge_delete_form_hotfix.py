"""Regression tests for the Knowledge Management deletion form.

Execute the real UI block with mocked Streamlit controls.
No database, network, or document deletion is performed.
"""

import ast
from contextlib import nullcontext
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "pages" / "knowledge_management.py"


def deletion_form_code():
    tree = ast.parse(SOURCE.read_text())

    for parent in ast.walk(tree):
        for _, value in ast.iter_fields(parent):
            if not isinstance(value, list):
                continue

            for index, node in enumerate(value[:-1]):
                if not isinstance(node, ast.With):
                    continue
                if "st.form" not in ast.unparse(node.items[0].context_expr):
                    continue
                if "delete_{d['id']}" not in ast.unparse(node):
                    continue

                following = value[index + 1]
                if not (
                    isinstance(following, ast.If)
                    and isinstance(following.test, ast.Name)
                    and following.test.id == "request_delete"
                ):
                    continue

                module = ast.fix_missing_locations(
                    ast.Module(body=[node, following], type_ignores=[])
                )
                return compile(module, str(SOURCE), "exec")

    pytest.fail("Expected deletion form and submit handler not found")


class FakeStreamlit:
    def __init__(self, confirmation, submitted):
        self.confirmation = confirmation
        self.submitted = submitted
        self.errors = []
        self.successes = []
        self.reruns = 0
        self.button_kwargs = None

    def form(self, key):
        assert key == "delete_doc-123"
        return nullcontext()

    def text_input(self, label, **kwargs):
        return self.confirmation

    def form_submit_button(self, label, **kwargs):
        assert label == "Delete document"
        self.button_kwargs = kwargs
        return self.submitted

    def error(self, message):
        self.errors.append(message)

    def success(self, message):
        self.successes.append(message)

    def rerun(self):
        self.reruns += 1


class FakeKnowledgeError(Exception):
    pass


def execute_form(confirmation, submitted=True, delete_error=None):
    st = FakeStreamlit(confirmation, submitted)
    calls = []

    def fake_delete(actor, document_id, value):
        calls.append((actor, document_id, value))
        if delete_error:
            raise FakeKnowledgeError("Simulated deletion failure")

    exec(
        deletion_form_code(),
        {
            "st": st,
            "d": {"id": "doc-123"},
            "actor": "test-admin",
            "delete_document": fake_delete,
            "KnowledgeError": FakeKnowledgeError,
        },
    )
    return st, calls


@pytest.mark.parametrize("confirmation", ["", "delete", "Delete", "DELETE ", "WRONG"])
def test_invalid_confirmation_never_deletes(confirmation):
    st, calls = execute_form(confirmation)

    assert calls == []
    assert st.errors == ["Type DELETE exactly to confirm deletion."]
    assert st.reruns == 0


def test_exact_confirmation_calls_protected_service():
    st, calls = execute_form("DELETE")

    assert calls == [("test-admin", "doc-123", "DELETE")]
    assert st.errors == []
    assert st.reruns == 1


def test_button_is_not_disabled():
    st, _ = execute_form("DELETE", submitted=False)

    assert "disabled" not in st.button_kwargs


def test_no_submission_never_deletes():
    st, calls = execute_form("DELETE", submitted=False)

    assert calls == []
    assert st.reruns == 0


def test_service_error_is_reported():
    st, calls = execute_form(
        "DELETE", delete_error=True
    )

    assert len(calls) == 1
    assert st.errors == ["Simulated deletion failure"]
    assert st.reruns == 0
