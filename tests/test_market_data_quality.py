"""Unit tests for market data quality validation (NSE/BSE equities).

Verifies all 10 deterministic validation checks:
1. Positive OHLC prices
2. High >= max(open, close)
3. Low <= min(open, close)
4. High >= low
5. Non-negative volume
6. Timezone-aware timestamps
7. Duplicate candles
8. Non-monotonic candle sequences
9. Stale market data (with injected 'now')
10. Missing intervals/gaps
plus boundary conditions and sequence consistency.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
)
from agentic_trading.market_data.quality import (
    DataQualityErrorCode,
    check_duplicate_timestamps,
    check_missing_intervals,
    check_ohlc_relationships,
    check_price_positivity,
    check_sequence_consistency,
    check_sequence_integrity,
    check_sequence_monotonicity,
    check_staleness,
    check_timezone_awareness,
    check_volume,
    validate_candle,
    validate_candle_sequence,
)


def make_candle(**overrides) -> Candle:
    """Helper to create test candles with sensible defaults."""
    base_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    values = {
        "symbol": "TCS",
        "exchange": Exchange.NSE,
        "interval": CandleInterval.M5,
        "open": Decimal("3500.00"),
        "high": Decimal("3510.00"),
        "low": Decimal("3495.00"),
        "close": Decimal("3505.00"),
        "volume": 5000,
        "timestamp": base_time,
        "source": "ZERODHA",
        "retrieval_timestamp": base_time + timedelta(seconds=2),
    }
    values.update(overrides)
    return Candle(**values)


# ============================================================================
# Rule 1: Positive OHLC prices
# ============================================================================


def test_positive_prices_accepted() -> None:
    candle = make_candle()
    result = validate_candle(candle)
    assert result.is_valid is True
    assert result.issues == ()
    assert not result.has_error(DataQualityErrorCode.NON_POSITIVE_PRICE)


@pytest.mark.parametrize(
    ("price_field", "bad_price"),
    [
        ("open", Decimal(0)),
        ("open", Decimal("-10.50")),
        ("high", Decimal(0)),
        ("high", Decimal("-5.00")),
        ("low", Decimal(0)),
        ("low", Decimal("-1.00")),
        ("close", Decimal(0)),
        ("close", Decimal("-100.00")),
    ],
)
def test_rejects_non_positive_prices(price_field: str, bad_price: Decimal) -> None:
    candle = make_candle(**{price_field: bad_price})
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NON_POSITIVE_PRICE)
    issues = result.get_issues_by_code(DataQualityErrorCode.NON_POSITIVE_PRICE)
    assert len(issues) >= 1
    assert issues[0].details["field"] == price_field


# ============================================================================
# Rules 2, 3, 4: OHLC Relationships
# ============================================================================


def test_rejects_high_less_than_open() -> None:
    # open=3500, high=3490 (high < open)
    candle = make_candle(open=Decimal("3500.00"), high=Decimal("3490.00"), low=Decimal("3480.00"), close=Decimal("3485.00"))
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE)


def test_rejects_high_less_than_close() -> None:
    # close=3520, high=3510 (high < close)
    candle = make_candle(open=Decimal("3500.00"), high=Decimal("3510.00"), low=Decimal("3490.00"), close=Decimal("3520.00"))
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE)


def test_rejects_low_greater_than_open() -> None:
    # open=3490, low=3495 (low > open)
    candle = make_candle(open=Decimal("3490.00"), high=Decimal("3510.00"), low=Decimal("3495.00"), close=Decimal("3500.00"))
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE)


def test_rejects_low_greater_than_close() -> None:
    # close=3490, low=3495 (low > close)
    candle = make_candle(open=Decimal("3500.00"), high=Decimal("3510.00"), low=Decimal("3495.00"), close=Decimal("3490.00"))
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE)


def test_rejects_high_less_than_low() -> None:
    # high=3490, low=3500 (high < low)
    candle = make_candle(open=Decimal("3495.00"), high=Decimal("3490.00"), low=Decimal("3500.00"), close=Decimal("3495.00"))
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_LOW)


def test_boundary_ohlc_equality_conditions() -> None:
    # 1. Flat candle: open == high == low == close
    flat_candle = make_candle(
        open=Decimal("3500.00"),
        high=Decimal("3500.00"),
        low=Decimal("3500.00"),
        close=Decimal("3500.00"),
    )
    result = validate_candle(flat_candle)
    assert result.is_valid is True

    # 2. Bullish marubozu: low == open, high == close
    marubozu = make_candle(
        open=Decimal("3500.00"),
        high=Decimal("3520.00"),
        low=Decimal("3500.00"),
        close=Decimal("3520.00"),
    )
    assert validate_candle(marubozu).is_valid is True

    # 3. Bearish marubozu: high == open, low == close
    bearish_marubozu = make_candle(
        open=Decimal("3520.00"),
        high=Decimal("3520.00"),
        low=Decimal("3500.00"),
        close=Decimal("3500.00"),
    )
    assert validate_candle(bearish_marubozu).is_valid is True


# ============================================================================
# Rule 5: Non-negative volume
# ============================================================================


def test_rejects_negative_volume() -> None:
    candle = make_candle(volume=-100)
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NEGATIVE_VOLUME)


def test_accepts_zero_volume_boundary() -> None:
    candle = make_candle(volume=0)
    result = validate_candle(candle)
    assert result.is_valid is True
    assert not result.has_error(DataQualityErrorCode.NEGATIVE_VOLUME)


# ============================================================================
# Rule 6: Timezone-aware timestamps
# ============================================================================


def test_rejects_naive_timestamp_in_quality_gate() -> None:
    naive_dt = datetime(2026, 11, 2, 9, 15)  # tzinfo=None
    # Bypass model init check using validate_timezone=False to test quality gate
    candle = make_candle(timestamp=naive_dt, validate_timezone=False)
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NAIVE_TIMESTAMP)


def test_check_timezone_awareness_helper() -> None:
    naive_dt = datetime(2026, 11, 2, 9, 15)
    aware_dt = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    assert check_timezone_awareness(aware_dt) == []
    issues = check_timezone_awareness(naive_dt, field_name="custom_ts")
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.NAIVE_TIMESTAMP


# ============================================================================
# Rule 9: Stale market data & Future timestamps (with injected 'now')
# ============================================================================


def test_staleness_detection_with_injected_now() -> None:
    candle_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = make_candle(timestamp=candle_time)

    # 1. Fresh candle: 5 minutes later, max_staleness=15 min -> fresh
    now_fresh = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    res_fresh = validate_candle(candle, now=now_fresh, max_staleness=timedelta(minutes=15))
    assert res_fresh.is_valid is True

    # 2. Boundary: exactly 15 minutes later, max_staleness=15 min -> fresh
    now_boundary = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    res_boundary = validate_candle(candle, now=now_boundary, max_staleness=timedelta(minutes=15))
    assert res_boundary.is_valid is True

    # 3. Stale candle: 15 minutes and 1 second later -> stale
    now_stale = datetime(2026, 11, 2, 9, 30, 1, tzinfo=IST)
    res_stale = validate_candle(candle, now=now_stale, max_staleness=timedelta(minutes=15))
    assert res_stale.is_valid is False
    assert res_stale.has_error(DataQualityErrorCode.STALE_DATA)


def test_future_timestamp_detection() -> None:
    candle_time = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    candle = make_candle(timestamp=candle_time)

    # Injected now is earlier than candle timestamp
    now_past = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    result = validate_candle(candle, now=now_past)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.FUTURE_TIMESTAMP)


def test_staleness_check_rejects_naive_now() -> None:
    candle = make_candle()
    naive_now = datetime(2026, 11, 2, 9, 30)
    with pytest.raises(ValueError, match="Injected 'now' parameter must be timezone-aware"):
        validate_candle(candle, now=naive_now)


# ============================================================================
# Rules 7, 8, 10: Duplicates, Monotonicity, and Missing Intervals (Gaps)
# ============================================================================


def make_candle_series(timestamps: list[datetime], interval: CandleInterval = CandleInterval.M5) -> list[Candle]:
    """Create a series of valid candles for sequence testing."""
    return [
        make_candle(
            interval=interval,
            timestamp=t,
            retrieval_timestamp=t + timedelta(seconds=1),
        )
        for t in timestamps
    ]


def test_valid_sequential_candles_acceptance() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    times = [t0 + timedelta(minutes=5 * i) for i in range(5)]
    series = make_candle_series(times, interval=CandleInterval.M5)

    now = times[-1] + timedelta(minutes=2)
    result = validate_candle_sequence(series, now=now, max_staleness=timedelta(minutes=15))
    assert result.is_valid is True
    assert result.issues == ()


def test_duplicate_candle_timestamps_detected() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    # Series with a duplicate timestamp at t1
    series = make_candle_series([t0, t1, t1, t0 + timedelta(minutes=15)])

    result = validate_candle_sequence(series)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)

    dup_issues = check_duplicate_timestamps(series)
    assert len(dup_issues) == 1
    assert dup_issues[0].code == DataQualityErrorCode.DUPLICATE_CANDLE


def test_out_of_order_non_monotonic_sequence_detected() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 10, tzinfo=IST)  # Out of order: earlier than t1!
    series = make_candle_series([t0, t1, t2])

    result = validate_candle_sequence(series)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NON_MONOTONIC_SEQUENCE)

    mono_issues = check_sequence_monotonicity(series)
    assert len(mono_issues) == 1
    assert mono_issues[0].code == DataQualityErrorCode.NON_MONOTONIC_SEQUENCE


def test_missing_intervals_gap_detection() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 35, tzinfo=IST)  # Gap: 15 min delta instead of 5 min!
    series = make_candle_series([t0, t1, t2], interval=CandleInterval.M5)

    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    gap_issues = check_missing_intervals(series, CandleInterval.M5)
    assert len(gap_issues) == 1
    assert gap_issues[0].details["estimated_missing_candles"] == 2


# ============================================================================
# Sequence Consistency & Integrity
# ============================================================================


def test_inconsistent_symbol_in_sequence() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c1 = make_candle(symbol="TCS", timestamp=t0)
    c2 = make_candle(symbol="INFY", timestamp=t1)

    result = validate_candle_sequence([c1, c2])
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.INCONSISTENT_SYMBOL)


def test_inconsistent_exchange_in_sequence() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c1 = make_candle(exchange=Exchange.NSE, timestamp=t0)
    c2 = make_candle(exchange=Exchange.BSE, timestamp=t1)

    result = validate_candle_sequence([c1, c2])
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.INCONSISTENT_EXCHANGE)


def test_empty_sequence_handling() -> None:
    res_empty_disallowed = validate_candle_sequence([], allow_empty=False)
    assert res_empty_disallowed.is_valid is False
    assert res_empty_disallowed.has_error(DataQualityErrorCode.EMPTY_SEQUENCE)

    res_empty_allowed = validate_candle_sequence([], allow_empty=True)
    assert res_empty_allowed.is_valid is True


def test_no_silent_repair_of_corrupted_data() -> None:
    """Verifies that validator never modifies or mutates corrupted input candles."""
    bad_candle = make_candle(
        open=Decimal("-10.00"),
        high=Decimal("5.00"),
        low=Decimal("20.00"),
        close=Decimal("0.00"),
        volume=-50,
    )
    original_open = bad_candle.open
    original_volume = bad_candle.volume

    result = validate_candle(bad_candle)
    assert result.is_valid is False
    # Verify input object remains untouched
    assert bad_candle.open == original_open
    assert bad_candle.volume == original_volume
    # Verify exact failure reasons are reported
    assert result.has_error(DataQualityErrorCode.NON_POSITIVE_PRICE)
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_LOW)
    assert result.has_error(DataQualityErrorCode.NEGATIVE_VOLUME)


# ============================================================================
# Granular Validator Helper Tests
# ============================================================================


def test_check_price_positivity_direct() -> None:
    # All positive
    assert check_price_positivity(Decimal(100), Decimal(110), Decimal(90), Decimal(105)) == []
    # Negative open
    issues = check_price_positivity(Decimal(-1), Decimal(110), Decimal(90), Decimal(105), symbol="TCS")
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.NON_POSITIVE_PRICE
    assert issues[0].symbol == "TCS"


def test_check_ohlc_relationships_direct() -> None:
    # High < Low
    issues = check_ohlc_relationships(Decimal(100), Decimal(80), Decimal(90), Decimal(85))
    assert any(i.code == DataQualityErrorCode.HIGH_LESS_THAN_LOW for i in issues)
    assert any(i.code == DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE for i in issues)

    # Low > min(open, close)
    issues_low = check_ohlc_relationships(Decimal(100), Decimal(110), Decimal(95), Decimal(90))
    assert any(i.code == DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE for i in issues_low)


def test_check_volume_direct() -> None:
    assert check_volume(500) == []
    assert check_volume(0) == []
    neg_issues = check_volume(-10, symbol="INFY")
    assert len(neg_issues) == 1
    assert neg_issues[0].code == DataQualityErrorCode.NEGATIVE_VOLUME
    assert neg_issues[0].symbol == "INFY"


def test_check_staleness_direct() -> None:
    t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    now = datetime(2026, 11, 2, 9, 25, tzinfo=IST)
    # 10 minutes age, 5 minutes max staleness -> Stale
    issues = check_staleness(t, now, timedelta(minutes=5))
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.STALE_DATA

    # 10 minutes age, 15 minutes max staleness -> Fresh
    assert check_staleness(t, now, timedelta(minutes=15)) == []


def test_check_sequence_consistency_direct() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c1 = make_candle(symbol="TCS", interval=CandleInterval.M5, timestamp=t0)
    c2 = make_candle(symbol="TCS", interval=CandleInterval.M15, timestamp=t1)
    issues = check_sequence_consistency([c1, c2])
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.INCONSISTENT_INTERVAL


def test_check_sequence_integrity_direct() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    c1 = make_candle(timestamp=t0)
    c2 = make_candle(timestamp=t1)
    issues = check_sequence_integrity([c1, c2], expected_interval=CandleInterval.M5)
    assert any(i.code == DataQualityErrorCode.MISSING_INTERVAL for i in issues)
