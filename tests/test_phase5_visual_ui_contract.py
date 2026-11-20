"""Static wiring regression; does not import/execute a Streamlit page."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def test_document_analysis_page_compiles_and_preserves_phase4_answering():
    s = source('pages/document_analysis.py')
    ast.parse(s)
    assert 'ask_and_record(st.session_state, user, question)' in s
    assert 'read_qa_history(st.session_state, user)' in s
    assert 'replace_document(st.session_state, user, uploaded.name, uploaded.getvalue())' in s


def test_document_analysis_requires_active_visual_checkbox():
    s = source('pages/document_analysis.py')
    assert 'st.checkbox(' in s
    assert 'disabled=not consent' in s
    assert 'replace_visual_document(' in s
    assert 'consent=consent' in s


def test_uploader_change_revokes_pending_consent():
    s = source('pages/document_analysis.py')
    assert 'on_change=_invalidate_visual_attempt' in s
    assert 'discard_visual_attempt(st.session_state)' in s
    assert "pending['nonce']" in s


def test_visual_provenance_labels_do_not_redefine_p_citations():
    s = source('pages/document_analysis.py')
    assert 'f"[P{idx + 1}] "' in s
    assert 'item.page_number is not None' in s
    assert 'source_segment.origin' in s
    assert 'docx_image_ordinal' in s


def test_logout_and_owner_switch_purge_phase5_session_state():
    s = source('services/session_service.py')
    assert 'key.startswith(("phase4_", "phase5_"))' in s
    assert 'key.startswith("phase5_")' in s
    assert 'clear_document(st.session_state, keep_owner=False)' in s
