"""M3.5-R6.3: dormant deterministic composition of externally adjudicated claims.

No model calls, Streamlit, persistence, or automatic semantic adjudication.
The caller MUST first obtain an authorised current temporary document. This
contract is not approved for user-facing summaries or production fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.fact_inventory_service import FactInventory
from services.semantic_support_service import (
    ClaimSpec, ClaimJudgement, CriticalRequirement, CoverageReport,
    assess_critical_coverage, evidence_fingerprint, SemanticContractError,
)

Mode = Literal['Concise', 'Detailed', 'Structured']
_MODES = ('Concise', 'Detailed', 'Structured')
_MAX_OUTPUT = 16000


class BoundedCompositionError(ValueError):
    """Content-free fail-closed composition failure."""


@dataclass(frozen=True)
class ComposedSummary:
    document_id: str
    owner_user_id: str
    fingerprint: str
    mode: Mode
    text: str
    claim_ids: tuple[str, ...]
    requirement_keys: tuple[str, ...]
    source_labels: tuple[str, ...]
    provenance: tuple[tuple[str, str, int | None, int | None], ...]
    approved_for_user: bool = False


def compose_supported_summary(
    document: object,
    inventory: FactInventory,
    claims: tuple[ClaimSpec, ...],
    judgements: tuple[ClaimJudgement, ...],
    requirements: tuple[CriticalRequirement, ...],
    *, mode: Mode = 'Concise', expected_fingerprint: str | None = None,
) -> ComposedSummary:
    """Format one explicitly adjudicated, source-linked assertion per requirement.

    Uses the actual installed citation and integrity validators. Coverage must be
    complete and unambiguous; no automatic promotion of R1/R2 candidates.
    Dates, values, conditions and uncertainties are reproduced ONLY as reviewed
    claim statements; no new conclusions or paraphrases are synthesized.
    """
    if mode not in _MODES:
        raise BoundedCompositionError('Unsupported composition mode.')
    try:
        report: CoverageReport = assess_critical_coverage(
            document, inventory, claims, judgements, requirements,
            expected_fingerprint=expected_fingerprint)
    except (SemanticContractError, ValueError, TypeError, AttributeError) as exc:
        raise BoundedCompositionError('Invalid semantic review or stale document.') from exc
    if (not report.complete or report.missing or report.ambiguous
            or report.conflicted or report.unsupported or report.approved_for_user):
        raise BoundedCompositionError('Critical fact coverage incomplete or uncertain.')

    keyed = {claim.requirement_key: claim for claim in claims}
    decisions = {item.claim_id: item for item in report.claim_assessments}
    if len(keyed) != len(requirements) or len(claims) != len(requirements):
        raise BoundedCompositionError('Only one reviewed claim per critical requirement is supported.')

    lines: list[str] = []
    if mode == 'Detailed':
        lines.append('## Document findings')
    elif mode == 'Structured':
        lines.append('# Summary')
    fact_ids: list[str] = []
    labels: set[str] = set()
    provenance: list[tuple[str, str, int | None, int | None]] = []
    for req in requirements:
        claim = keyed[req.key]
        decision = decisions[claim.claim_id]
        if (decision.outcome != 'supported' or not decision.adjudicated
                or decision.reason != 'explicit_source_support'
                or decision.label != claim.label):
            raise BoundedCompositionError('Claim not explicitly supported by review.')
        index = int(claim.label[1:]) - 1
        segment = document.segments[index]
        if claim.quote not in segment.text:
            raise BoundedCompositionError('Source quote changed during composition.')
        # Avoid citation injection or multiline input turning into unreviewed prose.
        if ('\n' in claim.statement or '\r' in claim.statement or
                '[P' in claim.statement or ']' in claim.statement):
            raise BoundedCompositionError('Reviewed statement has unsafe formatting.')
        statement = claim.statement.strip()
        if not statement:
            raise BoundedCompositionError('Reviewed statement is empty.')
        lines.append(f'- {statement} [{claim.label}]')
        fact_ids.append(claim.claim_id)
        labels.add(claim.label)
        origin = getattr(segment, 'origin', getattr(segment, 'source_origin', 'unknown'))
        provenance.append((claim.label, origin, getattr(segment, 'page_number', None),
                           getattr(segment, 'image_ordinal', None)))
    text = '\n'.join(lines)
    if len(text) > _MAX_OUTPUT:
        raise BoundedCompositionError('Composed summary exceeds output size limit.')

    # Import at call time; R6.3 is inactive and has no independent validator.
    from services.summarisation_service import _extract_labels, _quality_issues
    try:
        _extract_labels(text, labels)
        issues = _quality_issues(text, mode, document)
    except Exception as exc:
        raise BoundedCompositionError('Existing summary validators rejected composition.') from exc
    if not isinstance(issues, list) or issues:
        raise BoundedCompositionError('Existing summary validators rejected composition.')
    try:
        if evidence_fingerprint(document) != report.fingerprint:
            raise BoundedCompositionError('Document evidence changed during composition.')
    except SemanticContractError as exc:
        raise BoundedCompositionError('Invalid document evidence during composition.') from exc
    return ComposedSummary(
        document_id=report.document_id, owner_user_id=report.owner_user_id,
        fingerprint=report.fingerprint, mode=mode, text=text,
        claim_ids=tuple(fact_ids), requirement_keys=report.requirements,
        source_labels=tuple(sorted(labels, key=lambda v: int(v[1:]))),
        provenance=tuple(provenance), approved_for_user=False,
    )
