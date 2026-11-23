"""Integration tests for the market data pipeline and quality gate.

Validates end-to-end integration across:
1. Valid NSE data (structural, timing, provenance, and quality checks).
2. Stale market data (fail-closed detection and reporting).
3. Malformed data (missing fields, invalid prices, invalid volume, naive timestamps).
4. Duplicate data (distinguishing identical vs conflicting duplicates).
5. Sequence integrity (ordering, missing intervals, malformed non-bridging).
6. Provenance (source verification, retrieval vs close causality).
7. Risk-engine isolation and architectural integration gap documentation.

Safety Rules:
- Deterministic, synthetic NSE equity market data only.
- Explicit reference timestamps (no system clock dependencies).
- Zero network or broker connections.
- Zero mutations to production code or existing unit tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from agentic_trading.market_data import (
    IST,
    Candle,
    CandleInterval,
    DataQualityErrorCode,
    Exchange,
    ValidationResult,
    check_candle_structure,
    check_duplicate_timestamps,
    check_missing_intervals,
    check_sequence_monotonicity,
    validate_candle,
    validate_candle_sequence,
)
from agentic_trading.risk_engine import OrderProposal, RiskDecision, Side, evaluate_order


def _build_synthetic_nse_candle(
    symbol: str = "RELIANCE",
    interval: CandleInterval = CandleInterval.M5,
    timestamp: datetime | None = None,
    open_price: Decimal = Decimal("2500.00"),
    high_price: Decimal = Decimal("2515.50"),
    low_price: Decimal = Decimal("2495.00"),
    close_price: Decimal = Decimal("2510.25"),
    volume: int = 150000,
    source: str = "NSE_FEED_SYNTHETIC",
    retrieval_delay: timedelta = timedelta(seconds=2),
    **overrides: Any,
) -> Candle:
    """Construct a canonical, timezone-aware NSE equity candle with explicit provenance."""
    ts = timestamp or datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_ts = ts + interval.duration
    kwargs: dict[str, Any] = {
        "symbol": symbol,
        "exchange": Exchange.NSE,
        "interval": interval,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "timestamp": ts,
        "source": source,
        "retrieval_timestamp": close_ts + retrieval_delay,
    }
    kwargs.update(overrides)
    return Candle(**kwargs)


# ============================================================================
# Scenario 1: VALID NSE DATA
# ============================================================================


def test_valid_nse_candle_pipeline_passes_all_checks() -> None:
    """Confirm realistic, timezone-aware NSE candles pass all quality gate checks."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = _build_synthetic_nse_candle(
        symbol="RELIANCE",
        timestamp=t0,
        open_price=Decimal("2480.00"),
        high_price=Decimal("2495.50"),
        low_price=Decimal("2475.25"),
        close_price=Decimal("2490.00"),
        volume=125000,
        source="NSE_SYNTHETIC_FEED",
    )

    # Reference time is after candle close (09:20) and retrieval (09:20:02)
    pipeline_now = t0 + timedelta(minutes=6)
    result = validate_candle(candle, now=pipeline_now, max_staleness=timedelta(minutes=15))

    assert result.is_valid is True
    assert len(result.issues) == 0
    assert result.error_codes == ()

    # Verify structural integrity helper directly
    structural_issues = check_candle_structure(candle)
    assert len(structural_issues) == 0


def test_valid_nse_multi_candle_sequence_pipeline() -> None:
    """Confirm a continuous sequence of valid NSE 5m candles passes sequence validation."""
    t_start = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candles = [
        _build_synthetic_nse_candle(
            symbol="TCS",
            timestamp=t_start + timedelta(minutes=5 * i),
            open_price=Decimal("3500.00") + Decimal(i * 2),
            high_price=Decimal("3510.00") + Decimal(i * 2),
            low_price=Decimal("3495.00") + Decimal(i * 2),
            close_price=Decimal("3505.00") + Decimal(i * 2),
            volume=50000 + (i * 1000),
            source="NSE_SYNTHETIC_FEED",
        )
        for i in range(6)
    ]

    pipeline_now = t_start + timedelta(minutes=35)
    result = validate_candle_sequence(
        candles,
        expected_interval=CandleInterval.M5,
        now=pipeline_now,
        max_staleness=timedelta(minutes=30),
    )

    assert result.is_valid is True
    assert len(result.issues) == 0
    assert result.error_codes == ()


# ============================================================================
# Scenario 2: STALE MARKET DATA
# ============================================================================


def test_stale_market_data_fails_closed() -> None:
    """Confirm market data exceeding maximum allowed staleness fails closed."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = _build_synthetic_nse_candle(
        symbol="INFY",
        timestamp=t0,
        interval=CandleInterval.M5,  # Closes at 09:20:00 IST
    )

    # Pipeline time is 09:35:00 IST (15 minutes after close) with 5-minute max staleness
    staleness_limit = timedelta(minutes=5)
    pipeline_now = t0 + timedelta(minutes=20)

    result = validate_candle(candle, now=pipeline_now, max_staleness=staleness_limit)

    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.STALE_DATA)

    stale_issues = result.get_issues_by_code(DataQualityErrorCode.STALE_DATA)
    assert len(stale_issues) == 1
    issue = stale_issues[0]
    assert issue.details["close_time"] == "2026-11-02T09:20:00+05:30"
    assert issue.details["age_seconds"] == 900.0  # 15 minutes = 900s
    assert issue.details["max_staleness_seconds"] == 300.0  # 5 minutes = 300s


# ============================================================================
# Scenario 3: MALFORMED DATA
# ============================================================================


def test_malformed_market_data_structural_defects_fail_closed() -> None:
    """Confirm missing required fields produce structured MALFORMED_CANDLE issues."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)

    class IncompleteCandle:
        def __init__(self) -> None:
            self.symbol = "HDFCBANK"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal("1600.00")
            # Missing: high, low, close, volume, timestamp, source, retrieval_timestamp

    incomplete = IncompleteCandle()
    issues = check_candle_structure(incomplete)
    assert len(issues) >= 5

    missing_fields = {iss.details.get("missing_field") for iss in issues}
    assert "high" in missing_fields
    assert "low" in missing_fields
    assert "close" in missing_fields
    assert "volume" in missing_fields
    assert "source" in missing_fields

    # validate_candle must fail closed without uncaught AttributeError
    pipeline_now = t0 + timedelta(minutes=10)
    result = validate_candle(incomplete, now=pipeline_now)
    assert result.is_valid is False
    assert result.has_error(DataQualityErrorCode.MALFORMED_CANDLE)


def test_malformed_market_data_invalid_numeric_values_fail_closed() -> None:
    """Confirm invalid prices, non-finite values, and invalid volumes produce structured issues."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    pipeline_now = t0 + timedelta(minutes=10)

    # 1. Non-positive price
    candle_zero_price = _build_synthetic_nse_candle(
        timestamp=t0,
        open_price=Decimal("0.00"),
    )
    res_zero = validate_candle(candle_zero_price, now=pipeline_now)
    assert res_zero.is_valid is False
    assert res_zero.has_error(DataQualityErrorCode.NON_POSITIVE_PRICE)

    # 2. Inverted OHLC relationship (high < low)
    candle_bad_ohlc = _build_synthetic_nse_candle(
        timestamp=t0,
        open_price=Decimal("2500.00"),
        high_price=Decimal("2450.00"),  # High lower than low
        low_price=Decimal("2490.00"),
        close_price=Decimal("2480.00"),
    )
    res_ohlc = validate_candle(candle_bad_ohlc, now=pipeline_now)
    assert res_ohlc.is_valid is False
    assert res_ohlc.has_error(DataQualityErrorCode.HIGH_LESS_THAN_LOW)

    # 3. Negative volume
    candle_neg_vol = _build_synthetic_nse_candle(
        timestamp=t0,
        volume=-500,
    )
    res_vol = validate_candle(candle_neg_vol, now=pipeline_now)
    assert res_vol.is_valid is False
    assert res_vol.has_error(DataQualityErrorCode.NEGATIVE_VOLUME)

    # 4. Naive timestamp without timezone handled fail-closed
    # A. Model constructor strictly rejects naive timestamp with ValueError
    import pytest

    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        _build_synthetic_nse_candle(
            timestamp=datetime(2026, 11, 2, 9, 15),  # naive
        )

    # B. Duck-typed feed input with naive timestamp is caught by validate_candle
    class NaiveCandle:
        def __init__(self) -> None:
            self.symbol = "RELIANCE"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal("2500.00")
            self.high = Decimal("2510.00")
            self.low = Decimal("2490.00")
            self.close = Decimal("2505.00")
            self.volume = 1000
            self.timestamp = datetime(2026, 11, 2, 9, 15)  # naive!
            self.source = "FEED"
            self.retrieval_timestamp = datetime(2026, 11, 2, 9, 21, tzinfo=IST)
            self.open_time = datetime(2026, 11, 2, 9, 15)
            self.close_time = datetime(2026, 11, 2, 9, 20)

    res_naive = validate_candle(NaiveCandle(), now=pipeline_now)
    assert res_naive.is_valid is False
    assert res_naive.has_error(DataQualityErrorCode.NAIVE_TIMESTAMP)


# ============================================================================
# Scenario 4: DUPLICATE DATA
# ============================================================================


def test_duplicate_candles_distinguishes_identical_vs_conflicting() -> None:
    """Confirm pipeline distinguishes identical duplicate candles from conflicting duplicates."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    c1 = _build_synthetic_nse_candle(timestamp=t0, close_price=Decimal("2500.00"))

    # Identical duplicate (same identity and exact same OHLCV)
    c1_identical = _build_synthetic_nse_candle(timestamp=t0, close_price=Decimal("2500.00"))

    # Conflicting duplicate (same identity, differing OHLCV)
    c1_conflicting = _build_synthetic_nse_candle(timestamp=t0, close_price=Decimal("2520.00"))

    # 1. Identical duplicate check (both granular helper and full sequence validation)
    granular_identical = check_duplicate_timestamps([c1, c1_identical])
    assert any(iss.code == DataQualityErrorCode.DUPLICATE_CANDLE for iss in granular_identical)

    res_identical = validate_candle_sequence([c1, c1_identical])
    assert res_identical.is_valid is False
    assert res_identical.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)
    assert not res_identical.has_error(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)

    # 2. Conflicting duplicate check (both granular helper and full sequence validation)
    granular_conflicting = check_duplicate_timestamps([c1, c1_conflicting])
    assert any(
        iss.code == DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA for iss in granular_conflicting
    )

    res_conflicting = validate_candle_sequence([c1, c1_conflicting])
    assert res_conflicting.is_valid is False
    assert res_conflicting.has_error(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)
    assert not res_conflicting.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)

    issue = res_conflicting.get_issues_by_code(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)[0]
    assert "existing_ohlcv" in issue.details
    assert "conflicting_ohlcv" in issue.details
    assert issue.details["conflicting_ohlcv"]["close"] == "2520.00"


# ============================================================================
# Scenario 5: SEQUENCE INTEGRITY
# ============================================================================


def test_sequence_integrity_ordered_vs_out_of_order_and_gaps() -> None:
    """Confirm detection of out-of-order sequence timestamps and missing intraday intervals."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 25, tzinfo=IST)
    t3 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)

    c0 = _build_synthetic_nse_candle(timestamp=t0)
    c1 = _build_synthetic_nse_candle(timestamp=t1)
    c2 = _build_synthetic_nse_candle(timestamp=t2)
    c3 = _build_synthetic_nse_candle(timestamp=t3)

    # 1. Valid ordered sequence
    res_ordered = validate_candle_sequence([c0, c1, c2, c3], expected_interval=CandleInterval.M5)
    assert res_ordered.is_valid is True

    # 2. Out-of-order sequence (c2 before c1)
    res_ooo = validate_candle_sequence([c0, c2, c1, c3], expected_interval=CandleInterval.M5)
    assert res_ooo.is_valid is False
    assert res_ooo.has_error(DataQualityErrorCode.NON_MONOTONIC_SEQUENCE)

    # 3. Missing interval gap (c0 at 09:15, c3 at 09:30, missing 09:20 and 09:25)
    res_gap = validate_candle_sequence([c0, c3], expected_interval=CandleInterval.M5)
    assert res_gap.is_valid is False
    assert res_gap.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    gap_issue = res_gap.get_issues_by_code(DataQualityErrorCode.MISSING_INTERVAL)[0]
    assert gap_issue.details["estimated_missing_candles"] == 2


def test_sequence_integrity_malformed_middle_element_does_not_bridge() -> None:
    """Confirm a malformed middle element breaks continuity and does not bridge across gaps."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    c0 = _build_synthetic_nse_candle(timestamp=t0)
    c2 = _build_synthetic_nse_candle(timestamp=t2)
    malformed_candle = "corrupt_data_string"

    sequence = [c0, malformed_candle, c2]

    # Granular checks do not bridge across index 1
    mono_issues = check_sequence_monotonicity(sequence)
    assert any(
        iss.code == DataQualityErrorCode.MALFORMED_CANDLE and iss.details.get("index") == 1
        for iss in mono_issues
    )
    assert not any(iss.code == DataQualityErrorCode.NON_MONOTONIC_SEQUENCE for iss in mono_issues)

    miss_issues = check_missing_intervals(sequence, expected_interval=CandleInterval.M5)
    assert any(
        iss.code == DataQualityErrorCode.MALFORMED_CANDLE and iss.details.get("index") == 1
        for iss in miss_issues
    )
    # Crucial invariant: MISSING_INTERVAL must NOT bridge index 0 to index 2 across corrupt element
    assert not any(iss.code == DataQualityErrorCode.MISSING_INTERVAL for iss in miss_issues)

    # Full sequence validation confirms index preservation and no bridging
    result = validate_candle_sequence(sequence, expected_interval=CandleInterval.M5)
    assert result.is_valid is False
    assert any(
        iss.code == DataQualityErrorCode.MALFORMED_CANDLE and iss.details.get("index") == 1
        for iss in result.issues
    )
    assert not result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


# ============================================================================
# Scenario 6: PROVENANCE
# ============================================================================


def test_provenance_validation_missing_or_corrupt_timestamps() -> None:
    """Confirm missing provenance, early retrieval, or future retrieval fails closed."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_close = t0 + timedelta(minutes=5)  # 09:20:00 IST
    pipeline_now = t0 + timedelta(minutes=10)  # 09:25:00 IST

    # 1. Retrieval timestamp earlier than bar close (causality violation)
    candle_early_retrieval = _build_synthetic_nse_candle(
        timestamp=t0,
        retrieval_timestamp=t_close - timedelta(seconds=1),  # 09:19:59
    )
    res_early = validate_candle(candle_early_retrieval, now=pipeline_now)
    assert res_early.is_valid is False
    assert res_early.has_error(DataQualityErrorCode.RETRIEVAL_BEFORE_CLOSE)

    # 2. Retrieval timestamp in future relative to pipeline now
    candle_future_retrieval = _build_synthetic_nse_candle(
        timestamp=t0,
        retrieval_timestamp=pipeline_now + timedelta(minutes=1),
    )
    res_future = validate_candle(candle_future_retrieval, now=pipeline_now)
    assert res_future.is_valid is False
    assert res_future.has_error(DataQualityErrorCode.RETRIEVAL_AFTER_NOW)

    # 3. Missing source provenance attribute
    class NoSourceCandle:
        def __init__(self) -> None:
            self.symbol = "TCS"
            self.exchange = Exchange.NSE
            self.interval = CandleInterval.M5
            self.open = Decimal("3500.00")
            self.high = Decimal("3510.00")
            self.low = Decimal("3495.00")
            self.close = Decimal("3505.00")
            self.volume = 5000
            self.timestamp = t0
            self.retrieval_timestamp = t_close + timedelta(seconds=2)
            # source missing

    res_no_source = validate_candle(NoSourceCandle(), now=pipeline_now)
    assert res_no_source.is_valid is False
    assert res_no_source.has_error(DataQualityErrorCode.MALFORMED_CANDLE)


# ============================================================================
# Scenario 7: RISK-ENGINE ISOLATION & INTEGRATION GAP
# ============================================================================


def test_risk_engine_isolation_and_integration_gap() -> None:
    """Verify market data quality gating protects risk decisions, and document integration gap.

    Integration Gap Analysis:
    - Currently, `OrderProposal` in `src/agentic_trading/risk_engine.py` accepts scalar
      primitives (symbol: str, side: Side, quantity: int, limit_price: Decimal, ...).
    - There is NO existing adapter or interface connecting `Candle` or `ValidationResult`
      directly to `OrderProposal`.
    - This architectural boundary intentionally decouples the market-data quality gate
      from order risk evaluation at Milestone 2a.
    - Here we verify:
      1. A pipeline workflow pattern: unvalidated market data must be gated by `validate_candle`.
      2. If invalid market data is rejected, order creation cannot proceed.
      3. If corrupt prices bypass validation, the risk engine itself fails closed.
    """
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    pipeline_now = t0 + timedelta(minutes=10)

    # Pipeline gating helper mimicking a safe trading agent order workflow
    def propose_buy_order_from_market_data(
        candle: Any,
        quantity: int,
        cash: Decimal,
        equity: Decimal,
        now: datetime,
    ) -> tuple[ValidationResult, RiskDecision | None]:
        # Step 1: Market data quality gate
        val_result = validate_candle(candle, now=now, max_staleness=timedelta(minutes=10))
        if not val_result.is_valid:
            # Gating invariant: invalid market data cannot produce an order proposal
            return val_result, None

        # Step 2: Construct OrderProposal using validated candle close price
        proposal = OrderProposal(
            symbol=candle.symbol,
            side=Side.BUY,
            quantity=quantity,
            limit_price=candle.close,
            available_cash=cash,
            portfolio_equity=equity,
        )

        # Step 3: Evaluate risk
        decision = evaluate_order(proposal)
        return val_result, decision

    # Case A: Valid candle flows through quality gate to approved risk decision
    valid_candle = _build_synthetic_nse_candle(
        symbol="RELIANCE",
        timestamp=t0,
        open_price=Decimal("248.00"),
        high_price=Decimal("252.00"),
        low_price=Decimal("245.00"),
        close_price=Decimal("250.00"),
    )
    val_res_ok, decision_ok = propose_buy_order_from_market_data(
        valid_candle,
        quantity=2,
        cash=Decimal("10000.00"),
        equity=Decimal("10000.00"),
        now=pipeline_now,
    )
    assert val_res_ok.is_valid is True
    assert decision_ok is not None
    assert decision_ok.approved is True
    assert decision_ok.order_notional == Decimal("500.00")

    # Case B: Stale candle is halted at quality gate; no proposal reaches risk engine
    stale_candle = _build_synthetic_nse_candle(
        symbol="RELIANCE",
        timestamp=t0,
        open_price=Decimal("248.00"),
        high_price=Decimal("252.00"),
        low_price=Decimal("245.00"),
        close_price=Decimal("250.00"),
    )
    late_now = t0 + timedelta(hours=2)  # Stale
    val_res_stale, decision_stale = propose_buy_order_from_market_data(
        stale_candle,
        quantity=2,
        cash=Decimal("10000.00"),
        equity=Decimal("10000.00"),
        now=late_now,
    )
    assert val_res_stale.is_valid is False
    assert val_res_stale.has_error(DataQualityErrorCode.STALE_DATA)
    assert decision_stale is None  # Halted before risk engine

    # Case C: Defense-in-depth: if corrupt data bypasses the gate, risk engine fails closed
    proposal_zero_price = OrderProposal(
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=2,
        limit_price=Decimal("0.00"),  # Corrupt price
        available_cash=Decimal("10000.00"),
        portfolio_equity=Decimal("10000.00"),
    )
    decision_zero = evaluate_order(proposal_zero_price)
    assert decision_zero.approved is False
    assert "INVALID_PRICE" in decision_zero.reason_codes

    proposal_nan_price = OrderProposal(
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=2,
        limit_price=Decimal("NaN"),  # Corrupt non-finite price
        available_cash=Decimal("10000.00"),
        portfolio_equity=Decimal("10000.00"),
    )
    decision_nan = evaluate_order(proposal_nan_price)
    assert decision_nan.approved is False
    assert "INVALID_NUMERIC_INPUT" in decision_nan.reason_codes
