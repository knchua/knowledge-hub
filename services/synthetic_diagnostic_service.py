"""R6.5-C: dormant synthetic-only developer diagnostic contract.

No Streamlit import, navigation entrypoint, persistence, OpenAI invocation or
user-uploaded-document processing. This is NOT a trusted semantic adjudicator.
Enablement is intentionally denied by default; this capability must not be
wired to any UI without a separate integration and security approval.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Literal

from services.authorization_service import ApplicationUserContext
from services.document_analysis_service import verify_actor, OWNER, DOCUMENT, WIDGET_VERSION
from services.temporary_document_service import TemporaryDocument, TemporarySegment
from services.semantic_support_service import (
    ClaimSpec, ClaimJudgement, CriticalRequirement, evidence_fingerprint,
)
from services.authenticated_preview_orchestrator_service import (
    OfflineReviewBundle, OfflineTestReviewGateway, evaluate_authenticated_preview,
)
from services.bounded_summary_composer_service import ComposedSummary

_CASES = ('S1', 'S2', 'S3')
_MODES = ('Concise', 'Detailed', 'Structured')
_ENABLED = 'KH_PHASE5_DEV_DIAGNOSTICS_ENABLED'
_ALLOWLIST = 'KH_PHASE5_DEV_DIAGNOSTIC_USER_IDS'
_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = {
    'evidence': (_ROOT / 'tests/fixtures/phase5_r1/synthetic_fact_cases.json',
                 '63d9c6fcfd818b119a6c4cef13d18ea0e406e958b3026bdb92a84f6b3175bbbc'),
    'matrix': (_ROOT / 'tests/fixtures/phase5_r6_1/semantic_matrix.json',
               '892a6f83f1d39c77291c09b9798c831173914d8d855db0606bb414dd31b974ea'),
}


class SyntheticDiagnosticError(RuntimeError):
    """Content-free, fail-closed diagnostic denial."""


@dataclass(frozen=True)
class SyntheticDiagnostic:
    fixture: Literal['S1', 'S2', 'S3']
    mode: Literal['Concise', 'Detailed', 'Structured']
    document_id: str
    owner_user_id: str
    evidence_fingerprint: str
    text: str
    claim_count: int
    requirement_keys: tuple[str, ...]
    source_labels: tuple[str, ...]
    provenance: tuple[tuple[str, str, int | None, int | None], ...]
    synthetic_only: bool = True
    approved_for_user: bool = False


def _developer(actor: object) -> str:
    """Authorize twice per run, without trusting role/flag input alone."""
    if os.environ.get(_ENABLED) != '1':
        raise SyntheticDiagnosticError('Developer diagnostics disabled.')
    raw = os.environ.get(_ALLOWLIST, '')
    ids = [value.strip() for value in raw.split(',')]
    if (not raw or len(raw) > 2048 or len(ids) > 32 or
            any(not value or len(value) > 150 for value in ids)):
        raise SyntheticDiagnosticError('Developer identity allowlist invalid.')
    if not isinstance(actor, ApplicationUserContext):
        raise SyntheticDiagnosticError('Authenticated developer context required.')
    try:
        verified = verify_actor(actor)
    except Exception as exc:
        raise SyntheticDiagnosticError('Developer authentication failed.') from exc
    if (not isinstance(verified, ApplicationUserContext) or
            verified.user_id != actor.user_id or verified.user_id not in ids or
            verified.is_active is not True or verified.role != 'admin' or
            actor.role != 'admin' or actor.is_active is not True):
        raise SyntheticDiagnosticError('Developer authorization denied.')
    return verified.user_id


def _load_fixture(name: str) -> dict:
    path, expected = _FIXTURES[name]
    if path.is_symlink() or not path.is_file():
        raise SyntheticDiagnosticError('Synthetic fixture unavailable.')
    try:
        raw = path.read_bytes()
        if len(raw) > 100_000 or sha256(raw).hexdigest() != expected:
            raise SyntheticDiagnosticError('Synthetic fixture integrity mismatch.')
        value = json.loads(raw)
    except SyntheticDiagnosticError:
        raise
    except Exception as exc:
        raise SyntheticDiagnosticError('Synthetic fixture unreadable.') from exc
    if not isinstance(value, dict):
        raise SyntheticDiagnosticError('Invalid synthetic fixture.')
    return value


def _synthetic_document(case: str, owner: str, fixture: dict) -> TemporaryDocument:
    record = fixture[case]
    available = {field.name for field in fields(TemporarySegment)}
    segments = tuple(TemporarySegment(**{key: value for key, value in item.items()
                                         if key in available})
                     for item in record['segments'])
    return TemporaryDocument(
        document_id='r65c-fixture-' + case,
        owner_user_id=owner, filename='synthetic-' + case + record['extension'],
        extension=record['extension'], size_bytes=0,
        character_count=sum(len(segment.text) for segment in segments),
        page_count=2 if case in ('S1', 'S3') else None,
        segments=segments, warnings=(),
    )


def _review(doc: TemporaryDocument, selection: dict) -> OfflineReviewBundle:
    claims = tuple(ClaimSpec(f'C-{index:03}', item['key'], item['statement'],
                             item['label'], item['quote'])
                   for index, item in enumerate(selection['claims'], start=1))
    judgements = tuple(ClaimJudgement(claim.claim_id, 'supported',
                                      'explicit_source_support', True)
                       for claim in claims)
    requirements = tuple(CriticalRequirement(key, key.replace('_', ' '))
                         for key in selection['critical'])
    return OfflineReviewBundle(doc.document_id, doc.owner_user_id,
                               evidence_fingerprint(doc), claims, judgements,
                               requirements)


def run_synthetic_diagnostic(
    actor: ApplicationUserContext, fixture: Literal['S1', 'S2', 'S3'],
    *, mode: Literal['Concise', 'Detailed', 'Structured'] = 'Concise',
) -> SyntheticDiagnostic:
    """Evaluate a fixed synthetic fixture in isolated ephemeral state only.

    The caller cannot supply a document, review gateway, session dictionary,
    claim, output or fixture path. No output is approved for user publication.
    Each run rechecks authority after orchestration and enforces flag/allowlist
    again before returning the diagnostic. No result is stored.
    """
    if fixture not in _CASES or type(fixture) is not str or mode not in _MODES or type(mode) is not str:
        raise SyntheticDiagnosticError('Unsupported synthetic diagnostic request.')
    owner = _developer(actor)
    try:
        evidence = _load_fixture('evidence')
        matrix = _load_fixture('matrix')
        document = _synthetic_document(fixture, owner, evidence)
        selection = matrix[fixture]
        if not selection['claims'] or not selection['critical']:
            raise SyntheticDiagnosticError('Empty synthetic answer key.')
        state = {OWNER: owner, DOCUMENT: document, WIDGET_VERSION: 0}
        # The only gateway is constructed from integrity-pinned synthetic files;
        # callers cannot inject a review bundle or user-uploaded evidence.
        gateway = OfflineTestReviewGateway(lambda current: _review(current, selection))
        result = evaluate_authenticated_preview(state, actor, gateway, mode=mode)
        if not isinstance(result, ComposedSummary) or result.approved_for_user is not False:
            raise SyntheticDiagnosticError('Unapproved output contract violated.')
        if (result.document_id != document.document_id or result.owner_user_id != owner or
                result.fingerprint != evidence_fingerprint(document) or
                state[DOCUMENT] is not document or state[OWNER] != owner or
                state[WIDGET_VERSION] != 0):
            raise SyntheticDiagnosticError('Synthetic evidence changed.')
        if _developer(actor) != owner:
            raise SyntheticDiagnosticError('Developer authority changed.')
        if _load_fixture('evidence') != evidence or _load_fixture('matrix') != matrix:
            raise SyntheticDiagnosticError('Synthetic fixtures changed.')
        return SyntheticDiagnostic(
            fixture=fixture, mode=mode, document_id=result.document_id,
            owner_user_id=owner, evidence_fingerprint=result.fingerprint,
            text=result.text, claim_count=len(result.claim_ids),
            requirement_keys=result.requirement_keys,
            source_labels=result.source_labels, provenance=result.provenance,
        )
    except SyntheticDiagnosticError:
        raise
    except Exception as exc:
        raise SyntheticDiagnosticError('Synthetic diagnostic could not be completed.') from exc


def reject_diagnostic_publication(value: object) -> None:
    """Unconditionally refuse promotion to normal user-facing outputs."""
    raise SyntheticDiagnosticError('Synthetic diagnostics are not approved for publication.')
