"""End-to-end market data ingestion pipeline.

Orchestrates the ingestion flow:
Provider Response
  → Provider Adapter
  → Raw Data Validation
  → Normalization into Candle Model
  → Request Window Boundary Enforcement
  → M2a Quality Validation Gate
  → Accepted or Rejected Ingestion Result
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any

from agentic_trading.market_data.adapters import (
    ProviderAdapter,
    RawDataValidationError,
    StandardDictAdapter,
)
from agentic_trading.market_data.models import (
    DEFAULT_EXCHANGE_SESSION,
    IST,
    Candle,
    CandleInterval,
    Exchange,
    ExchangeCalendar,
    ExchangeSession,
    _deep_freeze,
)
from agentic_trading.market_data.provider import (
    HistoricalDataRequest,
    MarketDataProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderPayloadError,
    ProviderResponse,
    ProviderTimeoutError,
    _require_valid_tz_dt,
)
from agentic_trading.market_data.quality import (
    DataQualityErrorCode,
    ValidationResult,
    check_sequence_integrity,
    validate_candle,
    validate_candle_sequence,
)


class CoverageStatus(str, Enum):
    """Authoritative coverage classification for historical candle ingestion."""

    FULL_COVERAGE = "FULL_COVERAGE"
    COVERAGE_UNVERIFIED = "COVERAGE_UNVERIFIED"
    TRUNCATED_COVERAGE = "TRUNCATED_COVERAGE"
    MARKET_CALENDAR_REQUIRED = "MARKET_CALENDAR_REQUIRED"
    EMPTY_COVERAGE = "EMPTY_COVERAGE"
    SPARSE_COVERAGE = "SPARSE_COVERAGE"

# Unified _deep_freeze imported from models.py


def _require_valid_max_staleness(max_staleness: Any) -> None:
    """Validate that max_staleness is a non-negative timedelta."""
    if not isinstance(max_staleness, timedelta):
        raise TypeError(
            f"max_staleness must be a timedelta, got {type(max_staleness).__name__}"
        )
    if max_staleness < timedelta(0):
        raise ValueError(f"max_staleness cannot be negative, got {max_staleness}")


class UnsupportedIntervalFreshnessError(ValueError):
    """Raised when freshness evaluation is requested for an interval without policy or configuration."""


class MarketCalendarRequiredError(ValueError):
    """Raised when freshness evaluation requires exchange calendar evidence (e.g. weekend or multi-day D1 transitions)."""


@dataclass(frozen=True)
class FreshnessPolicy:
    """Explicit interval-aware freshness policy for Indian equities market data.

    Interval Rules:
    - M1: 3 minutes (3 * duration). Prevents M1 data from becoming arbitrarily stale.
    - M3: 9 minutes (3 * duration).
    - M5: 15 minutes (3 * duration).
    - M10: 20 minutes (2 * duration).
    - M15: 30 minutes (2 * duration).
    - M30: 60 minutes (2 * duration).
    - H1: 120 minutes (2 * duration).
    - D1: Session-aware:
        * Same calendar day (EOD analysis after session close 15:30 IST): 24 hours.
        * Next consecutive calendar weekday (Mon->Tue, Tue->Wed, Wed->Thu, Thu->Fri): 24 hours.
        * Multi-day transitions, weekends, and holidays: Fails closed with MarketCalendarRequiredError
          (reporting MARKET_CALENDAR_REQUIRED) because exchange calendar evidence is required to verify
          trading day boundaries without guessing.
    - Unsupported intervals (e.g. W1, MN1): Fails closed by raising UnsupportedIntervalFreshnessError
      unless custom limit is explicitly provided in custom_limits.
    """

    custom_limits: Mapping[CandleInterval, timedelta] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __init__(
        self,
        custom_limits: Mapping[CandleInterval, timedelta] | None = None,
    ) -> None:
        limits_dict: dict[CandleInterval, timedelta] = {}
        if custom_limits:
            for k, v in custom_limits.items():
                if not isinstance(k, CandleInterval):
                    raise TypeError(f"custom_limits keys must be CandleInterval, got {type(k).__name__}")
                _require_valid_max_staleness(v)
                limits_dict[k] = v
        object.__setattr__(self, "custom_limits", MappingProxyType(limits_dict))

    def __hash__(self) -> int:
        """Deterministic hash enabling FreshnessPolicy usage in sets and dict keys."""
        return hash(tuple(sorted((k.value, v.total_seconds()) for k, v in self.custom_limits.items())))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FreshnessPolicy):
            return False
        return dict(self.custom_limits) == dict(other.custom_limits)

    def get_max_staleness(
        self,
        interval: CandleInterval,
        now: datetime | None = None,
        candle_close_time: datetime | None = None,
        session: ExchangeSession | None = None,
        calendar: ExchangeCalendar | None = None,
    ) -> timedelta:
        """Resolve the maximum allowable staleness for a given interval and evaluation context."""
        if not isinstance(interval, CandleInterval):
            raise TypeError(f"interval must be CandleInterval enum, got {type(interval).__name__}")

        if interval in self.custom_limits:
            return self.custom_limits[interval]

        if interval == CandleInterval.M1:
            return timedelta(minutes=3)
        if interval == CandleInterval.M3:
            return timedelta(minutes=9)
        if interval == CandleInterval.M5:
            return timedelta(minutes=15)
        if interval == CandleInterval.M10:
            return timedelta(minutes=20)
        if interval == CandleInterval.M15:
            return timedelta(minutes=30)
        if interval == CandleInterval.M30:
            return timedelta(minutes=60)
        if interval == CandleInterval.H1:
            return timedelta(hours=2)

        if interval == CandleInterval.D1:
            if now is not None and candle_close_time is not None:
                market_tz = (
                    session.timezone
                    if session is not None
                    else (
                        calendar.get_session(now.date()).timezone
                        if calendar is not None
                        else (now.tzinfo or IST)
                    )
                )
                now_local = now.astimezone(market_tz)
                close_local = candle_close_time.astimezone(market_tz)
                day_delta = (now_local.date() - close_local.date()).days
                close_wd = close_local.weekday()

                # 1. Same calendar day: post-close EOD analysis
                if day_delta == 0:
                    return timedelta(hours=24)

                # 2. Next consecutive calendar weekday (Mon->Tue, etc.)
                if day_delta == 1 and close_wd < 4 and now_local.weekday() == close_wd + 1:
                    return timedelta(hours=24)

                # 3. Calendar-verified weekend / holiday span
                if calendar is not None:
                    missing_trading_days = [
                        cur_d
                        for cur_d in (
                            close_local.date() + timedelta(days=d)
                            for d in range(1, day_delta)
                        )
                        if calendar.is_trading_day(cur_d)
                    ]
                    if not missing_trading_days:
                        return timedelta(days=day_delta + 1)

                # 4. Multi-day gap without calendar verification: fail closed
                raise MarketCalendarRequiredError(
                    f"D1 freshness evaluation across {day_delta} calendar day(s) "
                    f"(from {close_local.date()} weekday {close_wd} to {now_local.date()} weekday {now_local.weekday()}) "
                    "requires reliable exchange calendar evidence; cannot verify trading days without calendar"
                )

            raise MarketCalendarRequiredError(
                "D1 freshness evaluation requires evaluation context ('now' and 'candle_close_time') "
                "or explicit custom_limits configuration; cannot evaluate session freshness in isolation"
            )

        raise UnsupportedIntervalFreshnessError(
            f"Freshness policy does not support interval '{interval.value}' without explicit configuration"
        )


def _require_valid_now(now: Any, allow_future: bool = False) -> datetime:
    """Validate injected 'now' parameter, fail-closed on None, non-datetime, naive, or invalid tz.

    Security & Freshness Boundary:
    Arbitrary future 'now' values cannot be injected to defeat freshness evaluation.
    Unless allow_future=True is explicitly passed in trusted simulation/backtest mode,
    'now' cannot be more than 365 days in the future relative to system clock time.
    """
    if now is None:
        raise ValueError("'now' timestamp is required and cannot be None")
    valid_now = _require_valid_tz_dt(now, "now")
    if not allow_future:
        # Enforce boundary against arbitrary distant future timestamps (e.g. year spoofing/bypass)
        # while permitting backtests and testing near the local evaluation horizon.
        max_system_future = datetime.now(timezone.utc) + timedelta(days=365)
        if valid_now.astimezone(timezone.utc) > max_system_future:
            raise ValueError(
                f"Injected 'now' parameter ({valid_now.isoformat()}) is in the distant future "
                f"relative to system clock ({max_system_future.isoformat()}); "
                "trusted historical/simulation mode requires explicit acknowledgement"
            )
    return valid_now


def _extract_record_timestamp(rec: Mapping[str, Any]) -> datetime | None:
    """Extract and parse record timestamp for latest-record selection, verifying timezone awareness.

    Cross-reference: Similar to `_parse_synthetic_record_timestamp` in `provider.py`.
    """
    if not isinstance(rec, Mapping):
        return None
    raw_ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
    if raw_ts is None:
        return None
    if isinstance(raw_ts, datetime):
        ts = raw_ts
    elif isinstance(raw_ts, str):
        try:
            ts = datetime.fromisoformat(raw_ts)
        except (ValueError, TypeError):
            return None
    else:
        return None

    if ts.tzinfo is None:
        return None
    try:
        offset = ts.tzinfo.utcoffset(ts)
        if offset is None:
            return None
    except (AttributeError, ValueError, TypeError, RuntimeError):
        return None
    return ts


@dataclass(frozen=True)
class IngestionResult:
    """Immutable result of single candle ingestion."""

    success: bool
    candle: Candle | None = None
    validation_result: ValidationResult | None = None
    error_message: str | None = None
    error_code: str | None = None
    raw_record: Mapping[str, Any] | None = None
    retrieval_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError(f"success must be a bool, got {type(self.success).__name__}")
        if self.candle is not None and not isinstance(self.candle, Candle):
            raise TypeError(f"candle must be a Candle instance, got {type(self.candle).__name__}")
        if self.success:
            if self.error_message is not None:
                raise ValueError(
                    f"Successful IngestionResult cannot have error_message: {self.error_message!r}"
                )
            if self.error_code is not None:
                raise ValueError(
                    f"Successful IngestionResult cannot have error_code: {self.error_code!r}"
                )
            if self.candle is None:
                raise ValueError("Successful IngestionResult must contain a valid candle")
            if self.validation_result is None:
                raise ValueError("Successful IngestionResult must contain a validation_result")
            if not self.validation_result.is_valid:
                raise ValueError(
                    "Successful IngestionResult cannot contain an invalid validation_result"
                )
        else:
            if self.candle is not None:
                raise ValueError("Failed IngestionResult cannot expose a valid candle")
            if not self.error_message:
                raise ValueError("Failed IngestionResult must contain an error_message")
            if not self.error_code:
                raise ValueError("Failed IngestionResult must contain an error_code")

        if self.raw_record is not None:
            if isinstance(self.raw_record, Mapping):
                object.__setattr__(self, "raw_record", _deep_freeze(self.raw_record))
            else:
                raise TypeError(f"raw_record must be a Mapping, got {type(self.raw_record).__name__}")


@dataclass(frozen=True)
class SequenceIngestionResult:
    """Immutable result of historical candle sequence ingestion."""

    success: bool
    candles: tuple[Candle, ...] = ()
    partial_candles: tuple[Candle, ...] = ()
    validation_result: ValidationResult | None = None
    error_message: str | None = None
    error_code: str | None = None
    raw_record_count: int = 0
    retrieval_timestamp: datetime | None = None
    coverage_status: str = CoverageStatus.COVERAGE_UNVERIFIED.value

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError(f"success must be a bool, got {type(self.success).__name__}")
        if not isinstance(self.candles, tuple):
            object.__setattr__(self, "candles", tuple(self.candles))
        if not isinstance(self.partial_candles, tuple):
            object.__setattr__(self, "partial_candles", tuple(self.partial_candles))

        # Validate candle types in sequence
        for idx, c in enumerate(self.candles):
            if not isinstance(c, Candle):
                raise TypeError(
                    f"candles element at index {idx} must be a Candle instance, got {type(c).__name__}"
                )
        for idx, c in enumerate(self.partial_candles):
            if not isinstance(c, Candle):
                raise TypeError(
                    f"partial_candles element at index {idx} must be a Candle instance, got {type(c).__name__}"
                )

        # Validate symbol and exchange consistency and strictly increasing timestamps
        if len(self.candles) > 0:
            first_sym = self.candles[0].symbol
            first_ex = self.candles[0].exchange
            for idx, c in enumerate(self.candles):
                if c.symbol != first_sym:
                    raise ValueError(
                        f"Candle at index {idx} has conflicting symbol '{c.symbol}' (expected '{first_sym}')"
                    )
                if c.exchange != first_ex:
                    raise ValueError(
                        f"Candle at index {idx} has conflicting exchange '{c.exchange}' (expected '{first_ex}')"
                    )
                if idx > 0 and c.timestamp <= self.candles[idx - 1].timestamp:
                    raise ValueError(
                        f"Candles must be strictly monotonically increasing: index {idx} timestamp "
                        f"({c.timestamp.isoformat()}) <= index {idx - 1} timestamp ({self.candles[idx - 1].timestamp.isoformat()})"
                    )

        if len(self.partial_candles) > 0:
            first_sym = self.partial_candles[0].symbol
            first_ex = self.partial_candles[0].exchange
            for idx, c in enumerate(self.partial_candles):
                if c.symbol != first_sym:
                    raise ValueError(
                        f"Partial candle at index {idx} has conflicting symbol '{c.symbol}' (expected '{first_sym}')"
                    )
                if c.exchange != first_ex:
                    raise ValueError(
                        f"Partial candle at index {idx} has conflicting exchange '{c.exchange}' (expected '{first_ex}')"
                    )
                if idx > 0 and c.timestamp <= self.partial_candles[idx - 1].timestamp:
                    raise ValueError(
                        f"Partial candles must be strictly monotonically increasing: index {idx} timestamp "
                        f"({c.timestamp.isoformat()}) <= index {idx - 1} timestamp ({self.partial_candles[idx - 1].timestamp.isoformat()})"
                    )

        # Validate coverage_status against CoverageStatus enum values
        allowed_statuses = {s.value for s in CoverageStatus}
        status_str = (
            self.coverage_status.value
            if isinstance(self.coverage_status, CoverageStatus)
            else (
                str(self.coverage_status).strip().upper()
                if isinstance(self.coverage_status, str)
                else None
            )
        )
        if status_str not in allowed_statuses:
            raise ValueError(
                f"Invalid coverage_status {self.coverage_status!r}; must be one of {sorted(allowed_statuses)}"
            )
        object.__setattr__(self, "coverage_status", status_str)

        # Validate raw_record_count
        if not isinstance(self.raw_record_count, int) or self.raw_record_count < 0:
            raise ValueError(
                f"raw_record_count must be a non-negative integer, got {self.raw_record_count!r}"
            )

        if self.success:
            if self.coverage_status in (
                CoverageStatus.TRUNCATED_COVERAGE.value,
                CoverageStatus.EMPTY_COVERAGE.value,
                CoverageStatus.MARKET_CALENDAR_REQUIRED.value,
            ):
                raise ValueError(
                    f"Successful SequenceIngestionResult cannot have coverage_status '{self.coverage_status}'"
                )
            if self.error_message is not None:
                raise ValueError(
                    f"Successful SequenceIngestionResult cannot have error_message: {self.error_message!r}"
                )
            if self.error_code is not None:
                raise ValueError(
                    f"Successful SequenceIngestionResult cannot have error_code: {self.error_code!r}"
                )
            if len(self.candles) == 0:
                raise ValueError(
                    "Successful SequenceIngestionResult must contain at least one candle"
                )
            if len(self.partial_candles) != 0:
                raise ValueError(
                    "Successful SequenceIngestionResult cannot contain partial_candles"
                )
            if self.validation_result is None:
                raise ValueError(
                    "Successful SequenceIngestionResult must contain a validation_result"
                )
            if not self.validation_result.is_valid:
                raise ValueError(
                    "Successful SequenceIngestionResult cannot contain an invalid validation_result"
                )
            if self.raw_record_count < len(self.candles):
                raise ValueError(
                    f"raw_record_count ({self.raw_record_count}) cannot be less than number of candles ({len(self.candles)})"
                )
            # A single intraday candle cannot represent FULL_COVERAGE
            if (
                len(self.candles) == 1
                and self.coverage_status == CoverageStatus.FULL_COVERAGE.value
                and self.candles[0].interval not in (CandleInterval.D1, CandleInterval.W1, CandleInterval.MN1)
            ):
                raise ValueError(
                    f"A single intraday candle ({self.candles[0].interval.value}) cannot represent FULL_COVERAGE"
                )
        else:
            if self.coverage_status == CoverageStatus.FULL_COVERAGE.value:
                raise ValueError(
                    "Failed SequenceIngestionResult cannot have coverage_status 'FULL_COVERAGE'"
                )
            if len(self.candles) != 0:
                raise ValueError("Failed SequenceIngestionResult cannot expose valid candles")
            if not self.error_message:
                raise ValueError("Failed SequenceIngestionResult must contain an error_message")
            if not self.error_code:
                raise ValueError("Failed SequenceIngestionResult must contain an error_code")
            if len(self.partial_candles) > 0 and self.raw_record_count < len(self.partial_candles):
                raise ValueError(
                    f"raw_record_count ({self.raw_record_count}) cannot be less than number of partial_candles ({len(self.partial_candles)})"
                )


class MarketDataIngestionPipeline:
    """Pipeline coordinating provider retrieval, adapter normalization, and quality gating."""

    def __init__(
        self,
        provider: MarketDataProvider,
        adapter: ProviderAdapter | None = None,
        freshness_policy: FreshnessPolicy | None = None,
    ) -> None:
        if not isinstance(provider, MarketDataProvider):
            raise TypeError(f"provider must be a MarketDataProvider, got {type(provider).__name__}")
        self._provider = provider
        self._adapter = adapter or StandardDictAdapter(
            source_name=provider.source_name,
            require_payload_identity=True,
        )
        self._freshness_policy = freshness_policy or FreshnessPolicy()

    @property
    def provider(self) -> MarketDataProvider:
        return self._provider

    @property
    def adapter(self) -> ProviderAdapter:
        return self._adapter

    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return self._freshness_policy

    def ingest_record(
        self,
        raw_record: Mapping[str, Any],
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        retrieval_timestamp: datetime,
        now: datetime | None = None,
        max_staleness: timedelta | None = None,
        session: ExchangeSession | None = None,
    ) -> IngestionResult:
        """Adapt a single raw provider record, normalize to Candle, and run M2a quality gate.

        Requires an explicit timezone-aware `now` timestamp to ensure timing and staleness
        validation is strictly enforced (fail-closed).
        Uses interval-aware FreshnessPolicy if `max_staleness` is omitted.
        """
        valid_now = _require_valid_now(now)

        resolved_session: ExchangeSession
        if session is not None:
            resolved_session = session
        else:
            try:
                resolved_session = ExchangeSession.for_exchange(exchange)
            except (ValueError, TypeError):
                resolved_session = DEFAULT_EXCHANGE_SESSION

        # Upfront raw record validation (Finding M-2)
        if not isinstance(raw_record, Mapping):
            return IngestionResult(
                success=False,
                error_message=f"raw_record must be a Mapping, got {type(raw_record).__name__}",
                error_code="RAW_VALIDATION_ERROR",
                raw_record=None,
                retrieval_timestamp=retrieval_timestamp if isinstance(retrieval_timestamp, datetime) else valid_now,
            )
        try:
            frozen_raw = _deep_freeze(raw_record)
        except (AttributeError, ValueError, TypeError, RuntimeError, OverflowError) as exc:
            return IngestionResult(
                success=False,
                error_message=f"raw_record cannot be frozen or validated: {exc}",
                error_code="RAW_VALIDATION_ERROR",
                raw_record=None,
                retrieval_timestamp=retrieval_timestamp if isinstance(retrieval_timestamp, datetime) else valid_now,
            )

        # Provenance integrity validation (Finding M-4)
        clean_prov_source = self._provider.source_name.strip().upper()
        clean_adapt_source = self._adapter.source_name.strip().upper()
        if clean_prov_source != clean_adapt_source:
            return IngestionResult(
                success=False,
                error_message=(
                    f"Pipeline provider source '{self._provider.source_name}' does not match "
                    f"adapter source '{self._adapter.source_name}'"
                ),
                error_code="PROVENANCE_MISMATCH",
                raw_record=frozen_raw,
                retrieval_timestamp=retrieval_timestamp,
            )

        # Step 1: Raw data validation & normalization via adapter
        try:
            candle = self._adapter.adapt_record(
                raw_record=frozen_raw,
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                retrieval_timestamp=retrieval_timestamp,
            )
        except RawDataValidationError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Raw payload validation failed: {exc}",
                error_code="RAW_VALIDATION_ERROR",
                raw_record=frozen_raw,
                retrieval_timestamp=retrieval_timestamp,
            )
        except (AttributeError, ValueError, TypeError, RuntimeError, OverflowError) as exc:
            return IngestionResult(
                success=False,
                error_message=f"Unexpected adaptation error: {exc}",
                error_code="ADAPTATION_EXCEPTION",
                raw_record=frozen_raw,
                retrieval_timestamp=retrieval_timestamp,
            )

        # Resolve staleness threshold (Finding H-1)
        if max_staleness is not None:
            _require_valid_max_staleness(max_staleness)
            staleness_limit = max_staleness
        else:
            try:
                staleness_limit = self._freshness_policy.get_max_staleness(
                    interval=candle.interval,
                    now=valid_now,
                    candle_close_time=candle.close_time,
                    session=resolved_session,
                )
            except UnsupportedIntervalFreshnessError as exc:
                return IngestionResult(
                    success=False,
                    error_message=f"Freshness policy error: {exc}",
                    error_code="UNSUPPORTED_FRESHNESS_INTERVAL",
                    raw_record=frozen_raw,
                    retrieval_timestamp=retrieval_timestamp,
                )
            except MarketCalendarRequiredError as exc:
                return IngestionResult(
                    success=False,
                    error_message=f"Market calendar required: {exc}",
                    error_code="MARKET_CALENDAR_REQUIRED",
                    raw_record=frozen_raw,
                    retrieval_timestamp=retrieval_timestamp,
                )

        # Step 2: Authoritative M2a quality validation
        val_res = validate_candle(candle, now=valid_now, max_staleness=staleness_limit, session=resolved_session)
        if not val_res.is_valid:
            return IngestionResult(
                success=False,
                candle=None,
                validation_result=val_res,
                error_message=f"M2a quality gate rejected candle: {list(val_res.error_codes)}",
                error_code="QUALITY_GATE_REJECTED",
                raw_record=frozen_raw,
                retrieval_timestamp=retrieval_timestamp,
            )

        return IngestionResult(
            success=True,
            candle=candle,
            validation_result=val_res,
            raw_record=frozen_raw,
            retrieval_timestamp=retrieval_timestamp,
        )

    def ingest_latest(
        self,
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        now: datetime | None = None,
        max_staleness: timedelta | None = None,
        session: ExchangeSession | None = None,
    ) -> IngestionResult:
        """Fetch latest completed bar from provider, normalize, and validate.

        Requires an explicit timezone-aware `now` timestamp to ensure timing and staleness
        validation is strictly enforced (fail-closed).
        Default staleness threshold is 30 minutes if `max_staleness` is omitted.
        """
        valid_now = _require_valid_now(now)

        try:
            resp = self._provider.fetch_latest(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                now=valid_now,
            )
        except ProviderTimeoutError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Provider timed out: {exc}",
                error_code="TIMEOUT",
                retrieval_timestamp=valid_now,
            )
        except ProviderConnectionError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Provider connection error: {exc}",
                error_code="PROVIDER_CONNECTION_ERROR",
                retrieval_timestamp=valid_now,
            )
        except ProviderPayloadError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Provider payload error: {exc}",
                error_code="PROVIDER_PAYLOAD_ERROR",
                retrieval_timestamp=valid_now,
            )
        except ProviderError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Provider error: {exc}",
                error_code="PROVIDER_ERROR",
                retrieval_timestamp=valid_now,
            )
        except (AttributeError, ValueError, TypeError, RuntimeError) as exc:
            return IngestionResult(
                success=False,
                error_message=f"Unexpected provider exception: {exc}",
                error_code="PROVIDER_EXCEPTION",
                retrieval_timestamp=valid_now,
            )

        if not isinstance(resp, ProviderResponse):
            return IngestionResult(
                success=False,
                error_message=f"Provider returned invalid response type: {type(resp).__name__}",
                error_code="INVALID_PROVIDER_RESPONSE",
                retrieval_timestamp=valid_now,
            )

        try:
            _require_valid_tz_dt(resp.retrieval_timestamp, "retrieval_timestamp")
        except ValueError as exc:
            return IngestionResult(
                success=False,
                error_message=f"Invalid retrieval timestamp in provider response: {exc}",
                error_code="INVALID_RETRIEVAL_TIMESTAMP",
                retrieval_timestamp=valid_now,
            )

        # Provenance integrity validation at pipeline boundary (Finding M-4)
        clean_resp_source = resp.source.strip().upper()
        clean_prov_source = self._provider.source_name.strip().upper()
        clean_adapt_source = self._adapter.source_name.strip().upper()

        if clean_resp_source != clean_prov_source:
            return IngestionResult(
                success=False,
                error_message=(
                    f"ProviderResponse source '{resp.source}' does not match "
                    f"provider source_name '{self._provider.source_name}'"
                ),
                error_code="PROVENANCE_MISMATCH",
                retrieval_timestamp=valid_now,
            )

        if clean_resp_source != clean_adapt_source:
            return IngestionResult(
                success=False,
                error_message=(
                    f"ProviderResponse source '{resp.source}' does not match "
                    f"adapter source_name '{self._adapter.source_name}'"
                ),
                error_code="PROVENANCE_MISMATCH",
                retrieval_timestamp=valid_now,
            )

        if resp.retrieval_timestamp > valid_now:
            return IngestionResult(
                success=False,
                error_message=(
                    f"Provider response retrieval timestamp ({resp.retrieval_timestamp.isoformat()}) "
                    f"is in the future relative to evaluation now ({valid_now.isoformat()})"
                ),
                error_code="RETRIEVAL_AFTER_NOW",
                retrieval_timestamp=resp.retrieval_timestamp,
            )

        if not resp.success:
            return IngestionResult(
                success=False,
                error_message=resp.error_message or "Provider reported failure",
                error_code=resp.error_code or "PROVIDER_ERROR",
                retrieval_timestamp=resp.retrieval_timestamp,
            )

        if not resp.records:
            return IngestionResult(
                success=False,
                error_message=f"Provider returned 0 records for latest candle of {symbol}",
                error_code="EMPTY_PROVIDER_RESPONSE",
                retrieval_timestamp=resp.retrieval_timestamp,
            )

        # Inspect provider response cardinality and resolve newest record unambiguously (Finding L-3)
        if len(resp.records) == 1:
            selected_record = resp.records[0]
        else:
            records_with_ts: list[tuple[datetime, Mapping[str, Any]]] = []
            for rec in resp.records:
                rec_ts = _extract_record_timestamp(rec)
                if rec_ts is None:
                    return IngestionResult(
                        success=False,
                        error_message=(
                            f"Provider returned multiple records for {symbol} with missing or "
                            "unparseable timestamps; ambiguous latest record"
                        ),
                        error_code="AMBIGUOUS_LATEST_RECORD",
                        retrieval_timestamp=resp.retrieval_timestamp,
                    )
                records_with_ts.append((rec_ts, rec))

            max_ts = max(ts for ts, _ in records_with_ts)
            newest_records = [rec for ts, rec in records_with_ts if ts == max_ts]

            if len(newest_records) > 1:
                return IngestionResult(
                    success=False,
                    error_message=(
                        f"Provider returned {len(newest_records)} duplicate or conflicting records "
                        f"sharing the maximum timestamp {max_ts.isoformat()}; ambiguous latest record"
                    ),
                    error_code="AMBIGUOUS_LATEST_RECORD",
                    retrieval_timestamp=resp.retrieval_timestamp,
                )

            selected_record = newest_records[0]

        return self.ingest_record(
            raw_record=selected_record,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            retrieval_timestamp=resp.retrieval_timestamp,
            now=valid_now,
            max_staleness=max_staleness,
            session=session,
        )

    def ingest_historical(
        self,
        request: HistoricalDataRequest,
        now: datetime | None = None,
        max_staleness: timedelta | None = None,
        check_gaps: bool = True,
        require_full_coverage: bool = False,
        allow_partial: bool = False,
        calendar: ExchangeCalendar | None = None,
        allow_sparse: bool = False,
    ) -> SequenceIngestionResult:
        """Fetch historical records from provider, normalize, and validate through M2a sequence gate.

        Requires an explicit timezone-aware `now` timestamp to ensure timing and staleness
        validation is strictly enforced (fail-closed).
        Historical backfills (`request.end_time <= now`) do not enforce live wall-clock staleness
        unless `max_staleness` is explicitly provided.
        Queries extending to current wall-clock time apply the interval-aware FreshnessPolicy.
        Enforces strict boundary checking on `[request.start_time, request.end_time)` and `close_time <= end_time`.
        Reports `coverage_status='EMPTY_COVERAGE'` if the provider returns 0 records.
        Reports `coverage_status='TRUNCATED_COVERAGE'` if the returned data does not span the requested
        start and end boundaries or contains interior sequence gaps (missing intervals or unverified multi-day transitions).
        Incomplete or truncated coverage fails closed by default (`success=False`).
        If caller explicitly opts in with `allow_partial=True`, `success=False` is preserved while partial
        candles are safely returned in `partial_candles` with `candles=()`.
        When boundaries match and interior continuity passes available checks with exchange calendar evidence,
        reports `coverage_status='FULL_COVERAGE'`; without calendar evidence, reports `coverage_status='COVERAGE_UNVERIFIED'`.
        """
        valid_now = _require_valid_now(now)

        try:
            resp = self._provider.fetch_historical(request)
        except ProviderTimeoutError as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Provider timed out: {exc}",
                error_code="TIMEOUT",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )
        except ProviderConnectionError as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Provider connection error: {exc}",
                error_code="PROVIDER_CONNECTION_ERROR",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )
        except ProviderPayloadError as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Provider payload error: {exc}",
                error_code="PROVIDER_PAYLOAD_ERROR",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )
        except ProviderError as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Provider error: {exc}",
                error_code="PROVIDER_ERROR",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )
        except (AttributeError, ValueError, TypeError, RuntimeError) as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Unexpected provider exception: {exc}",
                error_code="PROVIDER_EXCEPTION",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        if not isinstance(resp, ProviderResponse):
            return SequenceIngestionResult(
                success=False,
                error_message=f"Provider returned invalid response type: {type(resp).__name__}",
                error_code="INVALID_PROVIDER_RESPONSE",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        try:
            _require_valid_tz_dt(resp.retrieval_timestamp, "retrieval_timestamp")
        except ValueError as exc:
            return SequenceIngestionResult(
                success=False,
                error_message=f"Invalid retrieval timestamp in provider response: {exc}",
                error_code="INVALID_RETRIEVAL_TIMESTAMP",
                raw_record_count=0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        # Provenance integrity validation at pipeline boundary (Finding M-4)
        clean_resp_source = resp.source.strip().upper()
        clean_prov_source = self._provider.source_name.strip().upper()
        clean_adapt_source = self._adapter.source_name.strip().upper()

        if clean_resp_source != clean_prov_source:
            return SequenceIngestionResult(
                success=False,
                error_message=(
                    f"ProviderResponse source '{resp.source}' does not match "
                    f"provider source_name '{self._provider.source_name}'"
                ),
                error_code="PROVENANCE_MISMATCH",
                raw_record_count=len(resp.records) if resp.records else 0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        if clean_resp_source != clean_adapt_source:
            return SequenceIngestionResult(
                success=False,
                error_message=(
                    f"ProviderResponse source '{resp.source}' does not match "
                    f"adapter source_name '{self._adapter.source_name}'"
                ),
                error_code="PROVENANCE_MISMATCH",
                raw_record_count=len(resp.records) if resp.records else 0,
                retrieval_timestamp=valid_now,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        if resp.retrieval_timestamp > valid_now:
            return SequenceIngestionResult(
                success=False,
                candles=(),
                error_message=(
                    f"Provider response retrieval timestamp ({resp.retrieval_timestamp.isoformat()}) "
                    f"is in the future relative to evaluation now ({valid_now.isoformat()})"
                ),
                error_code="RETRIEVAL_AFTER_NOW",
                raw_record_count=len(resp.records),
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        if not resp.success:
            return SequenceIngestionResult(
                success=False,
                error_message=resp.error_message or "Provider reported failure",
                error_code=resp.error_code or "PROVIDER_ERROR",
                raw_record_count=0,
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
            )

        if not resp.records:
            return SequenceIngestionResult(
                success=False,
                candles=(),
                partial_candles=(),
                error_message=f"Provider returned 0 records for request {request.symbol}",
                error_code="EMPTY_PROVIDER_RESPONSE",
                raw_record_count=0,
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=CoverageStatus.EMPTY_COVERAGE.value,
            )

        # Step 1: Normalize all records to Candle domain models via adapter
        candles_list: list[Candle] = []
        for i, raw_rec in enumerate(resp.records):
            try:
                candle = self._adapter.adapt_record(
                    raw_record=raw_rec,
                    symbol=request.symbol,
                    exchange=request.exchange,
                    interval=request.interval,
                    retrieval_timestamp=resp.retrieval_timestamp,
                )
                candles_list.append(candle)
            except RawDataValidationError as exc:
                return SequenceIngestionResult(
                    success=False,
                    error_message=f"Raw validation error at record index {i}: {exc}",
                    error_code="RAW_VALIDATION_ERROR",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )
            except (AttributeError, ValueError, TypeError, RuntimeError, OverflowError) as exc:
                return SequenceIngestionResult(
                    success=False,
                    error_message=f"Unexpected adaptation error at record index {i}: {exc}",
                    error_code="ADAPTATION_EXCEPTION",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )

        # Step 2: Request window boundary enforcement (Finding H-2)
        req_start_utc = request.start_time.astimezone(UTC)
        req_end_utc = request.end_time.astimezone(UTC)

        for candle in candles_list:
            c_open_utc = candle.timestamp.astimezone(UTC)
            c_close_utc = candle.close_time.astimezone(UTC)

            if c_open_utc < req_start_utc:
                return SequenceIngestionResult(
                    success=False,
                    candles=(),
                    partial_candles=tuple(candles_list) if allow_partial else (),
                    error_message=(
                        f"Candle open time ({candle.timestamp.isoformat()}) is before "
                        f"request start time ({request.start_time.isoformat()})"
                    ),
                    error_code="BOUNDARY_VIOLATION",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )
            if c_open_utc >= req_end_utc:
                return SequenceIngestionResult(
                    success=False,
                    candles=(),
                    partial_candles=tuple(candles_list) if allow_partial else (),
                    error_message=(
                        f"Candle open time ({candle.timestamp.isoformat()}) is at or after "
                        f"request end time ({request.end_time.isoformat()})"
                    ),
                    error_code="BOUNDARY_VIOLATION",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )
            if c_close_utc > req_end_utc:
                return SequenceIngestionResult(
                    success=False,
                    candles=(),
                    partial_candles=tuple(candles_list) if allow_partial else (),
                    error_message=(
                        f"Candle close time ({candle.close_time.isoformat()}) exceeds "
                        f"request end time ({request.end_time.isoformat()})"
                    ),
                    error_code="BOUNDARY_VIOLATION",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )

        candles_tuple = tuple(candles_list)

        if calendar is not None and calendar.is_populated and not calendar.has_evidence_for_range(
            request.start_time.date(), request.end_time.date()
        ):
            return SequenceIngestionResult(
                success=False,
                error_message="Market calendar does not provide complete evidence for the requested window",
                error_code="MARKET_CALENDAR_REQUIRED",
                raw_record_count=len(resp.records),
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=CoverageStatus.MARKET_CALENDAR_REQUIRED.value,
            )

        # Resolve session from calendar or exchange
        resolved_session: ExchangeSession
        if calendar is not None:
            resolved_session = calendar.get_session(request.start_time.date())
        else:
            try:
                resolved_session = ExchangeSession.for_exchange(request.exchange)
            except (ValueError, TypeError):
                resolved_session = DEFAULT_EXCHANGE_SESSION

        # Step 3: Authoritative sequence quality validation
        eval_now = valid_now
        check_staleness: bool
        if max_staleness is not None:
            _require_valid_max_staleness(max_staleness)
            staleness_limit = max_staleness
            check_staleness = True
        elif request.end_time < valid_now:
            # Strictly historical backfill in the past: disable live staleness
            staleness_limit = None
            check_staleness = False
        else:
            # request.end_time >= valid_now: covers current wall-clock time, enforce live FreshnessPolicy
            try:
                latest_close = candles_list[-1].close_time if candles_list else None
                staleness_limit = self._freshness_policy.get_max_staleness(
                    interval=request.interval,
                    now=valid_now,
                    candle_close_time=latest_close,
                    session=resolved_session,
                    calendar=calendar,
                )
                check_staleness = True
            except UnsupportedIntervalFreshnessError as exc:
                return SequenceIngestionResult(
                    success=False,
                    error_message=f"Freshness policy error: {exc}",
                    error_code="UNSUPPORTED_FRESHNESS_INTERVAL",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value,
                )
            except MarketCalendarRequiredError as exc:
                return SequenceIngestionResult(
                    success=False,
                    error_message=f"Market calendar required: {exc}",
                    error_code="MARKET_CALENDAR_REQUIRED",
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=CoverageStatus.MARKET_CALENDAR_REQUIRED.value,
                )

        val_res = validate_candle_sequence(
            candles_tuple,
            expected_interval=request.interval,
            now=eval_now,
            max_staleness=staleness_limit,
            check_gaps=check_gaps,
            check_staleness=check_staleness,
            session=resolved_session,
            calendar=calendar,
            allow_sparse=allow_sparse,
        )

        # Coverage evaluation: boundary coverage and interior continuity
        c_first_utc = candles_list[0].timestamp.astimezone(UTC)
        c_last_close_utc = candles_list[-1].close_time.astimezone(UTC)

        is_d1 = (request.interval == CandleInterval.D1)
        if is_d1:
            req_start_local = request.start_time.astimezone(resolved_session.timezone)
            req_end_local = request.end_time.astimezone(resolved_session.timezone)
            c_first_local = candles_list[0].timestamp.astimezone(resolved_session.timezone)
            c_last_close_local = candles_list[-1].close_time.astimezone(resolved_session.timezone)

            # Start boundary: candle opening on start date satisfies start boundary if req_start is <= session open
            start_ok = (c_first_local.date() == req_start_local.date()) or (c_first_utc <= req_start_utc)
            # End boundary: if req_end is midnight next day (00:00:00) or >= session close on end date
            end_date = (
                req_end_local.date() - timedelta(days=1)
                if (req_end_local.time() == time(0, 0))
                else req_end_local.date()
            )
            end_ok = (c_last_close_local.date() == end_date) or (c_last_close_utc >= req_end_utc)
            is_boundary_truncated = not (start_ok and end_ok)
        elif allow_sparse:
            # In sparse mode for illiquid instruments, missing window edge bars are permitted
            is_boundary_truncated = False
        else:
            is_boundary_truncated = (c_first_utc > req_start_utc) or (c_last_close_utc < req_end_utc)

        # Interior continuity / gap check reusing M2a session-aware sequence integrity
        integrity_issues = check_sequence_integrity(
            candles_tuple,
            expected_interval=request.interval,
            session=resolved_session,
            calendar=calendar,
            allow_sparse=allow_sparse,
        )
        has_missing_interval = any(
            issue.code == DataQualityErrorCode.MISSING_INTERVAL for issue in integrity_issues
        )
        has_calendar_required = any(
            issue.code == DataQualityErrorCode.MARKET_CALENDAR_REQUIRED for issue in integrity_issues
        )
        has_exchange_mismatch = any(
            issue.code == DataQualityErrorCode.EXCHANGE_MISMATCH for issue in integrity_issues
        )

        # Check if calendar has sufficient evidence covering the entire query window
        has_calendar_evidence = (
            calendar is not None
            and calendar.is_populated
            and calendar.has_evidence_for_range(request.start_time.date(), request.end_time.date())
        )

        # Check if an intermediate scheduled weekday was skipped across multi-day transitions without calendar
        skipped_weekday = False
        if not has_calendar_evidence and len(candles_tuple) > 1:
            for i in range(len(candles_tuple) - 1):
                c1 = candles_tuple[i].timestamp.astimezone(resolved_session.timezone).date()
                c2 = candles_tuple[i + 1].timestamp.astimezone(resolved_session.timezone).date()
                day_gap = (c2 - c1).days
                if day_gap > 1 and any((c1 + timedelta(days=d)).weekday() < 5 for d in range(1, day_gap)):
                    skipped_weekday = True
                    break

        has_interior_gap = has_missing_interval or has_calendar_required or has_exchange_mismatch or skipped_weekday
        is_truncated = is_boundary_truncated or has_interior_gap

        # Check if sparse mode detected missing intervals or missing edge bars
        is_sparse_detected = allow_sparse and (
            has_missing_interval
            or (c_first_utc > req_start_utc)
            or (c_last_close_utc < req_end_utc)
        )

        if has_calendar_required or val_res.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED):
            coverage_status = CoverageStatus.MARKET_CALENDAR_REQUIRED.value
        elif is_boundary_truncated or has_missing_interval or has_exchange_mismatch or skipped_weekday:
            if allow_sparse and not is_boundary_truncated and not has_exchange_mismatch:
                coverage_status = CoverageStatus.SPARSE_COVERAGE.value
            else:
                coverage_status = CoverageStatus.TRUNCATED_COVERAGE.value
        elif is_sparse_detected:
            coverage_status = CoverageStatus.SPARSE_COVERAGE.value
        elif has_calendar_evidence:
            coverage_status = CoverageStatus.FULL_COVERAGE.value
        else:
            coverage_status = CoverageStatus.COVERAGE_UNVERIFIED.value

        # Quality gate failure check
        if not val_res.is_valid:
            if (has_calendar_required or val_res.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)) and not val_res.has_error(DataQualityErrorCode.MISSING_INTERVAL):
                failure_coverage = CoverageStatus.MARKET_CALENDAR_REQUIRED.value
                err_code = "MARKET_CALENDAR_REQUIRED"
            elif is_boundary_truncated or val_res.has_error(DataQualityErrorCode.MISSING_INTERVAL) or skipped_weekday:
                failure_coverage = CoverageStatus.TRUNCATED_COVERAGE.value
                err_code = "QUALITY_GATE_REJECTED"
            elif has_calendar_required or val_res.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED):
                failure_coverage = CoverageStatus.MARKET_CALENDAR_REQUIRED.value
                err_code = "MARKET_CALENDAR_REQUIRED"
            else:
                if coverage_status == CoverageStatus.FULL_COVERAGE.value:
                    failure_coverage = CoverageStatus.COVERAGE_UNVERIFIED.value
                else:
                    failure_coverage = coverage_status
                err_code = "QUALITY_GATE_REJECTED"

            return SequenceIngestionResult(
                success=False,
                candles=(),
                partial_candles=candles_tuple if allow_partial else (),
                validation_result=val_res,
                error_message=f"M2a quality gate rejected sequence: {list(val_res.error_codes)}",
                error_code=err_code,
                raw_record_count=len(resp.records),
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=failure_coverage,
            )

        # Fail closed on truncation unless legitimate sparse mode was requested
        if is_truncated and not (allow_sparse and coverage_status == CoverageStatus.SPARSE_COVERAGE.value):
            reasons = []
            if is_boundary_truncated:
                reasons.append("outer window boundary truncated")
            if has_missing_interval or skipped_weekday:
                reasons.append("interior sequence gap detected")
            if has_calendar_required and not skipped_weekday:
                reasons.append("unverified multi-day gap requires calendar evidence")
            if has_exchange_mismatch:
                reasons.append("exchange mismatch detected")
            reason_str = " and ".join(reasons)
            if (has_calendar_required and not is_boundary_truncated and not has_missing_interval and not has_exchange_mismatch and not skipped_weekday):
                err_code = "MARKET_CALENDAR_REQUIRED"
                failure_coverage = CoverageStatus.MARKET_CALENDAR_REQUIRED.value
            else:
                err_code = "TRUNCATED_COVERAGE"
                failure_coverage = CoverageStatus.TRUNCATED_COVERAGE.value
            return SequenceIngestionResult(
                success=False,
                candles=(),
                partial_candles=candles_tuple if allow_partial else (),
                validation_result=val_res,
                error_message=(
                    f"Historical sequence coverage is truncated ({reason_str}): "
                    f"requested window [{request.start_time.isoformat()} to {request.end_time.isoformat()}], "
                    f"returned data [{candles_list[0].timestamp.isoformat()} to {candles_list[-1].close_time.isoformat()}]"
                ),
                error_code=err_code,
                raw_record_count=len(resp.records),
                retrieval_timestamp=resp.retrieval_timestamp,
                coverage_status=failure_coverage,
            )

        # Enforce require_full_coverage contract (Priority 3)
        if require_full_coverage:
            if coverage_status != CoverageStatus.FULL_COVERAGE.value:
                err_map = {
                    CoverageStatus.COVERAGE_UNVERIFIED.value: (
                        "COVERAGE_UNVERIFIED",
                        "Historical sequence coverage cannot be verified without authoritative exchange calendar evidence",
                    ),
                    CoverageStatus.SPARSE_COVERAGE.value: (
                        "SPARSE_COVERAGE",
                        "Historical sequence contains sparse data gaps and does not satisfy require_full_coverage=True",
                    ),
                    CoverageStatus.MARKET_CALENDAR_REQUIRED.value: (
                        "MARKET_CALENDAR_REQUIRED",
                        "Historical sequence coverage requires exchange calendar evidence",
                    ),
                    CoverageStatus.TRUNCATED_COVERAGE.value: (
                        "TRUNCATED_COVERAGE",
                        "Historical sequence coverage is truncated",
                    ),
                }
                err_code, err_msg = err_map.get(
                    coverage_status,
                    ("INCOMPLETE_COVERAGE", f"Coverage status '{coverage_status}' fails require_full_coverage=True"),
                )
                return SequenceIngestionResult(
                    success=False,
                    candles=(),
                    partial_candles=candles_tuple if allow_partial else (),
                    validation_result=val_res,
                    error_message=err_msg,
                    error_code=err_code,
                    raw_record_count=len(resp.records),
                    retrieval_timestamp=resp.retrieval_timestamp,
                    coverage_status=coverage_status,
                )

        return SequenceIngestionResult(
            success=True,
            candles=candles_tuple,
            partial_candles=(),
            validation_result=val_res,
            raw_record_count=len(resp.records),
            retrieval_timestamp=resp.retrieval_timestamp,
            coverage_status=coverage_status,
        )
