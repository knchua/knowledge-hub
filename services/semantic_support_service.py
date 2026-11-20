"""Phase 5 M3.5-R6.1: dormant, human-adjudicated semantic support contract.

Source attribution is NOT semantic entailment. This module never automatically
marks a candidate supported, is not an LLM, and cannot approve user summaries.
Caller MUST obtain current authorised temporary document before invoking it.
No network, Streamlit, storage, logging or model calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal

from services.fact_inventory_service import FactInventory, bind_inventory, matches_document

Outcome = Literal['supported', 'unsupported', 'ambiguous', 'conflicted']
Reason = Literal['explicit_source_support', 'unsupported_in_source', 'unclear_evidence',
                 'conflicting_evidence', 'unreviewed']
LABEL = re.compile(r'P[1-9][0-9]*\Z')
KEY = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
_MAX_CLAIMS = 200
_MAX_REQUIREMENTS = 100
_MAX_TEXT = 1200


class SemanticContractError(ValueError):
    """Content-free error for invalid or stale review evidence."""


def _txt(value: object, field: str, limit: int = _MAX_TEXT) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise SemanticContractError(f'Invalid {field}.')
    return value


def evidence_fingerprint(document: object) -> str:
    """Hash every segment and explicit provenance; no text is logged or retained."""
    document_id = _txt(getattr(document, 'document_id', None), 'document identity', 150)
    owner = _txt(getattr(document, 'owner_user_id', None), 'owner identity', 150)
    segments = getattr(document, 'segments', None)
    if not isinstance(segments, (list, tuple)) or not 1 <= len(segments) <= 2000:
        raise SemanticContractError('Invalid document segments.')
    entries = []
    for i, seg in enumerate(segments):
        if type(getattr(seg, 'index', None)) is not int or seg.index != i:
            raise SemanticContractError('Invalid evidence segment index.')
        text = _txt(getattr(seg, 'text', None), 'evidence segment', 12000)
        origin = getattr(seg, 'origin', getattr(seg, 'source_origin', 'unknown'))
        if origin not in ('native_text', 'ocr_text', 'vision_description', 'unknown'):
            raise SemanticContractError('Invalid origin.')
        page = getattr(seg, 'page_number', None)
        image = getattr(seg, 'image_ordinal', None)
        for num in (page, image):
            if num is not None and (type(num) is not int or num < 1):
                raise SemanticContractError('Invalid evidence location.')
        entries.append((i, text, origin, page, image))
    raw = json.dumps([document_id, owner, entries], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class ClaimSpec:
    """Explicit claim and its one source-specific supporting quote."""
    claim_id: str
    requirement_key: str
    statement: str
    label: str
    quote: str
    # Verbatim alone is insufficient for semantic promotion.

    def __post_init__(self) -> None:
        _txt(self.claim_id, 'claim id', 80)
        if not KEY.fullmatch(self.requirement_key):
            raise SemanticContractError('Invalid coverage requirement key.')
        _txt(self.statement, 'claim statement')
        _txt(self.quote, 'source quote')
        if not LABEL.fullmatch(self.label):
            raise SemanticContractError('Invalid claim source label.')


@dataclass(frozen=True)
class ClaimJudgement:
    """An explicit external review decision, never inferred from quote matching."""
    claim_id: str
    outcome: Outcome = 'ambiguous'
    reason: Reason = 'unreviewed'
    # True means a human or separately approved verifier adjudicated the claim.
    # This contract does not assert the accuracy of external adjudicators.
    adjudicated: bool = False

    def __post_init__(self) -> None:
        _txt(self.claim_id, 'judgement claim id', 80)
        if self.outcome not in ('supported', 'unsupported', 'ambiguous', 'conflicted'):
            raise SemanticContractError('Invalid support decision.')
        required = {'supported': 'explicit_source_support',
                    'unsupported': 'unsupported_in_source',
                    'ambiguous': 'unclear_evidence',
                    'conflicted': 'conflicting_evidence'}
        if self.adjudicated:
            if self.reason != required[self.outcome]:
                raise SemanticContractError('Decision and rationale disagree.')
        elif self.outcome != 'ambiguous' or self.reason != 'unreviewed':
            raise SemanticContractError('Unreviewed claim cannot receive a decision.')


@dataclass(frozen=True)
class CriticalRequirement:
    key: str
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not KEY.fullmatch(self.key):
            raise SemanticContractError('Invalid critical requirement key.')
        _txt(self.description, 'critical requirement description', 160)


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    requirement_key: str
    label: str
    outcome: Outcome
    reason: Reason
    adjudicated: bool


@dataclass(frozen=True)
class CoverageReport:
    document_id: str
    owner_user_id: str
    fingerprint: str
    requirements: tuple[str, ...]
    covered: tuple[str, ...]
    missing: tuple[str, ...]
    ambiguous: tuple[str, ...]
    conflicted: tuple[str, ...]
    unsupported: tuple[str, ...]
    claim_assessments: tuple[ClaimAssessment, ...]
    approved_for_user: bool = False

    @property
    def complete(self) -> bool:
        return bool(self.requirements) and len(self.covered) == len(self.requirements)


def assess_critical_coverage(document: object, inventory: FactInventory,
                             claims: tuple[ClaimSpec, ...],
                             judgements: tuple[ClaimJudgement, ...],
                             requirements: tuple[CriticalRequirement, ...],
                             *, expected_fingerprint: str | None = None) -> CoverageReport:
    """Require exact source attribution AND explicit adjudication per critical claim.

    Unsupported, ambiguous, conflicting or missing critical facts fail coverage.
    This is an offline review contract; never an automatic semantic verifier.
    """
    fingerprint = evidence_fingerprint(document)
    if expected_fingerprint is not None and expected_fingerprint != fingerprint:
        raise SemanticContractError('Document evidence changed since review.')
    if not isinstance(inventory, FactInventory) or not matches_document(inventory, document):
        raise SemanticContractError('Fact inventory identity mismatch.')
    try:
        if bind_inventory(document, inventory.facts) != inventory:
            raise SemanticContractError('Fact inventory source mismatch.')
    except ValueError as exc:
        raise SemanticContractError('Invalid inventory source attribution.') from exc
    if not isinstance(claims, tuple) or not 0 <= len(claims) <= _MAX_CLAIMS:
        raise SemanticContractError('Invalid claim collection.')
    if not isinstance(judgements, tuple) or len(judgements) > _MAX_CLAIMS:
        raise SemanticContractError('Invalid judgement collection.')
    if not isinstance(requirements, tuple) or not 1 <= len(requirements) <= _MAX_REQUIREMENTS:
        raise SemanticContractError('Invalid requirement collection.')
    if not all(isinstance(v, ClaimSpec) for v in claims) or not all(isinstance(v, ClaimJudgement) for v in judgements) or not all(isinstance(v, CriticalRequirement) for v in requirements):
        raise SemanticContractError('Invalid assessment contract types.')
    keys = [r.key for r in requirements]
    ids = [c.claim_id for c in claims]
    judged_ids = [j.claim_id for j in judgements]
    if len(set(keys)) != len(keys) or len(set(ids)) != len(ids) or len(set(judged_ids)) != len(judged_ids):
        raise SemanticContractError('Duplicate assessment identifiers.')
    if not set(judged_ids) <= set(ids):
        raise SemanticContractError('Judgement has no matching claim.')
    if any(c.requirement_key not in keys for c in claims):
        raise SemanticContractError('Claim references unknown requirement.')
    judgments_by_id = {j.claim_id: j for j in judgements}
    decisions = []
    for claim in claims:
        idx = int(claim.label[1:]) - 1
        if idx >= len(document.segments) or claim.quote not in document.segments[idx].text:
            raise SemanticContractError('Claim quote missing from labelled source.')
        if claim.label not in inventory.source_labels:
            raise SemanticContractError('Claim label missing from inventory.')
        judgement = judgments_by_id.get(claim.claim_id, ClaimJudgement(claim.claim_id))
        # Source quote present is a *precondition*, not semantic proof.
        decisions.append(ClaimAssessment(claim.claim_id, claim.requirement_key,
                                         claim.label, judgement.outcome,
                                         judgement.reason, judgement.adjudicated))
    covered, missing, ambiguous, conflicted, unsupported = [], [], [], [], []
    for key in keys:
        relevant = [d for d in decisions if d.requirement_key == key]
        if not relevant:
            missing.append(key)
        elif any(d.outcome == 'conflicted' for d in relevant):
            conflicted.append(key)
        elif any(d.outcome == 'ambiguous' for d in relevant):
            ambiguous.append(key)
        elif any(d.outcome == 'unsupported' for d in relevant):
            unsupported.append(key)
        elif len(relevant) != 1 or not relevant[0].adjudicated:
            # Multiple affirmative claims about one required fact must be reviewed
            # for consistency rather than silently selected.
            conflicted.append(key)
        else:
            covered.append(key)
    return CoverageReport(
        document_id=inventory.document_id, owner_user_id=inventory.owner_user_id,
        fingerprint=fingerprint, requirements=tuple(keys), covered=tuple(covered),
        missing=tuple(missing), ambiguous=tuple(ambiguous),
        conflicted=tuple(conflicted), unsupported=tuple(unsupported),
        claim_assessments=tuple(decisions), approved_for_user=False,
    )
