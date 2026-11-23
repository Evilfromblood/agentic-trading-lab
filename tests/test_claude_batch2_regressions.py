"""Adversarial regression test suite verifying M2b Remediation Batch 2.

Addresses all findings from Claude B's independent audit report:
- Priority 1: Exchange & session architecture (H-1, COV-05, COV-07, COV-09).
- Priority 2: Fail-closed historical coverage & partial data (H-2, COV-01).
- Priority 3: Deep freeze memo identity, node budget, and depth bounding (H-3, M-1).
- Priority 4: Exchange calendar evidence, weekend/holiday spans, sparse data (M-2, COV-03, COV-08).
- Priority 5: Result-object invariants (M-4, ARCH-03).
- Priority 6: Paper-only broker boundaries (SEC-01).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentic_trading.market_data import (
    IST,
    US_EASTERN,
    Candle,
    CandleInterval,
    CoverageStatus,
    DataQualityErrorCode,
    Exchange,
    ExchangeCalendar,
    ExchangeSession,
    HistoricalDataRequest,
    IngestionResult,
    MarketDataIngestionPipeline,
    QualityIssue,
    SequenceIngestionResult,
    SyntheticMarketDataProvider,
    ValidationResult,
    validate_candle,
)
from agentic_trading.market_data.models import _deep_freeze, _USEasternFallback


def _build_batch2_record(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    interval: str = "5m",
    timestamp: str = "2026-11-02T09:15:00+05:30",
    open_price: str = "2500.00",
    high_price: str = "2515.00",
    low_price: str = "2495.00",
    close_price: str = "2510.00",
    volume: int = 50000,
    source: str = "SYNTHETIC_NSE",
    **overrides: Any,
) -> dict[str, Any]:
    """Helper to construct valid raw provider dictionary records with matching provenance."""
    rec: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "timestamp": timestamp,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "source": source,
    }
    rec.update(overrides)
    return rec


# ============================================================================
# Priority 1: Exchange and Session Architecture (H-1, COV-05, COV-07, COV-09)
# ============================================================================


def test_priority1_exchange_enum_supports_nyse_nasdaq() -> None:
    """Verify Exchange supports NSE, BSE, NYSE, and NASDAQ with case-insensitive normalization."""
    assert Exchange.NSE.value == "NSE"
    assert Exchange.BSE.value == "BSE"
    assert Exchange.NYSE.value == "NYSE"
    assert Exchange.NASDAQ.value == "NASDAQ"

    assert Exchange("nyse") == Exchange.NYSE
    assert Exchange("nasdaq") == Exchange.NASDAQ
    assert Exchange("NSE") == Exchange.NSE

    with pytest.raises(ValueError, match="is not a valid Exchange"):
        Exchange("LSE")


def test_priority1_us_eastern_session_resolution() -> None:
    """Verify ExchangeSession resolves US Eastern timezone and hours for NYSE and NASDAQ."""
    session_nyse = ExchangeSession.for_exchange(Exchange.NYSE)
    assert session_nyse.exchange == Exchange.NYSE
    assert session_nyse.session_open == time(9, 30)
    assert session_nyse.session_close == time(16, 0)
    assert session_nyse.timezone == US_EASTERN

    session_nasdaq = ExchangeSession.for_exchange(Exchange.NASDAQ)
    assert session_nasdaq.exchange == Exchange.NASDAQ
    assert session_nasdaq.session_open == time(9, 30)
    assert session_nasdaq.session_close == time(16, 0)


def test_priority1_us_eastern_dst_transition_rules() -> None:
    """Verify deterministic US Eastern DST transition rules (Energy Policy Act of 2005)."""
    tz = _USEasternFallback()

    # 1. Spring forward 2026: 2nd Sunday in March (March 8, 2026)
    # 01:59 EST is UTC-5
    dt_winter = datetime(2026, 3, 8, 1, 59, tzinfo=tz)
    assert tz.utcoffset(dt_winter) == timedelta(hours=-5)
    assert tz.tzname(dt_winter) == "EST"

    # 03:00 EDT is UTC-4
    dt_summer = datetime(2026, 3, 8, 3, 0, tzinfo=tz)
    assert tz.utcoffset(dt_summer) == timedelta(hours=-4)
    assert tz.tzname(dt_summer) == "EDT"

    # 2. Fall back 2026: 1st Sunday in November (November 1, 2026)
    dt_summer_end = datetime(2026, 11, 1, 0, 59, tzinfo=tz)
    assert tz.utcoffset(dt_summer_end) == timedelta(hours=-4)
    assert tz.tzname(dt_summer_end) == "EDT"

    dt_winter_start = datetime(2026, 11, 1, 2, 0, tzinfo=tz)
    assert tz.utcoffset(dt_winter_start) == timedelta(hours=-5)
    assert tz.tzname(dt_winter_start) == "EST"


def test_priority1_us_candle_close_time_dynamic_resolution() -> None:
    """Verify US equity candles dynamically resolve close_time without hardcoding IST/15:30."""
    t_open = datetime(2026, 6, 1, 9, 30, tzinfo=US_EASTERN)

    # 1. US D1 candle: 09:30 EDT open closes at 16:00 EDT on the same day (NOT next day)
    c_d1 = Candle(
        symbol="AAPL",
        exchange=Exchange.NASDAQ,
        interval=CandleInterval.D1,
        open=Decimal("180.00"),
        high=Decimal("185.00"),
        low=Decimal("179.00"),
        close=Decimal("184.00"),
        volume=50000000,
        timestamp=t_open,
        source="TEST",
        retrieval_timestamp=t_open + timedelta(hours=7),
    )
    assert c_d1.close_time == datetime(2026, 6, 1, 16, 0, tzinfo=US_EASTERN)

    # 2. US H1 candle at 15:30 EDT: 6th hour closes at regular session close 16:00 EDT (NOT 16:30)
    t_h1_final = datetime(2026, 6, 1, 15, 30, tzinfo=US_EASTERN)
    c_h1 = Candle(
        symbol="AAPL",
        exchange=Exchange.NASDAQ,
        interval=CandleInterval.H1,
        open=Decimal("183.00"),
        high=Decimal("184.50"),
        low=Decimal("182.50"),
        close=Decimal("184.00"),
        volume=10000000,
        timestamp=t_h1_final,
        source="TEST",
        retrieval_timestamp=t_h1_final + timedelta(minutes=35),
    )
    assert c_h1.close_time == datetime(2026, 6, 1, 16, 0, tzinfo=US_EASTERN)


def test_priority1_exchange_mismatch_detection() -> None:
    """Verify evaluating a candle against a mismatched ExchangeSession emits EXCHANGE_MISMATCH."""
    t_open = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle_bse = Candle(
        symbol="RELIANCE",
        exchange=Exchange.BSE,
        interval=CandleInterval.M5,
        open=Decimal("2500.00"),
        high=Decimal("2510.00"),
        low=Decimal("2495.00"),
        close=Decimal("2505.00"),
        volume=1000,
        timestamp=t_open,
        source="TEST",
        retrieval_timestamp=t_open + timedelta(minutes=6),
    )

    session_nse = ExchangeSession.for_exchange(Exchange.NSE)
    val_res = validate_candle(candle_bse, now=t_open + timedelta(minutes=10), session=session_nse)
    assert val_res.is_valid is False
    assert val_res.has_error(DataQualityErrorCode.EXCHANGE_MISMATCH)


def test_priority1_d1_w1_mn1_grid_anchor_validation() -> None:
    """Verify D1, W1, and MN1 grid anchors: off-grid timestamps (e.g. 03:00 IST) are rejected."""
    # 03:00 IST on Monday is off-grid
    t_bad = datetime(2026, 11, 2, 3, 0, tzinfo=IST)
    c_bad = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("2500"),
        high=Decimal("2520"),
        low=Decimal("2490"),
        close=Decimal("2510"),
        volume=100000,
        timestamp=t_bad,
        source="TEST",
        retrieval_timestamp=t_bad + timedelta(hours=20),
    )
    val_res = validate_candle(c_bad, now=t_bad + timedelta(days=1))
    assert val_res.is_valid is False
    assert val_res.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # Valid anchor: 09:15 IST (session open)
    t_good = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    c_good = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("2500"),
        high=Decimal("2520"),
        low=Decimal("2490"),
        close=Decimal("2510"),
        volume=100000,
        timestamp=t_good,
        source="TEST",
        retrieval_timestamp=t_good + timedelta(hours=7),
    )
    val_good = validate_candle(c_good, now=t_good + timedelta(hours=8))
    assert val_good.is_valid is True


# ============================================================================
# Priority 2: Fail-Closed Historical Coverage & Partial Opt-In (H-2, COV-01)
# ============================================================================


def test_priority2_truncated_coverage_fails_closed_by_default() -> None:
    """Verify that truncated coverage fails closed by default with success=False."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Requested 4 bars (09:15 to 09:35), provider returns only 2 bars (09:15 to 09:25)
    records = [
        _build_batch2_record(timestamp=t0.isoformat()),
        _build_batch2_record(timestamp=(t0 + timedelta(minutes=5)).isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=20),  # 09:35
    )
    eval_now = t0 + timedelta(minutes=25)

    # Default call without require_full_coverage argument must fail closed
    res = pipeline.ingest_historical(req, now=eval_now)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value
    assert res.candles == ()
    assert res.partial_candles == ()


def test_priority2_allow_partial_preserves_success_false_and_exposes_partial() -> None:
    """Verify that allow_partial=True preserves success=False while exposing partial_candles."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [
        _build_batch2_record(timestamp=t0.isoformat()),
        _build_batch2_record(timestamp=(t0 + timedelta(minutes=5)).isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=20),
    )
    eval_now = t0 + timedelta(minutes=25)

    res = pipeline.ingest_historical(req, now=eval_now, allow_partial=True)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value
    assert res.candles == ()  # candles attribute remains empty to prevent accidental full-data consumption
    assert len(res.partial_candles) == 2
    assert res.partial_candles[0].timestamp == t0


def test_priority2_check_gaps_false_cannot_bypass_interior_gaps() -> None:
    """Verify that check_gaps=False cannot bypass known interior sequence gaps."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 09:15 and 09:25 (09:20 missing)
    records = [
        _build_batch2_record(timestamp=t0.isoformat()),
        _build_batch2_record(timestamp=(t0 + timedelta(minutes=10)).isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )
    eval_now = t0 + timedelta(minutes=25)

    # Even with check_gaps=False, truncation fails closed
    res = pipeline.ingest_historical(req, now=eval_now, check_gaps=False)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value


# ============================================================================
# Priority 3: Deep Freezing Memo Identity & Work Bound (H-3, M-1)
# ============================================================================


class TempListMapping(Mapping[int, list[int]]):
    """Custom mapping that yields fresh temporary list instances on every lookup."""

    def __init__(self, size: int) -> None:
        self._size = size

    def __getitem__(self, key: int) -> list[int]:
        if 0 <= key < self._size:
            return [key]
        raise KeyError(key)

    def __iter__(self) -> Iterator[int]:
        return iter(range(self._size))

    def __len__(self) -> int:
        return self._size


def test_priority3_deep_freeze_memo_identity_corruption_fixed() -> None:
    """Verify that _deep_freeze preserves distinct temporary instances without ID reuse corruption."""
    mapping = TempListMapping(2000)
    frozen = _deep_freeze(mapping)

    assert len(frozen) == 2000
    wrong_count = 0
    for k in range(2000):
        val = frozen[k]
        if val != (k,):
            wrong_count += 1

    # Before fix, 1998 out of 2000 came back wrong due to CPython memory address reuse
    assert wrong_count == 0


def test_priority3_deep_freeze_node_budget_counts_elements() -> None:
    """Verify that max_nodes counts all nodes (primitives and containers) and bounds traversal."""
    data = list(range(100))

    with pytest.raises(ValueError, match="Maximum node count"):
        _deep_freeze(data, max_nodes=50)

    # Succeeds with adequate budget
    frozen = _deep_freeze(data, max_nodes=150)
    assert len(frozen) == 100


def test_priority3_deep_freeze_subtree_depth_limit_enforced() -> None:
    """Verify that memoized subtrees cannot bypass max_depth when reused deeper in a DAG."""
    sub = {"a": {"b": {"c": 1}}}
    root = {"sub1": sub, "wrapper": {"nested": {"further": sub}}}

    with pytest.raises(ValueError, match="Maximum nesting depth"):
        _deep_freeze(root, max_depth=3)


def test_priority3_deep_freeze_cycle_detection() -> None:
    """Verify cyclic data structures are rejected with explicit cycle detection error."""
    cyclic_dict: dict[str, Any] = {"name": "loop"}
    cyclic_dict["self"] = cyclic_dict

    with pytest.raises(ValueError, match="Cyclic"):
        _deep_freeze(cyclic_dict)


# ============================================================================
# Priority 4: Exchange Calendar & Multi-Day Spans (M-2, COV-03, COV-08)
# ============================================================================


def test_priority4_weekend_spanning_historical_window_with_calendar() -> None:
    """Verify that a weekend-spanning window (Friday to Monday) passes with calendar evidence."""
    # Friday 2026-11-06 close (15:25 M5, closes at 15:30)
    t_fri = datetime(2026, 11, 6, 15, 25, tzinfo=IST)
    # Monday 2026-11-09 open (09:15 M5, closes at 09:20)
    t_mon = datetime(2026, 11, 9, 9, 15, tzinfo=IST)

    records = [
        _build_batch2_record(timestamp=t_fri.isoformat()),
        _build_batch2_record(timestamp=t_mon.isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t_fri,
        end_time=t_mon + timedelta(minutes=5),
    )
    eval_now = t_mon + timedelta(minutes=10)

    # 1. Without calendar evidence: fails closed with MARKET_CALENDAR_REQUIRED
    res_no_cal = pipeline.ingest_historical(req, now=eval_now, calendar=None)
    assert res_no_cal.success is False
    assert res_no_cal.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res_no_cal.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value

    # 2. With exchange calendar verifying Sat/Sun are non-trading days: succeeds with FULL_COVERAGE!
    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 6), date(2026, 11, 9)}),
        complete=True,
    )
    res_with_cal = pipeline.ingest_historical(req, now=eval_now, calendar=calendar)
    assert res_with_cal.success is True
    assert res_with_cal.coverage_status == CoverageStatus.FULL_COVERAGE.value
    assert len(res_with_cal.candles) == 2


def test_priority4_holiday_evidence_with_calendar() -> None:
    """Verify that a weekday holiday (e.g. Diwali) is verified with ExchangeCalendar evidence."""
    t_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_wed = datetime(2026, 11, 4, 9, 15, tzinfo=IST)

    records = [
        _build_batch2_record(interval="1d", timestamp=t_mon.isoformat()),
        _build_batch2_record(interval="1d", timestamp=t_wed.isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        start_time=t_mon,
        end_time=t_wed.replace(hour=15, minute=30),
    )
    eval_now = t_wed + timedelta(days=2)

    # Complete calendar covering query window with Tuesday holiday
    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({date(2026, 11, 3)}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 4),
        complete=True,
    )
    res = pipeline.ingest_historical(req, now=eval_now, calendar=calendar)
    assert res.success is True
    assert res.coverage_status == CoverageStatus.FULL_COVERAGE.value


def test_priority4_special_session_muhurat_trading_support() -> None:
    """Verify ExchangeCalendar special session support (e.g. Muhurat 18:15 to 19:15)."""
    muhurat_date = date(2026, 11, 8)  # Sunday special session
    muhurat_session = ExchangeSession(
        name="NSE_MUHURAT",
        session_open=time(18, 15),
        session_close=time(19, 15),
        timezone=IST,
        exchange=Exchange.NSE,
    )
    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        special_sessions={muhurat_date: muhurat_session},
    )

    t_muhurat = datetime(2026, 11, 8, 18, 15, tzinfo=IST)
    candle = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        open=Decimal("2500"),
        high=Decimal("2550"),
        low=Decimal("2490"),
        close=Decimal("2540"),
        volume=50000,
        timestamp=t_muhurat,
        source="TEST",
        retrieval_timestamp=t_muhurat + timedelta(minutes=16),
    )

    val_res = validate_candle(candle, now=t_muhurat + timedelta(hours=1), session=calendar.get_session(muhurat_date))
    assert val_res.is_valid is True


def test_priority4_sparse_illiquid_data_contract() -> None:
    """Verify allow_sparse=True permits missing intraday bars for illiquid instruments."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Illiquid instrument trades only at 09:15 and 10:30 (missing intermediate bars)
    records = [
        _build_batch2_record(timestamp=t0.isoformat(), volume=100),
        _build_batch2_record(timestamp=(t0 + timedelta(minutes=75)).isoformat(), volume=200),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=80),
    )
    eval_now = t0 + timedelta(hours=2)

    # allow_sparse=True accepts sparse trading
    res = pipeline.ingest_historical(req, now=eval_now, allow_sparse=True)
    assert res.success is True
    assert len(res.candles) == 2


# ============================================================================
# Priority 5: Result-Object Invariants (M-4, ARCH-03)
# ============================================================================


def test_priority5_ingestion_result_invariants() -> None:
    """Verify IngestionResult enforces valid validation_result on success."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("2500"),
        high=Decimal("2510"),
        low=Decimal("2490"),
        close=Decimal("2505"),
        volume=1000,
        timestamp=t0,
        source="TEST",
        retrieval_timestamp=t0 + timedelta(minutes=6),
    )

    # 1. Success without validation_result raises ValueError
    with pytest.raises(ValueError, match="Successful IngestionResult must contain a validation_result"):
        IngestionResult(success=True, candle=candle, validation_result=None)

    # 2. Success with invalid validation_result raises ValueError
    invalid_val = ValidationResult(
        is_valid=False,
        issues=(QualityIssue(code=DataQualityErrorCode.STALE_DATA, message="stale"),),
    )
    with pytest.raises(ValueError, match="cannot contain an invalid validation_result"):
        IngestionResult(success=True, candle=candle, validation_result=invalid_val)


def test_priority5_sequence_ingestion_result_invariants() -> None:
    """Verify SequenceIngestionResult enforces coverage status and count invariants."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("2500"),
        high=Decimal("2510"),
        low=Decimal("2490"),
        close=Decimal("2505"),
        volume=1000,
        timestamp=t0,
        source="TEST",
        retrieval_timestamp=t0 + timedelta(minutes=6),
    )
    val_ok = ValidationResult(is_valid=True)

    # 1. Reject invalid coverage status enum
    with pytest.raises(ValueError, match="Invalid coverage_status"):
        SequenceIngestionResult(success=False, error_message="err", error_code="ERR", coverage_status="BOGUS")

    # 2. Reject raw_record_count < len(candles)
    with pytest.raises(ValueError, match="cannot be less than number of candles"):
        SequenceIngestionResult(success=True, candles=(candle,), validation_result=val_ok, raw_record_count=0)

    # 3. Reject success=True with TRUNCATED_COVERAGE
    with pytest.raises(ValueError, match="cannot have coverage_status 'TRUNCATED_COVERAGE'"):
        SequenceIngestionResult(
            success=True,
            candles=(candle,),
            validation_result=val_ok,
            raw_record_count=1,
            coverage_status="TRUNCATED_COVERAGE",
        )

    # 4. Reject success=True with partial_candles populated
    with pytest.raises(ValueError, match="cannot contain partial_candles"):
        SequenceIngestionResult(
            success=True,
            candles=(candle,),
            partial_candles=(candle,),
            validation_result=val_ok,
            raw_record_count=1,
        )


# ============================================================================
# Priority 6: Paper-Only Security Guardrails (SEC-01)
# ============================================================================


def test_priority6_zerodha_connector_order_placement_blocked() -> None:
    """Verify Zerodha connector order placement raises PermissionError in paper-only mode."""
    from pathlib import Path

    v3_path = str(Path(__file__).resolve().parent.parent / "v3-zerodha" / "src")
    if v3_path not in sys.path:
        sys.path.insert(0, v3_path)

    # Ensure keyring and kiteconnect are mockable even in environments without optional deps
    saved_keyring = sys.modules.get("keyring")
    saved_kiteconnect = sys.modules.get("kiteconnect")
    if "keyring" not in sys.modules:
        sys.modules["keyring"] = MagicMock()
    if "kiteconnect" not in sys.modules:
        sys.modules["kiteconnect"] = MagicMock()

    os.environ["KITE_API_KEY"] = "mock_key"  # pragma: allowlist secret
    try:
        from agentic_trading.zerodha_connector import ZerodhaReadOnlyConnector

        connector = ZerodhaReadOnlyConnector()

        # Direct connector order placement raises PermissionError
        with pytest.raises(PermissionError, match="Order placement is forbidden in paper-only mode"):
            connector.place_order(variety="regular", exchange="NSE", tradingsymbol="INFY", transaction_type="BUY", quantity=1)

        with pytest.raises(PermissionError, match="Order modification is forbidden in paper-only mode"):
            connector.modify_order(order_id="123")

        with pytest.raises(PermissionError, match="Order cancellation is forbidden in paper-only mode"):
            connector.cancel_order(order_id="123")

        # Underlying client wrapper order placement also raises PermissionError
        with pytest.raises(PermissionError, match="Order placement is forbidden in paper-only mode"):
            connector.client.place_order()

        with pytest.raises(PermissionError, match="Order modification is forbidden in paper-only mode"):
            connector.client.modify_order()

        with pytest.raises(PermissionError, match="Order cancellation is forbidden in paper-only mode"):
            connector.client.cancel_order()
    finally:
        os.environ.pop("KITE_API_KEY", None)
        if saved_keyring is None:
            sys.modules.pop("keyring", None)
        else:
            sys.modules["keyring"] = saved_keyring
        if saved_kiteconnect is None:
            sys.modules.pop("kiteconnect", None)
        else:
            sys.modules["kiteconnect"] = saved_kiteconnect
