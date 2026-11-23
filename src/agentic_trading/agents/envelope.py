"""Standardized agent envelope, input hashing, and fail-closed schema guards."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from agentic_trading.market_data.instruments import Money


def canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"non-finite Decimal cannot be canonicalized: {value}")
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite float cannot be canonicalized")
        return {"__float__": repr(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("naive datetime cannot be canonicalized")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Money):
        return {"amount": canonicalize(value.amount), "currency": canonicalize(value.currency)}
    if isinstance(value, Mapping):
        return {str(k): canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((canonicalize(item) for item in value), key=repr)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: canonicalize(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(f"cannot canonicalize type {type(value).__name__}")


def compute_inputs_hash(payload: Mapping[str, Any]) -> str:
    canonical = canonicalize(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class AgentEnvelope:
    run_id: str
    agent: str
    agent_version: str
    prompt_version: str
    model: str
    ticker: str
    as_of: datetime
    inputs_hash: str
    output: Mapping[str, Any]
    errors: tuple[str, ...]
    latency_ms: int
    cost_usd: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        if not isinstance(self.output, Mapping):
            raise TypeError("output must be a Mapping")
        if not isinstance(self.errors, tuple):
            object.__setattr__(self, "errors", tuple(self.errors))


def invoke_with_schema_guard(
    *,
    run_id: str,
    agent: str,
    agent_version: str,
    prompt_version: str,
    model: str,
    ticker: str,
    as_of: datetime,
    user_payload: Mapping[str, Any],
    caller: Callable[[str, Mapping[str, Any], str], str],
    system_prompt: str,
    required_keys: Sequence[str],
    cost_usd: Decimal = Decimal("0"),
) -> AgentEnvelope:
    try:
        inputs_hash = compute_inputs_hash(user_payload)
    except (ValueError, TypeError):
        return AgentEnvelope(
            run_id=run_id,
            agent=agent,
            agent_version=agent_version,
            prompt_version=prompt_version,
            model=model,
            ticker=ticker,
            as_of=as_of,
            inputs_hash=f"sha256:invalid_inputs_{ticker}",
            output={"data_quality": "missing"},
            errors=("Invalid non-finite input payload",),
            latency_ms=0,
            cost_usd=cost_usd,
        )
    start_time = time.perf_counter()

    for attempt in range(2):
        payload_to_send = (
            dict(user_payload)
            if attempt == 0
            else {"retry_notice": "Output must strictly match required JSON schema", **user_payload}
        )
        try:
            raw_response = caller(system_prompt, payload_to_send, model)
            parsed = json.loads(raw_response)
            if isinstance(parsed, dict) and all(k in parsed for k in required_keys):
                latency = int((time.perf_counter() - start_time) * 1000)
                return AgentEnvelope(
                    run_id=run_id,
                    agent=agent,
                    agent_version=agent_version,
                    prompt_version=prompt_version,
                    model=model,
                    ticker=ticker,
                    as_of=as_of,
                    inputs_hash=inputs_hash,
                    output=parsed,
                    errors=(),
                    latency_ms=latency,
                    cost_usd=cost_usd,
                )
        except (ValueError, TypeError, json.JSONDecodeError, KeyError, RuntimeError):
            pass

    latency = int((time.perf_counter() - start_time) * 1000)
    return AgentEnvelope(
        run_id=run_id,
        agent=agent,
        agent_version=agent_version,
        prompt_version=prompt_version,
        model=model,
        ticker=ticker,
        as_of=as_of,
        inputs_hash=inputs_hash,
        output={"data_quality": "missing"},
        errors=("Failed schema validation after retry",),
        latency_ms=latency,
        cost_usd=cost_usd,
    )
