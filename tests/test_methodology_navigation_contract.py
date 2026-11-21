"""S3 static contract for the existing Streamlit navigation and content guard."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_about_and_methodology_are_shared_but_admin_pages_remain_restricted():
    source = (ROOT / 'app.py').read_text(encoding='utf8')
    tree = ast.parse(source)
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_navigation')
    nav = ast.get_source_segment(source, func)
    assert '"pages/about_us.py"' in nav
    assert '"pages/methodology.py"' in nav
    assert 'title="Methodology"' in nav
    assert 'url_path="methodology"' in nav
    assert nav.count('"Information": information_pages') == 2
    assert 'default=True' in nav
    assert '"Administration": [' in nav
    assert '"Developer Tools"' in nav


def test_methodology_protects_direct_access():
    source = (ROOT / 'pages/methodology.py').read_text(encoding='utf8')
    assert 'get_stored_tokens()' in source
    assert 'resolve_application_user(access_token, refresh_token)' in source
    assert 'st.stop()' in source
