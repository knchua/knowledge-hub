"""Optional, session-scoped Phase 5 Gate 2 *estimated* API spending guard.

Enabled only with KH_PHASE5_GATE2_BUDGET_ENABLED=1. It cannot guarantee a
provider billing cap. A reservation is NOT refunded after an invocation, even
on failures (billing may be uncertain). Never persists data or document text.
All call sites must disable SDK automatic retries when this guard is enabled.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from typing import MutableMapping

STATE_KEY = "phase5_gate2_summary_qa_budget"
_ACTIVE: ContextVar[tuple[MutableMapping, str] | None] = ContextVar("phase5_gate2_scope", default=None)
_MODEL_PRICES = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
}


class Gate2BudgetError(RuntimeError):
    """User-safe budget or configuration failure."""


def enabled() -> bool:
    value = os.getenv("KH_PHASE5_GATE2_BUDGET_ENABLED", "0")
    if value not in ("0", "1"):
        raise Gate2BudgetError("Invalid Gate 2 budget configuration.")
    return value == "1"


def _config() -> tuple[Decimal, int, int]:
    try:
        limit = Decimal(os.getenv("KH_PHASE5_GATE2_MAX_ESTIMATED_USD", "0.10"))
        attempts = int(os.getenv("KH_PHASE5_GATE2_MAX_ATTEMPTS", "12"))
        operations = int(os.getenv("KH_PHASE5_GATE2_MAX_OPERATIONS", "6"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise Gate2BudgetError("Invalid Gate 2 budget configuration.") from exc
    if (
        not limit.is_finite()
        or not Decimal("0") < limit <= Decimal("1")
        or not 1 <= attempts <= 60
        or not 1 <= operations <= 30
    ):
        raise Gate2BudgetError("Invalid Gate 2 budget configuration.")
    return limit, attempts, operations


def _record(state: MutableMapping, owner_id: str) -> dict:
    record = state.get(STATE_KEY)
    if not isinstance(record, dict) or record.get("owner") != owner_id:
        # A change of authenticated owner MUST NOT inherit another user's data.
        record = {"owner": owner_id, "operations": 0, "attempts": 0,
                  "reserved_usd": "0", "reported_input_tokens": 0,
                  "reported_output_tokens": 0, "unreported_attempts": 0}
        state[STATE_KEY] = record
    return record


@contextmanager
def operation(state: MutableMapping, owner_id: str):
    """One UI-request operation, including any bounded application correction.

    Operations without an authenticated owner cannot enter an enabled budget.
    Do not use this scope for direct, unauthorised service invocation.
    """
    if not enabled():
        yield
        return
    if not isinstance(owner_id, str) or not owner_id:
        raise Gate2BudgetError("Gate 2 requires an authorised document owner.")
    limit, max_attempts, max_operations = _config()
    record = _record(state, owner_id)
    if record["operations"] >= max_operations or record["attempts"] >= max_attempts or Decimal(record["reserved_usd"]) >= limit:
        raise Gate2BudgetError("Gate 2 operation or estimated spending limit reached.")
    record["operations"] += 1  # Count even failed attempts; never refund.
    token = _ACTIVE.set((state, owner_id))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def reserve_attempt(*, model: str, prompt_chars: int, max_output_tokens: int) -> None:
    """Reserve conservative estimated cost *before* each actual provider call.

    Assumes up to one input token per UTF-8 byte, rounded up, including the
    whole prompt/system text. Input token estimates are NOT hard usage bounds.
    Unknown model prices or missing accounting scope fail closed when enabled.
    """
    if not enabled():
        return
    active = _ACTIVE.get()
    if active is None:
        raise Gate2BudgetError("Gate 2 request has no active budget scope.")
    if model not in _MODEL_PRICES or type(prompt_chars) is not int or prompt_chars < 0 or type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise Gate2BudgetError("Unable to estimate this model request safely.")
    state, owner = active
    record = _record(state, owner)
    limit, max_attempts, _ = _config()
    input_price, output_price = _MODEL_PRICES[model]
    # Conservative multiplier for prompt formatting, non-ASCII text, and overhead.
    reserved_input = prompt_chars * 2 + 512
    estimated = (Decimal(reserved_input) * input_price + Decimal(max_output_tokens) * output_price) / Decimal(1_000_000)
    if record["attempts"] >= max_attempts or Decimal(record["reserved_usd"]) + estimated > limit:
        raise Gate2BudgetError("Gate 2 provider-attempt or estimated spending limit reached.")
    record["attempts"] += 1
    record["reserved_usd"] = str(Decimal(record["reserved_usd"]) + estimated)
    record["unreported_attempts"] += 1


def record_usage(response: object) -> None:
    """Best-effort read of LangChain response usage; no accounting refund.

    A missing provider token report is not interpreted as zero usage.
    """
    if not enabled():
        return
    active = _ACTIVE.get()
    if active is None:
        return
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        return
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    if type(inp) is int and inp >= 0 and type(out) is int and out >= 0:
        state, owner = active
        record = _record(state, owner)
        record["reported_input_tokens"] += inp
        record["reported_output_tokens"] += out
        record["unreported_attempts"] = max(0, record["unreported_attempts"] - 1)


def snapshot(state: MutableMapping, owner_id: str) -> dict:
    """Non-sensitive, read-only budget report. Does not create state."""
    record = state.get(STATE_KEY)
    if not isinstance(record, dict) or record.get("owner") != owner_id:
        return {"operations": 0, "attempts": 0, "reserved_usd": "0", "unreported_attempts": 0}
    return {k: record[k] for k in ("operations", "attempts", "reserved_usd", "reported_input_tokens", "reported_output_tokens", "unreported_attempts")}
