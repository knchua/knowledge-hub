"""R6.5-E: disabled-by-default, synthetic-only developer diagnostic page.

Unapproved diagnostics NEVER enter phase4_results, Q&A history, or an upload.
This page provides no user-facing summary, data persistence or provider calls.
"""
from __future__ import annotations

import streamlit as st

from services.authorization_service import resolve_application_user
from services.session_service import get_stored_tokens
from services.synthetic_diagnostic_service import (
    SyntheticDiagnosticError,
    _developer,
    run_synthetic_diagnostic,
)

_CASES = ('S1', 'S2', 'S3')
_MODES = ('Concise', 'Detailed', 'Structured')


def main() -> None:
    # Required even for a direct URL; st.navigation visibility is not authority.
    try:
        access, refresh = get_stored_tokens()
        if not access or not refresh:
            raise SyntheticDiagnosticError('Missing developer session.')
        actor = resolve_application_user(access, refresh)
        _developer(actor)
    except Exception:
        st.error('Developer diagnostics unavailable.')
        st.stop()
        return

    st.title('Synthetic Grounding Diagnostics')
    st.warning('Developer-only synthetic diagnostics. NOT a verified or user-approved summary.')
    st.caption('This page never evaluates uploaded documents, modifies existing summaries, or calls a model.')
    case = st.selectbox('Synthetic fixture', _CASES, index=0)
    mode = st.selectbox('Composition mode', _MODES, index=0)
    if not st.button('Run synthetic diagnostic'):
        return

    try:
        # A forged state or stale selection is rejected even if widget internals change.
        if type(case) is not str or case not in _CASES or type(mode) is not str or mode not in _MODES:
            raise SyntheticDiagnosticError('Invalid synthetic diagnostic selection.')
        _developer(actor)
        result = run_synthetic_diagnostic(actor, case, mode=mode)
        _developer(actor)
        if (result.approved_for_user is not False or result.synthetic_only is not True or
                result.fixture != case or result.mode != mode or
                not isinstance(result.text, str)):
            raise SyntheticDiagnosticError('Invalid unapproved diagnostic result.')
    except Exception:
        # Never display raw exceptions, source text, identity, or previous results.
        st.error('Synthetic diagnostic was rejected. No result retained.')
        return

    # Deliberately no st.session_state writes, cache, markdown, download, or publish.
    st.warning('UNAPPROVED diagnostic preview — synthetic test data only.')
    st.text(f'Fixture: {result.fixture} | Mode: {result.mode}')
    st.text(f'Supported test claims: {result.claim_count}')
    st.text('Requirement keys: ' + ', '.join(result.requirement_keys))
    st.text('Source labels: ' + ', '.join(result.source_labels))
    for label, origin, page, image in result.provenance:
        st.text(f'Evidence: {label}, origin={origin}, page={page}, image={image}')
    st.text(result.text)


main()
