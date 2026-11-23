"""Unit tests for market data quality validation (NSE/BSE equities).

Verifies all quality checks and regression tests for confirmed audit findings:
- Explicit candle timing semantics and in-progress candle rejection.
- Exact candle-close boundary conditions.
- Retrieval provenance (rejection of retrieval before close or after now).
- Generator and iterable inputs handling.
- Graceful handling of naive timestamps without crashing.
- Duplicate detection across timezone representations.
- Distinguishing identical duplicates from conflicting duplicates.
- Market-session aware gap detection (no false positives on overnight/weekends).
- Immutable validation issue details and non-contradictory results.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
)
from agentic_trading.market_data.quality import (
    DataQualityErrorCode,
    QualityIssue,
    ValidationResult,
    check_candle_structure,
    check_duplicate_timestamps,
    check_missing_intervals,
    check_ohlc_relationships,
    check_price_positivity,
    check_sequence_consistency,
    check_sequence_integrity,
    check_sequence_monotonicity,
    check_staleness,
    check_timezone_awareness,
    check_timing_and_provenance,
    check_volume,
    validate_candle,
    validate_candle_sequence,
)


def make_candle(**overrides) -> Candle:
    """Helper to create test candles with sensible completed defaults."""
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)
    values = {
        "symbol": "TCS",
        "exchange": Exchange.NSE,
        "interval": CandleInterval.M5,
        "open": Decimal("3500.00"),
        "high": Decimal("3510.00"),
        "low": Decimal("3495.00"),
        "close": Decimal("3505.00"),
        "volume": 5000,
        "timestamp": open_time,
        "source": "ZERODHA",
        "retrieval_timestamp": close_time + timedelta(seconds=2),
    }
    values.update(overrides)
    return Candle(**values)


# ============================================================================
# Phase 1 & 2: Candle Timing Semantics & Retrieval Provenance
# ============================================================================


def test_rejects_in_progress_candle() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)  # 09:20
    # Injected now is during the candle: 09:18
    now_in_progress = open_time + timedelta(minutes=3)

    candle = make_candle(
        timestamp=open_time,
        retrieval_timestamp=close_time + timedelta(seconds=1),
    )
    result = validate_candle(candle, now=now_in_progress)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.IN_PROGRESS_CANDLE)


def test_exact_candle_close_boundary_acceptance() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)  # 09:20:00

    # Injected now is exactly the candle close time: 09:20:00
    now_exact_close = close_time
    candle = make_candle(
        timestamp=open_time,
        retrieval_timestamp=close_time,
    )
    result = validate_candle(candle, now=now_exact_close, max_staleness=timedelta(minutes=15))
    assert result.is_valid is True
    assert not result.has_error(DataQualityErrorCode.IN_PROGRESS_CANDLE)
    assert not result.has_error(DataQualityErrorCode.STALE_DATA)


def test_rejects_future_candle() -> None:
    open_time = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    now_past = datetime(2026, 11, 2, 9, 15, tzinfo=IST)

    candle = make_candle(timestamp=open_time, retrieval_timestamp=open_time + timedelta(minutes=6))
    result = validate_candle(candle, now=now_past)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.FUTURE_CANDLE)


def test_rejects_retrieval_before_candle_close() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Retrieval timestamp is 09:18 (earlier than 09:20 close)
    bad_retrieval = open_time + timedelta(minutes=3)
    candle = make_candle(
        timestamp=open_time,
        retrieval_timestamp=bad_retrieval,
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.RETRIEVAL_BEFORE_CLOSE)


def test_rejects_retrieval_after_injected_now() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)
    now = close_time + timedelta(seconds=5)

    # Retrieval claims to be 10 seconds later than now
    future_retrieval = now + timedelta(seconds=10)
    candle = make_candle(
        timestamp=open_time,
        retrieval_timestamp=future_retrieval,
    )
    result = validate_candle(candle, now=now)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.RETRIEVAL_AFTER_NOW)


def test_staleness_evaluated_from_bar_close() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)  # 09:20:00
    candle = make_candle(timestamp=open_time, retrieval_timestamp=close_time + timedelta(seconds=1))

    # 1. 10 minutes after close: within 15 min max staleness -> fresh
    now_fresh = close_time + timedelta(minutes=10)
    assert validate_candle(candle, now=now_fresh, max_staleness=timedelta(minutes=15)).is_valid is True

    # 2. Exactly 15 minutes after close -> fresh (boundary)
    now_boundary = close_time + timedelta(minutes=15)
    assert validate_candle(candle, now=now_boundary, max_staleness=timedelta(minutes=15)).is_valid is True

    # 3. 15 minutes and 1 second after close -> stale
    now_stale = close_time + timedelta(minutes=15, seconds=1)
    res_stale = validate_candle(candle, now=now_stale, max_staleness=timedelta(minutes=15))
    assert res_stale.is_valid is False
    assert res_stale.has_error(DataQualityErrorCode.STALE_DATA)


# ============================================================================
# Phase 3: Model Integrity & Result Immutability
# ============================================================================


def test_quality_issue_details_are_immutable() -> None:
    issue = QualityIssue(
        code=DataQualityErrorCode.NON_POSITIVE_PRICE,
        message="Test issue",
        details={
            "key": "initial_value",
            "nested_dict": {"inner_key": "inner_val"},
            "nested_list": ["item1", "item2"],
            "nested_set": {"set1", "set2"},
        },
    )
    assert isinstance(issue.details, MappingProxyType)
    # Top-level mutation forbidden
    with pytest.raises(TypeError):
        issue.details["key"] = "modified_value"  # type: ignore[index]
    with pytest.raises(TypeError):
        issue.details["new_key"] = "new_value"  # type: ignore[index]

    # Nested dictionary mutation forbidden
    assert isinstance(issue.details["nested_dict"], MappingProxyType)
    with pytest.raises(TypeError):
        issue.details["nested_dict"]["inner_key"] = "mutated"  # type: ignore[index]

    # Nested list converted to tuple (mutation forbidden)
    assert isinstance(issue.details["nested_list"], tuple)
    with pytest.raises(AttributeError):
        issue.details["nested_list"].append("new_item")  # type: ignore[union-attr]

    # Nested set converted to frozenset (mutation forbidden)
    assert isinstance(issue.details["nested_set"], frozenset)
    with pytest.raises(AttributeError):
        issue.details["nested_set"].add("new_set_item")  # type: ignore[union-attr]


def test_conflicting_duplicate_details_are_deeply_immutable() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    c1 = make_candle(timestamp=t0, close=Decimal(3500))
    c2_conflicting = make_candle(timestamp=t0, close=Decimal(3550))
    res = validate_candle_sequence([c1, c2_conflicting])
    issues = res.get_issues_by_code(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)
    assert len(issues) == 1
    issue = issues[0]

    # existing_ohlcv and conflicting_ohlcv must be deeply immutable
    assert isinstance(issue.details["existing_ohlcv"], MappingProxyType)
    assert isinstance(issue.details["conflicting_ohlcv"], MappingProxyType)
    with pytest.raises(TypeError):
        issue.details["existing_ohlcv"]["open"] = "999"  # type: ignore[index]
    with pytest.raises(TypeError):
        issue.details["conflicting_ohlcv"]["open"] = "999"  # type: ignore[index]


def test_parameter_validation_now_types() -> None:
    candle = make_candle()
    # Non-datetime type for now
    with pytest.raises(TypeError, match="'now' must be a datetime instance"):
        validate_candle(candle, now="2026-11-02T09:30:00Z")  # type: ignore[arg-type]

    # Naive datetime for now
    naive_now = datetime(2026, 11, 2, 9, 30)
    with pytest.raises(ValueError, match="Injected 'now' parameter must be timezone-aware"):
        validate_candle(candle, now=naive_now)

    with pytest.raises(ValueError, match="Injected 'now' parameter must be timezone-aware"):
        validate_candle_sequence([candle], now=naive_now)


def test_parameter_validation_max_staleness() -> None:
    candle = make_candle()
    now = candle.close_time + timedelta(minutes=5)

    # Non-timedelta type
    with pytest.raises(TypeError, match="'max_staleness' must be a timedelta instance"):
        validate_candle(candle, now=now, max_staleness=300)  # type: ignore[arg-type]

    # Negative timedelta
    with pytest.raises(ValueError, match="'max_staleness' must be a non-negative timedelta"):
        validate_candle(candle, now=now, max_staleness=timedelta(seconds=-1))


def test_zero_staleness_boundary() -> None:
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    exact_close = open_time + timedelta(minutes=5)
    candle = make_candle(timestamp=open_time, retrieval_timestamp=exact_close)

    # Zero staleness: exactly at close_time -> valid!
    res_exact = validate_candle(candle, now=exact_close, max_staleness=timedelta(0))
    assert res_exact.is_valid is True

    # Zero staleness: 1 microsecond after close_time -> stale!
    stale_now = exact_close + timedelta(microseconds=1)
    res_stale = validate_candle(candle, now=stale_now, max_staleness=timedelta(0))
    assert res_stale.is_valid is False
    assert res_stale.has_error(DataQualityErrorCode.STALE_DATA)


def test_validation_result_prevents_contradictions() -> None:
    issue = QualityIssue(
        code=DataQualityErrorCode.NON_POSITIVE_PRICE,
        message="Bad price",
    )
    # Contradiction: is_valid=True but issues provided
    with pytest.raises(ValueError, match="Contradictory ValidationResult"):
        ValidationResult(is_valid=True, issues=(issue,))

    # Contradiction: is_valid=False but no issues provided
    with pytest.raises(ValueError, match="Contradictory ValidationResult"):
        ValidationResult(is_valid=False, issues=())

    # Valid consistent outcomes
    assert ValidationResult(is_valid=True, issues=()).is_valid is True
    assert ValidationResult(is_valid=False, issues=(issue,)).is_valid is False


# ============================================================================
# OHLC and Volume Rules
# ============================================================================


def test_positive_prices_accepted() -> None:
    candle = make_candle()
    result = validate_candle(candle)
    assert result.is_valid is True
    assert result.issues == ()


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


def test_rejects_high_less_than_open() -> None:
    candle = make_candle(
        open=Decimal("3500.00"),
        high=Decimal("3490.00"),
        low=Decimal("3480.00"),
        close=Decimal("3485.00"),
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE)


def test_rejects_high_less_than_close() -> None:
    candle = make_candle(
        open=Decimal("3500.00"),
        high=Decimal("3510.00"),
        low=Decimal("3490.00"),
        close=Decimal("3520.00"),
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_MAX_OPEN_CLOSE)


def test_rejects_low_greater_than_open() -> None:
    candle = make_candle(
        open=Decimal("3490.00"),
        high=Decimal("3510.00"),
        low=Decimal("3495.00"),
        close=Decimal("3500.00"),
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE)


def test_rejects_low_greater_than_close() -> None:
    candle = make_candle(
        open=Decimal("3500.00"),
        high=Decimal("3510.00"),
        low=Decimal("3495.00"),
        close=Decimal("3490.00"),
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.LOW_GREATER_THAN_MIN_OPEN_CLOSE)


def test_rejects_high_less_than_low() -> None:
    candle = make_candle(
        open=Decimal("3495.00"),
        high=Decimal("3490.00"),
        low=Decimal("3500.00"),
        close=Decimal("3495.00"),
    )
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.HIGH_LESS_THAN_LOW)


def test_rejects_negative_volume() -> None:
    candle = make_candle(volume=-100)
    result = validate_candle(candle)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NEGATIVE_VOLUME)


def test_accepts_zero_volume_boundary() -> None:
    candle = make_candle(volume=0)
    result = validate_candle(candle)
    assert result.is_valid is True


# ============================================================================
# Phase 4: Sequence Validation & Session Gap Behavior
# ============================================================================


def make_candle_series(
    timestamps: list[datetime], interval: CandleInterval = CandleInterval.M5
) -> list[Candle]:
    """Helper to create sequential test candles."""
    duration = interval.duration
    return [
        make_candle(
            interval=interval,
            timestamp=t,
            retrieval_timestamp=t + duration + timedelta(seconds=1),
        )
        for t in timestamps
    ]


def test_generator_input_handling_in_sequence_validation() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    times = [t0 + timedelta(minutes=5 * i) for i in range(4)]

    # Pass a single-use generator
    gen = (
        make_candle(timestamp=t, retrieval_timestamp=t + timedelta(minutes=5, seconds=1))
        for t in times
    )

    now = times[-1] + timedelta(minutes=6)
    result = validate_candle_sequence(gen, now=now)
    assert result.is_valid is True
    assert result.issues == ()


def test_naive_timestamp_in_sequence_does_not_crash() -> None:
    """Ensure sequence validation gracefully reports errors instead of raising TypeError."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)

    class MockDuckCandle:
        def __init__(self, ts):
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal(100)
            self.high = Decimal(105)
            self.low = Decimal(95)
            self.close = Decimal(102)
            self.volume = 1000
            self.timestamp = ts
            self.retrieval_timestamp = ts
            self.open_time = ts
            self.close_time = ts

    c1 = MockDuckCandle(t0)
    c2 = MockDuckCandle(datetime(2026, 11, 2, 9, 20))  # Naive timestamp!

    result = validate_candle_sequence([c1, c2])  # Must not crash!
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NAIVE_TIMESTAMP)


def test_duplicate_detection_across_different_timezone_representations() -> None:
    # 09:15 IST is exactly 03:45 UTC
    t_ist = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_utc = datetime(2026, 11, 2, 3, 45, tzinfo=UTC)

    c1 = make_candle(timestamp=t_ist)
    c2 = make_candle(timestamp=t_utc)

    result = validate_candle_sequence([c1, c2])
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)


def test_distinguishes_identical_vs_conflicting_duplicates() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 1. Identical duplicate (same OHLCV)
    c1 = make_candle(timestamp=t0, close=Decimal(3500))
    c2_identical = make_candle(timestamp=t0, close=Decimal(3500))
    res_identical = validate_candle_sequence([c1, c2_identical])
    assert res_identical.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)
    assert not res_identical.has_error(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)

    # 2. Conflicting duplicate (different close price)
    c2_conflicting = make_candle(timestamp=t0, close=Decimal(3550))
    res_conflicting = validate_candle_sequence([c1, c2_conflicting])
    assert res_conflicting.has_error(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)


def test_out_of_order_non_monotonic_sequence_detected() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 10, tzinfo=IST)  # Out of order
    series = make_candle_series([t0, t1, t2])

    result = validate_candle_sequence(series)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.NON_MONOTONIC_SEQUENCE)


def test_intraday_same_day_missing_interval_detected() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 35, tzinfo=IST)  # Missing 09:25 and 09:30
    series = make_candle_series([t0, t1, t2], interval=CandleInterval.M5)

    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_overnight_market_closure_is_not_treated_as_gap() -> None:
    # Monday 15:25 IST to Tuesday 09:15 IST (normal overnight closure)
    t_mon_close = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    t_tue_open = datetime(2026, 11, 3, 9, 15, tzinfo=IST)

    series = [
        make_candle(timestamp=t_mon_close, retrieval_timestamp=t_mon_close + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_open, retrieval_timestamp=t_tue_open + timedelta(minutes=5, seconds=1)),
    ]

    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    # Must NOT report MISSING_INTERVAL for overnight closure
    assert not result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_weekend_market_closure_is_not_treated_as_gap() -> None:
    # Friday 15:25 IST (2026-11-06) to Monday 09:15 IST (2026-11-09)
    t_fri_close = datetime(2026, 11, 6, 15, 25, tzinfo=IST)  # Friday
    t_mon_open = datetime(2026, 11, 9, 9, 15, tzinfo=IST)  # Monday

    series = [
        make_candle(timestamp=t_fri_close, retrieval_timestamp=t_fri_close + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_mon_open, retrieval_timestamp=t_mon_open + timedelta(minutes=5, seconds=1)),
    ]

    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    # Must NOT report MISSING_INTERVAL for weekend closure
    assert not result.has_error(DataQualityErrorCode.MISSING_INTERVAL)
    # Multi-day weekend transition without exchange calendar requires calendar verification
    assert result.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)


def test_multi_day_unaccounted_gap_flags_calendar_required() -> None:
    # Monday (2026-11-02) to Thursday (2026-11-05), skipping Tue & Wed
    t_mon = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    t_thu = datetime(2026, 11, 5, 9, 15, tzinfo=IST)

    series = [
        make_candle(timestamp=t_mon, retrieval_timestamp=t_mon + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_thu, retrieval_timestamp=t_thu + timedelta(minutes=5, seconds=1)),
    ]

    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)


def test_daily_candles_weekend_handling() -> None:
    # Daily bars: Friday (2026-11-06) to Monday (2026-11-09) is 3 calendar days, normal weekend
    t_fri = datetime(2026, 11, 6, 9, 15, tzinfo=IST)
    t_mon = datetime(2026, 11, 9, 9, 15, tzinfo=IST)

    series = [
        make_candle(
            interval=CandleInterval.D1,
            timestamp=t_fri,
            retrieval_timestamp=t_fri + timedelta(days=1, seconds=1),
        ),
        make_candle(
            interval=CandleInterval.D1,
            timestamp=t_mon,
            retrieval_timestamp=t_mon + timedelta(days=1, seconds=1),
        ),
    ]

    result = validate_candle_sequence(series, expected_interval=CandleInterval.D1)
    # Must NOT report MISSING_INTERVAL
    assert not result.has_error(DataQualityErrorCode.MISSING_INTERVAL)
    # Without an exchange calendar, Friday-to-Monday jump requires calendar verification
    assert result.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)

    # In contrast, consecutive calendar weekdays (Mon -> Tue) pass cleanly without calendar
    t_tue = datetime(2026, 11, 10, 9, 15, tzinfo=IST)
    series_consec = [
        make_candle(interval=CandleInterval.D1, timestamp=t_mon, retrieval_timestamp=t_mon + timedelta(days=1, seconds=1)),
        make_candle(interval=CandleInterval.D1, timestamp=t_tue, retrieval_timestamp=t_tue + timedelta(days=1, seconds=1)),
    ]
    res_consec = validate_candle_sequence(series_consec, expected_interval=CandleInterval.D1)
    assert res_consec.is_valid is True


def test_sequence_consistency_inconsistent_interval() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c1 = make_candle(interval=CandleInterval.M5, timestamp=t0)
    c2 = make_candle(interval=CandleInterval.M15, timestamp=t1)

    result = validate_candle_sequence([c1, c2])
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.INCONSISTENT_INTERVAL)


# ============================================================================
# Additional M2a Regression Tests: Duplicate Identity & Malformed Inputs
# ============================================================================


def test_duplicate_identity_considers_symbol_exchange_interval() -> None:
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Same timestamp, but different symbol: NOT duplicate candles!
    c_tcs = make_candle(symbol="TCS", timestamp=t0)
    c_infy = make_candle(symbol="INFY", timestamp=t0)
    dup_symbol = check_duplicate_timestamps([c_tcs, c_infy])
    assert dup_symbol == []

    # Same timestamp, but different exchange: NOT duplicate candles!
    c_nse = make_candle(exchange=Exchange.NSE, timestamp=t0)
    c_bse = make_candle(exchange=Exchange.BSE, timestamp=t0)
    dup_exchange = check_duplicate_timestamps([c_nse, c_bse])
    assert dup_exchange == []

    # Same timestamp, but different interval: NOT duplicate candles!
    c_5m = make_candle(interval=CandleInterval.M5, timestamp=t0)
    c_15m = make_candle(interval=CandleInterval.M15, timestamp=t0)
    dup_interval = check_duplicate_timestamps([c_5m, c_15m])
    assert dup_interval == []


def test_gap_around_session_close_premature_close() -> None:
    # Monday ended prematurely at 14:00 (instead of 15:30); Tuesday opened normally at 09:15
    t_mon_early_close = datetime(2026, 11, 2, 14, 0, tzinfo=IST)
    t_tue_open = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    series = [
        make_candle(timestamp=t_mon_early_close, retrieval_timestamp=t_mon_early_close + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_open, retrieval_timestamp=t_tue_open + timedelta(minutes=5, seconds=1)),
    ]
    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_gap_around_session_open_delayed_open() -> None:
    # Monday closed normally at 15:25 (close 15:30); Tuesday opened late at 10:30 (instead of 09:15)
    t_mon_close = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    t_tue_late_open = datetime(2026, 11, 3, 10, 30, tzinfo=IST)
    series = [
        make_candle(timestamp=t_mon_close, retrieval_timestamp=t_mon_close + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_late_open, retrieval_timestamp=t_tue_late_open + timedelta(minutes=5, seconds=1)),
    ]
    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_large_gap_across_consecutive_calendar_dates() -> None:
    # Monday 11:00 to Tuesday 14:00 (missing both afternoon of Mon and morning of Tue)
    t_mon_mid = datetime(2026, 11, 2, 11, 0, tzinfo=IST)
    t_tue_mid = datetime(2026, 11, 3, 14, 0, tzinfo=IST)
    series = [
        make_candle(timestamp=t_mon_mid, retrieval_timestamp=t_mon_mid + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_mid, retrieval_timestamp=t_tue_mid + timedelta(minutes=5, seconds=1)),
    ]
    result = validate_candle_sequence(series, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_validate_sequence_with_none_and_malformed_elements() -> None:
    c1 = make_candle(timestamp=datetime(2026, 11, 2, 9, 15, tzinfo=IST))
    c2 = make_candle(timestamp=datetime(2026, 11, 2, 9, 20, tzinfo=IST))

    # Sequence with None element: must not crash!
    res_none = validate_candle_sequence([c1, None, c2])
    assert res_none.is_valid is False
    assert res_none.has_error(DataQualityErrorCode.MALFORMED_CANDLE)

    # Sequence with completely malformed string: must not crash!
    res_str = validate_candle_sequence([c1, "arbitrary_corrupt_data", c2])
    assert res_str.is_valid is False
    assert res_str.has_error(DataQualityErrorCode.MALFORMED_CANDLE)


def test_timezone_with_none_utcoffset_in_quality_check() -> None:
    from datetime import tzinfo

    class DummyNoneOffset(tzinfo):
        def utcoffset(self, dt):
            return None

        def tzname(self, dt):
            return "DUMMY"

        def dst(self, dt):
            return timedelta(0)

    dt_bad = datetime(2026, 11, 2, 9, 15, tzinfo=DummyNoneOffset())
    issues = check_timezone_awareness(dt_bad)
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.NAIVE_TIMESTAMP


# ============================================================================
# Second Review Follow-up Regression Tests
# ============================================================================


def test_candle_structural_validation_missing_fields() -> None:
    """Ensure missing high, low, close, volume, interval, or retrieval_timestamp are rejected with MALFORMED_CANDLE."""
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)

    class IncompleteCandle:
        def __init__(self, **kwargs):
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal(100)
            self.high = Decimal(105)
            self.low = Decimal(95)
            self.close = Decimal(102)
            self.volume = 1000
            self.timestamp = open_time
            self.source = "ZERODHA"
            self.retrieval_timestamp = close_time + timedelta(seconds=1)
            self.open_time = open_time
            self.close_time = close_time
            for k, v in kwargs.items():
                if v is None:
                    delattr(self, k)
                else:
                    setattr(self, k, v)

    for missing_field in ["high", "low", "close", "volume", "interval", "retrieval_timestamp"]:
        incomplete = IncompleteCandle(**{missing_field: None})
        res = validate_candle(incomplete)
        assert res.is_valid is False
        assert res.has_error(DataQualityErrorCode.MALFORMED_CANDLE)
        assert any(
            i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("missing_field") == missing_field
            for i in res.issues
        )


def test_incomplete_candle_cannot_pass_validate_candle() -> None:
    """validate_candle() must fail closed on malformed or empty objects."""
    assert validate_candle(None).is_valid is False
    assert validate_candle("completely_invalid_type").is_valid is False

    class EmptyObject:
        pass

    res = validate_candle(EmptyObject())
    assert res.is_valid is False
    assert res.has_error(DataQualityErrorCode.MALFORMED_CANDLE)


def test_market_session_exact_close_boundaries() -> None:
    """Verify exact 15:30 close boundary requirement vs 15:25 and 15:29."""
    # 1. Bar closing at 15:25 (5m bar at 15:20) followed by 09:15 next day -> MISSING_INTERVAL
    t_mon_1520 = datetime(2026, 11, 2, 15, 20, tzinfo=IST)
    t_tue_0915 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    series_1525 = [
        make_candle(timestamp=t_mon_1520, interval=CandleInterval.M5, retrieval_timestamp=t_mon_1520 + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_0915, interval=CandleInterval.M5, retrieval_timestamp=t_tue_0915 + timedelta(minutes=5, seconds=1)),
    ]
    res_1525 = validate_candle_sequence(series_1525, expected_interval=CandleInterval.M5)
    assert res_1525.is_valid is False
    assert res_1525.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 2. Bar closing at 15:29 (1m bar at 15:28) followed by 09:15 next day -> MISSING_INTERVAL
    t_mon_1528 = datetime(2026, 11, 2, 15, 28, tzinfo=IST)
    series_1529 = [
        make_candle(timestamp=t_mon_1528, interval=CandleInterval.M1, retrieval_timestamp=t_mon_1528 + timedelta(minutes=1, seconds=1)),
        make_candle(timestamp=t_tue_0915, interval=CandleInterval.M1, retrieval_timestamp=t_tue_0915 + timedelta(minutes=1, seconds=1)),
    ]
    res_1529 = validate_candle_sequence(series_1529, expected_interval=CandleInterval.M1)
    assert res_1529.is_valid is False
    assert res_1529.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 3. Bar closing exactly at 15:30 (5m bar at 15:25) followed by 09:15 next day -> Clean overnight
    t_mon_1525 = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    series_1530_5m = [
        make_candle(timestamp=t_mon_1525, interval=CandleInterval.M5, retrieval_timestamp=t_mon_1525 + timedelta(minutes=5, seconds=1)),
        make_candle(timestamp=t_tue_0915, interval=CandleInterval.M5, retrieval_timestamp=t_tue_0915 + timedelta(minutes=5, seconds=1)),
    ]
    res_1530_5m = validate_candle_sequence(series_1530_5m, expected_interval=CandleInterval.M5)
    assert not res_1530_5m.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 4. Bar closing exactly at 15:30 (1m bar at 15:29) followed by 09:15 next day -> Clean overnight
    t_mon_1529 = datetime(2026, 11, 2, 15, 29, tzinfo=IST)
    series_1530_1m = [
        make_candle(timestamp=t_mon_1529, interval=CandleInterval.M1, retrieval_timestamp=t_mon_1529 + timedelta(minutes=1, seconds=1)),
        make_candle(timestamp=t_tue_0915, interval=CandleInterval.M1, retrieval_timestamp=t_tue_0915 + timedelta(minutes=1, seconds=1)),
    ]
    res_1530_1m = validate_candle_sequence(series_1530_1m, expected_interval=CandleInterval.M1)
    assert not res_1530_1m.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_daily_candle_gaps_uncertain_transitions() -> None:
    """Validate daily candle transitions: only consecutive trading weekdays or Fri->Mon are accepted."""
    # 1. Mon to Tue (delta 1) -> accepted
    t_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_tue = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    res_mon_tue = validate_candle_sequence(
        [
            make_candle(interval=CandleInterval.D1, timestamp=t_mon, retrieval_timestamp=t_mon + timedelta(days=1, seconds=1)),
            make_candle(interval=CandleInterval.D1, timestamp=t_tue, retrieval_timestamp=t_tue + timedelta(days=1, seconds=1)),
        ],
        expected_interval=CandleInterval.D1,
    )
    assert not res_mon_tue.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)

    # 2. Fri to Sat (weekend trading without calendar) -> MARKET_CALENDAR_REQUIRED
    t_fri = datetime(2026, 11, 6, 9, 15, tzinfo=IST)
    t_sat = datetime(2026, 11, 7, 9, 15, tzinfo=IST)
    res_fri_sat = validate_candle_sequence(
        [
            make_candle(interval=CandleInterval.D1, timestamp=t_fri, retrieval_timestamp=t_fri + timedelta(days=1, seconds=1)),
            make_candle(interval=CandleInterval.D1, timestamp=t_sat, retrieval_timestamp=t_sat + timedelta(days=1, seconds=1)),
        ],
        expected_interval=CandleInterval.D1,
    )
    assert res_fri_sat.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)

    # 3. Mon to Wed (skipping Tue) -> MARKET_CALENDAR_REQUIRED
    t_wed = datetime(2026, 11, 4, 9, 15, tzinfo=IST)
    res_mon_wed = validate_candle_sequence(
        [
            make_candle(interval=CandleInterval.D1, timestamp=t_mon, retrieval_timestamp=t_mon + timedelta(days=1, seconds=1)),
            make_candle(interval=CandleInterval.D1, timestamp=t_wed, retrieval_timestamp=t_wed + timedelta(days=1, seconds=1)),
        ],
        expected_interval=CandleInterval.D1,
    )
    assert res_mon_wed.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)

    # 4. Thu to Mon (skipping Fri) -> MARKET_CALENDAR_REQUIRED
    t_thu = datetime(2026, 11, 5, 9, 15, tzinfo=IST)
    t_mon_next = datetime(2026, 11, 9, 9, 15, tzinfo=IST)
    res_thu_mon = validate_candle_sequence(
        [
            make_candle(interval=CandleInterval.D1, timestamp=t_thu, retrieval_timestamp=t_thu + timedelta(days=1, seconds=1)),
            make_candle(interval=CandleInterval.D1, timestamp=t_mon_next, retrieval_timestamp=t_mon_next + timedelta(days=1, seconds=1)),
        ],
        expected_interval=CandleInterval.D1,
    )
    assert res_thu_mon.has_error(DataQualityErrorCode.MARKET_CALENDAR_REQUIRED)


def test_sequence_preserves_original_indexes_with_malformed_elements() -> None:
    """Ensure malformed elements do not silently disappear and original sequence indexes are preserved."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    c0 = make_candle(timestamp=t0, retrieval_timestamp=t0 + timedelta(minutes=5, seconds=1))
    c2 = make_candle(timestamp=t2, retrieval_timestamp=t2 + timedelta(minutes=5, seconds=1))

    # Sequence has malformed element at index 1: [c0 (09:15), None, c2 (09:30)]
    result = validate_candle_sequence([c0, None, c2], expected_interval=CandleInterval.M5)
    assert result.is_valid is False

    # Verify MALFORMED_CANDLE reports index 1
    malformed_issues = [i for i in result.issues if i.code == DataQualityErrorCode.MALFORMED_CANDLE]
    assert len(malformed_issues) >= 1
    assert malformed_issues[0].details.get("index") == 1

    # Verify that sequence validation does NOT bridge across malformed element at index 1
    gap_issues = [i for i in result.issues if i.code == DataQualityErrorCode.MISSING_INTERVAL]
    assert len(gap_issues) == 0


def test_timezone_implementation_raising_exception_in_utcoffset() -> None:
    """Verify check_timezone_awareness captures tzinfo raising exceptions without crashing."""
    from datetime import tzinfo

    class CrashingTz(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("Corrupt timezone calculation")

        def tzname(self, dt):
            return "CRASH"

        def dst(self, dt):
            return timedelta(0)

    dt_crashing = datetime(2026, 11, 2, 9, 15, tzinfo=CrashingTz())
    issues = check_timezone_awareness(dt_crashing)
    assert len(issues) == 1
    assert issues[0].code == DataQualityErrorCode.NAIVE_TIMESTAMP
    assert "Corrupt timezone calculation" in issues[0].message


# ============================================================================
# Granular Helper Functions
# ============================================================================


def test_granular_helpers() -> None:
    assert check_price_positivity(Decimal(10), Decimal(12), Decimal(8), Decimal(11)) == []
    assert check_ohlc_relationships(Decimal(10), Decimal(12), Decimal(8), Decimal(11)) == []
    assert check_volume(100) == []
    assert check_timezone_awareness(datetime(2026, 11, 2, 9, 15, tzinfo=IST)) == []

    c = make_candle()
    now = c.close_time + timedelta(seconds=5)
    assert check_timing_and_provenance(c, now=now) == []
    assert check_sequence_consistency([c]) == []
    assert check_duplicate_timestamps([c]) == []
    assert check_sequence_monotonicity([c]) == []
    assert check_missing_intervals([c]) == []
    assert check_sequence_integrity([c]) == []
    assert check_staleness(c.timestamp, now, timedelta(hours=1)) == []


def test_validation_result_comprehensive_validation() -> None:
    """Verify ValidationResult boolean validation, issue tuple conversion, and element type validation."""
    issue = QualityIssue(code=DataQualityErrorCode.NEGATIVE_VOLUME, message="Negative volume")

    # 1. Convert mutable list of issues into an immutable tuple
    res = ValidationResult(is_valid=False, issues=[issue])
    assert isinstance(res.issues, tuple)
    assert len(res.issues) == 1
    assert res.issues[0] == issue

    # 2. Reject non-boolean is_valid
    with pytest.raises(TypeError, match="is_valid must be a bool"):
        ValidationResult(is_valid=1, issues=())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="is_valid must be a bool"):
        ValidationResult(is_valid="True", issues=())  # type: ignore[arg-type]

    # 3. Reject non-QualityIssue elements in issues
    with pytest.raises(TypeError, match="must be QualityIssue instances"):
        ValidationResult(is_valid=False, issues=["not_an_issue"])  # type: ignore[list-item]

    # 4. Prevent contradictions between is_valid and issues
    with pytest.raises(ValueError, match="Contradictory ValidationResult: is_valid is True"):
        ValidationResult(is_valid=True, issues=(issue,))

    with pytest.raises(ValueError, match="Contradictory ValidationResult: is_valid is False"):
        ValidationResult(is_valid=False, issues=())


def test_expected_interval_validation() -> None:
    """Verify type and positive duration validation for expected_interval."""
    c = make_candle()

    # Reject invalid types with TypeError
    with pytest.raises(TypeError, match="expected_interval must be CandleInterval, timedelta, or None"):
        validate_candle_sequence([c], expected_interval="5m")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected_interval must be CandleInterval, timedelta, or None"):
        validate_candle_sequence([c], expected_interval=300)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected_interval must be CandleInterval, timedelta, or None"):
        check_missing_intervals([c], expected_interval="1h")  # type: ignore[arg-type]

    # Reject non-positive timedelta with ValueError
    with pytest.raises(ValueError, match="expected_interval duration must be strictly positive"):
        validate_candle_sequence([c], expected_interval=timedelta(0))

    with pytest.raises(ValueError, match="expected_interval duration must be strictly positive"):
        validate_candle_sequence([c], expected_interval=timedelta(minutes=-5))

    with pytest.raises(ValueError, match="expected_interval duration must be strictly positive"):
        check_missing_intervals([c], expected_interval=timedelta(seconds=-1))


def test_check_candle_structure_field_types() -> None:
    """Verify check_candle_structure detects invalid field types across all candle attributes."""
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)

    class CustomCandle:
        def __init__(self, **kwargs):
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal(100)
            self.high = Decimal(105)
            self.low = Decimal(95)
            self.close = Decimal(102)
            self.volume = 1000
            self.timestamp = open_time
            self.source = "ZERODHA"
            self.retrieval_timestamp = close_time + timedelta(seconds=1)
            for k, v in kwargs.items():
                setattr(self, k, v)

    # Empty symbol or non-string symbol
    issues = check_candle_structure(CustomCandle(symbol=""))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "symbol" for i in issues)

    issues = check_candle_structure(CustomCandle(symbol=123))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "symbol" for i in issues)

    # Invalid exchange
    issues = check_candle_structure(CustomCandle(exchange="INVALID_EXCHANGE"))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "exchange" for i in issues)

    # Invalid interval
    issues = check_candle_structure(CustomCandle(interval="invalid_interval"))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "interval" for i in issues)

    # Float price or boolean price
    issues = check_candle_structure(CustomCandle(open=100.5))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "open" for i in issues)

    issues = check_candle_structure(CustomCandle(high=True))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "high" for i in issues)

    # Boolean or float volume
    issues = check_candle_structure(CustomCandle(volume=True))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "volume" for i in issues)

    issues = check_candle_structure(CustomCandle(volume=100.5))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "volume" for i in issues)

    # String timestamp
    issues = check_candle_structure(CustomCandle(timestamp="2026-11-02 09:15:00"))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "timestamp" for i in issues)

    # String retrieval_timestamp
    issues = check_candle_structure(CustomCandle(retrieval_timestamp="2026-11-02 09:20:01"))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "retrieval_timestamp" for i in issues)

    # Non-string source
    issues = check_candle_structure(CustomCandle(source=123))
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("field") == "source" for i in issues)


def test_timing_and_provenance_emits_malformed_on_missing_fields() -> None:
    """Verify check_timing_and_provenance emits MALFORMED_CANDLE when fields are missing (never [])."""
    class BareObject:
        pass

    issues = check_timing_and_provenance(BareObject())
    assert len(issues) > 0
    assert all(i.code == DataQualityErrorCode.MALFORMED_CANDLE for i in issues)


# ============================================================================
# Consolidated M2a Remediation Regression Tests
# ============================================================================


def test_check_gaps_false_disables_gap_detection_while_retaining_other_checks() -> None:
    """Verify check_gaps=False suppresses MISSING_INTERVAL while keeping other validation active."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 35, tzinfo=IST)  # Missing 09:20, 09:25, 09:30

    c0 = make_candle(timestamp=t0, retrieval_timestamp=t0 + timedelta(minutes=5, seconds=1))
    c1 = make_candle(timestamp=t1, retrieval_timestamp=t1 + timedelta(minutes=5, seconds=1))

    # 1. With check_gaps=True: reports MISSING_INTERVAL
    res_with_gaps = validate_candle_sequence([c0, c1], expected_interval=CandleInterval.M5, check_gaps=True)
    assert res_with_gaps.is_valid is False
    assert res_with_gaps.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 2. With check_gaps=False: suppresses MISSING_INTERVAL completely
    res_no_gaps = validate_candle_sequence([c0, c1], expected_interval=CandleInterval.M5, check_gaps=False)
    assert res_no_gaps.is_valid is True
    assert not res_no_gaps.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 3. Other validation (e.g. duplicate or out-of-order) still operates when check_gaps=False
    c_dup = make_candle(timestamp=t0, retrieval_timestamp=t0 + timedelta(minutes=5, seconds=1))
    res_dup_no_gaps = validate_candle_sequence([c0, c_dup], expected_interval=CandleInterval.M5, check_gaps=False)
    assert res_dup_no_gaps.is_valid is False
    assert res_dup_no_gaps.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)

    # 4. Monotonicity validation still operates when check_gaps=False
    t_earlier = datetime(2026, 11, 2, 9, 10, tzinfo=IST)
    c_out_of_order = make_candle(timestamp=t_earlier, retrieval_timestamp=t_earlier + timedelta(minutes=5, seconds=1))
    res_mono_no_gaps = validate_candle_sequence([c0, c_out_of_order], expected_interval=CandleInterval.M5, check_gaps=False)
    assert res_mono_no_gaps.is_valid is False
    assert res_mono_no_gaps.has_error(DataQualityErrorCode.NON_MONOTONIC_SEQUENCE)


def test_timezone_exception_safety_in_sequence_validation_functions() -> None:
    """Verify custom/malformed tzinfo implementations never raise uncaught exceptions across validation paths."""
    from datetime import tzinfo

    class CrashingValueErrorTz(tzinfo):
        def utcoffset(self, dt):
            raise ValueError("Corrupt offset calculation")

        def tzname(self, dt):
            return "CRASH_VAL"

        def dst(self, dt):
            return timedelta(0)

    class CrashingRuntimeErrorTz(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("Unexpected timezone engine fault")

        def tzname(self, dt):
            return "CRASH_RT"

        def dst(self, dt):
            return timedelta(0)

    t_val_err = datetime(2026, 11, 2, 9, 15, tzinfo=CrashingValueErrorTz())
    t_rt_err = datetime(2026, 11, 2, 9, 20, tzinfo=CrashingRuntimeErrorTz())

    class DuckCandle:
        def __init__(self, ts):
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal(100)
            self.high = Decimal(110)
            self.low = Decimal(90)
            self.close = Decimal(105)
            self.volume = 1000
            self.source = "TEST"
            self.timestamp = ts
            self.retrieval_timestamp = ts
            self.open_time = ts
            self.close_time = ts

    candles = [DuckCandle(t_val_err), DuckCandle(t_rt_err)]

    # None of these public sequence-validation functions may raise an uncaught exception
    res_dup = check_duplicate_timestamps(candles)
    assert isinstance(res_dup, list)

    res_mono = check_sequence_monotonicity(candles)
    assert isinstance(res_mono, list)

    res_miss = check_missing_intervals(candles)
    assert isinstance(res_miss, list)

    res_integ = check_sequence_integrity(candles)
    assert isinstance(res_integ, list)

    res_cons = check_sequence_consistency(candles)
    assert isinstance(res_cons, list)

    now_valid = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    res_stale = check_staleness(t_val_err, now_valid, timedelta(hours=1))
    assert len(res_stale) == 1
    assert res_stale[0].code == DataQualityErrorCode.NAIVE_TIMESTAMP

    res_seq = validate_candle_sequence(candles)
    assert res_seq.is_valid is False
    assert res_seq.has_error(DataQualityErrorCode.NAIVE_TIMESTAMP)


def test_validate_now_and_staleness_comprehensive() -> None:
    """Verify _validate_now_and_staleness strictly validates now and max_staleness types and boundaries."""
    from datetime import tzinfo

    from agentic_trading.market_data.quality import _validate_now_and_staleness

    class CrashingTz(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("Crash")

        def tzname(self, dt):
            return "CRASH"

        def dst(self, dt):
            return timedelta(0)

    # 1. Non-datetime now
    for bad_now in ["2026-11-02T09:30:00Z", 1234567890, True, 123.45]:
        with pytest.raises(TypeError, match="'now' must be a datetime instance"):
            _validate_now_and_staleness(bad_now, None)

    # 2. Naive datetime now
    with pytest.raises(ValueError, match="Injected 'now' parameter must be timezone-aware"):
        _validate_now_and_staleness(datetime(2026, 11, 2, 9, 30), None)

    # 3. Crashing tzinfo now
    with pytest.raises(ValueError, match="timezone calculation failed"):
        _validate_now_and_staleness(datetime(2026, 11, 2, 9, 30, tzinfo=CrashingTz()), None)

    # 4. Non-timedelta max_staleness
    good_now = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    for bad_staleness in [300, "15m", True, 15.5]:
        with pytest.raises(TypeError, match="'max_staleness' must be a timedelta instance"):
            _validate_now_and_staleness(good_now, bad_staleness)

    # 5. Negative max_staleness
    with pytest.raises(ValueError, match="'max_staleness' must be a non-negative timedelta"):
        _validate_now_and_staleness(good_now, timedelta(seconds=-1))

    # 6. Valid parameters pass cleanly
    _validate_now_and_staleness(good_now, timedelta(minutes=15))
    _validate_now_and_staleness(None, None)


def test_generator_input_in_all_sequence_functions() -> None:
    """Verify all sequence validation functions accept single-use generator inputs without crash."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)

    def make_gen():
        return (
            make_candle(
                timestamp=t0 + timedelta(minutes=5 * i),
                retrieval_timestamp=t0 + timedelta(minutes=5 * i + 5, seconds=1),
            )
            for i in range(3)
        )

    assert isinstance(check_duplicate_timestamps(make_gen()), list)
    assert isinstance(check_sequence_monotonicity(make_gen()), list)
    assert isinstance(check_missing_intervals(make_gen(), expected_interval=CandleInterval.M5), list)
    assert isinstance(check_sequence_integrity(make_gen(), expected_interval=CandleInterval.M5), list)
    assert isinstance(check_sequence_consistency(make_gen()), list)

    now = t0 + timedelta(minutes=20)
    res = validate_candle_sequence(make_gen(), now=now, expected_interval=CandleInterval.M5)
    assert res.is_valid is True


def test_malformed_interval_inference_does_not_crash() -> None:
    """Verify sequence validation with malformed interval values does not raise TypeError or crash."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    class BadIntervalCandle:
        def __init__(self, ts, interval_val):
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = interval_val
            self.open = Decimal(100)
            self.high = Decimal(110)
            self.low = Decimal(90)
            self.close = Decimal(105)
            self.volume = 1000
            self.source = "TEST"
            self.timestamp = ts
            self.retrieval_timestamp = ts + timedelta(minutes=5, seconds=1)
            self.open_time = ts
            self.close_time = ts + timedelta(minutes=5)

    # 1. Non-enum interval string
    c1 = BadIntervalCandle(t0, "bad_interval")
    c2 = BadIntervalCandle(t1, "bad_interval")
    res1 = validate_candle_sequence([c1, c2])
    assert res1.is_valid is False
    assert res1.has_error(DataQualityErrorCode.MALFORMED_CANDLE)

    # 2. Integer interval
    c3 = BadIntervalCandle(t0, 300)
    c4 = BadIntervalCandle(t1, 300)
    res2 = validate_candle_sequence([c3, c4])
    assert res2.is_valid is False
    assert res2.has_error(DataQualityErrorCode.MALFORMED_CANDLE)


def test_quality_issue_and_validation_result_immutability_and_serialization() -> None:
    """Verify QualityIssue argument validation, deep immutability, pickle serialization, and asdict."""
    import copy
    import pickle

    # 1. Constructor type validation
    with pytest.raises(TypeError, match="code must be DataQualityErrorCode or str"):
        QualityIssue(code=123, message="msg")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Invalid code string"):
        QualityIssue(code="NON_EXISTENT_CODE", message="msg")

    with pytest.raises(TypeError, match="message must be a str"):
        QualityIssue(code=DataQualityErrorCode.NON_POSITIVE_PRICE, message=123)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="symbol must be a str"):
        QualityIssue(code=DataQualityErrorCode.NON_POSITIVE_PRICE, message="msg", symbol=123)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="timestamp must be a datetime or None"):
        QualityIssue(code=DataQualityErrorCode.NON_POSITIVE_PRICE, message="msg", timestamp="2026-11-02")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="details must be a Mapping"):
        QualityIssue(code=DataQualityErrorCode.NON_POSITIVE_PRICE, message="msg", details=["not", "mapping"])  # type: ignore[arg-type]

    # 2. Deep immutability of nested structures
    issue = QualityIssue(
        code=DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA,
        message="Conflicting duplicate",
        details={
            "nested_dict": {"k": "v"},
            "nested_list": [1, [2, 3]],
            "nested_set": {"a", "b"},
        },
    )
    with pytest.raises(TypeError):
        issue.details["nested_dict"]["k"] = "mutated"  # type: ignore[index]

    with pytest.raises(AttributeError):
        issue.details["nested_list"].append(4)  # type: ignore[union-attr]

    # 3. Pickle serialization and deserialization preserves deep immutability
    pickled = pickle.dumps(issue)
    unpickled = pickle.loads(pickled)
    assert unpickled.code == issue.code
    assert unpickled.message == issue.message
    assert isinstance(unpickled.details["nested_dict"], MappingProxyType)
    with pytest.raises(TypeError):
        unpickled.details["nested_dict"]["k"] = "mutated"  # type: ignore[index]

    # 4. to_dict works on QualityIssue and ValidationResult preserving useful serialization without global side effects
    res = ValidationResult(is_valid=False, issues=(issue,))
    d_issue = issue.to_dict()
    d_res = res.to_dict()
    assert d_issue["code"] == DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA.value
    assert d_res["is_valid"] is False
    assert isinstance(d_issue["details"], dict)
    assert isinstance(d_issue["details"]["nested_dict"], dict)

    # 5. copy.deepcopy works on QualityIssue and ValidationResult
    issue_copy = copy.deepcopy(issue)
    assert issue_copy.code == issue.code
    assert issue_copy.details["nested_dict"]["k"] == "v"
    res_copy = copy.deepcopy(res)
    assert res_copy.is_valid is False
    assert len(res_copy.issues) == 1


def test_malformed_middle_element_does_not_bridge_in_sequence_validation() -> None:
    """Verify sequence validation functions report MALFORMED_CANDLE and do not bridge across invalid element."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    c0 = make_candle(timestamp=t0, retrieval_timestamp=t0 + timedelta(minutes=5, seconds=1))
    c2 = make_candle(timestamp=t2, retrieval_timestamp=t2 + timedelta(minutes=5, seconds=1))
    malformed_candle = "not_a_candle"

    seq = [c0, malformed_candle, c2]

    # Monotonicity check does not bridge across index 1
    mono_issues = check_sequence_monotonicity(seq)
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("index") == 1 for i in mono_issues)
    assert not any(i.code == DataQualityErrorCode.NON_MONOTONIC_SEQUENCE for i in mono_issues)

    # Missing intervals check does not bridge across index 1
    miss_issues = check_missing_intervals(seq, expected_interval=CandleInterval.M5)
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("index") == 1 for i in miss_issues)
    assert not any(i.code == DataQualityErrorCode.MISSING_INTERVAL for i in miss_issues)

    # Duplicate timestamps check reports structural defect at index 1
    dup_issues = check_duplicate_timestamps(seq)
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("index") == 1 for i in dup_issues)

    # Consistency check reports structural defect at index 1
    cons_issues = check_sequence_consistency(seq)
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("index") == 1 for i in cons_issues)

    # validate_candle_sequence aggregates correctly with index 1 flagged
    res = validate_candle_sequence(seq, expected_interval=CandleInterval.M5)
    assert res.is_valid is False
    assert any(i.code == DataQualityErrorCode.MALFORMED_CANDLE and i.details.get("index") == 1 for i in res.issues)
    assert not res.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_unstable_tzinfo_raising_on_subsequent_operations() -> None:
    """Verify unstable tzinfo raising during arithmetic/comparisons produces structured errors."""
    from datetime import tzinfo

    class UnstableTz(tzinfo):
        def __init__(self) -> None:
            self._call_count = 0

        def utcoffset(self, dt: object) -> timedelta | None:
            self._call_count += 1
            # Initial calls for _is_tz_valid succeed, subsequent calls during math/comparison raise
            if self._call_count > 2:
                raise RuntimeError("Unstable timezone failure during calculation")
            return timedelta(hours=5, minutes=30)

        def dst(self, dt: object) -> timedelta:
            return timedelta(0)

        def tzname(self, dt: object) -> str:
            return "UNSTABLE"

    class DuckUnstableCandle:
        def __init__(self, ts: datetime) -> None:
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal(100)
            self.high = Decimal(110)
            self.low = Decimal(90)
            self.close = Decimal(105)
            self.volume = 1000
            self.source = "TEST"
            self.timestamp = ts
            self.retrieval_timestamp = ts + timedelta(minutes=5, seconds=1)
            self.open_time = ts
            self.close_time = ts + timedelta(minutes=5)

    ts1 = datetime(2026, 11, 2, 9, 15, tzinfo=UnstableTz())
    ts2 = datetime(2026, 11, 2, 9, 20, tzinfo=UnstableTz())
    c1 = DuckUnstableCandle(ts1)
    c2 = DuckUnstableCandle(ts2)

    # check_timing_and_provenance with reference now
    now = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    issues_timing = check_timing_and_provenance(c1, now=now)
    assert isinstance(issues_timing, list)

    # Sequence validation functions must return structured issues, not uncaught exceptions
    issues_miss = check_missing_intervals([c1, c2], expected_interval=CandleInterval.M5)
    assert isinstance(issues_miss, list)

    issues_mono = check_sequence_monotonicity([c1, c2])
    assert isinstance(issues_mono, list)

    issues_dup = check_duplicate_timestamps([c1, c2])
    assert isinstance(issues_dup, list)

    res_seq = validate_candle_sequence([c1, c2], expected_interval=CandleInterval.M5)
    assert isinstance(res_seq, ValidationResult)
    assert res_seq.is_valid is False


def test_deep_freeze_rejects_unsupported_mutable_types() -> None:
    """Verify QualityIssue.details explicitly rejects unsupported mutable types with TypeError."""
    class CustomMutable:
        def __init__(self) -> None:
            self.data = [1, 2, 3]

    with pytest.raises(TypeError, match="Unsupported mutable or unhandled type in QualityIssue.details"):
        QualityIssue(
            code=DataQualityErrorCode.MALFORMED_CANDLE,
            message="Test custom mutable object",
            details={"bad_object": CustomMutable()},
        )

    with pytest.raises(TypeError, match="Unsupported mutable or unhandled type in QualityIssue.details"):
        QualityIssue(
            code=DataQualityErrorCode.MALFORMED_CANDLE,
            message="Test bytearray",
            details={"bad_bytes": bytearray(b"mutable bytes")},
        )
