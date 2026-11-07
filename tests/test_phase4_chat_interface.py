"""Static regression checks for the Phase 4 chat-view-only UI update.

These verify wiring without importing a Streamlit page that executes at import time.
"""
import ast
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / 'pages' / 'document_analysis.py'


def _source():
    return PAGE.read_text(encoding='utf-8')


def _calls():
    return [n for n in ast.walk(ast.parse(_source())) if isinstance(n, ast.Call)]


def _attrs():
    return [n.func.attr for n in _calls() if isinstance(n.func, ast.Attribute)]


def test_chat_bubbles_and_message_input():
    attrs = _attrs()
    assert attrs.count('chat_message') >= 2
    assert attrs.count('chat_input') == 1
    assert 'text_input' not in attrs


def test_existing_answer_and_history_service_reused():
    src = _source()
    assert 'ask_and_record(st.session_state, user, question)' in src
    assert 'read_qa_history(st.session_state, user)' in src
    assert 'clear_qa_history(st.session_state, user)' in src


def test_chat_input_scoped_to_document():
    assert 'phase4_chat_input_{document.document_id}' in _source()


def test_currency_and_citation_expanders_preserved():
    src = _source()
    assert 'escape_markdown_currency(turn.answer.text)' in src
    assert 'turn.answer.cited_evidence' in src
    assert 'st.text(item.text)' in src
    assert 'item.page_number is not None' in src


def test_document_cleanup_and_authorization_preserved():
    src = _source()
    assert 'resolve_application_user(access, refresh)' in src
    assert 'current_document(st.session_state, user)' in src
    assert 'clear_document(st.session_state)' in src
    assert 'replace_document(st.session_state, user, uploaded.name, uploaded.getvalue())' in src


def test_no_persistence_or_shared_index_added_to_page():
    src = _source()
    assert 'supabase' not in src.lower()
    assert 'pgvector' not in src.lower()
    assert 'st.chat_message("user")' in src
    assert 'st.chat_message("assistant")' in src
