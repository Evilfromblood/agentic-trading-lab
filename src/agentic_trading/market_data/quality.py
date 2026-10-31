"""Deterministic market data quality validation for Indian equities.

Implements strict validation rules for single candles and ordered candle sequences.
Fails closed and reports actionable error codes without silently repairing corrupted data.
All staleness checks require an explicit, injected 'now' reference timestamp.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from agentic_trading.market_data.models import Candle, CandleInterval


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
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    DUPLICATE_CANDLE = "DUPLICATE_CANDLE"
    NON_MONOTONIC_SEQUENCE = "NON_MONOTONIC_SEQUENCE"
    MISSING_INTERVAL = "MISSING_INTERVAL"
    INCONSISTENT_SYMBOL = "INCONSISTENT_SYMBOL"
    INCONSISTENT_EXCHANGE = "INCONSISTENT_EXCHANGE"
    INCONSISTENT_INTERVAL = "INCONSISTENT_INTERVAL"
    EMPTY_SEQUENCE = "EMPTY_SEQUENCE"


@dataclass(frozen=True)
class QualityIssue:
    """Detailed record of a single data quality failure."""

    code: DataQualityErrorCode
    message: str
    symbol: str = ""
    timestamp: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    """Aggregated outcome of market data quality evaluation."""

    is_valid: bool
    issues: tuple[QualityIssue, ...]

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
    dt: datetime,
    field_name: str = "timestamp",
    symbol: str = "",
) -> list[QualityIssue]:
    """Check that a datetime object has an explicit, active timezone offset."""
    issues: list[QualityIssue] = []
    if dt is None or dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message=f"{field_name} must be timezone-aware",
                symbol=symbol,
                timestamp=dt if (dt is not None and getattr(dt, "tzinfo", None) is not None) else None,
                details={"field": field_name},
            )
        )
    return issues


def check_staleness(
    candle_time: datetime,
    now: datetime,
    max_staleness: timedelta,
    symbol: str = "",
) -> list[QualityIssue]:
    """Deterministic staleness check using injected reference 'now'.

    Rejects naive 'now' to prevent accidental timezone bugs.
    Flags FUTURE_TIMESTAMP if candle_time is after now.
    Flags STALE_DATA if (now - candle_time) > max_staleness.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("Injected 'now' parameter must be timezone-aware")

    if candle_time.tzinfo is None or candle_time.tzinfo.utcoffset(candle_time) is None:
        return [
            QualityIssue(
                code=DataQualityErrorCode.NAIVE_TIMESTAMP,
                message="Cannot evaluate staleness for naive candle timestamp",
                symbol=symbol,
            )
        ]

    issues: list[QualityIssue] = []

    if candle_time > now:
        issues.append(
            QualityIssue(
                code=DataQualityErrorCode.FUTURE_TIMESTAMP,
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


def check_missing_intervals(
    candles: Sequence[Candle],
    expected_interval: CandleInterval | timedelta | None = None,
) -> list[QualityIssue]:
    """Check an ordered sequence of candles for missing intervals/gaps."""
    if len(candles) < 2:
        return []

    issues: list[QualityIssue] = []
    step: timedelta | None = None
    if isinstance(expected_interval, CandleInterval):
        step = expected_interval.duration
    elif isinstance(expected_interval, timedelta):
        step = expected_interval
    elif hasattr(candles[0], "interval") and isinstance(candles[0].interval, CandleInterval):
        step = candles[0].interval.duration

    if step is None:
        return []

    for i in range(1, len(candles)):
        prev = candles[i - 1]
        curr = candles[i]
        delta = curr.timestamp - prev.timestamp
        if delta > step:
            missing_bars = round(delta / step) - 1
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.MISSING_INTERVAL,
                    message=(
                        f"Gap detected between {prev.timestamp.isoformat()} and "
                        f"{curr.timestamp.isoformat()}: delta {delta} exceeds interval {step} "
                        f"(~{missing_bars} missing bars)"
                    ),
                    symbol=curr.symbol,
                    timestamp=curr.timestamp,
                    details={
                        "start_timestamp": prev.timestamp.isoformat(),
                        "end_timestamp": curr.timestamp.isoformat(),
                        "delta_seconds": delta.total_seconds(),
                        "step_seconds": step.total_seconds(),
                        "estimated_missing_candles": missing_bars,
                    },
                )
            )
    return issues


def check_duplicate_timestamps(candles: Sequence[Candle]) -> list[QualityIssue]:
    """Check for duplicate timestamps in a sequence of candles."""
    issues: list[QualityIssue] = []
    seen: set[datetime] = set()
    for i, c in enumerate(candles):
        if c.timestamp in seen:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.DUPLICATE_CANDLE,
                    message=f"Duplicate candle timestamp detected at index {i}: {c.timestamp.isoformat()}",
                    symbol=c.symbol,
                    timestamp=c.timestamp,
                    details={"index": i, "timestamp": c.timestamp.isoformat()},
                )
            )
        seen.add(c.timestamp)
    return issues


def check_sequence_monotonicity(candles: Sequence[Candle]) -> list[QualityIssue]:
    """Check that candles are strictly non-decreasing in timestamp."""
    issues: list[QualityIssue] = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        curr = candles[i]
        if curr.timestamp < prev.timestamp:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.NON_MONOTONIC_SEQUENCE,
                    message=(
                        f"Candle sequence out-of-order at index {i}: "
                        f"{curr.timestamp.isoformat()} is prior to previous candle {prev.timestamp.isoformat()}"
                    ),
                    symbol=curr.symbol,
                    timestamp=curr.timestamp,
                    details={
                        "index": i,
                        "timestamp": curr.timestamp.isoformat(),
                        "previous_timestamp": prev.timestamp.isoformat(),
                    },
                )
            )
    return issues


def check_sequence_integrity(
    candles: Sequence[Candle],
    expected_interval: CandleInterval | timedelta | None = None,
) -> list[QualityIssue]:
    """Validate sequence for duplicate timestamps, monotonicity, and missing intervals."""
    issues: list[QualityIssue] = []
    issues.extend(check_duplicate_timestamps(candles))
    issues.extend(check_sequence_monotonicity(candles))
    issues.extend(check_missing_intervals(candles, expected_interval=expected_interval))
    return issues


def check_sequence_consistency(candles: Sequence[Candle]) -> list[QualityIssue]:
    """Ensure all candles in a sequence share the same symbol, exchange, and interval."""
    if len(candles) <= 1:
        return []

    issues: list[QualityIssue] = []
    first = candles[0]

    for i, candle in enumerate(candles[1:], start=1):
        if candle.symbol != first.symbol:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_SYMBOL,
                    message=(
                        f"Inconsistent symbol at index {i}: got {candle.symbol}, "
                        f"expected {first.symbol}"
                    ),
                    symbol=candle.symbol,
                    timestamp=candle.timestamp,
                    details={"index": i, "expected": first.symbol, "found": candle.symbol},
                )
            )
        if candle.exchange != first.exchange:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_EXCHANGE,
                    message=(
                        f"Inconsistent exchange at index {i}: got {candle.exchange}, "
                        f"expected {first.exchange}"
                    ),
                    symbol=candle.symbol,
                    timestamp=candle.timestamp,
                    details={
                        "index": i,
                        "expected": str(first.exchange),
                        "found": str(candle.exchange),
                    },
                )
            )
        if candle.interval != first.interval:
            issues.append(
                QualityIssue(
                    code=DataQualityErrorCode.INCONSISTENT_INTERVAL,
                    message=(
                        f"Inconsistent interval at index {i}: got {candle.interval}, "
                        f"expected {first.interval}"
                    ),
                    symbol=candle.symbol,
                    timestamp=candle.timestamp,
                    details={
                        "index": i,
                        "expected": str(first.interval),
                        "found": str(candle.interval),
                    },
                )
            )

    return issues


def validate_candle(
    candle: Candle,
    now: datetime | None = None,
    max_staleness: timedelta | None = None,
) -> ValidationResult:
    """Validate a single candle against all individual bar quality rules.

    Checks:
    1. Positive OHLC prices.
    2. High >= max(open, close).
    3. Low <= min(open, close).
    4. High >= low.
    5. Non-negative volume.
    6. Timezone-aware timestamps.
    7. Stale / future market data (if injected 'now' is provided).
    """
    issues: list[QualityIssue] = []

    # 6. Timezone check
    issues.extend(check_timezone_awareness(candle.timestamp, "timestamp", candle.symbol))
    if hasattr(candle, "retrieval_timestamp") and candle.retrieval_timestamp is not None:
        issues.extend(
            check_timezone_awareness(
                candle.retrieval_timestamp, "retrieval_timestamp", candle.symbol
            )
        )

    # 1. Positive OHLC
    issues.extend(
        check_price_positivity(
            candle.open, candle.high, candle.low, candle.close, candle.symbol, candle.timestamp
        )
    )

    # 2, 3, 4. OHLC relationships
    issues.extend(
        check_ohlc_relationships(
            candle.open, candle.high, candle.low, candle.close, candle.symbol, candle.timestamp
        )
    )

    # 5. Non-negative volume
    issues.extend(check_volume(candle.volume, candle.symbol, candle.timestamp))

    # 9. Staleness (deterministic with injected 'now')
    if now is not None:
        staleness_limit = max_staleness
        if staleness_limit is None:
            staleness_limit = candle.interval.duration * 3
        issues.extend(check_staleness(candle.timestamp, now, staleness_limit, candle.symbol))

    return ValidationResult(is_valid=(len(issues) == 0), issues=tuple(issues))


def validate_candle_sequence(
    candles: Sequence[Candle],
    now: datetime | None = None,
    max_staleness: timedelta | None = None,
    expected_interval: CandleInterval | timedelta | None = None,
    allow_empty: bool = False,
    check_gaps: bool = True,
) -> ValidationResult:
    """Validate an ordered series of candles for an equity instrument.

    Checks:
    - Validity of each individual candle in sequence.
    - Consistency of symbol, exchange, and interval.
    - Duplicate timestamps.
    - Monotonicity (chronological order).
    - Missing intervals / gaps.
    - Staleness of the latest observation against reference 'now'.
    """
    if not candles:
        if allow_empty:
            return ValidationResult(is_valid=True, issues=())
        issue = QualityIssue(
            code=DataQualityErrorCode.EMPTY_SEQUENCE,
            message="Candle sequence is empty",
        )
        return ValidationResult(is_valid=False, issues=(issue,))

    all_issues: list[QualityIssue] = []

    # Validate each candle individually (without staleness; sequence staleness evaluated on latest)
    for c in candles:
        candle_result = validate_candle(c, now=None)
        all_issues.extend(candle_result.issues)

    # Sequence consistency (symbol, exchange, interval)
    all_issues.extend(check_sequence_consistency(candles))

    # Integrity: duplicates, monotonicity, gaps
    step = expected_interval if check_gaps else None
    if step is None and check_gaps and hasattr(candles[0], "interval"):
        step = candles[0].interval
    all_issues.extend(check_sequence_integrity(candles, expected_interval=step))

    # Staleness evaluation on the latest candle in the series
    if now is not None:
        latest = candles[-1]
        staleness_limit = max_staleness
        if staleness_limit is None and hasattr(latest, "interval"):
            staleness_limit = latest.interval.duration * 3
        elif staleness_limit is None:
            staleness_limit = timedelta(hours=1)
        all_issues.extend(check_staleness(latest.timestamp, now, staleness_limit, latest.symbol))

    return ValidationResult(is_valid=(len(all_issues) == 0), issues=tuple(all_issues))
