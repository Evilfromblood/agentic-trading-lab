"""Unit tests for Milestone 2b Market Data Ingestion and Provider Integration Foundation.

Verifies:
- Successful synthetic ingestion (single latest and historical sequences).
- Valid NSE/BSE-style candles.
- Invalid provider payloads (missing fields, wrong types, floats, NaN, negative volume).
- Missing provenance.
- Stale candles and future timestamps.
- Duplicate and conflicting candle rejection.
- Out-of-order sequence detection.
- Provider errors, timeouts, and empty responses.
- Rejection by the authoritative M2a validation layer.
- Deterministic output across repeated runs without network calls.
- Risk engine isolation boundary.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from agentic_trading.market_data import (
    IST,
    Candle,
    CandleInterval,
    DataQualityErrorCode,
    Exchange,
    FreshnessPolicy,
    HistoricalDataRequest,
    IngestionResult,
    MarketCalendarRequiredError,
    MarketDataIngestionPipeline,
    MarketDataProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderPayloadError,
    ProviderResponse,
    ProviderTimeoutError,
    RawDataValidationError,
    SequenceIngestionResult,
    StandardDictAdapter,
    SyntheticMarketDataProvider,
    UnsupportedIntervalFreshnessError,
    ValidationResult,
)
from agentic_trading.risk_engine import OrderProposal, Side, evaluate_order


class _UnfilteredRawProvider(MarketDataProvider):
    """Raw provider that bypasses SyntheticMarketDataProvider filtering for pipeline failure tests."""

    def __init__(self, records: Sequence[Mapping[str, Any]], source_name: str = "SYNTHETIC_NSE") -> None:
        self._records = tuple(records)
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
        return ProviderResponse(
            success=True,
            source=self._source_name,
            retrieval_timestamp=request.end_time,
            records=self._records,
        )

    def fetch_latest(
        self,
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        now: datetime | None = None,
    ) -> ProviderResponse:
        t = now or datetime.now(timezone.utc)
        return ProviderResponse(
            success=True,
            source=self._source_name,
            retrieval_timestamp=t,
            records=self._records,
        )


def _build_raw_record(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    interval: str = "5m",
    timestamp: str = "2026-11-02T09:15:00+05:30",
    open_price: str = "2500.00",
    high_price: str = "2515.00",
    low_price: str = "2495.00",
    close_price: str = "2510.00",
    volume: int = 50000,
    **overrides: Any,
) -> dict[str, Any]:
    """Helper to construct raw provider dictionary payloads."""
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
    }
    rec.update(overrides)
    return rec


# ============================================================================
# 1. Successful Synthetic Ingestion (Single & Historical)
# ============================================================================


def test_successful_synthetic_ingestion_single_candle() -> None:
    """Verify ingestion of a single valid latest completed NSE candle."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(
        symbol="RELIANCE",
        timestamp=t0.isoformat(),
        open_price="2500.00",
        high_price="2515.00",
        low_price="2495.00",
        close_price="2510.00",
        volume=120000,
    )
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now = t0 + timedelta(minutes=6)
    result = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now,
        max_staleness=timedelta(minutes=15),
    )

    assert result.success is True
    assert result.candle is not None
    assert result.candle.symbol == "RELIANCE"
    assert result.candle.exchange == Exchange.NSE
    assert result.candle.interval == CandleInterval.M5
    assert result.candle.open == Decimal("2500.00")
    assert result.candle.close == Decimal("2510.00")
    assert result.candle.volume == 120000
    assert result.candle.source == "SYNTHETIC_NSE"
    assert result.validation_result is not None
    assert result.validation_result.is_valid is True


def test_successful_synthetic_ingestion_historical_sequence() -> None:
    """Verify ingestion and M2a sequence validation of continuous historical NSE bars."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    provider = SyntheticMarketDataProvider.create_sample_series(
        symbol="TCS",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        count=6,
    )
    pipeline = MarketDataIngestionPipeline(provider)

    request = HistoricalDataRequest(
        symbol="TCS",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
    )

    eval_now = t0 + timedelta(minutes=35)
    result = pipeline.ingest_historical(
        request=request,
        now=eval_now,
        max_staleness=timedelta(minutes=20),
    )

    assert result.success is True
    assert len(result.candles) == 6
    assert result.raw_record_count == 6
    assert result.validation_result is not None
    assert result.validation_result.is_valid is True


# ============================================================================
# 2. Valid BSE-style Candles Ingestion
# ============================================================================


def test_valid_bse_style_candles_ingestion() -> None:
    """Verify provider ingestion handles BSE equity records correctly."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw_bse = _build_raw_record(
        symbol="INFY",
        exchange="BSE",
        timestamp=t0.isoformat(),
        open_price="1800.00",
        high_price="1810.00",
        low_price="1795.00",
        close_price="1805.00",
    )
    provider = SyntheticMarketDataProvider(records=[raw_bse])
    pipeline = MarketDataIngestionPipeline(provider)

    result = pipeline.ingest_latest(
        symbol="INFY",
        exchange=Exchange.BSE,
        interval=CandleInterval.M5,
        now=t0 + timedelta(minutes=6),
    )

    assert result.success is True
    assert result.candle is not None
    assert result.candle.exchange == Exchange.BSE
    assert result.validation_result is not None
    assert result.validation_result.is_valid is True


# ============================================================================
# 3. Invalid Provider Payloads (Raw Data Validation)
# ============================================================================


def test_invalid_provider_payloads_missing_fields_fail_closed() -> None:
    """Verify raw payloads missing essential fields fail closed at adapter level."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # Missing 'high'
    raw_no_high = {"open": "100", "low": "90", "close": "95", "volume": 100, "timestamp": "2026-11-02T09:15:00+05:30"}
    with pytest.raises(RawDataValidationError, match="Missing required field 'high'"):
        adapter.adapt_record(raw_no_high, "TCS", Exchange.NSE, CandleInterval.M5, t_ret)

    # Missing timestamp
    raw_no_ts = {"open": "100", "high": "110", "low": "90", "close": "95", "volume": 100}
    with pytest.raises(RawDataValidationError, match="Missing timestamp/date field"):
        adapter.adapt_record(raw_no_ts, "TCS", Exchange.NSE, CandleInterval.M5, t_ret)


def test_invalid_provider_payloads_types_and_numbers_fail_closed() -> None:
    """Verify raw payloads with floats, booleans, NaN, and negative volume fail closed."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # Float price rejected to prevent precision degradation
    raw_float = _build_raw_record(open_price=2500.50)  # float
    with pytest.raises(RawDataValidationError, match="cannot be float"):
        adapter.adapt_record(raw_float, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Boolean price rejected
    raw_bool = _build_raw_record(open_price=True)
    with pytest.raises(RawDataValidationError, match="cannot be boolean"):
        adapter.adapt_record(raw_bool, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Non-finite price rejected
    raw_nan = _build_raw_record(open_price="NaN")
    with pytest.raises(RawDataValidationError, match="must be finite|invalid numeric format"):
        adapter.adapt_record(raw_nan, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Negative volume rejected
    raw_neg_vol = _build_raw_record(volume=-100)
    with pytest.raises(RawDataValidationError, match="cannot be negative|invalid integer format"):
        adapter.adapt_record(raw_neg_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Naive timestamp string rejected
    raw_naive = _build_raw_record(timestamp="2026-11-02T09:15:00")  # no tz offset
    with pytest.raises(RawDataValidationError, match="must be timezone-aware"):
        adapter.adapt_record(raw_naive, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)


# ============================================================================
# 4. Pipeline Rejection of Stale and Future-Dated Candles
# ============================================================================


def test_stale_candle_rejected_by_pipeline() -> None:
    """Verify pipeline detects and rejects stale candles via the M2a quality gate."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())  # Closes at 09:20:00 IST
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    # Evaluated at 09:35:00 (15 min after close) with 5 min max staleness
    eval_now = t0 + timedelta(minutes=20)
    result = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now,
        max_staleness=timedelta(minutes=5),
    )

    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.STALE_DATA)


def test_future_candle_rejected_by_pipeline() -> None:
    """Verify pipeline rejects future-dated candles via the M2a quality gate."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = _UnfilteredRawProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    # Reference time is prior to candle open (09:10:00 IST)
    prior_now = t0 - timedelta(minutes=5)
    result = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=prior_now,
    )

    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.FUTURE_CANDLE)


# ============================================================================
# 5. Duplicate, Conflicting, and Out-of-Order Sequences
# ============================================================================


def test_duplicate_and_conflicting_historical_records_rejected() -> None:
    """Verify duplicate and conflicting records are detected during historical ingestion."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    rec1 = _build_raw_record(timestamp=t0.isoformat(), close_price="2500.00")
    rec2_identical = _build_raw_record(timestamp=t0.isoformat(), close_price="2500.00")
    rec2_conflicting = _build_raw_record(timestamp=t0.isoformat(), close_price="2520.00")

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=10),
    )

    # 1. Identical duplicates
    p_dup = SyntheticMarketDataProvider(records=[rec1, rec2_identical])
    pipe_dup = MarketDataIngestionPipeline(p_dup)
    res_dup = pipe_dup.ingest_historical(req, now=t0 + timedelta(minutes=10))
    assert res_dup.success is False
    assert res_dup.validation_result is not None
    assert res_dup.validation_result.has_error(DataQualityErrorCode.DUPLICATE_CANDLE)

    # 2. Conflicting duplicates
    p_conf = SyntheticMarketDataProvider(records=[rec1, rec2_conflicting])
    pipe_conf = MarketDataIngestionPipeline(p_conf)
    res_conf = pipe_conf.ingest_historical(req, now=t0 + timedelta(minutes=10))
    assert res_conf.success is False
    assert res_conf.validation_result is not None
    assert res_conf.validation_result.has_error(DataQualityErrorCode.CONFLICTING_DUPLICATE_DATA)


def test_out_of_order_historical_records_rejected() -> None:
    """Verify non-chronological records fail closed with NON_MONOTONIC_SEQUENCE."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    rec0 = _build_raw_record(timestamp=t0.isoformat())
    rec1 = _build_raw_record(timestamp=t1.isoformat())

    # Feed out-of-order: rec1 (09:20) before rec0 (09:15)
    provider = SyntheticMarketDataProvider(records=[rec1, rec0])
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
    )
    result = pipeline.ingest_historical(req, now=t0 + timedelta(minutes=30))

    assert result.success is False
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.NON_MONOTONIC_SEQUENCE)


def test_missing_intervals_detected_in_historical_ingestion() -> None:
    """Verify intraday gaps in provider payloads fail closed with MISSING_INTERVAL."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t2 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)  # Missing 09:20 and 09:25

    rec0 = _build_raw_record(timestamp=t0.isoformat())
    rec2 = _build_raw_record(timestamp=t2.isoformat())

    provider = SyntheticMarketDataProvider(records=[rec0, rec2])
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=35),
    )
    result = pipeline.ingest_historical(req, now=t0 + timedelta(minutes=35))

    assert result.success is False
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


# ============================================================================
# 6. Provider Errors, Timeouts, and Empty Responses
# ============================================================================


def test_provider_timeouts_and_errors_fail_closed() -> None:
    """Verify provider timeouts, errors, and empty responses fail closed gracefully."""
    provider = SyntheticMarketDataProvider()
    pipeline = MarketDataIngestionPipeline(provider)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    eval_now = t0 + timedelta(minutes=35)
    req = HistoricalDataRequest(
        symbol="TCS",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
    )

    # 1. Timeout simulation
    provider.set_failure_mode(simulate_timeout=True)
    res_to = pipeline.ingest_latest("TCS", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_to.success is False
    assert res_to.error_code == "TIMEOUT"

    res_to_hist = pipeline.ingest_historical(req, now=eval_now)
    assert res_to_hist.success is False
    assert res_to_hist.error_code == "TIMEOUT"

    # 2. Provider error simulation
    provider.set_failure_mode(simulate_error="Exchange upstream unavailable")
    res_err = pipeline.ingest_latest("TCS", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_err.success is False
    assert res_err.error_code == "PROVIDER_ERROR"

    # 3. Empty response simulation
    provider.set_failure_mode(simulate_timeout=False, simulate_error=None)
    provider.set_records([])
    res_empty = pipeline.ingest_latest("TCS", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_empty.success is False
    assert res_empty.error_code == "EMPTY_PROVIDER_RESPONSE"

    res_empty_hist = pipeline.ingest_historical(req, now=eval_now)
    assert res_empty_hist.success is False
    assert res_empty_hist.error_code == "EMPTY_PROVIDER_RESPONSE"
    assert res_empty_hist.coverage_status == "EMPTY_COVERAGE"


# ============================================================================
# 7. Determinism Across Repeated Runs
# ============================================================================


def test_deterministic_output_across_repeated_runs() -> None:
    """Verify ingestion pipeline produces byte-for-byte and value-for-value identical results."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    provider = SyntheticMarketDataProvider.create_sample_series(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        count=4,
    )
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=20),
    )
    eval_now = t0 + timedelta(minutes=25)

    results = [
        pipeline.ingest_historical(req, now=eval_now)
        for _ in range(5)
    ]

    base = results[0]
    for res in results[1:]:
        assert res.success == base.success
        assert len(res.candles) == len(base.candles)
        for c1, c2 in zip(res.candles, base.candles, strict=True):
            assert c1 == c2


# ============================================================================
# 8. Risk Engine Isolation Boundary
# ============================================================================


def test_risk_engine_isolation_boundary_with_ingestion() -> None:
    """Verify risk engine isolation and document integration boundary with ingestion pipeline.

    Integration Boundary Analysis:
    - The ingestion pipeline produces `IngestionResult` containing validated `Candle` objects.
    - The deterministic `evaluate_order()` risk engine operates strictly on `OrderProposal`.
    - No direct order placement or broker execution is permitted from the market data ingestion layer.
    - If unvalidated, stale, or malformed provider data fails ingestion, an order proposal cannot
      be formed from validated data.
    """
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    provider = SyntheticMarketDataProvider(records=[_build_raw_record(timestamp=t0.isoformat())])
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now = t0 + timedelta(minutes=6)
    ingest_res = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert ingest_res.success is True
    assert ingest_res.candle is not None

    # Safe order workflow pattern: only construct proposal from validated ingestion candle
    proposal = OrderProposal(
        symbol=ingest_res.candle.symbol,
        side=Side.BUY,
        quantity=2,
        limit_price=ingest_res.candle.close,
        available_cash=Decimal("50000.00"),
        portfolio_equity=Decimal("200000.00"),
    )
    decision = evaluate_order(proposal)
    assert decision.approved is True
    assert decision.order_notional == Decimal("5020.00")


# ============================================================================
# 9. Audit Finding Regression Tests
# ============================================================================


# ----------------------------------------------------------------------------
# Finding M-1: Payload Identity Mismatch & Malformed Identifiers
# ----------------------------------------------------------------------------


def test_adapter_accepts_matching_payload_identity_fields() -> None:
    """Verify adapter succeeds when raw payload contains matching identity fields."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)
    raw = _build_raw_record(
        symbol="RELIANCE",
        exchange="NSE",
        interval="5m",
        timestamp="2026-11-02T09:15:00+05:30",
    )
    candle = adapter.adapt_record(
        raw_record=raw,
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        retrieval_timestamp=t_ret,
    )
    assert candle.symbol == "RELIANCE"
    assert candle.exchange == Exchange.NSE
    assert candle.interval == CandleInterval.M5


def test_adapter_accepts_payload_without_optional_identity_fields() -> None:
    """Verify adapter succeeds when raw payload omits symbol/exchange/interval."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)
    raw = {
        "timestamp": "2026-11-02T09:15:00+05:30",
        "open": "2500.00",
        "high": "2515.00",
        "low": "2495.00",
        "close": "2510.00",
        "volume": 1000,
    }
    candle = adapter.adapt_record(
        raw_record=raw,
        symbol="INFY",
        exchange=Exchange.BSE,
        interval=CandleInterval.M15,
        retrieval_timestamp=t_ret,
    )
    assert candle.symbol == "INFY"
    assert candle.exchange == Exchange.BSE
    assert candle.interval == CandleInterval.M15


def test_adapter_rejects_contradictory_payload_identifiers() -> None:
    """Verify adapter fails closed when raw payload identity fields contradict request."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # 1. Contradictory symbol
    raw_bad_sym = _build_raw_record(symbol="TCS")
    with pytest.raises(RawDataValidationError, match="contradicts requested symbol"):
        adapter.adapt_record(raw_bad_sym, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 2. Contradictory exchange
    raw_bad_ex = _build_raw_record(exchange="BSE")
    with pytest.raises(RawDataValidationError, match="contradicts requested exchange"):
        adapter.adapt_record(raw_bad_ex, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 3. Contradictory interval
    raw_bad_iv = _build_raw_record(interval="15m")
    with pytest.raises(RawDataValidationError, match="contradicts requested interval"):
        adapter.adapt_record(raw_bad_iv, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)


def test_adapter_rejects_malformed_payload_identifier_types() -> None:
    """Verify adapter fails closed on non-string, unrecognized, or empty identity fields."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # Malformed symbol: empty, whitespace, integer, None
    for bad_sym in ("", "   ", 123, None):
        raw = _build_raw_record(symbol=bad_sym)
        with pytest.raises(RawDataValidationError, match="invalid symbol"):
            adapter.adapt_record(raw, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Malformed exchange: unrecognized string, integer, None
    for bad_ex in ("NASDAQ", 999, None):
        raw = _build_raw_record(exchange=bad_ex)
        with pytest.raises(RawDataValidationError, match="exchange"):
            adapter.adapt_record(raw, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Malformed interval: unrecognized string, integer, None
    for bad_iv in ("99m", 123, None):
        raw = _build_raw_record(interval=bad_iv)
        with pytest.raises(RawDataValidationError, match="interval"):
            adapter.adapt_record(raw, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)


# ----------------------------------------------------------------------------
# Finding L-1: Timezone Validation in HistoricalDataRequest
# ----------------------------------------------------------------------------


def test_historical_request_timezone_validation_fail_closed() -> None:
    """Verify HistoricalDataRequest strictly validates timezone awareness and exception safety."""
    from datetime import tzinfo

    t_valid = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_end = datetime(2026, 11, 2, 9, 30, tzinfo=IST)

    # 1. Naive datetime rejected
    naive_dt = datetime(2026, 11, 2, 9, 15)
    with pytest.raises(ValueError, match="must be a timezone-aware datetime"):
        HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, naive_dt, t_end)
    with pytest.raises(ValueError, match="must be a timezone-aware datetime"):
        HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t_valid, naive_dt)

    # 2. Timezone with utcoffset() returning None rejected
    class DummyNoneOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            return None

        def dst(self, dt: datetime | None) -> timedelta | None:
            return timedelta(0)

        def tzname(self, dt: datetime | None) -> str:
            return "DummyNoneOffset"

    dt_none_offset = datetime(2026, 11, 2, 9, 15, tzinfo=DummyNoneOffset())
    with pytest.raises(ValueError, match="utcoffset returned None"):
        HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, dt_none_offset, t_end)

    # 3. Timezone that raises on utcoffset calculation rejected
    class CrashingTz(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            raise RuntimeError("Corrupt timezone calculation")

        def dst(self, dt: datetime | None) -> timedelta | None:
            return timedelta(0)

        def tzname(self, dt: datetime | None) -> str:
            return "CrashingTz"

    dt_crashing = datetime(2026, 11, 2, 9, 15, tzinfo=CrashingTz())
    with pytest.raises(ValueError, match="timezone calculation failed"):
        HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, dt_crashing, t_end)

    # 4. Valid timezone-aware datetimes succeed
    req = HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t_valid, t_end)
    assert req.start_time == t_valid
    assert req.end_time == t_end


# ----------------------------------------------------------------------------
# Finding L-2: Synthetic Historical Range Filtering
# ----------------------------------------------------------------------------


def test_synthetic_provider_historical_range_filtering() -> None:
    """Verify SyntheticMarketDataProvider.fetch_historical filters by [start_time, end_time)."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    step = timedelta(minutes=5)

    # Construct records across boundaries:
    # 09:10 (before start)
    # 09:15 (start boundary - included)
    # 09:20 (inside range - included)
    # 09:25 (inside range - included)
    # 09:30 (end boundary - excluded)
    # 09:35 (after end - excluded)
    rec_before = _build_raw_record(timestamp=(t0 - step).isoformat())
    rec_start = _build_raw_record(timestamp=t0.isoformat())
    rec_in1 = _build_raw_record(timestamp=(t0 + step).isoformat())
    rec_in2 = _build_raw_record(timestamp=(t0 + (step * 2)).isoformat())
    rec_end_boundary = _build_raw_record(timestamp=(t0 + (step * 3)).isoformat())
    rec_after = _build_raw_record(timestamp=(t0 + (step * 4)).isoformat())

    all_records = [rec_before, rec_start, rec_in1, rec_in2, rec_end_boundary, rec_after]
    provider = SyntheticMarketDataProvider(records=all_records)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,  # 09:15
        end_time=t0 + (step * 3),  # 09:30
    )

    resp = provider.fetch_historical(req)
    assert resp.success is True
    # Exactly 3 records in [09:15, 09:30): 09:15, 09:20, 09:25
    assert len(resp.records) == 3
    assert resp.records[0]["timestamp"] == t0.isoformat()
    assert resp.records[1]["timestamp"] == (t0 + step).isoformat()
    assert resp.records[2]["timestamp"] == (t0 + (step * 2)).isoformat()


# ----------------------------------------------------------------------------
# Finding L-3: Latest-Record Contract & Ambiguity Resolution
# ----------------------------------------------------------------------------


def test_ingest_latest_resolves_ordered_and_unordered_records() -> None:
    """Verify ingest_latest resolves the newest record whether records are ordered or unordered."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t1 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    rec_0915 = _build_raw_record(timestamp=t0.isoformat(), close_price="2500.00")
    rec_0920 = _build_raw_record(timestamp=t1.isoformat(), close_price="2510.00")

    # 1. Single record
    p1 = SyntheticMarketDataProvider(records=[rec_0915])
    pipe1 = MarketDataIngestionPipeline(p1)
    res1 = pipe1.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=t0 + timedelta(minutes=6))
    assert res1.success is True
    assert res1.candle is not None
    assert res1.candle.close == Decimal("2500.00")

    # 2. Multiple ordered records [09:15, 09:20] -> selects 09:20
    p2 = SyntheticMarketDataProvider(records=[rec_0915, rec_0920])
    pipe2 = MarketDataIngestionPipeline(p2)
    res2 = pipe2.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=t1 + timedelta(minutes=6))
    assert res2.success is True
    assert res2.candle is not None
    assert res2.candle.close == Decimal("2510.00")

    # 3. Multiple unordered records [09:20, 09:15] -> correctly selects 09:20 (not blindly last element)
    p3 = SyntheticMarketDataProvider(records=[rec_0920, rec_0915])
    pipe3 = MarketDataIngestionPipeline(p3)
    res3 = pipe3.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=t1 + timedelta(minutes=6))
    assert res3.success is True
    assert res3.candle is not None
    assert res3.candle.close == Decimal("2510.00")


def test_ingest_latest_fails_closed_on_ambiguous_or_duplicate_max_timestamp() -> None:
    """Verify ingest_latest fails closed when multiple records share the maximum timestamp or have unparseable ts."""
    t0 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    rec_a = _build_raw_record(timestamp=t0.isoformat(), close_price="2500.00")
    rec_b = _build_raw_record(timestamp=t0.isoformat(), close_price="2515.00")

    # Two records sharing max timestamp (conflicting or duplicate)
    provider = SyntheticMarketDataProvider(records=[rec_a, rec_b])
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now = t0 + timedelta(minutes=6)
    res = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res.success is False
    assert res.error_code == "AMBIGUOUS_LATEST_RECORD"
    assert "ambiguous latest record" in (res.error_message or "").lower()

    # Records with missing timestamp among multiple records
    rec_no_ts = {"open": "2500", "high": "2510", "low": "2490", "close": "2505", "volume": 100}
    p_unparseable = _UnfilteredRawProvider(records=[rec_a, rec_no_ts])
    pipe_unparseable = MarketDataIngestionPipeline(p_unparseable)

    res_unparseable = pipe_unparseable.ingest_latest(
        "RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now
    )
    assert res_unparseable.success is False
    assert res_unparseable.error_code == "AMBIGUOUS_LATEST_RECORD"


# ============================================================================
# 10. M2b Audit Finding H1 Regression Tests: Fail-Closed Staleness and Timing
# ============================================================================


def test_h1_2020_candle_evaluated_in_2026_rejected_as_stale() -> None:
    """Verify that a 2020 candle evaluated with reference now in 2026 is rejected as STALE_DATA."""
    t_2020 = datetime(2020, 3, 23, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t_2020.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now_2026 = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    result = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now_2026,
    )

    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.STALE_DATA)
    assert result.candle is None


def test_h1_future_candle_rejected_as_future() -> None:
    """Verify that a candle timestamped in the future relative to now is rejected as FUTURE_CANDLE."""
    t_future = datetime(2026, 11, 2, 10, 0, tzinfo=IST)
    raw = _build_raw_record(timestamp=t_future.isoformat())
    provider = _UnfilteredRawProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now = datetime(2026, 11, 2, 9, 30, tzinfo=IST)
    result = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now,
    )

    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.validation_result is not None
    assert result.validation_result.has_error(DataQualityErrorCode.FUTURE_CANDLE)
    assert result.candle is None


def test_h1_now_none_rejected_in_all_paths() -> None:
    """Verify that now=None is strictly rejected with ValueError across all three ingestion paths."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )

    # 1. ingest_latest
    with pytest.raises(ValueError, match="'now' timestamp is required and cannot be None"):
        pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=None)

    # 2. ingest_historical
    with pytest.raises(ValueError, match="'now' timestamp is required and cannot be None"):
        pipeline.ingest_historical(req, now=None)

    # 3. ingest_record
    with pytest.raises(ValueError, match="'now' timestamp is required and cannot be None"):
        pipeline.ingest_record(
            raw_record=raw,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            retrieval_timestamp=t0 + timedelta(minutes=6),
            now=None,
        )


def test_h1_naive_now_rejected_in_all_paths() -> None:
    """Verify that naive now is strictly rejected with ValueError across all three ingestion paths."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )
    naive_now = datetime(2026, 11, 2, 9, 30)

    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=naive_now)

    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        pipeline.ingest_historical(req, now=naive_now)

    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        pipeline.ingest_record(
            raw_record=raw,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            retrieval_timestamp=t0 + timedelta(minutes=6),
            now=naive_now,
        )


def test_h1_crashing_tzinfo_now_rejected_in_all_paths() -> None:
    """Verify that now with a crashing tzinfo implementation raises ValueError across all paths."""
    from datetime import tzinfo

    class CrashingTz(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            raise RuntimeError("Corrupt tz calculation")

        def dst(self, dt: datetime | None) -> timedelta | None:
            return timedelta(0)

        def tzname(self, dt: datetime | None) -> str:
            return "CrashingTz"

    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )
    crashing_now = datetime(2026, 11, 2, 9, 30, tzinfo=CrashingTz())

    with pytest.raises(ValueError, match="now timezone calculation failed"):
        pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=crashing_now)

    with pytest.raises(ValueError, match="now timezone calculation failed"):
        pipeline.ingest_historical(req, now=crashing_now)

    with pytest.raises(ValueError, match="now timezone calculation failed"):
        pipeline.ingest_record(
            raw_record=raw,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            retrieval_timestamp=t0 + timedelta(minutes=6),
            now=crashing_now,
        )


def test_h1_explicit_custom_max_staleness_and_default_policy() -> None:
    """Verify that interval-aware freshness policy applies when omitted and custom threshold is honored."""
    policy = FreshnessPolicy()
    assert policy.get_max_staleness(CandleInterval.M5) == timedelta(minutes=15)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)  # Closes at 09:20 IST
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    # 1. 20 minutes after close: exceeds M5 15 min threshold -> rejected as STALE_DATA
    eval_now_20m = t0 + timedelta(minutes=5 + 20)  # 09:40 IST
    res_default = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now_20m,
        max_staleness=None,  # Should use FreshnessPolicy (15 min for M5)
    )
    assert res_default.success is False
    assert res_default.validation_result is not None
    assert res_default.validation_result.has_error(DataQualityErrorCode.STALE_DATA)

    # 2. Same 20 minutes with explicit custom max_staleness=timedelta(hours=1) -> accepted
    res_custom = pipeline.ingest_latest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        now=eval_now_20m,
        max_staleness=timedelta(hours=1),
    )
    assert res_custom.success is True
    assert res_custom.candle is not None


# ============================================================================
# 11. M2b Audit Finding H2 Regression Tests: Historical Window Enforcement
# ============================================================================


def test_h2_historical_ingestion_rejects_record_before_start_time() -> None:
    """Verify that historical ingestion fails closed if provider returns a record before start_time."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    step = timedelta(minutes=5)

    rec_early = _build_raw_record(timestamp=(t0 - step).isoformat())
    rec_valid = _build_raw_record(timestamp=t0.isoformat())

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + (step * 2),
    )

    class EarlyRecordProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "TEST_EARLY"

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source=self.source_name,
                retrieval_timestamp=request.end_time,
                records=(rec_early, rec_valid),
            )

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            raise NotImplementedError

    pipeline = MarketDataIngestionPipeline(EarlyRecordProvider())
    eval_now = t0 + timedelta(minutes=20)
    result = pipeline.ingest_historical(req, now=eval_now)

    assert result.success is False
    assert result.error_code == "BOUNDARY_VIOLATION"
    assert "is before request start time" in (result.error_message or "") or "violates request window" in (result.error_message or "")
    assert result.coverage_status == "COVERAGE_UNVERIFIED"
    assert result.candles == ()


def test_h2_historical_ingestion_rejects_record_at_exact_end_time_boundary() -> None:
    """Verify that a record at exactly request.end_time is rejected (convention [start_time, end_time))."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    step = timedelta(minutes=5)
    t_end = t0 + (step * 2)  # 09:25

    rec_valid = _build_raw_record(timestamp=t0.isoformat())
    rec_at_end = _build_raw_record(timestamp=t_end.isoformat())

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t_end,
    )

    class BoundaryRecordProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "TEST_BOUNDARY"

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source=self.source_name,
                retrieval_timestamp=request.end_time,
                records=(rec_valid, rec_at_end),
            )

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            raise NotImplementedError

    pipeline = MarketDataIngestionPipeline(BoundaryRecordProvider())
    result = pipeline.ingest_historical(req, now=t_end + timedelta(minutes=5))

    assert result.success is False
    assert result.error_code == "BOUNDARY_VIOLATION"
    assert "is at or after request end time" in (result.error_message or "") or "violates request window" in (result.error_message or "")
    assert result.coverage_status == "COVERAGE_UNVERIFIED"


def test_h2_historical_ingestion_rejects_record_after_end_time() -> None:
    """Verify that a record after request.end_time is rejected with BOUNDARY_VIOLATION."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    step = timedelta(minutes=5)
    t_end = t0 + step  # 09:20

    rec_valid = _build_raw_record(timestamp=t0.isoformat())
    rec_late = _build_raw_record(timestamp=(t_end + step).isoformat())

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t_end,
    )

    class LateRecordProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "TEST_LATE"

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source=self.source_name,
                retrieval_timestamp=request.end_time,
                records=(rec_valid, rec_late),
            )

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            raise NotImplementedError

    pipeline = MarketDataIngestionPipeline(LateRecordProvider())
    result = pipeline.ingest_historical(req, now=t_end + timedelta(minutes=20))

    assert result.success is False
    assert result.error_code == "BOUNDARY_VIOLATION"
    assert result.coverage_status == "COVERAGE_UNVERIFIED"


def test_h2_coverage_status_is_always_unverified() -> None:
    """Verify that coverage_status is always COVERAGE_UNVERIFIED and never VERIFIED without an exchange calendar."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    provider = SyntheticMarketDataProvider.create_sample_series(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        count=3,
    )
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )

    result = pipeline.ingest_historical(req, now=t0 + timedelta(minutes=20))
    assert result.success is True
    assert result.coverage_status == "COVERAGE_UNVERIFIED"
    assert result.coverage_status != "VERIFIED"


# ============================================================================
# 12. M2b Audit Finding M1 Regression Tests: Identity-less Raw Payloads
# ============================================================================


def test_m1_adapter_require_payload_identity_true_rejects_missing_fields() -> None:
    """Verify that StandardDictAdapter(require_payload_identity=True) rejects missing identity fields."""
    adapter = StandardDictAdapter(source_name="TEST_SRC", require_payload_identity=True)
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # Missing symbol
    raw_no_sym = _build_raw_record()
    del raw_no_sym["symbol"]
    with pytest.raises(RawDataValidationError, match="Required identity field 'symbol' is missing"):
        adapter.adapt_record(raw_no_sym, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Missing exchange
    raw_no_ex = _build_raw_record()
    del raw_no_ex["exchange"]
    with pytest.raises(RawDataValidationError, match="Required identity field 'exchange' is missing"):
        adapter.adapt_record(raw_no_ex, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Missing interval
    raw_no_iv = _build_raw_record()
    del raw_no_iv["interval"]
    with pytest.raises(RawDataValidationError, match="Required identity field 'interval' is missing"):
        adapter.adapt_record(raw_no_iv, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)


def test_m1_pipeline_default_adapter_enforces_require_payload_identity() -> None:
    """Verify that MarketDataIngestionPipeline automatically configures require_payload_identity=True by default."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Raw record without symbol field
    raw_anonymous = {
        "timestamp": t0.isoformat(),
        "open": "2500.00",
        "high": "2510.00",
        "low": "2490.00",
        "close": "2505.00",
        "volume": 1000,
    }
    provider = _UnfilteredRawProvider(records=[raw_anonymous])
    # Pipeline without explicit adapter uses default StandardDictAdapter with require_payload_identity=True
    pipeline = MarketDataIngestionPipeline(provider)

    eval_now = t0 + timedelta(minutes=6)
    result = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)

    assert result.success is False
    assert result.error_code == "RAW_VALIDATION_ERROR"
    assert "Required identity field" in (result.error_message or "")


# ============================================================================
# 13. M2b Audit Finding M2 Regression Tests: Provider Exceptions & Validation
# ============================================================================


def test_m2_pipeline_catches_provider_exceptions() -> None:
    """Verify that provider exceptions (timeout, connection, arbitrary) are caught and returned as structured failures."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    eval_now = t0 + timedelta(minutes=10)

    class ThrowingProvider(MarketDataProvider):
        def __init__(self, exc_to_raise: Exception) -> None:
            self._exc = exc_to_raise

        @property
        def source_name(self) -> str:
            return "THROWING_PROVIDER"

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            raise self._exc

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            raise self._exc

    # 1. ProviderTimeoutError
    pipe_to = MarketDataIngestionPipeline(ThrowingProvider(ProviderTimeoutError("Socket timeout")))
    res_to = pipe_to.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_to.success is False
    assert res_to.error_code == "TIMEOUT"
    assert "Socket timeout" in (res_to.error_message or "")

    # 2. ProviderConnectionError
    pipe_conn = MarketDataIngestionPipeline(ThrowingProvider(ProviderConnectionError("Connection refused")))
    res_conn = pipe_conn.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_conn.success is False
    assert res_conn.error_code == "PROVIDER_CONNECTION_ERROR"

    # 3. ProviderPayloadError
    pipe_pay = MarketDataIngestionPipeline(ThrowingProvider(ProviderPayloadError("Unparseable JSON")))
    res_pay = pipe_pay.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_pay.success is False
    assert res_pay.error_code == "PROVIDER_PAYLOAD_ERROR"

    # 4. Base ProviderError
    pipe_base = MarketDataIngestionPipeline(ThrowingProvider(ProviderError("Generic failure")))
    res_base = pipe_base.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_base.success is False
    assert res_base.error_code == "PROVIDER_ERROR"

    # 5. Arbitrary unexpected Exception
    pipe_arb = MarketDataIngestionPipeline(ThrowingProvider(RuntimeError("Fatal kernel crash")))
    res_arb = pipe_arb.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_arb.success is False
    assert res_arb.error_code == "PROVIDER_EXCEPTION"
    assert "Fatal kernel crash" in (res_arb.error_message or "")

    # Same exception handling for historical ingestion
    req = HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=10))
    res_hist_arb = pipe_arb.ingest_historical(req, now=eval_now)
    assert res_hist_arb.success is False
    assert res_hist_arb.error_code == "PROVIDER_EXCEPTION"


def test_m2_pipeline_rejects_non_provider_response_and_invalid_retrieval_ts() -> None:
    """Verify that pipeline rejects non-ProviderResponse objects and invalid retrieval timestamps."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    eval_now = t0 + timedelta(minutes=10)

    # 1. Provider returns a dict instead of ProviderResponse
    class NonEnvelopeProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "NON_ENVELOPE"

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> Any:
            return {"status": "ok", "candles": []}

        def fetch_historical(self, request: HistoricalDataRequest) -> Any:
            return {"status": "ok", "candles": []}

    pipe_non_env = MarketDataIngestionPipeline(NonEnvelopeProvider())
    res_non_env = pipe_non_env.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_non_env.success is False
    assert res_non_env.error_code == "INVALID_PROVIDER_RESPONSE"


# ============================================================================
# 14. M2b Audit Finding M3 Regression Tests: Timezone Safety
# ============================================================================


def test_m3_timezone_safety_helpers_and_models() -> None:
    """Verify timezone validation across _require_valid_tz_dt, ProviderResponse, and HistoricalDataRequest."""
    from agentic_trading.market_data.provider import _require_valid_tz_dt

    t_valid = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    assert _require_valid_tz_dt(t_valid, "test") == t_valid

    # Naive datetime
    naive_dt = datetime(2026, 11, 2, 9, 15)
    with pytest.raises(ValueError, match="test must be a timezone-aware datetime"):
        _require_valid_tz_dt(naive_dt, "test")

    # Non-datetime
    for bad_val in (None, 12345, "2026-11-02", True):
        with pytest.raises(ValueError, match="test must be a timezone-aware datetime"):
            _require_valid_tz_dt(bad_val, "test")

    # ProviderResponse rejecting naive retrieval_timestamp
    with pytest.raises(ValueError, match="retrieval_timestamp must be a timezone-aware datetime"):
        ProviderResponse(success=True, source="TEST", retrieval_timestamp=naive_dt)


# ============================================================================
# 15. M2b Audit Finding M4 Regression Tests: Provenance Correctness
# ============================================================================


def test_m4_adapter_provenance_validation_and_stamping() -> None:
    """Verify adapter validates raw payload source when present and stamps configured source when absent."""
    adapter = StandardDictAdapter(source_name="EXPECTED_SOURCE")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # 1. Matching source in payload -> accepted
    raw_matching = _build_raw_record(source="EXPECTED_SOURCE")
    candle_matching = adapter.adapt_record(raw_matching, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_matching.source == "EXPECTED_SOURCE"

    # 2. Contradictory source in payload -> rejected with RawDataValidationError
    raw_contradictory = _build_raw_record(source="ROGUE_FEED")
    with pytest.raises(RawDataValidationError, match="Payload source 'ROGUE_FEED' contradicts expected source"):
        adapter.adapt_record(raw_contradictory, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 3. Source absent from payload -> stamped with adapter's configured source
    raw_no_source = _build_raw_record()
    if "source" in raw_no_source:
        del raw_no_source["source"]
    candle_stamped = adapter.adapt_record(raw_no_source, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_stamped.source == "EXPECTED_SOURCE"


# ============================================================================
# 16. M2b Audit Finding M5 Regression Tests: Result Invariants & Immutability
# ============================================================================


def test_m5_ingestion_result_internal_consistency_invariants() -> None:
    """Verify that IngestionResult and SequenceIngestionResult enforce strict internal consistency."""
    from types import MappingProxyType

    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    valid_candle = Candle(
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

    # 1. Successful IngestionResult cannot have error fields
    with pytest.raises(ValueError, match="Successful IngestionResult cannot have error_message"):
        IngestionResult(success=True, candle=valid_candle, error_message="error")

    # 2. Successful IngestionResult must have a candle
    with pytest.raises(ValueError, match="Successful IngestionResult must contain a valid candle"):
        IngestionResult(success=True, candle=None)

    # 3. Failed IngestionResult cannot expose a candle
    with pytest.raises(ValueError, match="Failed IngestionResult cannot expose a valid candle"):
        IngestionResult(success=False, candle=valid_candle, error_message="rejected", error_code="ERR")

    # 4. Failed IngestionResult must have error details
    with pytest.raises(ValueError, match="Failed IngestionResult must contain an error_message"):
        IngestionResult(success=False, error_code="ERR")

    # 5. Raw record is deep-frozen as MappingProxyType
    mutable_raw = {"open": "2500.00"}
    res = IngestionResult(success=True, candle=valid_candle, validation_result=ValidationResult(is_valid=True), raw_record=mutable_raw)
    assert isinstance(res.raw_record, MappingProxyType)
    # Modifying original dict does not mutate the frozen proxy dict content
    mutable_raw["open"] = "9999.00"
    assert res.raw_record["open"] == "2500.00"

    # 6. SequenceIngestionResult invariants
    with pytest.raises(ValueError, match="Successful SequenceIngestionResult cannot have error_message"):
        SequenceIngestionResult(success=True, candles=(valid_candle,), validation_result=ValidationResult(is_valid=True), raw_record_count=1, error_message="err")

    with pytest.raises(ValueError, match="Successful SequenceIngestionResult must contain at least one candle"):
        SequenceIngestionResult(success=True, candles=(), validation_result=ValidationResult(is_valid=True))

    with pytest.raises(ValueError, match="Failed SequenceIngestionResult cannot expose valid candles"):
        SequenceIngestionResult(success=False, candles=(valid_candle,), error_message="err", error_code="ERR")


# ============================================================================
# 17. M2b Low-Severity Audit Finding Regression Tests
# ============================================================================


def test_low_synthetic_fetch_latest_requires_explicit_now_when_empty() -> None:
    """Verify SyntheticMarketDataProvider.fetch_latest raises ValueError if now is None and records are empty."""
    provider = SyntheticMarketDataProvider(records=[])
    with pytest.raises(ValueError, match="fetch_latest requires an explicit 'now' timestamp"):
        provider.fetch_latest("TCS", Exchange.NSE, CandleInterval.M5, now=None)


def test_low_synthetic_fetch_historical_excludes_unparseable_timestamps() -> None:
    """Verify SyntheticMarketDataProvider.fetch_historical skips records with missing/unparseable timestamps."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    step = timedelta(minutes=5)
    rec_valid = _build_raw_record(timestamp=t0.isoformat())
    rec_bad_ts = _build_raw_record(timestamp="not-a-timestamp")
    rec_no_ts = {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "open": "2500", "close": "2510", "high": "2515", "low": "2495", "volume": 100}

    provider = SyntheticMarketDataProvider(records=[rec_valid, rec_bad_ts, rec_no_ts])
    req = HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t0, t0 + (step * 2))

    resp = provider.fetch_historical(req)
    assert resp.success is True
    # Only rec_valid is matched; the unparseable/missing records are excluded
    assert len(resp.records) == 1
    assert resp.records[0]["timestamp"] == t0.isoformat()


def test_low_synthetic_provider_filters_by_exchange_and_interval() -> None:
    """Verify SyntheticMarketDataProvider filters stored records by exchange and interval."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    rec_nse_5m = _build_raw_record(exchange="NSE", interval="5m", timestamp=t0.isoformat())
    rec_bse_5m = _build_raw_record(exchange="BSE", interval="5m", timestamp=t0.isoformat())
    rec_nse_15m = _build_raw_record(exchange="NSE", interval="15m", timestamp=t0.isoformat())

    provider = SyntheticMarketDataProvider(records=[rec_nse_5m, rec_bse_5m, rec_nse_15m])

    # 1. Historical filter
    req = HistoricalDataRequest("RELIANCE", Exchange.NSE, CandleInterval.M5, t0, t0 + timedelta(minutes=10))
    resp_hist = provider.fetch_historical(req)
    assert len(resp_hist.records) == 1
    assert resp_hist.records[0]["exchange"] == "NSE"
    assert resp_hist.records[0]["interval"] == "5m"

    # 2. Latest filter
    resp_latest = provider.fetch_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=t0 + timedelta(minutes=6))
    assert len(resp_latest.records) == 1
    assert resp_latest.records[0]["exchange"] == "NSE"


def test_low_adapter_rejects_conflicting_timestamp_aliases() -> None:
    """Verify adapter rejects raw records with conflicting timestamp and date fields."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # 1. Conflicting timestamp vs date
    raw_conflict = _build_raw_record(
        timestamp="2026-11-02T09:15:00+05:30",
        date="2026-11-02T09:20:00+05:30",
    )
    with pytest.raises(RawDataValidationError, match="Conflicting timestamp fields in raw payload"):
        adapter.adapt_record(raw_conflict, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 2. Consistent timestamp and date aliases succeed
    raw_consistent = _build_raw_record(
        timestamp="2026-11-02T09:15:00+05:30",
        date="2026-11-02T09:15:00+05:30",
    )
    candle = adapter.adapt_record(raw_consistent, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle.timestamp == datetime(2026, 11, 2, 9, 15, tzinfo=IST)


# ============================================================================
# 16. Final Five-Defect Remediation Regression Tests (M4, H2, M5, L5, H1)
# ============================================================================


def test_m4_pipeline_rejects_forged_provider_response_source() -> None:
    """Verify that ProviderResponse.source is validated and forged source is rejected."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())

    class ForgedResponseProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "NSE_AUTHORITATIVE"

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source="FORGED_FEED",  # Contradicts self.source_name
                retrieval_timestamp=t0 + timedelta(minutes=6),
                records=(raw,),
            )

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source="FORGED_FEED",  # Contradicts self.source_name
                retrieval_timestamp=request.end_time,
                records=(raw,),
            )

    provider = ForgedResponseProvider()
    pipeline = MarketDataIngestionPipeline(provider)
    eval_now = t0 + timedelta(minutes=6)

    # 1. Latest ingestion rejects forged response source
    res_latest = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_latest.success is False
    assert res_latest.error_code == "PROVENANCE_MISMATCH"
    assert "does not match provider source_name" in (res_latest.error_message or "")

    # 2. Historical ingestion rejects forged response source
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=10),
    )
    res_hist = pipeline.ingest_historical(req, now=eval_now)
    assert res_hist.success is False
    assert res_hist.error_code == "PROVENANCE_MISMATCH"
    assert "does not match provider source_name" in (res_hist.error_message or "")


def test_m4_pipeline_rejects_mismatched_adapter_source() -> None:
    """Verify that pipeline rejects mismatched adapter source_name against provider/response."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(source_name="NSE_DIRECT", records=[raw])
    adapter = StandardDictAdapter(source_name="BSE_BACKUP")  # Mismatched source
    pipeline = MarketDataIngestionPipeline(provider=provider, adapter=adapter)
    eval_now = t0 + timedelta(minutes=6)

    # 1. ingest_latest rejects adapter mismatch
    res_latest = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res_latest.success is False
    assert res_latest.error_code == "PROVENANCE_MISMATCH"
    assert "does not match adapter source_name" in (res_latest.error_message or "")

    # 2. ingest_historical rejects adapter mismatch
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=10),
    )
    res_hist = pipeline.ingest_historical(req, now=eval_now)
    assert res_hist.success is False
    assert res_hist.error_code == "PROVENANCE_MISMATCH"
    assert "does not match adapter source_name" in (res_hist.error_message or "")

    # 3. ingest_record rejects adapter mismatch
    res_rec = pipeline.ingest_record(
        raw_record=raw,
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        retrieval_timestamp=eval_now,
        now=eval_now,
    )
    assert res_rec.success is False
    assert res_rec.error_code == "PROVENANCE_MISMATCH"


def test_m4_pipeline_accepts_valid_matching_provenance() -> None:
    """Verify that valid matching provenance is preserved without silent relabeling."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(timestamp=t0.isoformat(), source="NSE_FEED")
    provider = SyntheticMarketDataProvider(source_name="NSE_FEED", records=[raw])
    adapter = StandardDictAdapter(source_name="NSE_FEED")
    pipeline = MarketDataIngestionPipeline(provider=provider, adapter=adapter)
    eval_now = t0 + timedelta(minutes=6)

    res = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M5, now=eval_now)
    assert res.success is True
    assert res.candle is not None
    assert res.candle.source == "NSE_FEED"


def test_h2_historical_ingestion_accepts_exact_start_and_exact_end() -> None:
    """Verify that a candle starting exactly at start_time and closing at end_time is valid."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(interval="15m", timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),  # Close time is exactly 09:30
    )
    eval_now = t0 + timedelta(minutes=20)
    result = pipeline.ingest_historical(req, now=eval_now)

    assert result.success is True
    assert len(result.candles) == 1
    assert result.candles[0].timestamp == req.start_time
    assert result.candles[0].close_time == req.end_time


def test_h2_historical_ingestion_rejects_candle_closing_after_window_end() -> None:
    """Verify that a candle starting inside window but closing after end_time is rejected."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Candle opens at 09:20 (inside window [09:15, 09:30)) with 15m duration -> closes at 09:35 > 09:30
    c_open = t0 + timedelta(minutes=5)
    raw = _build_raw_record(interval="15m", timestamp=c_open.isoformat())

    class OvershootingCandleProvider(MarketDataProvider):
        @property
        def source_name(self) -> str:
            return "SYNTHETIC_PROVIDER"

        def fetch_latest(self, symbol: str, exchange: Exchange, interval: CandleInterval, now: datetime | None = None) -> ProviderResponse:
            raise NotImplementedError

        def fetch_historical(self, request: HistoricalDataRequest) -> ProviderResponse:
            return ProviderResponse(
                success=True,
                source=self.source_name,
                retrieval_timestamp=request.end_time,
                records=(raw,),
            )

    pipeline = MarketDataIngestionPipeline(OvershootingCandleProvider())
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),  # 09:30
    )
    result = pipeline.ingest_historical(req, now=t0 + timedelta(minutes=40))

    assert result.success is False
    assert result.error_code == "BOUNDARY_VIOLATION"
    assert "close time" in (result.error_message or "")
    assert "exceeds request end time" in (result.error_message or "")


def test_m5_recursive_immutability_and_mutation_isolation() -> None:
    """Verify that IngestionResult.raw_record and ProviderResponse.records are recursively immutable."""
    raw_payload = {
        "symbol": "RELIANCE",
        "open": "2500.00",
        "nested_dict": {"exchange_code": "NSE", "sub": {"depth": 1}},
        "nested_list": ["tag1", "tag2"],
        "nested_set": {"alpha", "beta"},
    }

    t_now = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    result = IngestionResult(
        success=False,
        error_message="Test failure",
        error_code="TEST_ERROR",
        raw_record=raw_payload,
        retrieval_timestamp=t_now,
    )

    # 1. Top-level mapping proxy rejects assignment
    with pytest.raises(TypeError):
        result.raw_record["symbol"] = "INFY"  # type: ignore[index]

    # 2. Nested dictionary is frozen into mappingproxy and rejects assignment
    assert isinstance(result.raw_record["nested_dict"], Mapping)
    with pytest.raises(TypeError):
        result.raw_record["nested_dict"]["exchange_code"] = "BSE"  # type: ignore[index]

    # 3. Deeply nested dictionary is also frozen
    with pytest.raises(TypeError):
        result.raw_record["nested_dict"]["sub"]["depth"] = 2  # type: ignore[index]

    # 4. Nested list is converted to immutable tuple
    assert isinstance(result.raw_record["nested_list"], tuple)
    with pytest.raises(AttributeError):
        result.raw_record["nested_list"].append("tag3")  # type: ignore[union-attr]

    # 5. Nested set is converted to frozenset
    assert isinstance(result.raw_record["nested_set"], frozenset)
    with pytest.raises(AttributeError):
        result.raw_record["nested_set"].add("gamma")  # type: ignore[union-attr]

    # 6. Mutating original caller payload AFTER ingestion does not alter result
    raw_payload["nested_dict"]["exchange_code"] = "MUTATED"
    raw_payload["nested_list"].append("MUTATED")
    assert result.raw_record["nested_dict"]["exchange_code"] == "NSE"
    assert "MUTATED" not in result.raw_record["nested_list"]


def test_m5_unsupported_mutable_types_rejected() -> None:
    """Verify that unsupported mutable objects in raw_record trigger a TypeError."""
    t_now = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    unsupported_payload = {
        "symbol": "RELIANCE",
        "custom_buf": bytearray(b"raw_bytes"),  # Mutable bytearray
    }
    with pytest.raises(TypeError, match="Unsupported mutable or unhandled type"):
        IngestionResult(
            success=False,
            error_message="Error",
            error_code="ERR",
            raw_record=unsupported_payload,
            retrieval_timestamp=t_now,
        )


def test_l5_strict_price_parsing_rules() -> None:
    """Verify strict price parsing: ASCII digits only, no Unicode numerals, no underscores, no NaN/inf."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    # 1. Unicode digits rejected (Devanagari numerals)
    raw_unicode = _build_raw_record(open_price="१२३.४५")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_unicode, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 2. Underscores rejected
    raw_underscore = _build_raw_record(open_price="2_500.00")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_underscore, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 3. Malformed signs rejected (+ sign, - sign, duplicate signs)
    raw_plus = _build_raw_record(open_price="+2500.00")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_plus, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    raw_minus = _build_raw_record(open_price="-2500.00")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_minus, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 4. Scientific notation rejected
    raw_sci = _build_raw_record(open_price="2.5e3")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_sci, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 5. Malformed decimal notation rejected (trailing dot, leading dot)
    raw_trail_dot = _build_raw_record(open_price="2500.")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_trail_dot, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    raw_lead_dot = _build_raw_record(open_price=".50")
    with pytest.raises(RawDataValidationError, match="invalid numeric format"):
        adapter.adapt_record(raw_lead_dot, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 6. NaN and Infinity rejected
    for non_finite in ("NaN", "Infinity", "-Infinity"):
        raw_nf = _build_raw_record(open_price=non_finite)
        with pytest.raises(RawDataValidationError, match="invalid numeric format"):
            adapter.adapt_record(raw_nf, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 7. Huge digit string exceeding MAX_PRICE_STR_LENGTH (18 chars)
    raw_huge_str = _build_raw_record(open_price="9999999999999999999")  # 19 digits
    with pytest.raises(RawDataValidationError, match="exceeds maximum allowed length"):
        adapter.adapt_record(raw_huge_str, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 8. Out of domain bounds: price > 10,000,000 or price <= 0
    raw_excess_val = _build_raw_record(open_price="10000001.00")
    with pytest.raises(RawDataValidationError, match="outside valid domain limits"):
        adapter.adapt_record(raw_excess_val, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    raw_zero_val = _build_raw_record(open_price="0.00")
    with pytest.raises(RawDataValidationError, match="outside valid domain limits"):
        adapter.adapt_record(raw_zero_val, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 9. Valid boundary values and exact Decimal precision
    raw_min_valid = _build_raw_record(
        open_price="0.0001",
        high_price="0.0002",
        low_price="0.0001",
        close_price="0.0002",
    )
    candle_min = adapter.adapt_record(raw_min_valid, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_min.open == Decimal("0.0001")

    raw_max_valid = _build_raw_record(
        open_price="10000000.00",
        high_price="10000000.00",
        low_price="9999999.00",
        close_price="10000000.00",
    )
    candle_max = adapter.adapt_record(raw_max_valid, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_max.open == Decimal("10000000.00")


def test_l5_strict_volume_parsing_rules() -> None:
    """Verify strict volume parsing: ASCII digits only, no Unicode numerals, no underscores, bounds."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 20, tzinfo=IST)

    # 1. Unicode numerals rejected in volume
    raw_unicode_vol = _build_raw_record(volume="१०००")
    with pytest.raises(RawDataValidationError, match="invalid integer format"):
        adapter.adapt_record(raw_unicode_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 2. Underscores rejected in volume
    raw_underscore_vol = _build_raw_record(volume="10_000")
    with pytest.raises(RawDataValidationError, match="invalid integer format"):
        adapter.adapt_record(raw_underscore_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 3. Signs rejected in volume (+ sign, - sign)
    raw_plus_vol = _build_raw_record(volume="+500")
    with pytest.raises(RawDataValidationError, match="invalid integer format"):
        adapter.adapt_record(raw_plus_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 4. Fractional units rejected
    raw_frac_vol = _build_raw_record(volume=Decimal("500.5"))
    with pytest.raises(RawDataValidationError, match="cannot have fractional units"):
        adapter.adapt_record(raw_frac_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 5. Huge volume string length > 15
    raw_huge_vol_str = _build_raw_record(volume="9999999999999999")  # 16 chars
    with pytest.raises(RawDataValidationError, match="exceeds maximum allowed length"):
        adapter.adapt_record(raw_huge_vol_str, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # 6. Volume bounds: 0 to 10,000,000,000,000
    raw_zero_vol = _build_raw_record(volume=0)
    candle_zero = adapter.adapt_record(raw_zero_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_zero.volume == 0

    raw_max_vol = _build_raw_record(volume=10_000_000_000_000)
    candle_max = adapter.adapt_record(raw_max_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle_max.volume == 10_000_000_000_000


def test_h1_interval_aware_freshness_policy_matrix() -> None:
    """Verify explicit interval-aware staleness thresholds across all supported intervals."""
    policy = FreshnessPolicy()

    # M1: 3 minutes
    assert policy.get_max_staleness(CandleInterval.M1) == timedelta(minutes=3)
    # M3: 9 minutes
    assert policy.get_max_staleness(CandleInterval.M3) == timedelta(minutes=9)
    # M5: 15 minutes
    assert policy.get_max_staleness(CandleInterval.M5) == timedelta(minutes=15)
    # M10: 20 minutes
    assert policy.get_max_staleness(CandleInterval.M10) == timedelta(minutes=20)
    # M15: 30 minutes
    assert policy.get_max_staleness(CandleInterval.M15) == timedelta(minutes=30)
    # M30: 60 minutes
    assert policy.get_max_staleness(CandleInterval.M30) == timedelta(minutes=60)
    # H1: 120 minutes (2 hours)
    assert policy.get_max_staleness(CandleInterval.H1) == timedelta(hours=2)


def test_h1_freshness_policy_m1_cannot_become_arbitrarily_stale() -> None:
    """Verify that M1 data rejects candles older than 3 minutes, preventing arbitrary staleness."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)  # Closes at 09:16:00
    raw = _build_raw_record(interval="1m", timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)

    # 1. Evaluated 2 minutes after close (09:18:00) -> fresh
    res_fresh = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M1, now=t0 + timedelta(minutes=3))
    assert res_fresh.success is True
    assert res_fresh.candle is not None

    # 2. Evaluated 4 minutes after close (09:20:00) -> stale
    res_stale = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.M1, now=t0 + timedelta(minutes=5))
    assert res_stale.success is False
    assert res_stale.validation_result is not None
    assert res_stale.validation_result.has_error(DataQualityErrorCode.STALE_DATA)


def test_h1_freshness_policy_d1_eod_and_consecutive_weekday() -> None:
    """Verify D1 freshness: valid post-close EOD analysis and consecutive weekday pre-market."""
    # Monday 2026-11-02 daily session bar: timestamp 09:15 IST (session open)
    mon_open = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw_mon = _build_raw_record(
        interval="1d",
        timestamp=mon_open.isoformat(),
    )
    provider_mon = SyntheticMarketDataProvider(records=[raw_mon])
    pipeline_mon = MarketDataIngestionPipeline(provider_mon)

    # 1a. Evaluated at 18:30 IST on Monday (3h post-close EOD analysis) -> fresh!
    # Daily candle close is 15:30 IST on session date; at 18:30 IST bar is complete and fresh.
    eod_now = datetime(2026, 11, 2, 18, 30, tzinfo=IST)
    res_eod = pipeline_mon.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=eod_now)
    assert res_eod.success is True
    assert res_eod.candle is not None
    assert res_eod.candle.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)
    assert res_eod.candle.open_time == mon_open

    # 1b. Also verify daily candle with midnight timestamp (00:00 IST) closes at 15:30 IST
    raw_mon_midnight = _build_raw_record(
        interval="1d",
        timestamp="2026-11-02T00:00:00+05:30",
    )
    p_mid = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=[raw_mon_midnight]))
    res_mid = p_mid.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=eod_now)
    assert res_mid.success is True
    assert res_mid.candle is not None
    assert res_mid.candle.close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)

    # 1c. Evaluated Tuesday morning pre-market at 08:30 IST (17h post-close, consecutive weekday) -> fresh!
    premarket_now = datetime(2026, 11, 3, 8, 30, tzinfo=IST)
    res_pre = pipeline_mon.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=premarket_now)
    assert res_pre.success is True
    assert res_pre.candle is not None

    # 1d. Evaluated Wednesday morning at 10:00 IST (skipping Tuesday, 2 calendar days elapsed):
    # Without exchange calendar evidence, multi-day gap fails closed with MARKET_CALENDAR_REQUIRED.
    wed_now = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    with pytest.raises(MarketCalendarRequiredError, match="requires reliable exchange calendar evidence"):
        pipeline_mon.freshness_policy.get_max_staleness(
            CandleInterval.D1,
            now=wed_now,
            candle_close_time=res_eod.candle.close_time,
        )
    res_wed = pipeline_mon.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=wed_now)
    assert res_wed.success is False
    assert res_wed.error_code == "MARKET_CALENDAR_REQUIRED"
    assert "requires reliable exchange calendar evidence" in (res_wed.error_message or "")


def test_d1_freshness_friday_weekend_fails_closed_without_calendar() -> None:
    """Verify that Friday daily candle evaluated on Sunday fails closed without exchange calendar.

    Prevents accepting Friday data on Sunday when newer data (e.g. Diwali Muhurat trading
    or disaster recovery mock trading) could exist.
    """
    fri_open = datetime(2026, 11, 6, 9, 15, tzinfo=IST)  # Friday
    raw_fri = _build_raw_record(
        interval="1d",
        timestamp=fri_open.isoformat(),
    )
    provider_fri = SyntheticMarketDataProvider(records=[raw_fri])
    pipeline_fri = MarketDataIngestionPipeline(provider_fri)

    # 1. Evaluated Friday evening post-close (18:30 IST) -> same-day, succeeds!
    fri_eod = datetime(2026, 11, 6, 18, 30, tzinfo=IST)
    res_fri_eod = pipeline_fri.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=fri_eod)
    assert res_fri_eod.success is True

    # 2. Evaluated Sunday evening at 18:00 IST:
    # Fails closed because exchange calendar evidence is required to establish whether Sunday traded.
    sun_now = datetime(2026, 11, 8, 18, 0, tzinfo=IST)
    res_sun = pipeline_fri.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=sun_now)
    assert res_sun.success is False
    assert res_sun.error_code == "MARKET_CALENDAR_REQUIRED"
    assert "requires reliable exchange calendar evidence" in (res_sun.error_message or "")

    # 3. If caller explicitly provides max_staleness override (e.g. 72h), ingestion succeeds
    res_override = pipeline_fri.ingest_latest(
        "RELIANCE",
        Exchange.NSE,
        CandleInterval.D1,
        now=sun_now,
        max_staleness=timedelta(hours=72),
    )
    assert res_override.success is True
    assert res_override.candle is not None


def test_d1_freshness_friday_tuesday_holiday_scenario() -> None:
    """Verify that Friday candle evaluated on Tuesday (Monday-holiday) reports calendar required.

    Does NOT falsely report STALE_DATA by guessing a 72h weekend limit when Monday was a holiday.
    With an explicit caller staleness override (e.g. 96h), the Friday candle is accepted.
    """
    fri_open = datetime(2026, 11, 6, 9, 15, tzinfo=IST)  # Friday
    raw_fri = _build_raw_record(
        interval="1d",
        timestamp=fri_open.isoformat(),
    )
    provider_fri = SyntheticMarketDataProvider(records=[raw_fri])
    pipeline_fri = MarketDataIngestionPipeline(provider_fri)

    # Tuesday morning pre-market at 08:30 IST (Monday was a national holiday)
    tue_holiday_now = datetime(2026, 11, 10, 8, 30, tzinfo=IST)

    # 1. Without calendar evidence, pipeline reports MARKET_CALENDAR_REQUIRED (not false STALE_DATA)
    res_tue = pipeline_fri.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=tue_holiday_now)
    assert res_tue.success is False
    assert res_tue.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res_tue.validation_result is None  # Never reached M2a quality gate with false stale error

    # 2. When caller has calendar context and supplies explicit 96h staleness override, ingestion succeeds
    res_with_override = pipeline_fri.ingest_latest(
        "RELIANCE",
        Exchange.NSE,
        CandleInterval.D1,
        now=tue_holiday_now,
        max_staleness=timedelta(hours=96),
    )
    assert res_with_override.success is True
    assert res_with_override.candle is not None
    assert res_with_override.candle.symbol == "RELIANCE"


def test_python311_dataclass_default_compatibility() -> None:
    """Verify that FreshnessPolicy dataclass declaration is fully compatible with Python 3.11.

    In Python 3.11, default values in dataclasses cannot be instances of unhashable types
    such as MappingProxyType. Using field(default_factory=...) ensures compatibility.
    """
    # 1. Field default is MISSING and default_factory is callable
    fields = {f.name: f for f in dataclasses.fields(FreshnessPolicy)}
    assert "custom_limits" in fields
    f_limits = fields["custom_limits"]
    assert f_limits.default is dataclasses.MISSING
    assert callable(f_limits.default_factory)
    assert f_limits.default_factory() == {}

    # 2. Instantiation with default arguments produces immutable MappingProxy
    policy_default = FreshnessPolicy()
    assert isinstance(policy_default.custom_limits, Mapping)
    assert len(policy_default.custom_limits) == 0

    # 3. Instantiation with custom limits works properly
    custom = FreshnessPolicy(custom_limits={CandleInterval.D1: timedelta(hours=48)})
    assert custom.get_max_staleness(CandleInterval.D1) == timedelta(hours=48)


def test_h1_freshness_policy_unsupported_intervals_fail_closed() -> None:
    """Verify that unsupported intervals fail closed without explicit configuration."""
    policy = FreshnessPolicy()
    with pytest.raises(UnsupportedIntervalFreshnessError, match="does not support interval '1w'"):
        policy.get_max_staleness(CandleInterval.W1)

    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(interval="1w", timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider)
    eval_now = t0 + timedelta(days=8)

    # Fails closed on W1 without custom configuration
    res = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.W1, now=eval_now)
    assert res.success is False
    assert res.error_code == "UNSUPPORTED_FRESHNESS_INTERVAL"
    assert "Freshness policy does not support interval '1w'" in (res.error_message or "")


def test_h1_freshness_policy_custom_configuration() -> None:
    """Verify that custom interval limits configure successfully and allow ingestion."""
    custom_policy = FreshnessPolicy(
        custom_limits={
            CandleInterval.W1: timedelta(days=10),
        }
    )
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw = _build_raw_record(interval="1w", timestamp=t0.isoformat())
    provider = SyntheticMarketDataProvider(records=[raw])
    pipeline = MarketDataIngestionPipeline(provider, freshness_policy=custom_policy)

    # Ingestion succeeds with configured custom freshness policy
    eval_now = t0 + timedelta(days=8)
    res = pipeline.ingest_latest("RELIANCE", Exchange.NSE, CandleInterval.W1, now=eval_now)
    assert res.success is True
    assert res.candle is not None
    assert res.candle.interval == CandleInterval.W1


# ============================================================================
# 19. Claude Independent Audit Adversarial Remediation Regression Tests
# ============================================================================


def test_m1_provider_response_recursive_immutability() -> None:
    """Verify that ProviderResponse records are deeply and recursively immutable."""
    t_ret = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    nested_list = [{"k1": "v1"}, {"k2": "v2"}]
    payload = {
        "symbol": "RELIANCE",
        "open": "2500.00",
        "nested_meta": {"tags": ["liquid", "largecap"], "flags": {"active": True}},
        "order_book": nested_list,
    }
    resp = ProviderResponse(
        success=True,
        source="TEST_FEED",
        retrieval_timestamp=t_ret,
        records=(payload,),
    )

    # 1. Mutating original dict/list does not affect frozen records
    payload["nested_meta"]["flags"]["active"] = False
    nested_list.append({"k3": "v3"})
    assert resp.records[0]["nested_meta"]["flags"]["active"] is True
    assert len(resp.records[0]["order_book"]) == 2

    # 2. Attempting to mutate nested mapping raises TypeError
    with pytest.raises(TypeError, match="mappingproxy"):
        resp.records[0]["nested_meta"]["flags"]["active"] = False

    # 3. Attempting to mutate nested list (converted to tuple) raises TypeError
    with pytest.raises(TypeError):
        resp.records[0]["nested_meta"]["tags"][0] = "illiquid"


def test_m2_deep_freeze_guards_against_cycles_and_excessive_depth() -> None:
    """Verify that _deep_freeze rejects cyclical graphs and excessive recursion depth."""
    from agentic_trading.market_data.ingestion import _deep_freeze as ing_freeze

    # 1. Cyclical dictionary graph
    cyclic_dict: dict[str, Any] = {"name": "loop"}
    cyclic_dict["self"] = cyclic_dict
    with pytest.raises(ValueError, match="Cyclical reference detected"):
        ing_freeze(cyclic_dict)

    # 2. Cyclical list graph
    cyclic_list: list[Any] = [1, 2]
    cyclic_list.append(cyclic_list)
    with pytest.raises(ValueError, match="Cyclical reference detected"):
        ing_freeze(cyclic_list)

    # 3. Excessive recursion depth (> 16 levels)
    deep_dict: dict[str, Any] = {"val": 0}
    curr = deep_dict
    for _ in range(25):
        curr["child"] = {"val": 1}
        curr = curr["child"]
    with pytest.raises(ValueError, match="Maximum nesting depth"):
        ing_freeze(deep_dict)

    # 4. Shared DAG (acyclic diamond structure) must succeed without false cycle detection
    shared_child = {"leaf": 42}
    dag: dict[str, Any] = {"branch_a": shared_child, "branch_b": shared_child}
    frozen_dag = ing_freeze(dag)
    assert frozen_dag["branch_a"]["leaf"] == 42
    assert frozen_dag["branch_b"]["leaf"] == 42


def test_m2_ingest_record_guards_against_cyclical_and_non_mapping_raw_record() -> None:
    """Verify that ingest_record fails closed gracefully without escaping unhandled exceptions."""
    provider = SyntheticMarketDataProvider()
    pipeline = MarketDataIngestionPipeline(provider)
    t_ret = datetime(2026, 11, 2, 9, 20, tzinfo=IST)
    eval_now = t_ret + timedelta(minutes=5)

    # 1. Cyclical raw record passed to ingest_record
    cyclic_dict: dict[str, Any] = {"symbol": "RELIANCE"}
    cyclic_dict["self"] = cyclic_dict
    res_cyclic = pipeline.ingest_record(
        cyclic_dict, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret, now=eval_now
    )
    assert res_cyclic.success is False
    assert res_cyclic.error_code == "RAW_VALIDATION_ERROR"
    assert res_cyclic.raw_record is None
    assert "cannot be frozen" in (res_cyclic.error_message or "").lower()

    # 2. Non-mapping object passed as raw_record
    res_non_map = pipeline.ingest_record(
        "invalid_string_payload", "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret, now=eval_now  # type: ignore[arg-type]
    )
    assert res_non_map.success is False
    assert res_non_map.error_code == "RAW_VALIDATION_ERROR"
    assert res_non_map.raw_record is None


def test_m3_session_truncated_h1_candles_handled_correctly() -> None:
    """Verify that H1 bars ending at 15:15 (6 bars) or 15:30 (7 bars with truncated close) pass without gap error."""
    # Day 1: Monday Nov 2, 2026. Day 2: Tuesday Nov 3, 2026.
    t0_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t0_tue = datetime(2026, 11, 3, 9, 15, tzinfo=IST)

    # Case A: 6 H1 bars per day (09:15 to 15:15) followed by next day open 09:15
    bars_6_mon = [
        _build_raw_record(
            interval="1h",
            timestamp=(t0_mon + timedelta(hours=i)).isoformat(),
        )
        for i in range(6)
    ]
    bar_tue_open = _build_raw_record(
        interval="1h",
        timestamp=t0_tue.isoformat(),
    )
    provider_6 = SyntheticMarketDataProvider(records=bars_6_mon + [bar_tue_open])
    pipeline_6 = MarketDataIngestionPipeline(provider_6)
    req_6 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.H1,
        start_time=t0_mon,
        end_time=t0_tue + timedelta(hours=1),
    )
    res_6 = pipeline_6.ingest_historical(req_6, now=t0_tue + timedelta(hours=2))
    assert res_6.success is True
    assert len(res_6.candles) == 7

    # Case B: 7 H1 bars per day with the 7th bar opening at 15:15 IST (truncated at 15:30 IST)
    bar_mon_truncated = _build_raw_record(
        interval="1h",
        timestamp=datetime(2026, 11, 2, 15, 15, tzinfo=IST).isoformat(),
    )
    bars_7_mon = bars_6_mon + [bar_mon_truncated]
    provider_7 = SyntheticMarketDataProvider(records=bars_7_mon + [bar_tue_open])
    pipeline_7 = MarketDataIngestionPipeline(provider_7)
    res_7 = pipeline_7.ingest_historical(req_6, now=t0_tue + timedelta(hours=2))
    assert res_7.success is True
    assert len(res_7.candles) == 8
    # Candle opening at 15:15 IST truncates close_time to 15:30:00 IST
    assert res_7.candles[6].close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)


def test_m3_session_truncated_m10_candles_handled_correctly() -> None:
    """Verify that M10 bars ending at 15:25 (37 bars) or 15:30 (38 bars) pass without gap error."""
    t0_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t0_tue = datetime(2026, 11, 3, 9, 15, tzinfo=IST)

    # 37 full bars (09:15 to 15:25) followed by next day 09:15
    bars_37_mon = [
        _build_raw_record(
            interval="10m",
            timestamp=(t0_mon + timedelta(minutes=10 * i)).isoformat(),
        )
        for i in range(37)
    ]
    bar_tue_open = _build_raw_record(
        interval="10m",
        timestamp=t0_tue.isoformat(),
    )
    provider_37 = SyntheticMarketDataProvider(records=bars_37_mon + [bar_tue_open])
    pipeline_37 = MarketDataIngestionPipeline(provider_37)
    req_37 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M10,
        start_time=t0_mon,
        end_time=t0_tue + timedelta(minutes=10),
    )
    res_37 = pipeline_37.ingest_historical(req_37, now=t0_tue + timedelta(minutes=20))
    assert res_37.success is True
    assert len(res_37.candles) == 38

    # 38th truncated bar: opens 15:25, truncates close to 15:30:00 IST
    bar_38_trunc = _build_raw_record(
        interval="10m",
        timestamp=datetime(2026, 11, 2, 15, 25, tzinfo=IST).isoformat(),
    )
    provider_38 = SyntheticMarketDataProvider(records=bars_37_mon + [bar_38_trunc, bar_tue_open])
    pipeline_38 = MarketDataIngestionPipeline(provider_38)
    res_38 = pipeline_38.ingest_historical(req_37, now=t0_tue + timedelta(minutes=20))
    assert res_38.success is True
    assert len(res_38.candles) == 39
    assert res_38.candles[37].close_time == datetime(2026, 11, 2, 15, 30, tzinfo=IST)


def test_m4_historical_backfill_does_not_enforce_live_staleness() -> None:
    """Verify that historical queries from past dates succeed without requiring unbounded staleness overrides."""
    t0_2024 = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    records_2024 = [
        _build_raw_record(
            timestamp=(t0_2024 + timedelta(minutes=5 * i)).isoformat(),
        )
        for i in range(5)
    ]
    provider = SyntheticMarketDataProvider(records=records_2024)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0_2024,
        end_time=t0_2024 + timedelta(minutes=25),
    )
    # Evaluated at wall-clock year 2026 without any max_staleness override!
    now_2026 = datetime(2026, 11, 2, 18, 0, tzinfo=IST)
    res = pipeline.ingest_historical(req, now=now_2026, max_staleness=None)
    assert res.success is True
    assert len(res.candles) == 5
    assert res.error_code is None


def test_m5_truncated_historical_coverage_reported_explicitly() -> None:
    """Verify that partial historical sequences report TRUNCATED_COVERAGE and fail closed when required."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Provider only has records starting at 09:30 instead of 09:15
    partial_records = [
        _build_raw_record(
            timestamp=(t0 + timedelta(minutes=15 + 5 * i)).isoformat(),
        )
        for i in range(3)  # 09:30 to 09:45
    ]
    provider = SyntheticMarketDataProvider(records=partial_records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,  # Requested 09:15
        end_time=t0 + timedelta(minutes=45),  # Requested 10:00
    )
    eval_now = t0 + timedelta(minutes=50)

    # 1. Default (require_full_coverage=True): fails closed with TRUNCATED_COVERAGE
    res_default = pipeline.ingest_historical(req, now=eval_now)
    assert res_default.success is False
    assert res_default.coverage_status == "TRUNCATED_COVERAGE"
    assert res_default.candles == ()

    # 1b. allow_partial=True: preserves success=False while exposing partial_candles
    res_partial = pipeline.ingest_historical(req, now=eval_now, allow_partial=True)
    assert res_partial.success is False
    assert res_partial.coverage_status == "TRUNCATED_COVERAGE"
    assert res_partial.candles == ()
    assert len(res_partial.partial_candles) == 3

    # 2. Strict (require_full_coverage=True): fails closed with TRUNCATED_COVERAGE
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res_strict.success is False
    assert res_strict.error_code == "TRUNCATED_COVERAGE"
    assert res_strict.coverage_status == "TRUNCATED_COVERAGE"
    assert "coverage is truncated" in (res_strict.error_message or "").lower()


def test_phase3_valid_decimal_representations_scientific_and_clean() -> None:
    """Verify that Decimal instances with scientific notation or clean decimals are accepted directly."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)
    raw = _build_raw_record(
        open_price=Decimal("1E+2"),  # Scientific notation Decimal
        high_price=Decimal("2500.50"),
        low_price=Decimal("100"),
        close_price=Decimal("2500.00"),
    )
    candle = adapter.adapt_record(raw, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)
    assert candle.open == Decimal("100")
    assert candle.high == Decimal("2500.50")


def test_phase3_rejects_bytes_in_all_fields() -> None:
    """Verify that bytes are rejected across all price, volume, and identity fields."""
    adapter = StandardDictAdapter(source_name="TEST_SRC")
    t_ret = datetime(2026, 11, 2, 9, 21, tzinfo=IST)

    # Price field bytes rejected
    raw_bytes_price = _build_raw_record(open_price=b"2500.00")
    with pytest.raises(RawDataValidationError, match="cannot be bytes"):
        adapter.adapt_record(raw_bytes_price, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Volume field bytes rejected
    raw_bytes_vol = _build_raw_record(volume=b"1000")
    with pytest.raises(RawDataValidationError, match="cannot be a bytes"):
        adapter.adapt_record(raw_bytes_vol, "RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)

    # Argument bytes rejected
    raw_valid = _build_raw_record()
    with pytest.raises(RawDataValidationError, match="symbol argument cannot be bytes"):
        adapter.adapt_record(raw_valid, b"RELIANCE", Exchange.NSE, CandleInterval.M5, t_ret)  # type: ignore[arg-type]


def test_phase3_fetch_latest_now_none_causal_timestamp_d1_and_truncated() -> None:
    """Verify that fetch_latest(now=None) produces causal retrieval timestamp respecting session close."""
    t0_d1 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw_d1 = _build_raw_record(interval="1d", timestamp=t0_d1.isoformat())
    provider_d1 = SyntheticMarketDataProvider(records=[raw_d1])
    resp_d1 = provider_d1.fetch_latest("RELIANCE", Exchange.NSE, CandleInterval.D1, now=None)
    # Session close is 15:30:00 IST on session date; causal retrieval timestamp is 15:30:01 IST
    assert resp_d1.retrieval_timestamp == datetime(2026, 11, 2, 15, 30, 1, tzinfo=IST)

    # Truncated H1 bar at 15:15 IST
    t0_h1_trunc = datetime(2026, 11, 2, 15, 15, tzinfo=IST)
    raw_h1 = _build_raw_record(interval="1h", timestamp=t0_h1_trunc.isoformat())
    provider_h1 = SyntheticMarketDataProvider(records=[raw_h1])
    resp_h1 = provider_h1.fetch_latest("RELIANCE", Exchange.NSE, CandleInterval.H1, now=None)
    assert resp_h1.retrieval_timestamp == datetime(2026, 11, 2, 15, 30, 1, tzinfo=IST)


def test_phase3_synthetic_fetch_historical_filters_exceeding_end_time() -> None:
    """Verify that synthetic fetch_historical filters out candles whose close_time exceeds end_time."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Candle opens at 09:25 with interval 15m -> close_time is 09:40
    raw_bar = _build_raw_record(interval="15m", timestamp=(t0 + timedelta(minutes=10)).isoformat())
    provider = SyntheticMarketDataProvider(records=[raw_bar])
    # Request ends at 09:30 (bar opens at 09:25 inside [09:15, 09:30) but close_time 09:40 > 09:30)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
    )
    resp = provider.fetch_historical(req)
    assert len(resp.records) == 0  # Filtered out by synthetic provider


def test_phase3_adapter_identity_less_payload_succeeds_when_require_identity_false() -> None:
    """Verify that StandardDictAdapter(require_payload_identity=False) adapts identity-less payloads cleanly."""
    adapter = StandardDictAdapter(source_name="TEST_SRC", require_payload_identity=False)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    raw_no_ident = {
        "timestamp": t0.isoformat(),
        "open": "2500.00",
        "high": "2510.00",
        "low": "2495.00",
        "close": "2505.00",
        "volume": 50000,
    }
    candle = adapter.adapt_record(
        raw_no_ident,
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        retrieval_timestamp=t0 + timedelta(minutes=6),
    )
    assert candle.symbol == "RELIANCE"
    assert candle.exchange == Exchange.NSE
    assert candle.interval == CandleInterval.M5
    assert candle.open == Decimal("2500.00")


# ============================================================================
# 19. Historical Coverage Correctness & Sequence Continuity (Audit Remediation)
# ============================================================================


def test_coverage_complete_four_candle_m5_sequence() -> None:
    """Verify that a 4-candle M5 sequence spanning the full request window passes with COVERAGE_UNVERIFIED."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    records = [
        _build_raw_record(
            timestamp=(t0 + timedelta(minutes=5 * i)).isoformat(),
        )
        for i in range(4)  # 09:15, 09:20, 09:25, 09:30 (closes at 09:35)
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

    res = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=False)
    assert res.success is True
    assert res.coverage_status == "COVERAGE_UNVERIFIED"
    assert len(res.candles) == 4
    assert res.candles[0].timestamp == t0
    assert res.candles[-1].close_time == req.end_time

    # Under require_full_coverage=True, lack of calendar evidence fails closed
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res_strict.success is False
    assert res_strict.error_code == "COVERAGE_UNVERIFIED"
    assert res_strict.coverage_status == "COVERAGE_UNVERIFIED"


def test_coverage_missing_first_candle() -> None:
    """Verify that a missing first candle triggers TRUNCATED_COVERAGE and fails closed when required."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Missing 09:15; only includes 09:20, 09:25, 09:30
    records = [
        _build_raw_record(
            timestamp=(t0 + timedelta(minutes=5 * i)).isoformat(),
        )
        for i in range(1, 4)
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,  # 09:15
        end_time=t0 + timedelta(minutes=20),  # 09:35
    )
    eval_now = t0 + timedelta(minutes=25)

    # 1. Default mode: fails closed with TRUNCATED_COVERAGE
    res_default = pipeline.ingest_historical(req, now=eval_now)
    assert res_default.success is False
    assert res_default.coverage_status == "TRUNCATED_COVERAGE"
    assert res_default.candles == ()

    # 1b. allow_partial=True: fails closed but exposes partial_candles
    res_partial = pipeline.ingest_historical(req, now=eval_now, allow_partial=True, check_gaps=False)
    assert res_partial.success is False
    assert res_partial.coverage_status == "TRUNCATED_COVERAGE"
    assert res_partial.candles == ()
    assert len(res_partial.partial_candles) == 3

    # 2. Strict mode: fails closed with TRUNCATED_COVERAGE
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res_strict.success is False
    assert res_strict.error_code == "TRUNCATED_COVERAGE"
    assert res_strict.coverage_status == "TRUNCATED_COVERAGE"
    assert "coverage is truncated" in (res_strict.error_message or "").lower()
    assert res_strict.candles == ()


def test_coverage_missing_last_candle() -> None:
    """Verify that a missing last candle triggers TRUNCATED_COVERAGE and fails closed when required."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Missing 09:30; only includes 09:15, 09:20, 09:25 (closes at 09:30 < req.end_time 09:35)
    records = [
        _build_raw_record(
            timestamp=(t0 + timedelta(minutes=5 * i)).isoformat(),
        )
        for i in range(3)
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,  # 09:15
        end_time=t0 + timedelta(minutes=20),  # 09:35
    )
    eval_now = t0 + timedelta(minutes=25)

    # 1. Default mode: fails closed with TRUNCATED_COVERAGE
    res_default = pipeline.ingest_historical(req, now=eval_now)
    assert res_default.success is False
    assert res_default.coverage_status == "TRUNCATED_COVERAGE"
    assert res_default.candles == ()

    # 1b. allow_partial=True: fails closed but exposes partial_candles
    res_partial = pipeline.ingest_historical(req, now=eval_now, allow_partial=True, check_gaps=False)
    assert res_partial.success is False
    assert res_partial.coverage_status == "TRUNCATED_COVERAGE"
    assert res_partial.candles == ()
    assert len(res_partial.partial_candles) == 3

    # 2. Strict mode: fails closed with TRUNCATED_COVERAGE
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res_strict.success is False
    assert res_strict.error_code == "TRUNCATED_COVERAGE"
    assert res_strict.coverage_status == "TRUNCATED_COVERAGE"
    assert "coverage is truncated" in (res_strict.error_message or "").lower()
    assert res_strict.candles == ()


def test_coverage_missing_middle_candle_check_gaps_true() -> None:
    """Verify that a missing middle candle with check_gaps=True rejects at quality gate with TRUNCATED_COVERAGE."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 09:15, 09:25, 09:30 (09:20 missing)
    records = [
        _build_raw_record(timestamp=t0.isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=10)).isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=15)).isoformat()),
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

    res = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=False, check_gaps=True)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == "TRUNCATED_COVERAGE"
    assert res.validation_result is not None
    assert res.validation_result.has_error(DataQualityErrorCode.MISSING_INTERVAL)
    assert res.candles == ()


def test_coverage_missing_middle_candle_check_gaps_false_require_full_true() -> None:
    """Verify that require_full_coverage=True detects interior missing middle candle even when check_gaps=False."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 09:15, 09:25, 09:30 (09:20 missing)
    records = [
        _build_raw_record(timestamp=t0.isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=10)).isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=15)).isoformat()),
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

    # Even though check_gaps=False, require_full_coverage=True independently catches the interior gap
    res = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == "TRUNCATED_COVERAGE"
    assert "coverage is truncated" in (res.error_message or "").lower()
    assert "interior sequence gap detected" in (res.error_message or "")
    assert res.candles == ()


def test_coverage_multiple_consecutive_missing_middle_candles() -> None:
    """Verify that multiple consecutive missing candles are detected as interior gaps."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 09:15 and 09:35 (09:20, 09:25, 09:30 are missing - 20 minute gap)
    records = [
        _build_raw_record(timestamp=t0.isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=20)).isoformat()),
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=25),  # 09:40
    )
    eval_now = t0 + timedelta(minutes=30)

    # 1. Strict mode fails closed
    res_strict = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res_strict.success is False
    assert res_strict.error_code == "TRUNCATED_COVERAGE"
    assert res_strict.coverage_status == "TRUNCATED_COVERAGE"
    assert "interior sequence gap detected" in (res_strict.error_message or "")
    assert res_strict.candles == ()

    # 2. allow_partial=True with check_gaps=False preserves success=False and reports TRUNCATED_COVERAGE
    res_partial = pipeline.ingest_historical(req, now=eval_now, allow_partial=True, check_gaps=False)
    assert res_partial.success is False
    assert res_partial.coverage_status == "TRUNCATED_COVERAGE"
    assert res_partial.candles == ()
    assert len(res_partial.partial_candles) == 2


def test_coverage_entire_intermediate_trading_day_missing() -> None:
    """Verify that an entire missing intermediate trading day fails closed with TRUNCATED_COVERAGE."""
    # Monday 2026-11-02 and Wednesday 2026-11-04 (Tuesday 2026-11-03 missing entirely)
    # Intraday M15: Monday session close 15:15 (close 15:30) and Wednesday session open 09:15
    t_mon_close = datetime(2026, 11, 2, 15, 15, tzinfo=IST)
    t_wed_open = datetime(2026, 11, 4, 9, 15, tzinfo=IST)
    records_intraday = [
        _build_raw_record(interval="15m", timestamp=t_mon_close.isoformat()),
        _build_raw_record(interval="15m", timestamp=t_wed_open.isoformat()),
    ]
    provider_intraday = SyntheticMarketDataProvider(records=records_intraday)
    pipeline_intraday = MarketDataIngestionPipeline(provider_intraday)
    req_intraday = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        start_time=t_mon_close,
        end_time=t_wed_open + timedelta(minutes=15),
    )
    eval_now = t_wed_open + timedelta(hours=1)

    res_intraday = pipeline_intraday.ingest_historical(req_intraday, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res_intraday.success is False
    assert res_intraday.error_code == "TRUNCATED_COVERAGE"
    assert res_intraday.coverage_status == "TRUNCATED_COVERAGE"
    assert "interior sequence gap detected" in (res_intraday.error_message or "")

    # D1 daily candles: Monday and Wednesday (Tuesday missing)
    t_mon_d1 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_wed_d1 = datetime(2026, 11, 4, 9, 15, tzinfo=IST)
    records_d1 = [
        _build_raw_record(interval="1d", timestamp=t_mon_d1.isoformat()),
        _build_raw_record(interval="1d", timestamp=t_wed_d1.isoformat()),
    ]
    provider_d1 = SyntheticMarketDataProvider(records=records_d1)
    pipeline_d1 = MarketDataIngestionPipeline(provider_d1)
    req_d1 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        start_time=t_mon_d1,
        end_time=t_wed_d1 + timedelta(days=1),
    )
    eval_now_d1 = t_wed_d1 + timedelta(days=2)
    res_d1 = pipeline_d1.ingest_historical(req_d1, now=eval_now_d1, require_full_coverage=True, check_gaps=False)
    assert res_d1.success is False
    assert res_d1.error_code == "TRUNCATED_COVERAGE"
    assert res_d1.coverage_status == "TRUNCATED_COVERAGE"


def test_coverage_empty_provider_response_reports_empty_coverage() -> None:
    """Verify that an empty provider response explicitly reports EMPTY_COVERAGE."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    provider = SyntheticMarketDataProvider(records=[])
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=20),
    )
    eval_now = t0 + timedelta(minutes=25)

    res = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res.success is False
    assert res.error_code == "EMPTY_PROVIDER_RESPONSE"
    assert res.coverage_status == "EMPTY_COVERAGE"
    assert res.candles == ()
    assert "0 records" in (res.error_message or "")


def test_coverage_require_full_coverage_false_with_incomplete_data() -> None:
    """Verify that allow_partial=True preserves success=False on incomplete sequence with TRUNCATED_COVERAGE."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # 09:15, 09:25 (missing 09:20 and 09:30)
    records = [
        _build_raw_record(timestamp=t0.isoformat()),
        _build_raw_record(timestamp=(t0 + timedelta(minutes=10)).isoformat()),
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

    res = pipeline.ingest_historical(req, now=eval_now, allow_partial=True, check_gaps=False)
    assert res.success is False
    assert res.coverage_status == "TRUNCATED_COVERAGE"
    assert res.candles == ()
    assert len(res.partial_candles) == 2


def test_coverage_require_full_coverage_true_with_incomplete_data() -> None:
    """Verify that require_full_coverage=True fails closed on any incomplete sequence."""
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    # Only 1 candle returned for 4-candle request window
    records = [_build_raw_record(timestamp=t0.isoformat())]
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

    res = pipeline.ingest_historical(req, now=eval_now, require_full_coverage=True)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == "TRUNCATED_COVERAGE"
    assert res.candles == ()


def test_coverage_session_truncated_h1_m30_m10() -> None:
    """Verify that premature session closes across day boundaries trigger TRUNCATED_COVERAGE for H1, M30, and M10."""
    eval_now = datetime(2026, 11, 3, 11, 0, tzinfo=IST)

    # 1. H1: Normal session closes at 15:15 (or 15:30 with truncated bar).
    # Premature bar stopping at 13:15 (close 14:15) followed by next day 09:15
    t_mon_h1 = datetime(2026, 11, 2, 13, 15, tzinfo=IST)
    t_tue_h1 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    recs_h1 = [
        _build_raw_record(interval="1h", timestamp=t_mon_h1.isoformat()),
        _build_raw_record(interval="1h", timestamp=t_tue_h1.isoformat()),
    ]
    pipe_h1 = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=recs_h1))
    req_h1 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.H1,
        start_time=t_mon_h1,
        end_time=t_tue_h1 + timedelta(hours=1),
    )
    res_h1 = pipe_h1.ingest_historical(req_h1, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res_h1.success is False
    assert res_h1.error_code == "TRUNCATED_COVERAGE"
    assert res_h1.coverage_status == "TRUNCATED_COVERAGE"

    # 2. M30: Normal session closes at 15:15 (or 15:30).
    # Premature bar stopping at 14:15 (close 14:45) followed by next day 09:15
    t_mon_m30 = datetime(2026, 11, 2, 14, 15, tzinfo=IST)
    t_tue_m30 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    recs_m30 = [
        _build_raw_record(interval="30m", timestamp=t_mon_m30.isoformat()),
        _build_raw_record(interval="30m", timestamp=t_tue_m30.isoformat()),
    ]
    pipe_m30 = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=recs_m30))
    req_m30 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M30,
        start_time=t_mon_m30,
        end_time=t_tue_m30 + timedelta(minutes=30),
    )
    res_m30 = pipe_m30.ingest_historical(req_m30, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res_m30.success is False
    assert res_m30.error_code == "TRUNCATED_COVERAGE"
    assert res_m30.coverage_status == "TRUNCATED_COVERAGE"

    # 3. M10: Normal session closes at 15:25 (or 15:30).
    # Premature bar stopping at 14:55 (close 15:05) followed by next day 09:15
    t_mon_m10 = datetime(2026, 11, 2, 14, 55, tzinfo=IST)
    t_tue_m10 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    recs_m10 = [
        _build_raw_record(interval="10m", timestamp=t_mon_m10.isoformat()),
        _build_raw_record(interval="10m", timestamp=t_tue_m10.isoformat()),
    ]
    pipe_m10 = MarketDataIngestionPipeline(SyntheticMarketDataProvider(records=recs_m10))
    req_m10 = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M10,
        start_time=t_mon_m10,
        end_time=t_tue_m10 + timedelta(minutes=10),
    )
    res_m10 = pipe_m10.ingest_historical(req_m10, now=eval_now, require_full_coverage=True, check_gaps=False)
    assert res_m10.success is False
    assert res_m10.error_code == "TRUNCATED_COVERAGE"
    assert res_m10.coverage_status == "TRUNCATED_COVERAGE"
