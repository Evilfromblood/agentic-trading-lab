"""Immutable, tamper-evident experiment manifests sealing every input of a backtest."""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Context, Decimal
from enum import Enum
from typing import Any

from agentic_trading.market_data.instruments import Instrument, Money
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange, _deep_freeze


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
        digits = len(value.as_tuple().digits)
        return format(value.normalize(Context(prec=max(28, digits + 2))), "f")
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
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be str, got {type(key).__name__}")
            out[key] = canonicalize(item)
        return out
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((canonicalize(item) for item in value), key=_dumps)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: canonicalize(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(f"cannot canonicalize type {type(value).__name__}")


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(_dumps(canonicalize(value)).encode("ascii")).hexdigest()


def compute_dataset_sha256(candles: Sequence[Candle]) -> str:
    rows = [
        [c.timestamp, c.close_time, c.open, c.high, c.low, c.close, c.volume] for c in candles
    ]
    return sha256_of(rows)


_SEALED_FIELDS = (
    "manifest_id",
    "created_at",
    "dataset_sha256",
    "provider_source",
    "exchange",
    "symbol",
    "interval",
    "start_time",
    "end_time",
    "instrument_version",
    "corporate_action_policy",
    "strategy_id",
    "strategy_params",
    "fee_model_name",
    "slippage_model_name",
    "risk_policy",
    "initial_capital",
    "random_seed",
    "git_commit",
)


@dataclass(frozen=True)
class ExperimentManifest:
    manifest_id: str
    created_at: datetime
    dataset_sha256: str
    provider_source: str
    exchange: Exchange
    symbol: str
    interval: CandleInterval
    start_time: datetime
    end_time: datetime
    instrument_version: int
    corporate_action_policy: str
    strategy_id: str
    strategy_params: Mapping[str, Any]
    fee_model_name: str
    slippage_model_name: str
    risk_policy: Mapping[str, Any]
    initial_capital: Money
    random_seed: int
    git_commit: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("created_at must be a timezone-aware datetime")
        object.__setattr__(self, "strategy_params", _deep_freeze(dict(self.strategy_params)))
        object.__setattr__(self, "risk_policy", _deep_freeze(dict(self.risk_policy)))


def _to_key_bytes(hmac_key: bytes | str) -> bytes:
    if isinstance(hmac_key, str):
        if not hmac_key:
            raise ValueError("hmac_key cannot be empty")
        return hmac_key.encode("utf-8")
    if isinstance(hmac_key, (bytes, bytearray)):
        if not hmac_key:
            raise ValueError("hmac_key cannot be empty")
        return bytes(hmac_key)
    raise TypeError("hmac_key must be bytes or str")


def _compute_seal(
    manifest: ExperimentManifest, hmac_key: bytes | str | None = None
) -> str:
    canonical_payload = _dumps(
        canonicalize({name: getattr(manifest, name) for name in _SEALED_FIELDS})
    ).encode("ascii")
    if hmac_key is not None:
        key_bytes = _to_key_bytes(hmac_key)
        return hmac.new(key_bytes, canonical_payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(canonical_payload).hexdigest()


def build_experiment_manifest(
    *,
    instrument: Instrument,
    candles: Sequence[Candle],
    provider_source: str,
    corporate_action_policy: str,
    strategy_id: str,
    strategy_params: Mapping[str, Any],
    fee_model_name: str,
    slippage_model_name: str,
    risk_policy: Mapping[str, Any],
    initial_capital: Money,
    random_seed: int,
    git_commit: str,
    created_at: datetime | None = None,
    manifest_id: str | None = None,
    hmac_key: bytes | str | None = None,
) -> ExperimentManifest:
    if not candles:
        raise ValueError("candles must be non-empty")
    start_time = candles[0].timestamp
    end_time = candles[-1].close_time
    created = created_at if created_at is not None else end_time
    fields_map: dict[str, Any] = {
        "created_at": created,
        "dataset_sha256": compute_dataset_sha256(candles),
        "provider_source": provider_source,
        "exchange": instrument.exchange,
        "symbol": instrument.symbol,
        "interval": candles[0].interval,
        "start_time": start_time,
        "end_time": end_time,
        "instrument_version": instrument.version,
        "corporate_action_policy": corporate_action_policy,
        "strategy_id": strategy_id,
        "strategy_params": strategy_params,
        "fee_model_name": fee_model_name,
        "slippage_model_name": slippage_model_name,
        "risk_policy": risk_policy,
        "initial_capital": initial_capital,
        "random_seed": random_seed,
        "git_commit": git_commit,
    }
    resolved_id = manifest_id if manifest_id is not None else f"exp-{sha256_of(fields_map)[:16]}"
    unsealed = ExperimentManifest(manifest_id=resolved_id, manifest_sha256="", **fields_map)
    sealed = _compute_seal(unsealed, hmac_key=hmac_key)
    return ExperimentManifest(
        manifest_id=resolved_id, manifest_sha256=sealed, **fields_map
    )


def verify_manifest_integrity(
    manifest: ExperimentManifest, hmac_key: bytes | str | None = None
) -> bool:
    try:
        expected = _compute_seal(manifest, hmac_key=hmac_key)
        stored = manifest.manifest_sha256
        if not isinstance(stored, str):
            return False
        return hmac.compare_digest(expected.encode("ascii"), stored.encode("utf-8"))
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False
