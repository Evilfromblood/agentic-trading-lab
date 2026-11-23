"""Provider-independent market data interfaces and synthetic provider for NSE/BSE.

Defines the contract for external market data sources, explicit request/response
structures, error models, and a deterministic synthetic provider for development
and testing without network or broker dependencies.
"""
from __future__ import annotations

import calendar as py_calendar
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from agentic_trading.market_data.models import (
    DEFAULT_EXCHANGE_SESSION,
    IST,
    CandleInterval,
    Exchange,
    ExchangeSession,
    _deep_freeze,
)

# Valid NSE/BSE equity symbol format for historical requests: alphanumeric with hyphens, underscores, or ampersands
_VALID_SYMBOL_REGEX = re.compile(r"^[A-Z0-9&_\-]+$")


class ProviderError(Exception):
    """Base exception for external market data provider failures."""


class ProviderTimeoutError(ProviderError):
    """Raised when an external market data provider request times out."""


class ProviderPayloadError(ProviderError):
    """Raised when an external market data provider returns an unparseable payload."""


class ProviderConnectionError(ProviderError):
    """Raised when connection to an external market data provider fails."""


def _require_valid_tz_dt(dt: Any, field_name: str) -> datetime:
    """Validate timezone-aware datetime, fail-closed on None, non-datetime, naive, or invalid tz."""
    if isinstance(dt, bool) or not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    try:
        offset = dt.tzinfo.utcoffset(dt)
    except (AttributeError, ValueError, TypeError, OverflowError, RuntimeError) as exc:
        raise ValueError(f"{field_name} timezone calculation failed: {exc}") from exc
    if offset is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime (utcoffset returned None)")
    return dt


# Backward compatibility alias for _require_valid_tz_dt
_validate_request_datetime = _require_valid_tz_dt


def _parse_synthetic_record_timestamp(rec: Mapping[str, Any]) -> datetime | None:
    """Extract and parse record timestamp for range filtering in synthetic provider.

    Cross-reference: Similar to `_extract_record_timestamp` in `ingestion.py`. Maintained
    here for provider-internal synthetic filtering without coupling to ingestion pipeline.
    """
    raw_ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
    if raw_ts is None:
        return None
    if isinstance(raw_ts, datetime):
        return raw_ts
    if isinstance(raw_ts, str):
        try:
            return datetime.fromisoformat(raw_ts)
        except (ValueError, TypeError):
            return None
    return None


@dataclass(frozen=True)
class HistoricalDataRequest:
    """Immutable request specification for historical market data retrieval."""

    symbol: str
    exchange: Exchange
    interval: CandleInterval
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = self.symbol.strip().upper()
        if not _VALID_SYMBOL_REGEX.match(clean_symbol):
            raise ValueError(
                f"symbol contains invalid characters: {self.symbol!r} "
                "(must contain only alphanumeric characters, hyphens, underscores, or ampersands)"
            )
        object.__setattr__(self, "symbol", clean_symbol)

        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")
        if not isinstance(self.interval, CandleInterval):
            raise TypeError(f"interval must be a CandleInterval enum, got {type(self.interval).__name__}")

        _require_valid_tz_dt(self.start_time, "start_time")
        _require_valid_tz_dt(self.end_time, "end_time")

        try:
            is_start_ge_end = self.start_time >= self.end_time
        except (AttributeError, ValueError, TypeError, OverflowError, RuntimeError) as exc:
            raise ValueError(f"Failed to compare start_time and end_time: {exc}") from exc

        if is_start_ge_end:
            raise ValueError(
                f"start_time ({self.start_time.isoformat()}) must be strictly prior to "
                f"end_time ({self.end_time.isoformat()})"
            )


# Unified _deep_freeze imported from models.py


@dataclass(frozen=True)
class ProviderResponse:
    """Immutable envelope for market data provider responses."""

    success: bool
    source: str
    retrieval_timestamp: datetime
    records: tuple[Mapping[str, Any], ...] = ()
    error_message: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("success must be a bool")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        _require_valid_tz_dt(self.retrieval_timestamp, "retrieval_timestamp")
        records_tuple = tuple(self.records) if not isinstance(self.records, tuple) else self.records
        frozen_records: list[Any] = []
        for r in records_tuple:
            if not isinstance(r, Mapping):
                raise TypeError(f"ProviderResponse record must be a Mapping, got {type(r).__name__}")
            frozen_records.append(_deep_freeze(r))
        object.__setattr__(self, "records", tuple(frozen_records))


class MarketDataProvider(ABC):
    """Abstract base class for market data providers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Declared identifier of the market data source."""

    @abstractmethod
    def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
        """Fetch historical candle records matching the request parameters."""

    @abstractmethod
    def fetch_latest(
        self,
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        now: datetime | None = None,
    ) -> ProviderResponse:
        """Fetch the single latest completed candle record."""


def _calculate_synthetic_close_time(
    ts: datetime,
    interval: CandleInterval,
    exchange: Exchange = Exchange.NSE,
) -> datetime:
    """Calculate the completion/close time of a synthetic candle respecting session boundaries."""
    try:
        session = ExchangeSession.for_exchange(exchange)
    except (ValueError, TypeError):
        session = DEFAULT_EXCHANGE_SESSION

    if interval == CandleInterval.D1:
        try:
            ts_local = ts.astimezone(session.timezone)
            if ts_local.time() < session.session_close:
                close_local = ts_local.replace(
                    hour=session.session_close.hour,
                    minute=session.session_close.minute,
                    second=0,
                    microsecond=0,
                )
                return close_local.astimezone(ts.tzinfo)
        except (AttributeError, ValueError, TypeError, OverflowError):
            pass
        return ts + interval.duration

    if interval == CandleInterval.MN1:
        try:
            ts_local = ts.astimezone(session.timezone)
            num_days = py_calendar.monthrange(ts_local.year, ts_local.month)[1]
            last_day = ts_local.date().replace(day=num_days)
            close_local = ts_local.replace(
                year=last_day.year,
                month=last_day.month,
                day=last_day.day,
                hour=session.session_close.hour,
                minute=session.session_close.minute,
                second=0,
                microsecond=0,
            )
            return close_local.astimezone(ts.tzinfo)
        except (AttributeError, ValueError, TypeError, OverflowError):
            pass
        return ts + interval.duration

    nominal_close = ts + interval.duration
    if interval in (
        CandleInterval.M1,
        CandleInterval.M3,
        CandleInterval.M5,
        CandleInterval.M10,
        CandleInterval.M15,
        CandleInterval.M30,
        CandleInterval.H1,
    ):
        try:
            ts_local = ts.astimezone(session.timezone)
            nom_close_local = nominal_close.astimezone(session.timezone)
            if (
                ts_local.time() < session.session_close
                and nom_close_local.date() == ts_local.date()
                and nom_close_local.time() > session.session_close
            ):
                truncated_local = ts_local.replace(
                    hour=session.session_close.hour,
                    minute=session.session_close.minute,
                    second=0,
                    microsecond=0,
                )
                return truncated_local.astimezone(ts.tzinfo)
        except (AttributeError, ValueError, TypeError, OverflowError):
            pass
    return nominal_close


class SyntheticMarketDataProvider(MarketDataProvider):
    """Deterministic synthetic market data provider for testing and offline development.

    Supports pre-configured records, failure simulation (timeouts, errors, empty results),
    and synthetic continuous NSE bar generation.
    """

    def __init__(
        self,
        source_name: str = "SYNTHETIC_NSE",
        records: list[Mapping[str, Any]] | None = None,
        simulate_timeout: bool = False,
        simulate_error: str | None = None,
    ) -> None:
        self._source_name = source_name
        self._records = list(records) if records is not None else []
        self._simulate_timeout = simulate_timeout
        self._simulate_error = simulate_error

    @property
    def source_name(self) -> str:
        return self._source_name

    def set_records(self, records: list[Mapping[str, Any]]) -> None:
        """Update the stored synthetic records."""
        self._records = list(records)

    def set_failure_mode(
        self,
        simulate_timeout: bool = False,
        simulate_error: str | None = None,
    ) -> None:
        """Configure simulation of provider faults."""
        self._simulate_timeout = simulate_timeout
        self._simulate_error = simulate_error

    def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
        """Fetch historical candle records matching the request parameters.

        Note on timing determinism: retrieval_timestamp is set to request.end_time.
        If request.end_time is in the future relative to wall-clock time, retrieval_timestamp
        will also reflect that end_time; this is intentional for deterministic offline testing.
        """
        retrieval_time = request.end_time

        if self._simulate_timeout:
            return ProviderResponse(
                success=False,
                source=self._source_name,
                retrieval_timestamp=retrieval_time,
                error_message="Synthetic provider timed out",
                error_code="TIMEOUT",
            )

        if self._simulate_error:
            return ProviderResponse(
                success=False,
                source=self._source_name,
                retrieval_timestamp=retrieval_time,
                error_message=self._simulate_error,
                error_code="PROVIDER_ERROR",
            )

        # Filter stored records strictly by request parameters (symbol, exchange, interval, and [start_time, end_time))
        matched: list[Mapping[str, Any]] = []
        for r in self._records:
            r_sym = r.get("symbol")
            if r_sym is None or str(r_sym).strip().upper() != request.symbol:
                continue

            r_ex = r.get("exchange")
            if r_ex is None:
                continue
            ex_val = r_ex.value if isinstance(r_ex, Exchange) else str(r_ex).strip().upper()
            if ex_val != request.exchange.value:
                continue

            r_iv = r.get("interval")
            if r_iv is None:
                continue
            iv_val = r_iv.value if isinstance(r_iv, CandleInterval) else str(r_iv).strip()
            if iv_val != request.interval.value:
                continue

            # Time range filter using candle convention [start_time, end_time) and rec_close <= end_time
            rec_ts = _parse_synthetic_record_timestamp(r)
            if rec_ts is None or rec_ts.tzinfo is None:
                continue
            rec_close = _calculate_synthetic_close_time(rec_ts, request.interval, exchange=request.exchange)
            try:
                is_outside_range = (
                    rec_ts < request.start_time
                    or rec_ts >= request.end_time
                    or rec_close > request.end_time
                )
            except (ValueError, TypeError, RuntimeError):
                is_outside_range = True

            if is_outside_range:
                continue

            matched.append(r)

        return ProviderResponse(
            success=True,
            source=self._source_name,
            retrieval_timestamp=retrieval_time,
            records=tuple(matched),
        )

    def fetch_latest(
        self,
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        now: datetime | None = None,
    ) -> ProviderResponse:
        matched: list[Mapping[str, Any]] = []
        clean_target_sym = symbol.strip().upper()
        for r in self._records:
            r_sym = r.get("symbol")
            if r_sym is None or str(r_sym).strip().upper() != clean_target_sym:
                continue
            r_ex = r.get("exchange")
            if r_ex is None:
                continue
            ex_val = r_ex.value if isinstance(r_ex, Exchange) else str(r_ex).strip().upper()
            if ex_val != exchange.value:
                continue
            r_iv = r.get("interval")
            if r_iv is None:
                continue
            iv_val = r_iv.value if isinstance(r_iv, CandleInterval) else str(r_iv).strip()
            if iv_val != interval.value:
                continue
            rec_ts_fl = _parse_synthetic_record_timestamp(r)
            if rec_ts_fl is not None and rec_ts_fl.tzinfo is not None:
                rec_close_fl = _calculate_synthetic_close_time(rec_ts_fl, interval, exchange=exchange)
                if now is not None and rec_close_fl > now:
                    continue
            matched.append(r)

        if now is not None:
            retrieval_time = _require_valid_tz_dt(now, "now")
        elif matched:
            parsed_tss = [
                ts
                for r in matched
                if (ts := _parse_synthetic_record_timestamp(r)) is not None and ts.tzinfo is not None
            ]
            if parsed_tss:
                max_ts = max(parsed_tss)
                close_time = _calculate_synthetic_close_time(max_ts, interval, exchange=exchange)
                retrieval_time = close_time + timedelta(seconds=1)
            else:
                raise ValueError(
                    "fetch_latest requires an explicit 'now' timestamp when no records have valid timestamps"
                )
        else:
            raise ValueError(
                "fetch_latest requires an explicit 'now' timestamp when no records are available"
            )

        if self._simulate_timeout:
            return ProviderResponse(
                success=False,
                source=self._source_name,
                retrieval_timestamp=retrieval_time,
                error_message="Synthetic provider timed out",
                error_code="TIMEOUT",
            )

        if self._simulate_error:
            return ProviderResponse(
                success=False,
                source=self._source_name,
                retrieval_timestamp=retrieval_time,
                error_message=self._simulate_error,
                error_code="PROVIDER_ERROR",
            )

        return ProviderResponse(
            success=True,
            source=self._source_name,
            retrieval_timestamp=retrieval_time,
            records=tuple(matched),
        )

    @classmethod
    def create_sample_series(
        cls,
        symbol: str = "RELIANCE",
        exchange: Exchange = Exchange.NSE,
        interval: CandleInterval = CandleInterval.M5,
        start_time: datetime | None = None,
        count: int = 5,
        base_price: Decimal = Decimal("2500.00"),
    ) -> SyntheticMarketDataProvider:
        """Factory helper creating a provider preloaded with valid synthetic NSE bars."""
        if start_time is None:
            try:
                session = ExchangeSession.for_exchange(exchange)
                t0 = datetime(2026, 11, 2, session.session_open.hour, session.session_open.minute, tzinfo=session.timezone)
            except (ValueError, TypeError):
                t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
        else:
            t0 = start_time
        records: list[Mapping[str, Any]] = []

        for i in range(count):
            open_t = t0 + (interval.duration * i)
            step_price = base_price + Decimal(i * 2)
            records.append(
                {
                    "symbol": symbol,
                    "exchange": exchange.value,
                    "interval": interval.value,
                    "timestamp": open_t.isoformat(),
                    "open": str(step_price),
                    "high": str(step_price + Decimal("10.00")),
                    "low": str(step_price - Decimal("5.00")),
                    "close": str(step_price + Decimal("5.00")),
                    "volume": 10000 + (i * 500),
                }
            )

        return cls(records=records)
