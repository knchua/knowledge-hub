"""Static UI placement tests for document upload and clear controls."""
import ast
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "pages" / "document_analysis.py"

def _tree():
    return ast.parse(PAGE.read_text(encoding="utf-8"))

def _function(name):
    return next(n for n in _tree().body if isinstance(n, ast.FunctionDef) and n.name == name)

def _source():
    return PAGE.read_text(encoding="utf-8")

def test_upload_controls_called_for_empty_and_loaded_states():
    main = _function('main')
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '_render_document_controls']
    assert len(calls) == 2

def test_loaded_document_controls_above_summarisation():
    source = _source()
    assert source.index('st.write(f"**Extracted characters:**') < source.index('        _render_document_controls(user, document)\n        st.divider()') < source.index('st.subheader("Summarise this document")')

def test_form_and_clear_button_are_together():
    helper = _function('_render_document_controls')
    calls = [n.func.attr for n in ast.walk(helper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    # Phase 4 F-07 uses a standard uploader plus explicit submit/clear buttons,
    # rather than the original Streamlit form. Verify the intended controls.
    assert 'file_uploader' in calls
    assert calls.count('button') >= 2
    labels = {node.value for node in ast.walk(helper) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert {'Upload Document', 'Replace Document', 'Clear Document'} <= labels
    assert 'clear_document' in [n.func.id for n in ast.walk(helper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]

def test_chat_and_summary_remain_present():
    source = _source()
    for text in ['st.chat_input(', 'st.chat_message("assistant")', 'summarise_current_document(st.session_state, user, mode)', 'ask_and_record(st.session_state, user, question)']:
        assert text in source
