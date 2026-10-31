"""Deterministic market data quality validation for Indian equities.

Implements strict validation rules for single candles and ordered candle sequences.
Fails closed and reports actionable error codes without silently repairing corrupted data.

Timing and provenance semantics:
- Completed candle invariant: `open_time < close_time <= retrieval_timestamp <= now`.
- In-progress candles (`open_time <= now < close_time`) are rejected.
- Retrieval prior to bar close (`retrieval_timestamp < close_time`) is rejected.
- Retrieval in the future (`retrieval_timestamp > now`) is rejected.
- Market session awareness: Uses NSE/BSE regular trading session boundaries
  (09:15 to 15:30 IST) to evaluate intraday session gaps. Requires the previous bar
  to close exactly at 15:30 IST and next bar to open at 09:15 IST for legitimate
  overnight and weekend market closures.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

from agentic_trading.market_data.models import IST, CandleInterval, Exchange

# Standard NSE/BSE Equity continuous trading session boundaries in IST
NSE_SESSION_OPEN = time(9, 15)
NSE_SESSION_CLOSE = time(15, 30)


class DataQualityErrorCode(str, Enum):
    """Actionable machine-readable error codes for market data validation."""

    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    HIGH_LESS_THAN_MAX_OPEN_CLOSE = "HIGH_LESS_THAN_MAX_OPEN_CLOSE"
    LOW_GREATER_THAN_MIN_OPEN_CLOSE = "LOW_GREATER_THAN_MIN_OPEN_CLOSE"
    HIGH_LESS_THAN_LOW = "HIGH_LESS_THAN_LOW"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    NON_FINITE_NUMERIC = "NON_FINITE_NUMERIC"
    STALE_DATA = "STALE_DATA"
    FUTURE_CANDLE = "FUTURE_CANDLE"
    IN_PROGRESS_CANDLE = "IN_PROGRESS_CANDLE"
    RETRIEVAL_BEFORE_CLOSE = "RETRIEVAL_BEFORE_CLOSE"
    RETRIEVAL_AFTER_NOW = "RETRIEVAL_AFTER_NOW"
    DUPLICATE_CANDLE = "DUPLICATE_CANDLE"
    CONFLICTING_DUPLICATE_DATA = "CONFLICTING_DUPLICATE_DATA"
    NON_MONOTONIC_SEQUENCE = "NON_MONOTONIC_SEQUENCE"
    MISSING_INTERVAL = "MISSING_INTERVAL"
    MARKET_CALENDAR_REQUIRED = "MARKET_CALENDAR_REQUIRED"
    INCONSISTENT_SYMBOL = "INCONSISTENT_SYMBOL"
    INCONSISTENT_EXCHANGE = "INCONSISTENT_EXCHANGE"
    INCONSISTENT_INTERVAL = "INCONSISTENT_INTERVAL"
    EMPTY_SEQUENCE = "EMPTY_SEQUENCE"
    MALFORMED_CANDLE = "MALFORMED_CANDLE"


_ALLOWED_PRIMITIVE_TYPES = (
    str, int, float, bool, Decimal, datetime, time, timedelta, Enum, bytes, type(None)
)


def _deep_freeze(obj: Any) -> Any:
    """Recursively freeze mutable mappings, lists, and sets into immutable types.

    Rejects unsupported mutable types to guarantee deep immutability.
    """
    if isinstance(obj, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(_deep_freeze(v) for v in obj)
    if isinstance(obj, _ALLOWED_PRIMITIVE_TYPES):
        return obj
    raise TypeError(
        f"Unsupported mutable or unhandled type in QualityIssue.details: {type(obj).__name__}"
    )




def _validate_now_and_staleness(now: Any, max_staleness: Any) -> None:
    """Validate injected 'now' and 'max_staleness' parameters."""
    if now is not None:
        if isinstance(now, bool) or not isinstance(now, datetime):
            raise TypeError(f"'now' must be a datetime instance, got {type(now).__name__}")
        if now.tzinfo is None:
            raise ValueError(
                "Injected 'now' parameter must be timezone-aware (tzinfo with valid utcoffset required)"
            )
        try:
            offset = now.tzinfo.utcoffset(now)
        except Exception as exc:
            raise ValueError(
                f"Injected 'now' parameter timezone calculation failed: {exc}"
            ) from exc
        if offset is None:
            raise ValueError(
                "Injected 'now' parameter must be timezone-aware (tzinfo with valid utcoffset required)"
            )
    if max_staleness is not None:
        if isinstance(max_staleness, bool) or not isinstance(max_staleness, timedelta):
            raise TypeError(
                f"'max_staleness' must be a timedelta instance, got {type(max_staleness).__name__}"
            )
        if max_staleness < timedelta(0):
            raise ValueError(
                f"'max_staleness' must be a non-negative timedelta, got {max_staleness}"
            )



def _is_tz_valid(dt: Any) -> bool:
    """Return True if a datetime has working tzinfo whose utcoffset() returns a non-None offset.

    Catches any exception from malformed tzinfo implementations without propagating it.
    """
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        return False
    try:
        return dt.tzinfo.utcoffset(dt) is not None
    except Exception:  # noqa: BLE001
        return False


def _validate_expected_interval(expected_interval: Any) -> timedelta | None:
    """Validate expected_interval parameter for type and strictly positive duration."""
    if expected_interval is None:
        return None
    if isinstance(expected_interval, CandleInterval):
        return expected_interval.duration
    if isinstance(expected_interval, timedelta):
        if expected_interval <= timedelta(0):
            raise ValueError(
                f"expected_interval duration must be strictly positive, got {expected_interval}"
            )
        return expected_interval
    raise TypeError(
        f"expected_interval must be CandleInterval, timedelta, or None, got {type(expected_interval).__name__}"
    )


@dataclass(frozen=True)
class QualityIssue:
    """Detailed deeply-immutable record of a single data quality failure."""

    code: DataQualityErrorCode
    message: str
    symbol: str = ""
    timestamp: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, DataQualityErrorCode):
            if isinstance(self.code, str):
                try:
                    object.__setattr__(self, "code", DataQualityErrorCode(self.code))
                except ValueError as exc:
                    raise TypeError(f"Invalid code string: {self.code!r}") from exc
            else:
                raise TypeError(
                    f"code must be DataQualityErrorCode or str, got {type(self.code).__name__}"
                )
        if not isinstance(self.message, str):
            raise TypeError(f"message must be a str, got {type(self.message).__name__}")
        if not isinstance(self.symbol, str):
            raise TypeError(f"symbol must be a str, got {type(self.symbol).__name__}")
        if self.timestamp is not None and not isinstance(self.timestamp, datetime):
            raise TypeError(
                f"timestamp must be a datetime or None, got {type(self.timestamp).__name__}"
            )
        if not isinstance(self.details, Mapping):
            raise TypeError(f"details must be a Mapping, got {type(self.details).__name__}")

        # Deeply freeze nested mappings, lists, and sets to guarantee immutability
        object.__setattr__(self, "details", _deep_freeze(self.details))

    def to_dict(self) -> dict[str, Any]:
        """Convert issue to a plain dictionary for serialization without global side effects."""
        def _to_plain(val: Any) -> Any:
            if isinstance(val, Mapping):
                return {k: _to_plain(v) for k, v in val.items()}
            if isinstance(val, (list, tuple)):
                return [_to_plain(v) for v in val]
            if isinstance(val, (set, frozenset)):
                return [_to_plain(v) for v in val]
            return val

        return {
            "code": self.code.value,
            "message": self.message,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if self.timestamp is not None else None,
            "details": _to_plain(self.details),
        }

    def __reduce__(self) -> tuple[Any, ...]:
        """Support pickle serialization while preserving deep immutability on unpickle."""
        def _unfreeze(obj: Any) -> Any:
            if isinstance(obj, Mapping):
                return {k: _unfreeze(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return tuple(_unfreeze(v) for v in obj)
            if isinstance(obj, (set, frozenset)):
                return set(obj)
            return obj

        return (
            QualityIssue,
            (
                self.code,
                self.message,
                self.symbol,
                self.timestamp,
                _unfreeze(self.details),
            ),
        )


@dataclass(frozen=True)
class ValidationResult:
    """Aggregated outcome of market data quality evaluation."""

    is_valid: bool
    issues: tuple[QualityIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # 1. Validate the boolean type of is_valid
        if not isinstance(self.is_valid, bool):
            raise TypeError(
                f"ValidationResult.is_valid must be a bool, got {type(self.is_valid).__name__}"
            )

        # 2. Convert issues to an immutable tuple in __post_init__
        if not isinstance(self.issues, tuple):
            try:
                issues_tuple = tuple(self.issues)
            except TypeError as exc:
                raise TypeError(
                    f"ValidationResult.issues must be an iterable of QualityIssue, got {type(self.issues).__name__}"
                ) from exc
            object.__setattr__(self, "issues", issues_tuple)

        # 3. Validate issue element types
        for idx, item in enumerate(self.issues):
            if not isinstance(item, QualityIssue):
                raise TypeError(
                    f"All elements in ValidationResult.issues must be QualityIssue instances, "
                    f"got {type(item).__name__} at index {idx}"
                )

        # 4. Guarantee that is_valid cannot contradict reported issues
        expected_valid = len(self.issues) == 0
        if self.is_valid != expected_valid:
            raise ValueError(
                f"Contradictory ValidationResult: is_valid is {self.is_valid} "
                f"but found {len(self.issues)} reported issue(s)."
            )

    @property
    def error_codes(self) -> tuple[str, ...]:
        """Return a tuple of string error code representations."""
        return tuple(issue.code.value for issue in self.issues)

    def has_error(self, code: DataQualityErrorCode | str) -> bool:
        """Return True if the specified error code is present in issues."""
        code_str = code.value if isinstance(code, DataQualityErrorCode) else str(code)
        return code_str in self.error_codes

    def get_issues_by_code(self, code: DataQualityErrorCode | str) -> tuple[QualityIssue, ...]:
        """Return all quality issues matching a given error code."""
        code_str = code.value if isinstance(code, DataQualityErrorCode) else str(code)
        return tuple(issue for issue in self.issues if issue.code.value == code_str)

    def to_dict(self) -> dict[str, Any]:
        """Convert validation result to a plain dictionary for serialization without global side effects."""
        return {
            "is_valid": self.is_valid,
            "error_codes": list(self.error_codes),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def __reduce__(self) -> tuple[Any, ...]:
        """Support pickle serialization without global side effects."""
        return (ValidationResult, (self.is_valid, self.issues))


def check_candle_structure(candle: Any) -> list[QualityIssue]:
    """Validate presence and structural integrity of required candle fields.

    Validates every required field and its type before accessing any candle attribute.
    Missing or incorrectly typed high, low, close, volume, interval, source, or
    retrieval_timestamp produce MALFORMED_CANDLE.
    """
    if candle is None:
        return [
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message="Candle object is None",
            )
        ]

    required_fields = [
        "symbol",
        "exchange",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "timestamp",
        "retrieval_timestamp",
        "source",
    ]
    issues: list[QualityIssue] = []
    symbol = getattr(candle, "symbol", "")
    if not isinstance(symbol, str):
        symbol = ""

    for field_name in required_fields:
        if not hasattr(candle, field_name) or getattr(candle, field_name, None) is None:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message=f"Candle is missing required field: {field_name}",
                    symbol=symbol,
                    details={"missing_field": field_name, "field": field_name},
                )
            )
        else:
            val = getattr(candle, field_name)
            if field_name == "symbol":
                if not isinstance(val, str) or not val.strip():
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"symbol must be a non-empty string, got {val!r}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
            elif field_name == "exchange":
                if isinstance(val, bool) or not isinstance(val, (Exchange, str)):
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"exchange must be Exchange or str, got {type(val).__name__}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
                elif isinstance(val, str):
                    try:
                        Exchange(val.strip().upper())
                    except ValueError:
                        issues.append(
                            QualityIssue(
                                code=DataQualityErrorCode.MALFORMED_CANDLE,
                                message=f"Invalid exchange value: {val!r}",
                                symbol=symbol,
                                details={"field": field_name},
                            )
                        )
            elif field_name == "interval":
                if isinstance(val, bool) or not isinstance(val, (CandleInterval, str)):
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"interval must be CandleInterval or str, got {type(val).__name__}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
                elif isinstance(val, str):
                    try:
                        CandleInterval(val)
                    except ValueError:
                        issues.append(
                            QualityIssue(
                                code=DataQualityErrorCode.MALFORMED_CANDLE,
                                message=f"Invalid interval value: {val!r}",
                                symbol=symbol,
                                details={"field": field_name},
                            )
                        )
            elif field_name in ("open", "high", "low", "close"):
                if isinstance(val, bool) or not isinstance(val, Decimal):
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"{field_name} must be a Decimal instance, got {type(val).__name__}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
            elif field_name == "volume":
                if isinstance(val, bool) or not isinstance(val, int):
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"volume must be an integer, got {type(val).__name__}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
            elif field_name in ("timestamp", "retrieval_timestamp"):
                if not isinstance(val, datetime):
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MALFORMED_CANDLE,
                            message=f"{field_name} must be a datetime instance, got {type(val).__name__}",
                            symbol=symbol,
                            details={"field": field_name},
                        )
                    )
            elif field_name == "source" and (not isinstance(val, str) or not val.strip()):
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.MALFORMED_CANDLE,
                        message="source must be a non-empty string representing provenance",
                        symbol=symbol,
                        details={"field": field_name},
                    )
                )

    return issues


def check_price_positivity(
    open_p: Decimal,
    high_p: Decimal,
    low_p: Decimal,
    close_p: Decimal,
    symbol: str = "",
    timestamp: datetime | None = None,
) -> list[QualityIssue]:
    """Check that all OHLC prices are strictly positive (> 0)."""
    issues: list[QualityIssue] = []
    prices = {"open": open_p, "high": high_p, "low": low_p, "close": close_p}
    for field_name, price in prices.items():
        if price <= Decimal(0):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.NON_POSITIVE_PRICE,
                    message=f"{field_name.capitalize()} price must be positive (> 0), got {price}",
                    symbol=symbol,
                    timestamp=timestamp,
                    details={"field": field_name, "value": str(price)},
                )
            )
    return issues


def check_ohlc_relationships(
    open_p: Decimal,
    high_p: Decimal,
    low_p: Decimal,
    close_p: Decimal,
    symbol: str = "",
    timestamp: datetime | None = None,
) -> list[QualityIssue]:
    """Validate internal geometric consistency of an OHLC bar.

    Rules:
    - High >= Low
    - High >= max(Open, Close)
    - Low <= min(Open, Close)
    """
    issues: list[QualityIssue] = []

    # High >= Low
    if high_p < low_p:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.HIGH_LESS_THAN_LOW,
                message=f"High price ({high_p}) cannot be less than low price ({low_p})",
                symbol=symbol,
                timestamp=timestamp,
                details={"high": str(high_p), "low": str(low_p)},
            )
        )

    # High >= max(Open, Close)
    max_oc = max(open_p, close_p)
    if high_p < max_oc:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE,
                message=(
                    f"High price ({high_p}) must be >= max(open, close) "
                    f"(open={open_p}, close={close_p}, max={max_oc})"
                ),
                symbol=symbol,
                timestamp=timestamp,
                details={
                    "high": str(high_p),
                    "open": str(open_p),
                    "close": str(close_p),
                    "max_open_close": str(max_oc),
                },
            )
        )

    # Low <= min(Open, Close)
    min_oc = min(open_p, close_p)
    if low_p > min_oc:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE,
                message=(
                    f"Low price ({low_p}) must be <= min(open, close) "
                    f"(open={open_p}, close={close_p}, min={min_oc})"
                ),
                symbol=symbol,
                timestamp=timestamp,
                details={
                    "low": str(low_p),
                    "open": str(open_p),
                    "close": str(close_p),
                    "min_open_close": str(min_oc),
                },
            )
        )

    return issues


def check_volume(
    volume: int,
    symbol: str = "",
    timestamp: datetime | None = None,
) -> list[QualityIssue]:
    """Check that volume is non-negative (>= 0)."""
    issues: list[QualityIssue] = []
    if volume < 0:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NEGATIVE_VOLUME,
                message=f"Volume cannot be negative, got {volume}",
                symbol=symbol,
                timestamp=timestamp,
                details={"volume": volume},
            )
        )
    return issues


def check_timezone_awareness(
    dt: Any,
    field_name: str = "timestamp",
    symbol: str = "",
) -> list[QualityIssue]:
    """Check that a datetime object has an explicit, active timezone offset."""
    issues: list[QualityIssue] = []
    if not isinstance(dt, datetime):
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message=f"{field_name} must be a datetime instance, got {type(dt).__name__}",
                symbol=symbol,
                details={"field": field_name},
            )
        )
        return issues

    if dt.tzinfo is None:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message=f"{field_name} must be timezone-aware (tzinfo is None)",
                symbol=symbol,
                timestamp=dt,
                details={"field": field_name},
            )
        )
        return issues

    try:
        offset = dt.tzinfo.utcoffset(dt)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message=f"{field_name} timezone utcoffset raised {type(exc).__name__}: {exc}",
                symbol=symbol,
                timestamp=dt,
                details={"field": field_name, "error": str(exc)},
            )
        )
        return issues

    if offset is None:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message=f"{field_name} timezone utcoffset returned None",
                symbol=symbol,
                timestamp=dt,
                details={"field": field_name},
            )
        )

    return issues


def check_timing_and_provenance(
    candle: Any,
    now: datetime | None = None,
    max_staleness: timedelta | None = None,
) -> list[QualityIssue]:
    """Validate candle timing boundaries, completeness, and retrieval provenance.

    Fail-closed invariants:
    1. Timing fields (`open_time`, `close_time`, `retrieval_timestamp`) must be present,
       valid datetimes, and timezone-aware. Missing or invalid types emit MALFORMED_CANDLE.
    2. Retrieval provenance: `retrieval_timestamp >= candle.close_time`
       (cannot observe a completed candle before it finishes closing).
    3. Future check: `candle.open_time <= now`.
    4. Completeness check: `candle.close_time <= now`. A candle cannot be considered
       complete while in-progress (`open_time <= now < close_time`).
    5. Retrieval freshness: `retrieval_timestamp <= now` (cannot be observed in future).
    6. Staleness check: `(now - candle.close_time) <= max_staleness`.
    """
    _validate_now_and_staleness(now, max_staleness)

    issues: list[QualityIssue] = []
    symbol = getattr(candle, "symbol", "")
    if not isinstance(symbol, str):
        symbol = ""

    retrieval_ts = getattr(candle, "retrieval_timestamp", None)
    close_time = getattr(candle, "close_time", None)
    open_time = getattr(candle, "open_time", getattr(candle, "timestamp", None))

    # Fail closed on missing timing attributes
    if open_time is None:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message="Candle is missing open_time / timestamp",
                symbol=symbol,
                details={"field": "open_time"},
            )
        )
    if close_time is None:
        interval = getattr(candle, "interval", None)
        if isinstance(open_time, datetime) and isinstance(interval, CandleInterval):
            close_time = open_time + interval.duration
        else:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message="Candle is missing close_time",
                    symbol=symbol,
                    details={"field": "close_time"},
                )
            )
    if retrieval_ts is None:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message="Candle is missing retrieval_timestamp",
                symbol=symbol,
                details={"field": "retrieval_timestamp"},
            )
        )

    if open_time is None or close_time is None or retrieval_ts is None:
        return issues

    # Validate timing field types and timezone awareness
    for name, ts in [("open_time", open_time), ("close_time", close_time), ("retrieval_timestamp", retrieval_ts)]:
        if not isinstance(ts, datetime):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message=f"{name} must be a datetime instance, got {type(ts).__name__}",
                    symbol=symbol,
                    details={"field": name},
                )
            )
        else:
            tz_issues = check_timezone_awareness(ts, name, symbol)
            issues.extend(tz_issues)

    if issues:
        return issues

    # Timing causality with robust exception safety against unstable or flaking tzinfo
    try:
        is_open_ge_close = open_time >= close_time
    except Exception as exc:  # noqa: BLE001
        return [
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message=f"Error comparing open_time and close_time: {exc}",
                symbol=symbol,
                details={"error": str(exc)},
            )
        ]

    if is_open_ge_close:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message=(
                    f"open_time ({open_time.isoformat()}) must be strictly prior to "
                    f"close_time ({close_time.isoformat()})"
                ),
                symbol=symbol,
                details={"open_time": open_time.isoformat(), "close_time": close_time.isoformat()},
            )
        )

    try:
        is_retrieval_before_close = retrieval_ts < close_time
    except Exception as exc:  # noqa: BLE001
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.MALFORMED_CANDLE,
                message=f"Error comparing retrieval_timestamp and close_time: {exc}",
                symbol=symbol,
                details={"error": str(exc)},
            )
        )
        return issues

    if is_retrieval_before_close:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.RETRIEVAL_BEFORE_CLOSE,
                message=(
                    f"Retrieval timestamp ({retrieval_ts.isoformat()}) "
                    f"is earlier than candle close time ({close_time.isoformat()})"
                ),
                symbol=symbol,
                timestamp=getattr(candle, "timestamp", None),
                details={
                    "retrieval_timestamp": retrieval_ts.isoformat(),
                    "close_time": close_time.isoformat(),
                },
            )
        )

    if now is not None:
        try:
            is_retrieval_after_now = retrieval_ts > now
            is_open_future = open_time > now
            is_in_progress = now < close_time
        except Exception as exc:  # noqa: BLE001
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message=f"Error comparing timestamps against reference now: {exc}",
                    symbol=symbol,
                    details={"error": str(exc)},
                )
            )
            return issues

        if is_retrieval_after_now:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.RETRIEVAL_AFTER_NOW,
                    message=(
                        f"Retrieval timestamp ({retrieval_ts.isoformat()}) "
                        f"is in the future relative to current time ({now.isoformat()})"
                    ),
                    symbol=symbol,
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "retrieval_timestamp": retrieval_ts.isoformat(),
                        "now": now.isoformat(),
                    },
                )
            )

        if is_open_future:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.FUTURE_CANDLE,
                    message=(
                        f"Candle open time ({open_time.isoformat()}) "
                        f"is in the future relative to current time ({now.isoformat()})"
                    ),
                    symbol=symbol,
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "open_time": open_time.isoformat(),
                        "now": now.isoformat(),
                    },
                )
            )
            return issues

        if is_in_progress:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.IN_PROGRESS_CANDLE,
                    message=(
                        f"Candle is currently in-progress: close time ({close_time.isoformat()}) "
                        f"is after reference current time ({now.isoformat()})"
                    ),
                    symbol=symbol,
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "open_time": open_time.isoformat(),
                        "close_time": close_time.isoformat(),
                        "now": now.isoformat(),
                    },
                )
            )
            return issues

        if max_staleness is not None:
            try:
                age = now - close_time
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.MALFORMED_CANDLE,
                        message=f"Error calculating data staleness from bar close: {exc}",
                        symbol=symbol,
                        details={"error": str(exc)},
                    )
                )
                return issues

            if age > max_staleness:
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.STALE_DATA,
                        message=(
                            f"Market data is stale: age from bar close ({age}) "
                            f"exceeds maximum allowed staleness of {max_staleness}"
                        ),
                        symbol=symbol,
                        timestamp=getattr(candle, "timestamp", None),
                        details={
                            "close_time": close_time.isoformat(),
                            "now": now.isoformat(),
                            "age_seconds": age.total_seconds(),
                            "max_staleness_seconds": max_staleness.total_seconds(),
                        },
                    )
                )

    return issues


def check_staleness(
    candle_time: datetime,
    now: datetime,
    max_staleness: timedelta,
    symbol: str = "",
) -> list[QualityIssue]:
    """Compatibility helper: deterministic staleness check against injected 'now'."""
    _validate_now_and_staleness(now, max_staleness)

    if not isinstance(candle_time, datetime) or not _is_tz_valid(candle_time):
        return [
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message="Cannot evaluate staleness for naive or invalid candle timestamp",
                symbol=symbol,
            )
        ]

    issues: list[QualityIssue] = []
    if candle_time > now:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.FUTURE_CANDLE,
                message=(
                    f"Candle timestamp ({candle_time.isoformat()}) is in the "
                    f"future relative to reference now ({now.isoformat()})"
                ),
                symbol=symbol,
                timestamp=candle_time,
                details={
                    "candle_timestamp": candle_time.isoformat(),
                    "reference_now": now.isoformat(),
                },
            )
        )
        return issues

    age = now - candle_time
    if age > max_staleness:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.STALE_DATA,
                message=(
                    f"Market data is stale: age {age} exceeds maximum permitted "
                    f"staleness of {max_staleness}"
                ),
                symbol=symbol,
                timestamp=candle_time,
                details={
                    "age_seconds": age.total_seconds(),
                    "max_staleness_seconds": max_staleness.total_seconds(),
                },
            )
        )

    return issues


def check_duplicate_timestamps(candles: Iterable[Any]) -> list[QualityIssue]:
    """Check for duplicate timestamps, distinguishing identical from conflicting candles.

    Includes exchange, symbol, interval, and UTC-normalized timestamp in candle identity.
    Only compares OHLCV values when identity matches.
    Emits MALFORMED_CANDLE for structural defects, preserving original sequence indices.
    """
    candles_seq: Sequence[Any] = candles if isinstance(candles, Sequence) else tuple(candles)
    issues: list[QualityIssue] = []
    seen: dict[tuple[Any, Any, Any, datetime], tuple[int, Any]] = {}

    for i, c in enumerate(candles_seq):
        structural_errs = check_candle_structure(c)
        if structural_errs:
            for issue in structural_errs:
                details = dict(issue.details)
                details["index"] = i
                issues.append(
                    QualityIssue(
                        code=issue.code,
                        message=issue.message,
                        symbol=issue.symbol,
                        timestamp=issue.timestamp,
                        details=details,
                    )
                )
            continue

        if not _is_tz_valid(c.timestamp):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                    message=f"Candle at index {i} has naive or invalid timezone timestamp",
                    symbol=getattr(c, "symbol", ""),
                    timestamp=getattr(c, "timestamp", None),
                    details={"index": i, "field": "timestamp"},
                )
            )
            continue

        try:
            utc_time = c.timestamp.astimezone(UTC)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message=f"Timezone conversion failed for candle at index {i}: {exc}",
                    symbol=getattr(c, "symbol", ""),
                    timestamp=getattr(c, "timestamp", None),
                    details={"index": i, "error": str(exc)},
                )
            )
            continue

        key = (
            getattr(c, "exchange", None),
            getattr(c, "symbol", None),
            getattr(c, "interval", None),
            utc_time,
        )

        if key in seen:
            prev_idx, prev_candle = seen[key]
            is_identical = (
                getattr(c, "open", None) == getattr(prev_candle, "open", None)
                and getattr(c, "high", None) == getattr(prev_candle, "high", None)
                and getattr(c, "low", None) == getattr(prev_candle, "low", None)
                and getattr(c, "close", None) == getattr(prev_candle, "close", None)
                and getattr(c, "volume", None) == getattr(prev_candle, "volume", None)
            )
            if is_identical:
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.DUPLICATE_CANDLE,
                        message=f"Duplicate identical candle timestamp detected at index {i}: {c.timestamp.isoformat()}",
                        symbol=getattr(c, "symbol", ""),
                        timestamp=c.timestamp,
                        details={"index": i, "previous_index": prev_idx, "timestamp": c.timestamp.isoformat()},
                    )
                )
            else:
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA,
                        message=(
                            f"Conflicting candle data for identical timestamp at index {i}: "
                            f"{c.timestamp.isoformat()} has differing OHLCV values"
                        ),
                        symbol=getattr(c, "symbol", ""),
                        timestamp=c.timestamp,
                        details={
                            "index": i,
                            "previous_index": prev_idx,
                            "timestamp": c.timestamp.isoformat(),
                            "existing_ohlcv": {
                                "open": str(getattr(prev_candle, "open", None)),
                                "high": str(getattr(prev_candle, "high", None)),
                                "low": str(getattr(prev_candle, "low", None)),
                                "close": str(getattr(prev_candle, "close", None)),
                                "volume": getattr(prev_candle, "volume", None),
                            },
                            "conflicting_ohlcv": {
                                "open": str(getattr(c, "open", None)),
                                "high": str(getattr(c, "high", None)),
                                "low": str(getattr(c, "low", None)),
                                "close": str(getattr(c, "close", None)),
                                "volume": getattr(c, "volume", None),
                            },
                        },
                    )
                )
        else:
            seen[key] = (i, c)

    return issues


def check_sequence_monotonicity(candles: Iterable[Any]) -> list[QualityIssue]:
    """Check that candles are strictly non-decreasing in chronological order, preserving sequence indices.

    Emits MALFORMED_CANDLE for structural defects without bridging across invalid elements.
    """
    candles_seq: Sequence[Any] = candles if isinstance(candles, Sequence) else tuple(candles)
    issues: list[QualityIssue] = []
    prev_valid_idx: int | None = None
    prev_candle: Any = None

    for i, curr in enumerate(candles_seq):
        structural_errs = check_candle_structure(curr)
        if structural_errs:
            for issue in structural_errs:
                details = dict(issue.details)
                details["index"] = i
                issues.append(
                    QualityIssue(
                        code=issue.code,
                        message=issue.message,
                        symbol=issue.symbol,
                        timestamp=issue.timestamp,
                        details=details,
                    )
                )
            # Break sequence continuity: do NOT bridge across malformed element!
            prev_candle = None
            prev_valid_idx = None
            continue

        if not _is_tz_valid(curr.timestamp):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                    message=f"Candle at index {i} has naive or invalid timezone timestamp",
                    symbol=getattr(curr, "symbol", ""),
                    timestamp=getattr(curr, "timestamp", None),
                    details={"index": i, "field": "timestamp"},
                )
            )
            prev_candle = None
            prev_valid_idx = None
            continue

        if prev_candle is not None:
            try:
                is_out_of_order = curr.timestamp < prev_candle.timestamp
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.MALFORMED_CANDLE,
                        message=f"Timestamp comparison failed at index {i}: {exc}",
                        symbol=getattr(curr, "symbol", ""),
                        timestamp=curr.timestamp,
                        details={"index": i, "error": str(exc)},
                    )
                )
                prev_candle = None
                prev_valid_idx = None
                continue

            if is_out_of_order:
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.NON_MONOTONIC_SEQUENCE,
                        message=(
                            f"Candle sequence out-of-order at index {i}: "
                            f"{curr.timestamp.isoformat()} is prior to previous candle {prev_candle.timestamp.isoformat()} "
                            f"at index {prev_valid_idx}"
                        ),
                        symbol=getattr(curr, "symbol", ""),
                        timestamp=curr.timestamp,
                        details={
                            "index": i,
                            "previous_index": prev_valid_idx,
                            "timestamp": curr.timestamp.isoformat(),
                            "previous_timestamp": prev_candle.timestamp.isoformat(),
                        },
                    )
                )

        prev_valid_idx = i
        prev_candle = curr

    return issues


def check_missing_intervals(
    candles: Iterable[Any],
    expected_interval: CandleInterval | timedelta | None = None,
) -> list[QualityIssue]:
    """Check sequence for missing intervals within continuous market trading sessions.

    Uses NSE/BSE regular trading session boundaries (09:15 to 15:30 IST):
    - Intraday bars: Requires consecutive calendar weekday transition (day_diff == 1)
      where previous bar closes EXACTLY at 15:30 IST and next bar opens EXACTLY at 09:15 IST.
    - All multi-day transitions (day_diff > 1, including ordinary Friday-to-Monday weekend
      and holiday gaps) return MARKET_CALENDAR_REQUIRED because exchange calendar evidence
      is required to establish whether weekend or holiday trading occurred.
    - Daily bars: Single-day consecutive weekday transitions (Mon->Tue, etc.) are accepted;
      multi-day transitions (day_delta > 1, including Friday-to-Monday) return MARKET_CALENDAR_REQUIRED.
    - Malformed elements emit MALFORMED_CANDLE and do not bridge intervals across corrupt data.
    """
    step: timedelta | None = _validate_expected_interval(expected_interval)
    candles_seq: Sequence[Any] = candles if isinstance(candles, Sequence) else tuple(candles)
    if len(candles_seq) < 2:
        return []

    issues: list[QualityIssue] = []
    if step is None:
        first_candle_with_interval = next(
            (
                c
                for c in candles_seq
                if c is not None and hasattr(c, "interval") and isinstance(c.interval, CandleInterval)
            ),
            None,
        )
        if first_candle_with_interval is not None:
            step = first_candle_with_interval.interval.duration

    if step is None:
        return []

    is_daily = step >= timedelta(days=1)
    prev_idx: int | None = None
    prev: Any = None

    for i, curr in enumerate(candles_seq):
        structural_errs = check_candle_structure(curr)
        if structural_errs:
            for issue in structural_errs:
                details = dict(issue.details)
                details["index"] = i
                issues.append(
                    QualityIssue(
                        code=issue.code,
                        message=issue.message,
                        symbol=issue.symbol,
                        timestamp=issue.timestamp,
                        details=details,
                    )
                )
            # Break sequence continuity: do NOT bridge across malformed element!
            prev = None
            prev_idx = None
            continue

        if not _is_tz_valid(curr.timestamp):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                    message=f"Candle at index {i} has naive or invalid timezone timestamp",
                    symbol=getattr(curr, "symbol", ""),
                    timestamp=getattr(curr, "timestamp", None),
                    details={"index": i, "field": "timestamp"},
                )
            )
            prev = None
            prev_idx = None
            continue

        if prev is not None:
            try:
                t_prev = prev.timestamp.astimezone(IST)
                t_curr = curr.timestamp.astimezone(IST)
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.MALFORMED_CANDLE,
                        message=f"Timezone conversion failed between index {prev_idx} and {i}: {exc}",
                        symbol=getattr(curr, "symbol", ""),
                        timestamp=curr.timestamp,
                        details={"index": i, "error": str(exc)},
                    )
                )
                prev_idx = i
                prev = curr
                continue

            if is_daily:
                day_delta = (t_curr.date() - t_prev.date()).days
                prev_wd = t_prev.weekday()
                curr_wd = t_curr.weekday()

                # Accepted without calendar: strictly single-day consecutive weekday step (delta == 1, Mon-Thu -> next)
                # Any multi-day jump (including Friday-to-Monday delta == 3 and holiday gaps) requires exchange calendar (M2b)
                is_valid_weekday_step = (day_delta == 1 and prev_wd < 4 and curr_wd == prev_wd + 1)

                if not is_valid_weekday_step:
                    is_ordinary_weekend = (day_delta == 3 and prev_wd == 4 and curr_wd == 0)
                    issues.append(
                        QualityIssue(
                            code=DataQualityErrorCode.MARKET_CALENDAR_REQUIRED,
                            message=(
                                f"Ambiguous daily transition detected between {t_prev.date()} (weekday {prev_wd}) and "
                                f"{t_curr.date()} (weekday {curr_wd}): {day_delta} calendar day(s) elapsed "
                                f"({'ordinary weekend' if is_ordinary_weekend else 'potential holiday/special session'}); "
                                "full exchange holiday calendar required (M2b)"
                            ),
                            symbol=getattr(curr, "symbol", ""),
                            timestamp=curr.timestamp,
                            details={
                                "start_index": prev_idx,
                                "end_index": i,
                                "previous_date": str(t_prev.date()),
                                "current_date": str(t_curr.date()),
                                "calendar_days": day_delta,
                                "previous_weekday": prev_wd,
                                "current_weekday": curr_wd,
                                "is_weekend_transition": is_ordinary_weekend,
                            },
                        )
                    )
            else:
                # Intraday candles (e.g. 1m, 5m, 15m)
                if t_prev.date() == t_curr.date():
                    # Same calendar day
                    try:
                        delta = t_curr - t_prev
                    except Exception as exc:  # noqa: BLE001
                        issues.append(
                            QualityIssue(
                                code=DataQualityErrorCode.MALFORMED_CANDLE,
                                message=f"Timestamp delta calculation error at index {i}: {exc}",
                                symbol=getattr(curr, "symbol", ""),
                                timestamp=curr.timestamp,
                                details={"index": i, "error": str(exc)},
                            )
                        )
                        prev_idx = i
                        prev = curr
                        continue

                    if delta > step:
                        missing_bars = round(delta / step) - 1
                        issues.append(
                            QualityIssue(
                                code=DataQualityErrorCode.MISSING_INTERVAL,
                                message=(
                                    f"Intraday gap detected between {t_prev.isoformat()} and {t_curr.isoformat()}: "
                                    f"delta {delta} exceeds interval {step} (~{missing_bars} missing bars)"
                                ),
                                symbol=getattr(curr, "symbol", ""),
                                timestamp=curr.timestamp,
                                details={
                                    "start_index": prev_idx,
                                    "end_index": i,
                                    "start_timestamp": t_prev.isoformat(),
                                    "end_timestamp": t_curr.isoformat(),
                                    "delta_seconds": delta.total_seconds(),
                                    "step_seconds": step.total_seconds(),
                                    "estimated_missing_candles": missing_bars,
                                },
                            )
                        )
                else:
                    # Crossing calendar date boundary
                    day_diff = (t_curr.date() - t_prev.date()).days
                    prev_wd = t_prev.weekday()
                    curr_wd = t_curr.weekday()

                    # Only consecutive calendar weekdays (day_diff == 1, Mon-Thu) are valid without exchange calendar
                    # Friday-to-Monday (day_diff == 3) or multi-day holiday gaps cannot be assumed valid without calendar
                    if day_diff == 1 and prev_wd < 4 and curr_wd == prev_wd + 1:
                        # Consecutive weekdays: require EXACT session boundaries (close 15:30, open 09:15)
                        prev_close_time = getattr(
                            prev, "close_time", prev.timestamp + step
                        )
                        curr_open_time = getattr(
                            curr, "open_time", curr.timestamp
                        )
                        try:
                            prev_close_time = prev_close_time.astimezone(IST)
                            curr_open_time = curr_open_time.astimezone(IST)
                        except Exception as exc:  # noqa: BLE001
                            issues.append(
                                QualityIssue(
                                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                                    message=f"Session boundary timezone conversion failed at index {i}: {exc}",
                                    symbol=getattr(curr, "symbol", ""),
                                    timestamp=curr.timestamp,
                                    details={"index": i, "error": str(exc)},
                                )
                            )
                            prev_idx = i
                            prev = curr
                            continue

                        normal_prev_close = (prev_close_time.time() == NSE_SESSION_CLOSE)
                        normal_curr_open = (curr_open_time.time() == NSE_SESSION_OPEN)

                        if not normal_prev_close or not normal_curr_open:
                            issues.append(
                                QualityIssue(
                                    code=DataQualityErrorCode.MISSING_INTERVAL,
                                    message=(
                                        f"Gap around session transition between {t_prev.isoformat()} and {t_curr.isoformat()}: "
                                        f"previous bar closed at {prev_close_time.time()} (expected exact {NSE_SESSION_CLOSE}) or "
                                        f"current bar opened at {curr_open_time.time()} (expected exact {NSE_SESSION_OPEN})"
                                    ),
                                    symbol=getattr(curr, "symbol", ""),
                                    timestamp=curr.timestamp,
                                    details={
                                        "start_index": prev_idx,
                                        "end_index": i,
                                        "previous_close_time": str(prev_close_time.time()),
                                        "current_open_time": str(curr_open_time.time()),
                                        "expected_session_open": str(NSE_SESSION_OPEN),
                                        "expected_session_close": str(NSE_SESSION_CLOSE),
                                    },
                                )
                            )
                    else:
                        # Ambiguous multi-day transition: ordinary weekend or holiday gap requires exchange calendar
                        is_ordinary_weekend = (day_diff == 3 and prev_wd == 4 and curr_wd == 0)
                        issues.append(
                            QualityIssue(
                                code=DataQualityErrorCode.MARKET_CALENDAR_REQUIRED,
                                message=(
                                    f"Multi-day transition detected between {t_prev.date()} and {t_curr.date()}: "
                                    f"{day_diff} calendar days elapsed ({'ordinary weekend' if is_ordinary_weekend else 'potential holiday gap'}); "
                                    "reliable exchange calendar required (M2b) to verify trading days"
                                ),
                                symbol=getattr(curr, "symbol", ""),
                                timestamp=curr.timestamp,
                                details={
                                    "start_index": prev_idx,
                                    "end_index": i,
                                    "previous_date": str(t_prev.date()),
                                    "current_date": str(t_curr.date()),
                                    "day_difference": day_diff,
                                    "is_weekend_transition": is_ordinary_weekend,
                                },
                            )
                        )

        prev_idx = i
        prev = curr

    return issues


def check_sequence_integrity(
    candles: Iterable[Any],
    expected_interval: CandleInterval | timedelta | None = None,
) -> list[QualityIssue]:
    """Validate sequence for duplicate timestamps, monotonicity, and missing intervals."""
    candles_seq: Sequence[Any] = candles if isinstance(candles, Sequence) else tuple(candles)
    issues: list[QualityIssue] = []
    issues.extend(check_duplicate_timestamps(candles_seq))
    issues.extend(check_sequence_monotonicity(candles_seq))
    issues.extend(check_missing_intervals(candles_seq, expected_interval=expected_interval))
    return issues


def check_sequence_consistency(candles: Iterable[Any]) -> list[QualityIssue]:
    """Ensure all valid candles in a sequence share the same symbol, exchange, and interval, preserving indices.

    Emits MALFORMED_CANDLE for structural defects.
    """
    candles_seq: Sequence[Any] = candles if isinstance(candles, Sequence) else tuple(candles)
    issues: list[QualityIssue] = []

    first: Any = None

    for i, candle in enumerate(candles_seq):
        structural_errs = check_candle_structure(candle)
        if structural_errs:
            for issue in structural_errs:
                details = dict(issue.details)
                details["index"] = i
                issues.append(
                    QualityIssue(
                        code=issue.code,
                        message=issue.message,
                        symbol=issue.symbol,
                        timestamp=issue.timestamp,
                        details=details,
                    )
                )
            continue

        if first is None:
            first = candle
            continue

        if getattr(candle, "symbol", None) != getattr(first, "symbol", None):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_SYMBOL,
                    message=(
                        f"Inconsistent symbol at index {i}: got {getattr(candle, 'symbol', None)}, "
                        f"expected {getattr(first, 'symbol', None)}"
                    ),
                    symbol=getattr(candle, "symbol", ""),
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "index": i,
                        "expected": getattr(first, "symbol", ""),
                        "found": getattr(candle, "symbol", ""),
                    },
                )
            )
        if getattr(candle, "exchange", None) != getattr(first, "exchange", None):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_EXCHANGE,
                    message=(
                        f"Inconsistent exchange at index {i}: got {getattr(candle, 'exchange', None)}, "
                        f"expected {getattr(first, 'exchange', None)}"
                    ),
                    symbol=getattr(candle, "symbol", ""),
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "index": i,
                        "expected": str(getattr(first, "exchange", "")),
                        "found": str(getattr(candle, "exchange", "")),
                    },
                )
            )
        if getattr(candle, "interval", None) != getattr(first, "interval", None):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_INTERVAL,
                    message=(
                        f"Inconsistent interval at index {i}: got {getattr(candle, 'interval', None)}, "
                        f"expected {getattr(first, 'interval', None)}"
                    ),
                    symbol=getattr(candle, "symbol", ""),
                    timestamp=getattr(candle, "timestamp", None),
                    details={
                        "index": i,
                        "expected": str(getattr(first, "interval", "")),
                        "found": str(getattr(candle, "interval", "")),
                    },
                )
            )

    return issues


def validate_candle(
    candle: Any,
    now: datetime | None = None,
    max_staleness: timedelta | None = None,
) -> ValidationResult:
    """Validate a single candle against all individual bar quality rules.

    Checks:
    1. Structural validation: presence of required fields.
    2. Timezone-aware timestamps on candle open and retrieval.
    3. Positive OHLC prices.
    4. High >= max(open, close).
    5. Low <= min(open, close).
    6. High >= low.
    7. Non-negative volume.
    8. Timing & Provenance:
       - Retrieval timestamp >= close time.
       - Rejection of in-progress candles (now < close time).
       - Rejection of future candles (now < open time).
       - Retrieval timestamp <= now.
       - Deterministic staleness check from bar close.
    """
    _validate_now_and_staleness(now, max_staleness)

    issues: list[QualityIssue] = []

    # 1. Structural validation
    structural_issues = check_candle_structure(candle)
    issues.extend(structural_issues)
    if candle is None:
        return ValidationResult(is_valid=False, issues=tuple(issues))

    symbol = getattr(candle, "symbol", "") if isinstance(getattr(candle, "symbol", None), str) else ""
    ts = getattr(candle, "timestamp", None)

    # 2. Timezone checks on timestamp attributes
    if ts is not None:
        issues.extend(check_timezone_awareness(ts, "timestamp", symbol))
    ret_ts = getattr(candle, "retrieval_timestamp", None)
    if ret_ts is not None and ret_ts != ts:
        issues.extend(check_timezone_awareness(ret_ts, "retrieval_timestamp", symbol))

    # If structural issues were found, fail closed immediately before domain evaluation
    if structural_issues:
        return ValidationResult(is_valid=False, issues=tuple(issues))

    # 3. Numeric price checks
    o = getattr(candle, "open", None)
    h = getattr(candle, "high", None)
    l = getattr(candle, "low", None)
    c = getattr(candle, "close", None)

    for field_name, p in [("open", o), ("high", h), ("low", l), ("close", c)]:
        if p is not None:
            if isinstance(p, bool) or not isinstance(p, Decimal):
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.MALFORMED_CANDLE,
                        message=f"{field_name} must be a Decimal instance, got {type(p).__name__}",
                        symbol=symbol,
                        timestamp=ts if isinstance(ts, datetime) else None,
                        details={"field": field_name},
                    )
                )
            elif not p.is_finite():
                issues.append(
                    QualityIssue(
                        code=DataQualityErrorCode.NON_FINITE_NUMERIC,
                        message=f"{field_name} must be finite, got {p}",
                        symbol=symbol,
                        timestamp=ts if isinstance(ts, datetime) else None,
                        details={"field": field_name, "value": str(p)},
                    )
                )

    # 4. Positive OHLC and OHLC relationships (only if all 4 prices are valid finite Decimals)
    if (
        all(isinstance(p, Decimal) and p.is_finite() for p in (o, h, l, c))
        and not any(isinstance(p, bool) for p in (o, h, l, c))
    ):
        issues.extend(check_price_positivity(o, h, l, c, symbol, ts if isinstance(ts, datetime) else None))
        issues.extend(check_ohlc_relationships(o, h, l, c, symbol, ts if isinstance(ts, datetime) else None))

    # 5. Non-negative volume
    vol = getattr(candle, "volume", None)
    if vol is not None:
        if isinstance(vol, bool) or not isinstance(vol, int):
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MALFORMED_CANDLE,
                    message=f"volume must be an integer, got {type(vol).__name__}",
                    symbol=symbol,
                    timestamp=ts if isinstance(ts, datetime) else None,
                    details={"field": "volume"},
                )
            )
        else:
            issues.extend(check_volume(vol, symbol, ts if isinstance(ts, datetime) else None))

    # 6. Timing boundaries, provenance, and staleness
    timing_issues = check_timing_and_provenance(candle, now=now, max_staleness=max_staleness)
    existing_codes = {issue.code for issue in issues}
    for t_issue in timing_issues:
        if t_issue.code == DataQualityErrorCode.NAIVE_TIMESTAMP and DataQualityErrorCode.NAIVE_TIMESTAMP in existing_codes:
            continue
        issues.append(t_issue)

    return ValidationResult(is_valid=(len(issues) == 0), issues=tuple(issues))


def validate_candle_sequence(
    candles: Iterable[Any],
    now: datetime | None = None,
    max_staleness: timedelta | None = None,
    expected_interval: CandleInterval | timedelta | None = None,
    allow_empty: bool = False,
    check_gaps: bool = True,
) -> ValidationResult:
    """Validate an ordered series of candles for an equity instrument.

    Guarantees:
    - Parameter validation for `now` and `max_staleness`.
    - Deterministic materialization for generator/iterator inputs.
    - Pre-validation of all elements, recording original sequence indices for malformed elements.
    - Sequence consistency (symbol, exchange, interval) across valid candles.
    - Complete identity in duplicate detection (symbol, exchange, interval, UTC timestamp).
    - Session-aware intraday gap detection without false positives for overnight/weekends.
    - Freshness check on latest completed bar.
    """
    _validate_now_and_staleness(now, max_staleness)
    _validate_expected_interval(expected_interval)

    # Materialize iterable to handle generators deterministically
    candles_tuple: tuple[Any, ...] = tuple(candles)

    if not candles_tuple:
        if allow_empty:
            return ValidationResult(is_valid=True, issues=())
        issue = QualityIssue(
            code=DataQualityErrorCode.EMPTY_SEQUENCE,
            message="Candle sequence is empty",
        )
        return ValidationResult(is_valid=False, issues=(issue,))

    all_issues: list[QualityIssue] = []

    # Validate each candle individually, recording original sequence index
    for i, c in enumerate(candles_tuple):
        candle_result = validate_candle(c, now=None)
        for issue in candle_result.issues:
            details_dict = dict(issue.details)
            details_dict["index"] = i
            all_issues.append(
                QualityIssue(
                    code=issue.code,
                    message=issue.message,
                    symbol=issue.symbol,
                    timestamp=issue.timestamp,
                    details=details_dict,
                )
            )

    # Sequence consistency (symbol, exchange, interval) preserving indices
        # Deduplicated issue aggregation preserving issue uniqueness and original indices
    def _add_unique(issues_to_add: list[QualityIssue]) -> None:
        existing_keys = {
            (
                iss.code,
                iss.details.get("index"),
                iss.details.get("field"),
                iss.details.get("missing_field"),
            )
            for iss in all_issues
        }
        for iss in issues_to_add:
            key = (
                iss.code,
                iss.details.get("index"),
                iss.details.get("field"),
                iss.details.get("missing_field"),
            )
            if key not in existing_keys:
                all_issues.append(iss)
                existing_keys.add(key)

    # Sequence consistency (symbol, exchange, interval) preserving indices
    _add_unique(check_sequence_consistency(candles_tuple))

    # Integrity: duplicates (with complete identity), monotonicity, session-aware gaps
    # check_gaps=False suppresses missing-interval detection; duplicates and monotonicity still run.
    if check_gaps:
        # Resolve gap-checking interval: caller-supplied or inferred from first valid candle.
        inferred_step: CandleInterval | timedelta | None = expected_interval
        if inferred_step is None:
            first_valid = next(
                (
                    c for c in candles_tuple
                    if c is not None and isinstance(getattr(c, "interval", None), CandleInterval)
                ),
                None,
            )
            if first_valid is not None:
                inferred_step = first_valid.interval
        _add_unique(check_sequence_integrity(candles_tuple, expected_interval=inferred_step))
    else:
        # Gap detection disabled: run only duplicate and monotonicity checks.
        _add_unique(check_duplicate_timestamps(candles_tuple))
        _add_unique(check_sequence_monotonicity(candles_tuple))

    last_valid_entry = None
    for c in reversed(candles_tuple):
        if c is not None and getattr(c, "timestamp", None) is not None and getattr(c, "close_time", None) is not None:
            last_valid_entry = c
            break

    if now is not None and last_valid_entry is not None:
        staleness_limit = max_staleness
        if staleness_limit is None and hasattr(last_valid_entry, "interval") and isinstance(last_valid_entry.interval, CandleInterval):
            staleness_limit = last_valid_entry.interval.duration * 3
        elif staleness_limit is None:
            staleness_limit = timedelta(hours=1)
        all_issues.extend(check_timing_and_provenance(last_valid_entry, now=now, max_staleness=staleness_limit))

    return ValidationResult(is_valid=(len(all_issues) == 0), issues=tuple(all_issues))
