"""Phase 5 M3.5-R6.4-A: dormant, offline authenticated preview orchestration.

NOT a Streamlit integration, user-facing capability, trusted adjudicator or API.
Caller must only inject the OfflineTestReviewGateway from controlled tests. In
particular, an untrusted client must never be permitted to supply that gateway.
No derived data is retained in the session by this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from services.fact_extraction_service import extract_fact_candidates
from services.semantic_support_service import (
    ClaimSpec, ClaimJudgement, CriticalRequirement, evidence_fingerprint,
)
from services.bounded_summary_composer_service import compose_supported_summary, ComposedSummary


class OrchestrationError(RuntimeError):
    """Content-free, fail-closed rejection."""


@dataclass(frozen=True)
class OfflineReviewBundle:
    document_id: str
    owner_user_id: str
    fingerprint: str
    claims: tuple[ClaimSpec, ...]
    judgements: tuple[ClaimJudgement, ...]
    requirements: tuple[CriticalRequirement, ...]


# Deliberately explicit TEST-ONLY injection, not a production security token.
# Python callers can construct such a gateway; never expose it via Streamlit,
# a request endpoint, or any user-controlled path. Only a separately reviewed,
# authenticated adjudication service could satisfy a future production boundary.
@dataclass(frozen=True)
class OfflineTestReviewGateway:
    supply: Callable[[object], OfflineReviewBundle]


def _snapshot(state: object, document: object) -> tuple[object, ...]:
    from services.document_analysis_service import DOCUMENT, OWNER, WIDGET_VERSION
    if state.get(DOCUMENT) is not document:
        raise OrchestrationError('Current document changed during processing.')
    owner = getattr(document, 'owner_user_id', None)
    if state.get(OWNER) != owner:
        raise OrchestrationError('Document owner binding changed.')
    generation = state.get(WIDGET_VERSION)
    if type(generation) is not int or generation < 0:
        raise OrchestrationError('Invalid document session generation.')
    return (getattr(document, 'document_id', None), owner,
            evidence_fingerprint(document), generation, id(document))


def evaluate_authenticated_preview(
    state: object, actor: object, gateway: OfflineTestReviewGateway | None = None,
    *, mode: Literal['Concise', 'Detailed', 'Structured'] = 'Concise',
) -> ComposedSummary:
    """Evaluate only the *current* authorised document in a controlled test.

    A fresh active-user verification happens inside current_document both
    before processing and before returning. Any changed identity, session
    generation, document instance or evidence fingerprint rejects the result.
    The returned preview remains approved_for_user=False, without persistence.
    """
    if not isinstance(gateway, OfflineTestReviewGateway) or not callable(gateway.supply):
        raise OrchestrationError('Trusted offline test review gateway required.')
    if mode not in ('Concise', 'Detailed', 'Structured'):
        raise OrchestrationError('Unsupported preview mode.')
    from services.document_analysis_service import current_document
    try:
        document = current_document(state, actor)
        if document is None:
            raise OrchestrationError('No authorised current document.')
        beginning = _snapshot(state, document)
        inventory = extract_fact_candidates(document)
        review = gateway.supply(document)
        if not isinstance(review, OfflineReviewBundle):
            raise OrchestrationError('Invalid offline review bundle.')
        if (review.document_id != beginning[0] or
                review.owner_user_id != beginning[1] or
                review.fingerprint != beginning[2]):
            raise OrchestrationError('Review bound to different document evidence.')
        # Enforce concrete tuple contracts before calling the composer.
        if (not isinstance(review.claims, tuple) or
                not isinstance(review.judgements, tuple) or
                not isinstance(review.requirements, tuple)):
            raise OrchestrationError('Invalid review collection types.')
        # Check for replacement during review *before* composing.
        if _snapshot(state, document) != beginning:
            raise OrchestrationError('Document changed during review.')
        preview = compose_supported_summary(
            document, inventory, review.claims, review.judgements,
            review.requirements, mode=mode, expected_fingerprint=beginning[2],
        )
        # Recheck authoritative active user and selected document after work.
        current = current_document(state, actor)
        if current is not document or _snapshot(state, current) != beginning:
            raise OrchestrationError('Document or session changed during processing.')
        if (not isinstance(preview, ComposedSummary) or
                preview.approved_for_user is not False or
                preview.document_id != beginning[0] or
                preview.owner_user_id != beginning[1] or
                preview.fingerprint != beginning[2]):
            raise OrchestrationError('Unapproved preview contract violated.')
        return preview
    except OrchestrationError:
        raise
    except Exception as exc:
        # Do not leak source snippets, identities, credentials or document text.
        raise OrchestrationError('Offline authenticated preview could not be completed.') from exc
