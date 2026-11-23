"""Adversarial regression test suite for Claude A M2b Remediation Batch 1.

Covers:
- Priority 1: Candle integrity (overlapping candles, grid anchoring, session membership,
  preserving valid session-truncated candles, missing final session candle detection for M5, M15, H1, M30, M10).
- Priority 2: Historical freshness (future timestamp validation in historical mode,
  end_time == now vs end_time < now vs end_time > now, boundary retrieval_timestamp validation).
- Priority 3: Recursive immutability (linear shared DAG freezing, cycle detection, depth bounds, node budgets).
- Priority 4: Coverage and result consistency (TRUNCATED_COVERAGE vs MARKET_CALENDAR_REQUIRED distinction,
  full coverage invariants).
- Priority 5: Additional confirmed defects (D1 close_time non-zero duration, whitespace numeric rejection,
  FreshnessPolicy hashability and dataclass equality).
"""
from __future__ import annotations

import time as py_time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from agentic_trading.market_data.adapters import (
    RawDataValidationError,
    StandardDictAdapter,
)
from agentic_trading.market_data.ingestion import (
    FreshnessPolicy,
    MarketDataIngestionPipeline,
)
from agentic_trading.market_data.ingestion import (
    _deep_freeze as ing_deep_freeze,
)
from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
    _validate_finite_decimal,
    _validate_volume,
)
from agentic_trading.market_data.models import (
    _deep_freeze as mod_deep_freeze,
)
from agentic_trading.market_data.provider import (
    HistoricalDataRequest,
    ProviderResponse,
    SyntheticMarketDataProvider,
)
from agentic_trading.market_data.provider import (
    _deep_freeze as prov_deep_freeze,
)
from agentic_trading.market_data.quality import (
    DataQualityErrorCode,
    check_sequence_monotonicity,
    validate_candle,
    validate_candle_sequence,
)
from agentic_trading.market_data.quality import (
    _deep_freeze as qual_deep_freeze,
)


def _make_candle(
    timestamp: datetime,
    interval: CandleInterval = CandleInterval.M5,
    symbol: str = "RELIANCE",
    exchange: Exchange = Exchange.NSE,
    open_p: str = "2500.00",
    high_p: str = "2510.00",
    low_p: str = "2490.00",
    close_p: str = "2505.00",
    volume: int = 1000,
    retrieval_timestamp: datetime | None = None,
    source: str = "SYNTHETIC",
) -> Candle:
    """Helper to create a canonical Candle for testing."""
    close_time = timestamp + interval.duration
    ret_ts = retrieval_timestamp or (close_time + timedelta(seconds=1))
    return Candle(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=volume,
        timestamp=timestamp,
        source=source,
        retrieval_timestamp=ret_ts,
    )


def _make_raw_record(
    timestamp: str,
    interval: str = "5m",
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    open_p: str = "2500.00",
    high_p: str = "2510.00",
    low_p: str = "2490.00",
    close_p: str = "2505.00",
    volume: int = 1000,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
        "timestamp": timestamp,
    }


# ============================================================================
# Priority 1: Candle Integrity
# ============================================================================


def test_priority1_rejects_overlapping_candles() -> None:
    """Verify that candles with overlapping intervals are rejected with OVERLAPPING_CANDLE."""
    # Candle A: 09:15 to 09:20 (close 09:20)
    # Candle B: 09:18 to 09:23 (opens before Candle A closes)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_overlap = datetime(2026, 11, 2, 9, 18, tzinfo=IST)

    cA = _make_candle(t0, CandleInterval.M5)
    cB = _make_candle(t_overlap, CandleInterval.M5)

    # 1. Monotonicity check directly catches overlap
    issues = check_sequence_monotonicity([cA, cB])
    assert any(iss.code == DataQualityErrorCode.OVERLAPPING_CANDLE for iss in issues)

    # 2. validate_candle_sequence fails closed on overlap
    res = validate_candle_sequence([cA, cB], expected_interval=CandleInterval.M5)
    assert res.is_valid is False
    assert res.has_error(DataQualityErrorCode.OVERLAPPING_CANDLE)

    # 3. Contiguous non-overlapping candles pass without overlap error
    t_contiguous = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c_ok = _make_candle(t_contiguous, CandleInterval.M5)
    res_ok = validate_candle_sequence([cA, c_ok], expected_interval=CandleInterval.M5)
    assert not res_ok.has_error(DataQualityErrorCode.OVERLAPPING_CANDLE)


def test_priority1_validates_interval_grid_anchoring() -> None:
    """Verify that intraday candles must align with interval grid relative to session open."""
    # Valid on-grid 5m bar at 09:15
    t_valid = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    c_valid = _make_candle(t_valid, CandleInterval.M5)
    assert not validate_candle(c_valid).has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # Off-grid 5m bar at 09:17 (not divisible by 5)
    t_offgrid_5m = datetime(2026, 11, 2, 9, 17, tzinfo=IST)
    c_offgrid_5m = _make_candle(t_offgrid_5m, CandleInterval.M5)
    res_5m = validate_candle(c_offgrid_5m)
    assert res_5m.is_valid is False
    assert res_5m.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # Off-grid 15m bar at 09:20 (elapsed 5m not divisible by 15)
    t_offgrid_15m = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    c_offgrid_15m = _make_candle(t_offgrid_15m, CandleInterval.M15)
    res_15m = validate_candle(c_offgrid_15m)
    assert res_15m.is_valid is False
    assert res_15m.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # Intraday bar with non-zero second
    t_non_zero_sec = datetime(2026, 11, 2, 9, 15, 30, tzinfo=IST)
    c_sec = _make_candle(t_non_zero_sec, CandleInterval.M5)
    assert validate_candle(c_sec).has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # Intraday bar with non-zero microsecond
    t_non_zero_us = datetime(2026, 11, 2, 9, 15, 0, 500000, tzinfo=IST)
    c_us = _make_candle(t_non_zero_us, CandleInterval.M5)
    assert validate_candle(c_us).has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)


def test_priority1_validates_exchange_session_membership() -> None:
    """Verify that intraday candles outside trading days or session hours are rejected."""
    # Weekend candle (Sunday 2026-11-01)
    t_sunday = datetime(2026, 11, 1, 9, 15, tzinfo=IST)
    c_sun = _make_candle(t_sunday, CandleInterval.M5)
    res_sun = validate_candle(c_sun)
    assert res_sun.is_valid is False
    assert res_sun.has_error(DataQualityErrorCode.OUTSIDE_SESSION)

    # Pre-market candle (08:30 IST)
    t_pre_market = datetime(2026, 11, 2, 8, 30, tzinfo=IST)
    c_pre = _make_candle(t_pre_market, CandleInterval.M5)
    res_pre = validate_candle(c_pre)
    assert res_pre.is_valid is False
    assert res_pre.has_error(DataQualityErrorCode.OUTSIDE_SESSION)

    # Post-market candle (16:00 IST)
    t_post_market = datetime(2026, 11, 2, 16, 0, tzinfo=IST)
    c_post = _make_candle(t_post_market, CandleInterval.M5)
    res_post = validate_candle(c_post)
    assert res_post.is_valid is False
    assert res_post.has_error(DataQualityErrorCode.OUTSIDE_SESSION)


def test_priority1_preserves_valid_session_truncated_candles() -> None:
    """Verify that session-truncated bars for H1, M30, and M10 are valid and preserved."""
    # H1 bar opened at 15:15 IST truncates at 15:30 IST
    t_h1 = datetime(2026, 11, 2, 15, 15, tzinfo=IST)
    c_h1 = _make_candle(t_h1, CandleInterval.H1, retrieval_timestamp=t_h1 + timedelta(minutes=15, seconds=2))
    assert c_h1.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)
    res_h1 = validate_candle(c_h1)
    assert not res_h1.has_error(DataQualityErrorCode.OUTSIDE_SESSION)
    assert not res_h1.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # M30 bar opened at 15:15 IST truncates at 15:30 IST
    t_m30 = datetime(2026, 11, 2, 15, 15, tzinfo=IST)
    c_m30 = _make_candle(t_m30, CandleInterval.M30, retrieval_timestamp=t_m30 + timedelta(minutes=15, seconds=2))
    assert c_m30.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)
    res_m30 = validate_candle(c_m30)
    assert not res_m30.has_error(DataQualityErrorCode.OUTSIDE_SESSION)
    assert not res_m30.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)

    # M10 bar opened at 15:25 IST truncates at 15:30 IST
    t_m10 = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    c_m10 = _make_candle(t_m10, CandleInterval.M10, retrieval_timestamp=t_m10 + timedelta(minutes=5, seconds=2))
    assert c_m10.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)
    res_m10 = validate_candle(c_m10)
    assert not res_m10.has_error(DataQualityErrorCode.OUTSIDE_SESSION)
    assert not res_m10.has_error(DataQualityErrorCode.OFF_GRID_TIMESTAMP)


def test_priority1_detects_missing_final_session_candle_across_intervals() -> None:
    """Verify missing final session candle detection across day boundaries for M5, M15, H1, M30, M10."""
    t_tue_open = datetime(2026, 11, 3, 9, 15, tzinfo=IST)

    # 1. M5: Premature close at 15:20 on Monday followed by Tuesday 09:15 -> MISSING_INTERVAL
    t_mon_m5_premature = datetime(2026, 11, 2, 15, 15, tzinfo=IST)  # closes at 15:20
    seq_m5_premature = [
        _make_candle(t_mon_m5_premature, CandleInterval.M5),
        _make_candle(t_tue_open, CandleInterval.M5),
    ]
    res_m5 = validate_candle_sequence(seq_m5_premature, expected_interval=CandleInterval.M5)
    assert res_m5.is_valid is False
    assert res_m5.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 2. M15: Premature close at 15:15 on Monday followed by Tuesday 09:15 -> MISSING_INTERVAL
    t_mon_m15_premature = datetime(2026, 11, 2, 15, 0, tzinfo=IST)  # closes at 15:15
    seq_m15_premature = [
        _make_candle(t_mon_m15_premature, CandleInterval.M15),
        _make_candle(t_tue_open, CandleInterval.M15),
    ]
    res_m15 = validate_candle_sequence(seq_m15_premature, expected_interval=CandleInterval.M15)
    assert res_m15.is_valid is False
    assert res_m15.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 3. H1: Premature bar stopping at 13:15 (closes 14:15) -> MISSING_INTERVAL
    t_mon_h1_premature = datetime(2026, 11, 2, 13, 15, tzinfo=IST)
    seq_h1_premature = [
        _make_candle(t_mon_h1_premature, CandleInterval.H1),
        _make_candle(t_tue_open, CandleInterval.H1),
    ]
    res_h1_premature = validate_candle_sequence(seq_h1_premature, expected_interval=CandleInterval.H1)
    assert res_h1_premature.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 4. H1: Valid bar stopping at 14:15 (closes at natural 15:15) -> Clean overnight
    t_mon_h1_natural = datetime(2026, 11, 2, 14, 15, tzinfo=IST)  # closes at 15:15
    seq_h1_natural = [
        _make_candle(t_mon_h1_natural, CandleInterval.H1),
        _make_candle(t_tue_open, CandleInterval.H1),
    ]
    res_h1_natural = validate_candle_sequence(seq_h1_natural, expected_interval=CandleInterval.H1)
    assert not res_h1_natural.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 5. M30: Premature close at 14:45 -> MISSING_INTERVAL
    t_mon_m30_premature = datetime(2026, 11, 2, 14, 15, tzinfo=IST)  # closes at 14:45
    seq_m30_premature = [
        _make_candle(t_mon_m30_premature, CandleInterval.M30),
        _make_candle(t_tue_open, CandleInterval.M30),
    ]
    res_m30_premature = validate_candle_sequence(seq_m30_premature, expected_interval=CandleInterval.M30)
    assert res_m30_premature.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 6. M30: Natural close at 15:15 -> Clean overnight
    t_mon_m30_natural = datetime(2026, 11, 2, 14, 45, tzinfo=IST)  # closes at 15:15
    seq_m30_natural = [
        _make_candle(t_mon_m30_natural, CandleInterval.M30),
        _make_candle(t_tue_open, CandleInterval.M30),
    ]
    res_m30_natural = validate_candle_sequence(seq_m30_natural, expected_interval=CandleInterval.M30)
    assert not res_m30_natural.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 7. M10: Premature close at 15:15 -> MISSING_INTERVAL
    t_mon_m10_premature = datetime(2026, 11, 2, 15, 5, tzinfo=IST)  # closes at 15:15
    seq_m10_premature = [
        _make_candle(t_mon_m10_premature, CandleInterval.M10),
        _make_candle(t_tue_open, CandleInterval.M10),
    ]
    res_m10_premature = validate_candle_sequence(seq_m10_premature, expected_interval=CandleInterval.M10)
    assert res_m10_premature.has_error(DataQualityErrorCode.MISSING_INTERVAL)

    # 8. M10: Natural close at 15:25 -> Clean overnight
    t_mon_m10_natural = datetime(2026, 11, 2, 15, 15, tzinfo=IST)  # closes at 15:25
    seq_m10_natural = [
        _make_candle(t_mon_m10_natural, CandleInterval.M10),
        _make_candle(t_tue_open, CandleInterval.M10),
    ]
    res_m10_natural = validate_candle_sequence(seq_m10_natural, expected_interval=CandleInterval.M10)
    assert not res_m10_natural.has_error(DataQualityErrorCode.MISSING_INTERVAL)


# ============================================================================
# Priority 2: Historical Freshness
# ============================================================================


def test_priority2_historical_mode_validates_future_timestamps() -> None:
    """Verify that historical mode disables live staleness, but enforces future timestamp validation."""
    t0 = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    # Candle 0 is in 2024, but Candle 1 is stamped in the future relative to eval_now
    eval_now = datetime(2024, 6, 3, 10, 0, tzinfo=IST)
    t_future = datetime(2024, 6, 3, 10, 5, tzinfo=IST)  # open_time > eval_now

    records = [
        _make_raw_record(t0.isoformat()),
        _make_raw_record(t_future.isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t_future + timedelta(minutes=5),
    )
    # The historical request has a candle in the future relative to eval_now
    res = pipeline.ingest_historical(req, now=eval_now)
    assert res.success is False
    assert res.error_code in ("RETRIEVAL_AFTER_NOW", "QUALITY_GATE_REJECTED")


def test_priority2_boundary_end_time_equal_now_enforces_live_freshness() -> None:
    """Verify that end_time == now enforces live FreshnessPolicy staleness checking."""
    # When request.end_time == now, this is a query covering current time, not past backfill
    t_now = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    # Provider returns stale data ending at 09:15 (15m old for 1m candle -> exceeds 3m limit)
    t_stale = datetime(2026, 11, 2, 9, 14, tzinfo=IST)
    records = [_make_raw_record(t_stale.isoformat(), interval="1m")]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M1,
        start_time=t_stale,
        end_time=t_now,  # end_time == now
    )
    res = pipeline.ingest_historical(req, now=t_now)
    assert res.success is False
    assert res.error_code in ("QUALITY_GATE_REJECTED", "TRUNCATED_COVERAGE")
    assert res.validation_result is not None
    assert res.validation_result.has_error(DataQualityErrorCode.STALE_DATA)


def test_priority2_boundary_end_time_less_than_now_skips_live_staleness() -> None:
    """Verify that end_time < now is treated as a historical backfill that skips live staleness."""
    # Backfill from 2 years ago evaluated at wall-clock 2026
    t0_2024 = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    records = [
        _make_raw_record((t0_2024 + timedelta(minutes=5 * i)).isoformat())
        for i in range(3)
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0_2024,
        end_time=t0_2024 + timedelta(minutes=15),
    )
    now_2026 = datetime(2026, 11, 2, 18, 0, tzinfo=IST)
    res = pipeline.ingest_historical(req, now=now_2026)
    assert res.success is True
    assert len(res.candles) == 3


def test_priority2_pipeline_rejects_future_retrieval_timestamp_at_boundary() -> None:
    """Verify pipeline boundary rejects responses whose retrieval_timestamp > now."""
    eval_now = datetime(2026, 11, 2, 10, 0, tzinfo=IST)
    future_ret = eval_now + timedelta(minutes=5)

    class FutureRetProvider(SyntheticMarketDataProvider):
        def fetch_historical(self, req: HistoricalDataRequest) -> ProviderResponse:
            resp = super().fetch_historical(req)
            return ProviderResponse(
                success=True,
                source=self.source_name,
                records=resp.records,
                retrieval_timestamp=future_ret,  # in the future!
            )

    provider = FutureRetProvider()
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
        end_time=datetime(2026, 11, 2, 9, 30, tzinfo=IST),
    )
    res = pipeline.ingest_historical(req, now=eval_now)
    assert res.success is False
    assert res.error_code == "RETRIEVAL_AFTER_NOW"


# ============================================================================
# Priority 3: Recursive Immutability & Shared DAGs
# ============================================================================


def test_priority3_shared_dag_freezes_in_linear_time() -> None:
    """Verify that deep freezing a binary shared DAG is linear O(V) and does not blow up exponentially."""
    # Build a 15-level diamond DAG where child is referenced twice at each level:
    # 2^15 = 32,768 paths without memoization!
    curr: Any = {"leaf": 42}
    for i in range(14):
        curr = {"level": i, "left": curr, "right": curr}

    start = py_time.perf_counter()
    frozen = mod_deep_freeze(curr)
    elapsed = py_time.perf_counter() - start

    assert elapsed < 0.1, f"Freezing shared DAG took too long ({elapsed:.4f}s), exponential blowup detected"
    assert frozen["level"] == 13
    assert frozen["left"]["level"] == 12


def test_priority3_preserves_cycle_detection_on_active_stack() -> None:
    """Verify that cyclical references on the active call stack are rejected immediately."""
    cyclic_dict: dict[str, Any] = {"name": "cycle"}
    cyclic_dict["self"] = cyclic_dict

    with pytest.raises(ValueError, match="Cyclical reference detected"):
        mod_deep_freeze(cyclic_dict)


def test_priority3_bounds_recursion_depth_and_node_budget() -> None:
    """Verify that excessive depth (>16) and excessive node count (>10,000) are bounded."""
    # Depth limit test
    deep_dict: dict[str, Any] = {"val": 0}
    curr = deep_dict
    for _ in range(25):
        curr["child"] = {"val": 1}
        curr = curr["child"]
    with pytest.raises(ValueError, match="Maximum nesting depth"):
        mod_deep_freeze(deep_dict)

    # Node count budget test
    large_list = list(range(12_000))
    with pytest.raises(ValueError, match="Maximum node count"):
        mod_deep_freeze(large_list)


def test_priority3_unifies_freeze_implementations() -> None:
    """Verify that _deep_freeze across models, quality, provider, and ingestion are identical."""
    assert mod_deep_freeze is qual_deep_freeze
    assert mod_deep_freeze is prov_deep_freeze
    assert mod_deep_freeze is ing_deep_freeze


# ============================================================================
# Priority 4: Coverage & Result Consistency
# ============================================================================


def test_priority4_distinguishes_truncated_coverage_from_market_calendar_required() -> None:
    """Verify distinction between known TRUNCATED_COVERAGE and ambiguous MARKET_CALENDAR_REQUIRED."""
    # 1. Known truncated coverage: Missing intraday candle within same continuous session
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records_intraday_gap = [
        _make_raw_record(t0.isoformat()),
        _make_raw_record((t0 + timedelta(minutes=10)).isoformat()),  # 09:20 missing
    ]
    pipe = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=records_intraday_gap))
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )
    res_gap = pipe.ingest_historical(req, now=t0 + timedelta(minutes=20), require_full_coverage=True, check_gaps=False)
    assert res_gap.success is False
    assert res_gap.error_code == "TRUNCATED_COVERAGE"
    assert res_gap.coverage_status == "TRUNCATED_COVERAGE"

    # 2. Ambiguous multi-day gap (weekend Friday 15:25 to Monday 09:15) with require_full_coverage=False
    # Both boundaries intact, both sessions clean, but weekend requires calendar evidence
    t_fri = datetime(2026, 10, 30, 15, 25, tzinfo=IST)  # closes 15:30
    t_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records_weekend = [
        _make_raw_record(t_fri.isoformat()),
        _make_raw_record(t_mon.isoformat()),
    ]
    pipe_wk = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=records_weekend))
    req_wk = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t_fri,
        end_time=t_mon + timedelta(minutes=5),
    )
    res_wk = pipe_wk.ingest_historical(req_wk, now=t_mon + timedelta(minutes=20), require_full_coverage=False, check_gaps=False)
    assert res_wk.coverage_status == "MARKET_CALENDAR_REQUIRED"


def test_priority4_result_invariants_across_all_paths() -> None:
    """Verify that success, candles, error_code, and coverage_status maintain strict invariants."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [_make_raw_record(t0.isoformat())]
    pipe = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=records))
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=5),
    )

    # Successful result invariant: success=True, candles tuple, no error fields
    res_success = pipe.ingest_historical(req, now=t0 + timedelta(minutes=10))
    assert res_success.success is True
    assert len(res_success.candles) == 1
    assert res_success.error_code is None
    assert res_success.error_message is None
    assert res_success.coverage_status in ("COVERAGE_UNVERIFIED", "MARKET_CALENDAR_REQUIRED")

    # Failed result invariant: success=False, candles empty tuple, non-empty error fields
    # (Since 0 records for other requested range or truncated)
    req_trunc = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),  # requested 6 bars, returned 1
    )
    res_trunc = pipe.ingest_historical(req_trunc, now=t0 + timedelta(minutes=35), require_full_coverage=True)
    assert res_trunc.success is False
    assert res_trunc.candles == ()
    assert res_trunc.error_code is not None
    assert res_trunc.error_message is not None


# ============================================================================
# Priority 5: Additional Confirmed Defects
# ============================================================================


def test_priority5_d1_close_time_non_zero_duration() -> None:
    """Verify D1 close_time returns strictly positive duration for all timestamp edge cases."""
    # 1. Bar opened at 09:15 IST closes at 15:30 IST on same date -> duration = 6h 15m > 0
    t_0915 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    c_0915 = _make_candle(t_0915, CandleInterval.D1)
    assert c_0915.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)
    assert c_0915.close_time > c_0915.timestamp

    # 2. Bar opened at 15:30:00 IST -> returns nominal 24h close, duration = 24h > 0
    t_1530 = datetime(2026, 11, 2, 15, 30, 0, tzinfo=IST)
    c_1530 = _make_candle(t_1530, CandleInterval.D1)
    assert c_1530.close_time == t_1530 + timedelta(days=1)
    assert c_1530.close_time > c_1530.timestamp

    # 3. Bar opened at 15:30:15 IST -> returns nominal 24h close, duration = 24h > 0 (NOT 15:30:00)
    t_153015 = datetime(2026, 11, 2, 15, 30, 15, tzinfo=IST)
    c_153015 = _make_candle(t_153015, CandleInterval.D1)
    assert c_153015.close_time == t_153015 + timedelta(days=1)
    assert c_153015.close_time > c_153015.timestamp


def test_priority5_whitespace_padded_numeric_input_strictly_rejected() -> None:
    """Verify that whitespace-padded numbers are strictly rejected under strict validation."""
    adapter = StandardDictAdapter(source_name="SYNTHETIC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # 1. Adapter price with whitespace padding
    raw_ws_price = _make_raw_record("2026-11-02T09:15:00+05:30", open_p=" 2500.00 ")
    with pytest.raises(RawDataValidationError, match="whitespace padding"):
        adapter.adapt_record(raw_ws_price, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 2. Adapter volume with whitespace padding
    raw_ws_vol = _make_raw_record("2026-11-02T09:15:00+05:30")
    raw_ws_vol["volume"] = " 1000 "
    with pytest.raises(RawDataValidationError, match="whitespace padding"):
        adapter.adapt_record(raw_ws_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 3. Model price validation with whitespace padding
    with pytest.raises(ValueError, match="whitespace padding"):
        _validate_finite_decimal(" 2500.00 ", "open")

    # 4. Model volume validation with whitespace padding
    with pytest.raises(ValueError, match="whitespace padding"):
        _validate_volume(" 1000 ")


def test_priority5_freshness_policy_hashability_and_dataclass_compat() -> None:
    """Verify FreshnessPolicy is hashable, usable in sets/dict keys, and implements clean equality."""
    p1 = FreshnessPolicy()
    p2 = FreshnessPolicy()
    p_custom = FreshnessPolicy({CandleInterval.M5: timedelta(minutes=10)})

    # 1. Deterministic hashing without TypeError: unhashable type
    h1 = hash(p1)
    h2 = hash(p2)
    assert h1 == h2
    assert isinstance(h1, int)

    # 2. Set usage
    policy_set = {p1, p2, p_custom}
    assert len(policy_set) == 2  # p1 and p2 deduplicate

    # 3. Dict key usage
    policy_dict = {p1: "default", p_custom: "custom"}
    assert policy_dict[p2] == "default"

    # 4. Equality semantics
    assert p1 == p2
    assert p1 != p_custom
    assert p1 != "not_a_policy"
