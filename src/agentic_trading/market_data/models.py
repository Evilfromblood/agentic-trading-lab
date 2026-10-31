"""Canonical market data models for Indian equities (NSE/BSE).

Provides immutable OHLCV candle representations, exchange identifiers,
and standard trading intervals. Financial prices use Decimal to guarantee
precision and avoid floating-point representation artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Standard Indian Standard Time timezone (+05:30)
try:
    IST = ZoneInfo("Asia/Kolkata")
except (ZoneInfoNotFoundError, OSError):  # pragma: no cover
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class Exchange(str, Enum):
    """Supported Indian exchanges."""

    NSE = "NSE"
    BSE = "BSE"


class CandleInterval(str, Enum):
    """Canonical candle intervals for equity market data."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M10 = "10m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"
    MN1 = "1M"

    @property
    def duration(self) -> timedelta:
        """Return the nominal timedelta represented by this interval."""
        durations: dict[str, timedelta] = {
            "1m": timedelta(minutes=1),
            "3m": timedelta(minutes=3),
            "5m": timedelta(minutes=5),
            "10m": timedelta(minutes=10),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
            "1w": timedelta(days=7),
            "1M": timedelta(days=30),
        }
        return durations[self.value]


def _validate_finite_decimal(value: Any, field_name: str) -> Decimal:
    """Validate and convert an input into a finite Decimal.

    Rejects floats to eliminate floating point precision degradation.
    """
    if isinstance(value, bool):
        raise TypeError(f"{field_name} cannot be a boolean")
    if isinstance(value, float):
        raise TypeError(
            f"{field_name} cannot be float; use Decimal, str, or int to preserve precision"
        )
    try:
        dec = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {value!r}") from exc

    if not dec.is_finite():
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return dec


def _validate_volume(vol: Any) -> int:
    """Validate and normalize equity share volume as an integer."""
    if isinstance(vol, bool):
        raise TypeError("volume cannot be a boolean")
    if isinstance(vol, float):
        raise TypeError("volume cannot be float")
    if isinstance(vol, Decimal):
        if not vol.is_finite():
            raise ValueError("volume must be finite")
        if vol % 1 != 0:
            raise ValueError(f"volume must be an integer, got {vol}")
        return int(vol)
    if not isinstance(vol, int):
        try:
            return int(vol)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"volume must be an integer, got {vol!r}") from exc
    return vol


def _validate_timezone_aware(dt: Any, field_name: str) -> datetime:
    """Ensure timestamp is an instance of datetime and has explicit tzinfo."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return dt


@dataclass(frozen=True)
class Candle:
    """Canonical, immutable OHLCV candle for Indian equities.

    Guarantees:
    - Immutability (frozen dataclass).
    - Decimal prices for exact precision.
    - Timezone-aware datetimes for determinism.
    - Strict rejection of non-finite numbers (NaN, Inf).
    """

    symbol: str
    exchange: Exchange
    interval: CandleInterval
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timestamp: datetime
    source: str
    retrieval_timestamp: datetime
    validate_timezone: bool = True

    def __post_init__(self) -> None:
        # Validate symbol
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = self.symbol.strip().upper()
        if any(c.isspace() for c in clean_symbol):
            raise ValueError(f"symbol must not contain whitespace: {self.symbol!r}")
        object.__setattr__(self, "symbol", clean_symbol)

        # Validate exchange
        if isinstance(self.exchange, str):
            try:
                object.__setattr__(self, "exchange", Exchange(self.exchange.upper()))
            except ValueError as exc:
                raise ValueError(f"Invalid exchange: {self.exchange!r}") from exc
        elif not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be Exchange or str, got {type(self.exchange).__name__}")

        # Validate interval
        if isinstance(self.interval, str):
            try:
                object.__setattr__(self, "interval", CandleInterval(self.interval))
            except ValueError as exc:
                raise ValueError(f"Invalid interval: {self.interval!r}") from exc
        elif not isinstance(self.interval, CandleInterval):
            raise TypeError(
                f"interval must be CandleInterval or str, got {type(self.interval).__name__}"
            )

        # Validate prices (Decimal and finite)
        object.__setattr__(self, "open", _validate_finite_decimal(self.open, "open"))
        object.__setattr__(self, "high", _validate_finite_decimal(self.high, "high"))
        object.__setattr__(self, "low", _validate_finite_decimal(self.low, "low"))
        object.__setattr__(self, "close", _validate_finite_decimal(self.close, "close"))

        # Validate volume
        object.__setattr__(self, "volume", _validate_volume(self.volume))

        # Validate timestamps
        if self.validate_timezone:
            object.__setattr__(
                self, "timestamp", _validate_timezone_aware(self.timestamp, "timestamp")
            )
            object.__setattr__(
                self,
                "retrieval_timestamp",
                _validate_timezone_aware(self.retrieval_timestamp, "retrieval_timestamp"),
            )

        # Validate source
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        object.__setattr__(self, "source", self.source.strip().upper())

    @property
    def candle_timestamp(self) -> datetime:
        """Alias for timestamp."""
        return self.timestamp

    @property
    def data_source(self) -> str:
        """Alias for source."""
        return self.source

    @property
    def is_bullish(self) -> bool:
        """Return True if close is greater than or equal to open."""
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        """Return True if close is strictly less than open."""
        return self.close < self.open

    @property
    def spread(self) -> Decimal:
        """Return candle range (high - low)."""
        return self.high - self.low

    @classmethod
    def create(
        cls,
        symbol: str,
        exchange: Exchange | str,
        interval: CandleInterval | str,
        open: Decimal | str | int,
        high: Decimal | str | int,
        low: Decimal | str | int,
        close: Decimal | str | int,
        volume: int,
        timestamp: datetime | None = None,
        source: str = "SIMULATED",
        retrieval_timestamp: datetime | None = None,
        candle_timestamp: datetime | None = None,
        data_source: str | None = None,
        validate_timezone: bool = True,
    ) -> Candle:
        """Convenience factory method accepting both canonical and alias parameter names."""
        ts = candle_timestamp if candle_timestamp is not None else timestamp
        if ts is None:
            raise ValueError("Candle timestamp must be provided")

        src = data_source if data_source is not None else source
        ret_ts = retrieval_timestamp if retrieval_timestamp is not None else ts

        return cls(
            symbol=symbol,
            exchange=Exchange(exchange.upper()) if isinstance(exchange, str) else exchange,
            interval=CandleInterval(interval) if isinstance(interval, str) else interval,
            open=open if isinstance(open, Decimal) else Decimal(str(open)),
            high=high if isinstance(high, Decimal) else Decimal(str(high)),
            low=low if isinstance(low, Decimal) else Decimal(str(low)),
            close=close if isinstance(close, Decimal) else Decimal(str(close)),
            volume=volume,
            timestamp=ts,
            source=src,
            retrieval_timestamp=ret_ts,
            validate_timezone=validate_timezone,
        )
