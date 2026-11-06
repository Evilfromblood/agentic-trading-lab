"""Authoritative regression test suite for Claude C M2b Batch 2 findings (Batch 3 remediation).

Covers:
- Priority 1: Calendar evidence must never fail open (unpopulated vs populated, declared holidays, multi-week).
- Priority 2: Enforce Zerodha paper-only boundary (read-only allowlist, blocked order/mutation methods, attribute isolation).
- Priority 3: Trustworthy coverage success & explicit sparse mode (SPARSE_COVERAGE, missing edge bars, require_full_coverage).
- Priority 5: Result-object constructor invariants (monotonic, symbol/exchange consistency, forbidden statuses).
- Additional: MN1 calendar month boundaries (leap/non-leap, 30/31 days), US Eastern pre-2007 rejection, D1 midnight boundary.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

_V3_ZERODHA_SRC = pathlib.Path(__file__).resolve().parent.parent / "v3-zerodha" / "src"
if str(_V3_ZERODHA_SRC) not in sys.path:
    sys.path.insert(0, str(_V3_ZERODHA_SRC))

from agentic_trading.zerodha_connector import (  # noqa: E402
    ZerodhaReadOnlyConnector,
    _ReadOnlyKiteWrapper,
)

from agentic_trading.market_data.ingestion import (  # noqa: E402
    CoverageStatus,
    HistoricalDataRequest,
    MarketDataIngestionPipeline,
    SequenceIngestionResult,
)
from agentic_trading.market_data.models import (  # noqa: E402
    IST,
    Candle,
    CandleInterval,
    Exchange,
    ExchangeCalendar,
    _USEasternFallback,
)
from agentic_trading.market_data.provider import SyntheticMarketDataProvider  # noqa: E402
from agentic_trading.market_data.quality import (  # noqa: E402
    DataQualityErrorCode,
    ValidationResult,
    validate_candle,
)


def _build_test_record(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    interval: str = "5m",
    timestamp: str = "2026-11-02T09:15:00+05:30",
    open_p: str = "2500.00",
    high_p: str = "2510.00",
    low_p: str = "2495.00",
    close_p: str = "2505.00",
    volume: int = 10000,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "timestamp": timestamp,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
    }


def _make_candle(
    symbol: str = "RELIANCE",
    exchange: Exchange = Exchange.NSE,
    interval: CandleInterval = CandleInterval.M5,
    timestamp: datetime | None = None,
    open_p: str = "2500.00",
    high_p: str = "2510.00",
    low_p: str = "2495.00",
    close_p: str = "2505.00",
    volume: int = 1000,
    source: str = "TEST_SRC",
    retrieval_timestamp: datetime | None = None,
) -> Candle:
    ts = timestamp or datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_ts = retrieval_timestamp or datetime(2026, 11, 2, 18, 0, tzinfo=IST)
    return Candle(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        timestamp=ts,
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal(volume),
        source=source,
        retrieval_timestamp=ret_ts,
    )


# ============================================================================
# Priority 1: Calendar Evidence Must Never Fail Open
# ============================================================================


def test_priority1_unpopulated_calendar_has_no_evidence() -> None:
    """Verify that an empty/unpopulated ExchangeCalendar reports is_populated=False and has no evidence."""
    empty_cal = ExchangeCalendar(exchange=Exchange.NSE)
    assert empty_cal.is_populated is False
    assert empty_cal.has_evidence_for_date(date(2026, 11, 2)) is False
    assert empty_cal.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 6)) is False


def test_priority1_populated_calendar_distinguishes_evidence() -> None:
    """Verify that a populated calendar reports evidence within its defined range."""
    # 1. Defined by explicit coverage start and end with complete=True contract
    cal_range = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        complete=True,
    )
    assert cal_range.is_populated is True
    assert cal_range.has_evidence_for_date(date(2026, 6, 15)) is True
    assert cal_range.has_evidence_for_date(date(2025, 12, 31)) is False
    assert cal_range.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 6)) is True

    # 1b. Incomplete calendar with bounds only has no completeness evidence
    cal_bounds_only = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        complete=False,
    )
    assert cal_bounds_only.is_populated is False
    assert cal_bounds_only.has_evidence_for_date(date(2026, 6, 15)) is False

    # 2. Partial calendar defined by concrete holidays has evidence ONLY for declared dates (no year inference)
    cal_hol = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({date(2026, 11, 3)}),
    )
    assert cal_hol.is_populated is True
    assert cal_hol.has_evidence_for_date(date(2026, 11, 3)) is True  # Declared holiday has evidence
    assert cal_hol.has_evidence_for_date(date(2026, 11, 2)) is False  # Unrelated date has NO evidence
    assert cal_hol.has_evidence_for_date(date(2025, 11, 2)) is False


def test_priority1_candle_on_declared_holiday_rejected() -> None:
    """Verify that candles occurring on declared calendar holidays are rejected as OUTSIDE_SESSION."""
    # Tuesday 2026-11-03 declared as Diwali holiday
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({date(2026, 11, 3)}),
    )
    assert cal.is_trading_day(date(2026, 11, 3)) is False

    t_diwali = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    candle = _make_candle(timestamp=t_diwali)

    # validate_candle with calendar evidence must fail
    res = validate_candle(candle, calendar=cal)
    assert res.is_valid is False
    assert res.has_error(DataQualityErrorCode.OUTSIDE_SESSION)
    assert any("holiday" in issue.message.lower() for issue in res.issues)


def test_priority1_empty_calendar_never_claims_full_coverage() -> None:
    """Verify that an empty calendar never claims FULL_COVERAGE for multi-day sequences."""
    t_fri = datetime(2026, 11, 6, 15, 25, tzinfo=IST)
    t_mon = datetime(2026, 11, 9, 9, 15, tzinfo=IST)
    records = [
        _build_test_record(timestamp=t_fri.isoformat()),
        _build_test_record(timestamp=t_mon.isoformat()),
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

    # An empty calendar passed in: must fail closed with MARKET_CALENDAR_REQUIRED
    empty_cal = ExchangeCalendar(exchange=Exchange.NSE)
    res = pipeline.ingest_historical(req, now=eval_now, calendar=empty_cal)
    assert res.success is False
    assert res.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value


def test_priority1_multi_week_requests_with_calendar_evidence() -> None:
    """Verify multi-week daily data succeeds with FULL_COVERAGE when calendar evidence covers the range."""
    # Two weeks: Monday 2026-11-02 to Friday 2026-11-13 (10 trading days)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = []
    cur = t0
    for _ in range(14):
        if cur.weekday() < 5:
            records.append(_build_test_record(interval="1d", timestamp=cur.isoformat()))
        cur += timedelta(days=1)

    assert len(records) == 10  # 10 weekdays across 2 weeks

    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        start_time=t0,
        end_time=t0 + timedelta(days=11, hours=6, minutes=15),  # Friday 15:30
    )
    eval_now = t0 + timedelta(days=15)

    # Complete calendar covering 2026
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        complete=True,
    )
    res = pipeline.ingest_historical(req, now=eval_now, calendar=cal, require_full_coverage=True)
    assert res.success is True
    assert res.coverage_status == CoverageStatus.FULL_COVERAGE.value
    assert len(res.candles) == 10


# ============================================================================
# Priority 2: Enforce the Zerodha Paper-Only Boundary
# ============================================================================


def test_priority2_zerodha_read_only_allowlist() -> None:
    """Verify read-only methods can be invoked and are allowed on the wrapper."""
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {"user_id": "AB1234"}
    mock_kite.instruments.return_value = [{"instrument_token": 12345}]
    mock_kite.quote.return_value = {"NSE:RELIANCE": {"last_price": 2500.0}}

    wrapper = _ReadOnlyKiteWrapper(mock_kite)
    assert wrapper.profile() == {"user_id": "AB1234"}
    assert wrapper.instruments() == [{"instrument_token": 12345}]
    assert wrapper.quote() == {"NSE:RELIANCE": {"last_price": 2500.0}}


def test_priority2_zerodha_order_placement_and_mutation_blocked() -> None:
    """Verify all order placement, modification, cancellation, and GTT calls raise PermissionError."""
    mock_kite = MagicMock()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=mock_kite)

    # 1. Standard orders
    with pytest.raises(PermissionError, match="Order placement is forbidden"):
        connector.place_order(variety="regular", exchange="NSE", tradingsymbol="RELIANCE")

    with pytest.raises(PermissionError, match="Order modification is forbidden"):
        connector.modify_order(variety="regular", order_id="123")

    with pytest.raises(PermissionError, match="Order cancellation is forbidden"):
        connector.cancel_order(variety="regular", order_id="123")

    with pytest.raises(PermissionError, match="Order exit is forbidden"):
        connector.exit_order(variety="regular", order_id="123")

    # 2. GTT orders
    with pytest.raises(PermissionError, match="forbidden"):
        connector.place_gtt(trigger_type=1, tradingsymbol="RELIANCE")

    with pytest.raises(PermissionError, match="forbidden"):
        connector.modify_gtt(trigger_id=123)

    with pytest.raises(PermissionError, match="forbidden"):
        connector.delete_gtt(trigger_id=123)

    # 3. Position conversion and mutual funds
    with pytest.raises(PermissionError, match="forbidden"):
        connector.convert_position(exchange="NSE", tradingsymbol="RELIANCE")

    with pytest.raises(PermissionError, match="forbidden"):
        connector.place_mf_order(tradingsymbol="INF123")

    with pytest.raises(PermissionError, match="forbidden"):
        connector.cancel_mf_order(order_id="123")


def test_priority2_zerodha_private_client_attribute_access_blocked() -> None:
    """Verify direct, nested, and forwarded access to underlying KiteConnect client is blocked."""
    mock_kite = MagicMock()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=mock_kite)

    # Direct private attribute access blocked
    with pytest.raises((PermissionError, AttributeError)):
        _ = connector._client

    with pytest.raises((PermissionError, AttributeError)):
        _ = connector.__client

    with pytest.raises((PermissionError, AttributeError)):
        _ = connector._raw_client

    # Accessing through client wrapper
    wrapper = connector.client
    with pytest.raises((PermissionError, AttributeError)):
        _ = wrapper._client

    with pytest.raises((PermissionError, AttributeError)):
        _ = wrapper.__client


def test_priority2_zerodha_raw_http_methods_blocked() -> None:
    """Verify raw HTTP methods on the wrapper raise PermissionError."""
    mock_kite = MagicMock()
    wrapper = _ReadOnlyKiteWrapper(mock_kite)

    with pytest.raises(PermissionError, match="forbidden"):
        wrapper._post("orders/regular")

    with pytest.raises(PermissionError, match="forbidden"):
        wrapper._request("POST", "orders/regular")

    with pytest.raises(PermissionError, match="forbidden"):
        wrapper._put("orders/regular")

    with pytest.raises(PermissionError, match="forbidden"):
        wrapper._delete("orders/regular")


# ============================================================================
# Priority 3: Make Coverage Success Trustworthy & Explicit Sparse Mode
# ============================================================================


def test_priority3_require_full_coverage_contract() -> None:
    """Verify require_full_coverage=True fails closed when calendar evidence is unverified."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [_build_test_record(timestamp=t0.isoformat())]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=5),
    )
    eval_now = t0 + timedelta(minutes=10)

    # 1. With require_full_coverage=True (strict mode) and no calendar: must fail closed
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True, calendar=None)
    assert res_strict.success is False
    assert res_strict.error_code == "COVERAGE_UNVERIFIED"
    assert res_strict.coverage_status == CoverageStatus.COVERAGE_UNVERIFIED.value

    # 2. With require_full_coverage=False (permissive mode): succeeds with COVERAGE_UNVERIFIED marker
    res_opt_in = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=False, calendar=None)
    assert res_opt_in.success is True
    assert res_opt_in.coverage_status == CoverageStatus.COVERAGE_UNVERIFIED.value

    # 3. With complete calendar and require_full_coverage=True: succeeds with FULL_COVERAGE
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        complete=True,
    )
    # A single intraday bar cannot claim FULL_COVERAGE (invariant), so provide 2 bars
    records_two = [
        _build_test_record(timestamp=t0.isoformat()),
        _build_test_record(timestamp=(t0 + timedelta(minutes=5)).isoformat()),
    ]
    pipe_two = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=records_two))
    req_two = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=10),
    )
    res_full = pipe_two.ingest_historical(req_two, now=eval_now, require_full_coverage=True, calendar=cal)
    assert res_full.success is True
    assert res_full.coverage_status == CoverageStatus.FULL_COVERAGE.value


def test_priority3_allow_sparse_missing_edge_bars_illiquid() -> None:
    """Verify allow_sparse=True supports illiquid instruments with missing edge and interior bars."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Illiquid instrument trades only at 09:30 and 10:00 (window is 09:15 to 10:30)
    # Missing 09:15 (start edge), 09:20, 09:25, 09:35..09:55, 10:05..10:25 (end edge)
    records = [
        _build_test_record(symbol="ILLIQUID_STOCK", timestamp=(t0 + timedelta(minutes=15)).isoformat(), volume=50),
        _build_test_record(symbol="ILLIQUID_STOCK", timestamp=(t0 + timedelta(minutes=45)).isoformat(), volume=75),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="ILLIQUID_STOCK",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=75),
    )
    eval_now = t0 + timedelta(hours=2)

    # 1. Normal mode (allow_sparse=False) must fail closed with TRUNCATED_COVERAGE
    res_normal = pipeline.ingest_historical(req, now=eval_now, allow_sparse=False)
    assert res_normal.success is False
    assert res_normal.error_code in ("TRUNCATED_COVERAGE", "QUALITY_GATE_REJECTED")

    # 2. Sparse mode (allow_sparse=True) succeeds with SPARSE_COVERAGE
    res_sparse = pipeline.ingest_historical(req, now=eval_now, allow_sparse=True)
    assert res_sparse.success is True
    assert res_sparse.coverage_status == CoverageStatus.SPARSE_COVERAGE.value
    assert len(res_sparse.candles) == 2

    # 3. Sparse mode cannot satisfy require_full_coverage=True
    res_sparse_strict = pipeline.ingest_historical(req, now=eval_now, allow_sparse=True, require_full_coverage=True)
    assert res_sparse_strict.success is False
    assert res_sparse_strict.error_code == "SPARSE_COVERAGE"


def test_priority3_two_bar_full_day_rejected_without_sparse() -> None:
    """Verify that a 2-bar response for a full-day request is rejected when allow_sparse=False."""
    t_open = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_close = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    records = [
        _build_test_record(timestamp=t_open.isoformat()),
        _build_test_record(timestamp=t_close.isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t_open,
        end_time=t_close + timedelta(minutes=5),  # 15:30
    )
    eval_now = t_close + timedelta(hours=1)

    res = pipeline.ingest_historical(req, now=eval_now, allow_sparse=False)
    assert res.success is False
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value


# ============================================================================
# Priority 5: Result-Object Constructor Invariants
# ============================================================================


def test_priority5_sequence_result_invariant_candle_types() -> None:
    """Verify SequenceIngestionResult enforces that all elements in candles are Candle instances."""
    val_res = ValidationResult(is_valid=True)
    valid_c = _make_candle()

    with pytest.raises(TypeError, match="must be a Candle instance"):
        SequenceIngestionResult(
            success=True,
            candles=(valid_c, {"bad": "dict"}),  # type: ignore[arg-type]
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.FULL_COVERAGE.value,
        )


def test_priority5_sequence_result_invariant_symbol_consistency() -> None:
    """Verify SequenceIngestionResult forbids candles with conflicting symbols."""
    val_res = ValidationResult(is_valid=True)
    c1 = _make_candle(symbol="RELIANCE")
    c2 = _make_candle(symbol="TCS", timestamp=datetime(2026, 11, 2, 9, 20, tzinfo=IST))

    with pytest.raises(ValueError, match="conflicting symbol"):
        SequenceIngestionResult(
            success=True,
            candles=(c1, c2),
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.FULL_COVERAGE.value,
        )


def test_priority5_sequence_result_invariant_monotonic_ordering() -> None:
    """Verify SequenceIngestionResult forbids non-monotonic candle timestamps."""
    val_res = ValidationResult(is_valid=True)
    c1 = _make_candle(timestamp=datetime(2026, 11, 2, 9, 20, tzinfo=IST))
    c2 = _make_candle(timestamp=datetime(2026, 11, 2, 9, 15, tzinfo=IST))  # Earlier than c1!

    with pytest.raises(ValueError, match="strictly monotonically increasing"):
        SequenceIngestionResult(
            success=True,
            candles=(c1, c2),
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.FULL_COVERAGE.value,
        )


def test_priority5_sequence_result_invariant_forbidden_statuses() -> None:
    """Verify SequenceIngestionResult forbids contradictory success and coverage_status combinations."""
    val_res = ValidationResult(is_valid=True)
    c1 = _make_candle()
    c2 = _make_candle(timestamp=datetime(2026, 11, 2, 9, 20, tzinfo=IST))

    # success=True with TRUNCATED_COVERAGE
    with pytest.raises(ValueError, match="Successful SequenceIngestionResult cannot have coverage_status"):
        SequenceIngestionResult(
            success=True,
            candles=(c1, c2),
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.TRUNCATED_COVERAGE.value,
        )

    # success=True with MARKET_CALENDAR_REQUIRED
    with pytest.raises(ValueError, match="Successful SequenceIngestionResult cannot have coverage_status"):
        SequenceIngestionResult(
            success=True,
            candles=(c1, c2),
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.MARKET_CALENDAR_REQUIRED.value,
        )

    # success=False with FULL_COVERAGE
    with pytest.raises(ValueError, match="Failed SequenceIngestionResult cannot have coverage_status 'FULL_COVERAGE'"):
        SequenceIngestionResult(
            success=False,
            candles=(),
            error_message="Failed",
            error_code="FAIL",
            validation_result=val_res,
            raw_record_count=2,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.FULL_COVERAGE.value,
        )

    # Single intraday candle claiming FULL_COVERAGE
    with pytest.raises(ValueError, match="cannot represent FULL_COVERAGE"):
        SequenceIngestionResult(
            success=True,
            candles=(c1,),
            validation_result=val_res,
            raw_record_count=1,
            retrieval_timestamp=datetime.now(UTC),
            coverage_status=CoverageStatus.FULL_COVERAGE.value,
        )


# ============================================================================
# Additional Findings: MN1 Boundaries, US Eastern Pre-2007, Caller 'now'
# ============================================================================


def test_mn1_monthly_close_time_calendar_boundaries() -> None:
    """Verify Candle.close_time calculates exact calendar month boundaries for MN1."""
    # Leap year February: 2024-02-01 should close on 2024-02-29 at 15:30 IST
    c_feb_leap = _make_candle(
        interval=CandleInterval.MN1,
        timestamp=datetime(2024, 2, 1, 9, 15, tzinfo=IST),
    )
    assert c_feb_leap.close_time == datetime(2024, 2, 29, 15, 30, tzinfo=IST)

    # Non-leap year February: 2023-02-01 should close on 2023-02-28 at 15:30 IST
    c_feb_non_leap = _make_candle(
        interval=CandleInterval.MN1,
        timestamp=datetime(2023, 2, 1, 9, 15, tzinfo=IST),
    )
    assert c_feb_non_leap.close_time == datetime(2023, 2, 28, 15, 30, tzinfo=IST)

    # 30-day month April: 2024-04-01 should close on 2024-04-30 at 15:30 IST
    c_apr = _make_candle(
        interval=CandleInterval.MN1,
        timestamp=datetime(2024, 4, 1, 9, 15, tzinfo=IST),
    )
    assert c_apr.close_time == datetime(2024, 4, 30, 15, 30, tzinfo=IST)

    # 31-day month January: 2024-01-01 should close on 2024-01-31 at 15:30 IST
    c_jan = _make_candle(
        interval=CandleInterval.MN1,
        timestamp=datetime(2024, 1, 1, 9, 15, tzinfo=IST),
    )
    assert c_jan.close_time == datetime(2024, 1, 31, 15, 30, tzinfo=IST)


def test_us_eastern_fallback_pre_2007_fails_explicitly() -> None:
    """Verify _USEasternFallback raises ValueError for historical dates prior to 2007."""
    fallback_tz = _USEasternFallback()

    # Pre-2007 historical dates fail explicitly
    dt_1995 = datetime(1995, 4, 5, 12, 0)
    with pytest.raises(ValueError, match="prior to 2007"):
        fallback_tz.dst(dt_1995)

    # Post-2007 dates calculate DST offset cleanly (summer = EDT, winter = EST)
    dt_summer = datetime(2024, 7, 1, 12, 0)
    assert fallback_tz.dst(dt_summer) == timedelta(hours=1)
    dt_winter = datetime(2024, 1, 1, 12, 0)
    assert fallback_tz.dst(dt_winter) == timedelta(0)


def test_caller_supplied_now_distant_future_boundary() -> None:
    """Verify pipeline rejects arbitrary distant future 'now' injections."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [_build_test_record(timestamp=t0.isoformat())]
    pipeline = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=records))
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=5),
    )

    # Injected now in year 2099 is rejected
    far_future_now = datetime(2099, 1, 1, 12, 0, tzinfo=IST)
    with pytest.raises(ValueError, match="distant future"):
        pipeline.ingest_historical(req, now=far_future_now)
