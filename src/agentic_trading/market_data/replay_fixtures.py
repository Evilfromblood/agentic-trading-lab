"""Tier-2 stored replay fixtures: cryptographic manifests, tamper detection, and deterministic replay."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from agentic_trading.market_data.models import CandleInterval, Exchange
from agentic_trading.market_data.provider import (
    HistoricalDataRequest,
    MarketDataProvider,
    ProviderPayloadError,
    ProviderResponse,
    _require_valid_tz_dt,
)

_FIXTURE_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]+$")


class FixtureIntegrityError(ValueError):
    """Raised when a replay fixture violates integrity or security invariants."""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return dict(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@dataclass(frozen=True)
class FixtureManifest:
    """Cryptographic manifest attesting to the recorded market data payload."""

    fixture_id: str
    source: str
    exchange: Exchange
    symbol: str
    interval: CandleInterval
    recorded_at: datetime
    record_count: int
    payload_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.fixture_id, str) or not _FIXTURE_ID_REGEX.match(self.fixture_id):
            raise FixtureIntegrityError(f"fixture_id must match {_FIXTURE_ID_REGEX.pattern}, got {self.fixture_id!r}")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if not isinstance(self.interval, CandleInterval):
            raise TypeError(f"interval must be a CandleInterval enum, got {type(self.interval).__name__}")
        _require_valid_tz_dt(self.recorded_at, "recorded_at")
        if isinstance(self.record_count, bool) or not isinstance(self.record_count, int) or self.record_count < 0:
            raise ValueError(f"record_count must be a non-negative integer, got {self.record_count}")
        if not isinstance(self.payload_sha256, str) or len(self.payload_sha256) != 64:
            raise FixtureIntegrityError("payload_sha256 must be a 64-character hex string")


def _resolve_safe_fixture_paths(directory: Path | str, fixture_id: str) -> tuple[Path, Path]:
    if not isinstance(fixture_id, str) or not _FIXTURE_ID_REGEX.match(fixture_id):
        raise FixtureIntegrityError(f"fixture_id contains invalid characters: '{fixture_id}'")
    base_dir = Path(directory).resolve()
    manifest_path = (base_dir / f"{fixture_id}.manifest.json").resolve()
    payload_path = (base_dir / f"{fixture_id}.payload.json").resolve()
    try:
        manifest_path.relative_to(base_dir)
        payload_path.relative_to(base_dir)
    except ValueError as exc:
        raise FixtureIntegrityError(f"Path traversal detected for fixture '{fixture_id}'") from exc
    return manifest_path, payload_path


def save_replay_fixture(
    directory: Path | str,
    fixture_id: str,
    response: ProviderResponse,
    exchange: Exchange,
    symbol: str,
    interval: CandleInterval,
) -> FixtureManifest:
    """Save provider records and cryptographic manifest as a canonical JSON fixture."""
    if not isinstance(response, ProviderResponse):
        raise TypeError(f"response must be a ProviderResponse, got {type(response).__name__}")
    if not response.success:
        raise ValueError("Cannot save an unsuccessful ProviderResponse as a replay fixture")

    manifest_path, payload_path = _resolve_safe_fixture_paths(directory, fixture_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    payload_json = json.dumps(
        list(response.records),
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    payload_bytes = payload_json.encode("utf-8")
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    manifest = FixtureManifest(
        fixture_id=fixture_id,
        source=response.source,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        recorded_at=response.retrieval_timestamp,
        record_count=len(response.records),
        payload_sha256=payload_sha256,
    )

    manifest_data = {
        "fixture_id": manifest.fixture_id,
        "source": manifest.source,
        "exchange": manifest.exchange.value,
        "symbol": manifest.symbol,
        "interval": manifest.interval.value,
        "recorded_at": manifest.recorded_at.isoformat(),
        "record_count": manifest.record_count,
        "payload_sha256": manifest.payload_sha256,
    }

    manifest_json = json.dumps(manifest_data, sort_keys=True, indent=2)

    payload_path.write_bytes(payload_bytes)
    manifest_path.write_text(manifest_json, encoding="utf-8")

    return manifest


class StoredReplayFixtureProvider(MarketDataProvider):
    """Deterministic market data provider backed by verified stored disk fixtures."""

    def __init__(self, directory: Path | str, fixture_id: str) -> None:
        self._directory = Path(directory)
        self._fixture_id = fixture_id
        self._manifest_path, self._payload_path = _resolve_safe_fixture_paths(
            self._directory, self._fixture_id
        )

    def _load_and_verify(self) -> tuple[FixtureManifest, tuple[Mapping[str, Any], ...]]:
        if not self._manifest_path.is_file():
            raise FixtureIntegrityError(f"Missing fixture manifest file: {self._manifest_path}")
        if not self._payload_path.is_file():
            raise FixtureIntegrityError(f"Missing fixture payload file: {self._payload_path}")

        try:
            manifest_dict = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FixtureIntegrityError(f"Corrupt manifest JSON in {self._manifest_path}: {exc}") from exc

        recorded_at = datetime.fromisoformat(manifest_dict["recorded_at"])
        manifest = FixtureManifest(
            fixture_id=manifest_dict["fixture_id"],
            source=manifest_dict["source"],
            exchange=Exchange(manifest_dict["exchange"]),
            symbol=manifest_dict["symbol"],
            interval=CandleInterval(manifest_dict["interval"]),
            recorded_at=recorded_at,
            record_count=manifest_dict["record_count"],
            payload_sha256=manifest_dict["payload_sha256"],
        )

        payload_bytes = self._payload_path.read_bytes()
        computed_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        if not hmac.compare_digest(computed_sha256, manifest.payload_sha256):
            raise FixtureIntegrityError(
                f"Payload SHA-256 digest mismatch for fixture '{self._fixture_id}': "
                f"expected {manifest.payload_sha256}, got {computed_sha256}"
            )

        try:
            records_raw = json.loads(payload_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderPayloadError(f"Corrupt payload JSON in {self._payload_path}: {exc}") from exc

        if not isinstance(records_raw, list):
            raise ProviderPayloadError(f"Payload records must be a list, got {type(records_raw).__name__}")

        records: list[Mapping[str, Any]] = []
        for rec in records_raw:
            if not isinstance(rec, Mapping):
                raise ProviderPayloadError(f"Record must be a Mapping, got {type(rec).__name__}")
            records.append(rec)

        if len(records) != manifest.record_count:
            raise FixtureIntegrityError(
                f"Record count mismatch in fixture '{self._fixture_id}': "
                f"manifest claims {manifest.record_count}, found {len(records)}"
            )

        return manifest, tuple(records)

    @property
    def source_name(self) -> str:
        manifest, _ = self._load_and_verify()
        return manifest.source

    def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
        manifest, records = self._load_and_verify()
        filtered_records: list[Mapping[str, Any]] = []

        for rec in records:
            ts_raw = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
            if ts_raw is None:
                continue
            ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
            if request.start_time <= ts < request.end_time:
                filtered_records.append(rec)

        return ProviderResponse(
            success=True,
            source=manifest.source,
            retrieval_timestamp=manifest.recorded_at,
            records=tuple(filtered_records),
        )

    def fetch_latest(
        self,
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        now: datetime | None = None,
    ) -> ProviderResponse:
        manifest, records = self._load_and_verify()
        clean_symbol = symbol.strip().upper()

        matching_records: list[tuple[datetime, Mapping[str, Any]]] = []
        for rec in records:
            rec_sym = rec.get("symbol")
            if rec_sym is not None and str(rec_sym).strip().upper() != clean_symbol:
                continue
            rec_ex = rec.get("exchange")
            if rec_ex is not None and str(rec_ex).strip().upper() != exchange.value:
                continue
            rec_iv = rec.get("interval")
            if rec_iv is not None and str(rec_iv).strip() != interval.value:
                continue

            ts_raw = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
            if ts_raw is None:
                continue
            ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
            if now is not None and ts >= now:
                continue
            matching_records.append((ts, rec))

        if not matching_records:
            return ProviderResponse(
                success=True,
                source=manifest.source,
                retrieval_timestamp=manifest.recorded_at,
                records=(),
            )

        matching_records.sort(key=lambda x: x[0])
        latest_record = matching_records[-1][1]

        return ProviderResponse(
            success=True,
            source=manifest.source,
            retrieval_timestamp=manifest.recorded_at,
            records=(latest_record,),
        )
