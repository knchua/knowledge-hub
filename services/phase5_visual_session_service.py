"""Phase 5 M2.5: consent-bound, authenticated visual attempt lifecycle.

All state is session-only. Never persist bytes, original text or API output.
A pending attempt is scoped to owner, uploader generation, filename and SHA-256.
"""
from __future__ import annotations

from hashlib import sha256
import math
import os
from typing import MutableMapping
from uuid import uuid4

from services.authorization_service import ApplicationUserContext
from services.document_analysis_service import (
    DOCUMENT, WIDGET_VERSION, DocumentAccessError, verify_actor, bind_owner,
    clear_document,
)
from services.visual_extraction_manifest_service import inspect_visual_manifest, VisualManifest
from services.visual_document_processing_service import process_visual_document
from services.visual_provider_service import VisionBudget, VisualProviderError

PENDING = 'phase5_visual_pending'


def discard_visual_attempt(state: MutableMapping) -> None:
    """Cancel staged consent without replacing or clearing the current document."""
    state.pop(PENDING, None)


def _fingerprint(name: str, raw: bytes) -> str:
    if not isinstance(name, str) or not isinstance(raw, bytes):
        raise DocumentAccessError('Invalid selected document.')
    return sha256(name.encode('utf-8') + b'\x00' + raw).hexdigest()


def _setting(name: str) -> str:
    """No default prices or application budget: fail closed until configured."""
    value = os.environ.get(name, '').strip()
    if not value:
        try:
            import streamlit as st
            value = str(st.secrets.get(name, '')).strip()
        except Exception:
            pass
    return value


def configured_vision_budget(calls: int) -> VisionBudget:
    """Create a fresh budget only when explicitly configured by operator."""
    try:
        if type(calls) is not int or calls < 1 or calls > 10:
            raise ValueError('invalid calls')
        keys = ('KH_VISION_MAX_ESTIMATED_USD', 'KH_VISION_INPUT_PRICE_PER_MILLION_USD',
                'KH_VISION_OUTPUT_PRICE_PER_MILLION_USD')
        values = [float(_setting(k)) for k in keys]
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('invalid pricing')
        return VisionBudget(max_estimated_usd=values[0],
                            input_price_per_million_usd=values[1],
                            output_price_per_million_usd=values[2], max_calls=calls)
    except (ValueError, VisualProviderError) as exc:
        raise DocumentAccessError('Vision pricing or spending limit is not configured correctly.') from exc


def prepare_visual_attempt(state: MutableMapping, actor: ApplicationUserContext,
                           filename: str, data: bytes) -> VisualManifest:
    """Local-only inspection. Upload alone never authorises OpenAI calls."""
    try:
        user = verify_actor(actor)
    except DocumentAccessError:
        clear_document(state, keep_owner=False)
        raise
    bind_owner(state, user.user_id)
    discard_visual_attempt(state)
    manifest = inspect_visual_manifest(filename, data)
    if manifest.consent_required:
        state[PENDING] = {
            'owner': user.user_id,
            'fingerprint': _fingerprint(filename, data),
            'generation': state.get(WIDGET_VERSION, 0),
            'nonce': uuid4().hex,
            'manifest': manifest,
        }
    return manifest


def visual_attempt_matches(state: MutableMapping, filename: str, data: bytes) -> bool:
    pending = state.get(PENDING)
    return (isinstance(pending, dict)
            and pending.get('generation') == state.get(WIDGET_VERSION, 0)
            and pending.get('fingerprint') == _fingerprint(filename, data)
            and isinstance(pending.get('manifest'), VisualManifest))


def replace_visual_document(state: MutableMapping, actor: ApplicationUserContext,
                            filename: str, data: bytes, *, consent: bool,
                            client=None, vision_fn=None):
    """Commit exactly once, only after complete consented processing/rechecks."""
    if consent is not True:
        raise DocumentAccessError('Explicit document-specific consent is required.')
    try:
        current = verify_actor(actor)
    except DocumentAccessError:
        clear_document(state, keep_owner=False)
        raise
    bind_owner(state, current.user_id)
    pending = state.get(PENDING)
    if not visual_attempt_matches(state, filename, data) or pending['owner'] != current.user_id:
        raise DocumentAccessError('Selected document changed. Inspect and consent again.')
    # A nonce identifies the exact attempt, independent of the file's digest.
    nonce = pending['nonce']
    generation = pending['generation']
    manifest = pending['manifest']
    budget = configured_vision_budget(manifest.proposed_vision_calls)

    def revalidate() -> None:
        try:
            fresh = verify_actor(actor)
        except DocumentAccessError:
            clear_document(state, keep_owner=False)
            raise
        if (fresh.user_id != current.user_id or state.get(WIDGET_VERSION, 0) != generation
                or state.get(PENDING) is not pending or pending.get('nonce') != nonce
                or pending.get('fingerprint') != _fingerprint(filename, data)
                or pending.get('owner') != current.user_id):
            raise DocumentAccessError('Document or consent changed during processing.')

    try:
        # Inject a fake adapter for tests, otherwise use the real M2.3 provider.
        kwargs = {} if vision_fn is None else {'vision_fn': vision_fn}
        result = process_visual_document(owner_user_id=current.user_id,
                                         filename=filename, data=data,
                                         manifest=manifest, consent=True,
                                         budget=budget, revalidate=revalidate,
                                         client=client, **kwargs)
        revalidate()
        # Do not clear a previously valid document on provider failure.
        clear_document(state)
        state[DOCUMENT] = result
        return result
    finally:
        # A failed attempt must be freshly inspected/consented before retry.
        if state.get(PENDING) is pending:
            discard_visual_attempt(state)
