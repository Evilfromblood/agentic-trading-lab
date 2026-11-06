"""Adversarial and regression tests for M2b Remediation Batch 4.

Verifies:
1. H-1: Zerodha connector and wrapper raw-client escape paths closed (all 9 paths blocked).
2. N-1: Holiday candle rejection pipeline failure path returns typed error without crash.
3. H-2: Authoritative calendar evidence completeness contract (fail-closed, no year inference).
4. Four-exchange coverage (NSE, BSE, NYSE, NASDAQ).
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from agentic_trading.zerodha_connector import (
    _READ_ONLY_ALLOWLIST,
    ZerodhaReadOnlyConnector,
    _ReadOnlyKiteWrapper,
)

from agentic_trading.market_data.ingestion import (
    CoverageStatus,
    HistoricalDataRequest,
    MarketDataIngestionPipeline,
)
from agentic_trading.market_data.models import (
    Candle,
    CandleInterval,
    Exchange,
    ExchangeCalendar,
    ExchangeSession,
)
from agentic_trading.market_data.provider import SyntheticMarketDataProvider
from agentic_trading.market_data.quality import DataQualityErrorCode

IST = timezone(timedelta(hours=5, minutes=30), "IST")
UTC = timezone.utc


class InstrumentedStubKite:
    """Stub KiteConnect client instrumented to record any accidental order-routing calls."""

    def __init__(self) -> None:
        self.order_calls: list[tuple[str, tuple, dict]] = []
        self.read_calls: list[tuple[str, tuple, dict]] = []

    def _record_order(self, name: str, args: tuple, kwargs: dict) -> None:
        self.order_calls.append((name, args, kwargs))

    def _record_read(self, name: str, args: tuple, kwargs: dict) -> Any:
        self.read_calls.append((name, args, kwargs))
        return {name: "success"}

    # Mutation methods
    def place_order(self, *args, **kwargs): self._record_order("place_order", args, kwargs)
    def modify_order(self, *args, **kwargs): self._record_order("modify_order", args, kwargs)
    def cancel_order(self, *args, **kwargs): self._record_order("cancel_order", args, kwargs)
    def exit_order(self, *args, **kwargs): self._record_order("exit_order", args, kwargs)
    def place_gtt(self, *args, **kwargs): self._record_order("place_gtt", args, kwargs)
    def modify_gtt(self, *args, **kwargs): self._record_order("modify_gtt", args, kwargs)
    def delete_gtt(self, *args, **kwargs): self._record_order("delete_gtt", args, kwargs)
    def convert_position(self, *args, **kwargs): self._record_order("convert_position", args, kwargs)
    def place_mf_order(self, *args, **kwargs): self._record_order("place_mf_order", args, kwargs)
    def cancel_mf_order(self, *args, **kwargs): self._record_order("cancel_mf_order", args, kwargs)
    def _post(self, *args, **kwargs): self._record_order("_post", args, kwargs)
    def _request(self, *args, **kwargs): self._record_order("_request", args, kwargs)
    def _put(self, *args, **kwargs): self._record_order("_put", args, kwargs)
    def _delete(self, *args, **kwargs): self._record_order("_delete", args, kwargs)

    # Allowlisted read methods
    def quote(self, *args, **kwargs): return self._record_read("quote", args, kwargs)
    def ltp(self, *args, **kwargs): return self._record_read("ltp", args, kwargs)
    def historical_data(self, *args, **kwargs): return self._record_read("historical_data", args, kwargs)
    def instruments(self, *args, **kwargs): return self._record_read("instruments", args, kwargs)
    def profile(self, *args, **kwargs): return self._record_read("profile", args, kwargs)
    def margins(self, *args, **kwargs): return self._record_read("margins", args, kwargs)
    def holdings(self, *args, **kwargs): return self._record_read("holdings", args, kwargs)
    def positions(self, *args, **kwargs): return self._record_read("positions", args, kwargs)
    def trades(self, *args, **kwargs): return self._record_read("trades", args, kwargs)
    def orders(self, *args, **kwargs): return self._record_read("orders", args, kwargs)
    def order_history(self, *args, **kwargs): return self._record_read("order_history", args, kwargs)
    def order_trades(self, *args, **kwargs): return self._record_read("order_trades", args, kwargs)
    def mf_instruments(self, *args, **kwargs): return self._record_read("mf_instruments", args, kwargs)
    def mf_holdings(self, *args, **kwargs): return self._record_read("mf_holdings", args, kwargs)
    def get_gtts(self, *args, **kwargs): return self._record_read("get_gtts", args, kwargs)
    def get_gtt(self, *args, **kwargs): return self._record_read("get_gtt", args, kwargs)
    def generate_session(self, *args, **kwargs): return {"access_token": "mock_token"}
    def set_access_token(self, *args, **kwargs): return None
    def invalidate_access_token(self, *args, **kwargs): return None
    def login_url(self, *args, **kwargs): return "https://kite.zerodha.com/connect/login"


# ==============================================================================
# 1. H-1: Zerodha Connector & Wrapper Adversarial Security Tests
# ==============================================================================

def test_h1_raw_client_retrieval_methods_removed() -> None:
    """Verify that _get_raw_client and _get_underlying are completely removed."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    # Neither object possesses the removed escape methods
    with pytest.raises((AttributeError, PermissionError)):
        _ = connector._get_raw_client

    with pytest.raises((AttributeError, PermissionError)):
        _ = wrapper._get_underlying


def test_h1_bound_method_self_does_not_leak_client() -> None:
    """Verify that every allowlisted method's __self__ is the wrapper, NOT the raw client."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    for method_name in _READ_ONLY_ALLOWLIST:
        attr = getattr(wrapper, method_name)
        if callable(attr):
            bound_self = getattr(attr, "__self__", None)
            assert bound_self is wrapper, f"Method {method_name}.__self__ leaked: {bound_self}"
            assert bound_self is not stub, f"Method {method_name}.__self__ leaked raw stub client"
            # Attempting order routing through leaked __self__ raises PermissionError
            with pytest.raises(PermissionError):
                bound_self.place_order(variety="regular", exchange="NSE", tradingsymbol="INFY")


def test_h1_vars_and_dict_access_blocked() -> None:
    """Verify that vars() and __dict__ access on wrapper and connector fail closed."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    # vars() raises TypeError or PermissionError on slotted instances without __dict__
    with pytest.raises((TypeError, PermissionError)):
        vars(wrapper)

    with pytest.raises((TypeError, PermissionError)):
        vars(connector)

    # __dict__ access raises AttributeError or PermissionError
    with pytest.raises((AttributeError, PermissionError)):
        _ = wrapper.__dict__

    with pytest.raises((AttributeError, PermissionError)):
        _ = connector.__dict__


def test_h1_object_getattribute_bypass_blocked() -> None:
    """Verify object.__getattribute__ cannot extract raw client references."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    prohibited_names = (
        "_client",
        "__client",
        "_raw_client",
        "raw_client",
        "__raw_client",
        "_underlying",
        "_ReadOnlyKiteWrapper__raw_client",
        "_ZerodhaReadOnlyConnector__client",
    )
    for name in prohibited_names:
        with pytest.raises(AttributeError):
            object.__getattribute__(wrapper, name)
        with pytest.raises(AttributeError):
            object.__getattribute__(connector, name)


def test_h1_class_level_method_access_blocked() -> None:
    """Verify class-level unbound/bound method invocations cannot route orders."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    mutation_methods = (
        "place_order",
        "modify_order",
        "cancel_order",
        "exit_order",
        "place_gtt",
        "modify_gtt",
        "delete_gtt",
        "convert_position",
        "place_mf_order",
        "cancel_mf_order",
        "_post",
        "_request",
        "_put",
        "_delete",
    )

    for method_name in mutation_methods:
        wrapper_fn = getattr(_ReadOnlyKiteWrapper, method_name)
        with pytest.raises(PermissionError):
            wrapper_fn(wrapper)

        connector_fn = getattr(ZerodhaReadOnlyConnector, method_name)
        with pytest.raises(PermissionError):
            connector_fn(connector)

    # Verify stub client NEVER received any order or mutation calls
    assert len(stub.order_calls) == 0


def test_h1_all_allowlisted_operations_dispatch_safely() -> None:
    """Verify all read operations succeed without exposing raw client or order routing."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    res_ltp = wrapper.ltp("NSE:INFY")
    assert res_ltp == {"ltp": "success"}

    res_quote = wrapper.quote("NSE:INFY")
    assert res_quote == {"quote": "success"}

    res_hist = wrapper.historical_data(1234, "2026-01-01", "2026-01-02", "5minute")
    assert res_hist == {"historical_data": "success"}

    assert len(stub.read_calls) == 3
    assert len(stub.order_calls) == 0


# ==============================================================================
# 2. N-1: Holiday Rejection Pipeline Failure Path Tests
# ==============================================================================

def _make_m5_candle(ts: datetime, open_p: str = "100.0") -> Candle:
    op = Decimal(open_p)
    return Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=op,
        high=op + Decimal("1.0"),
        low=op - Decimal("1.0"),
        close=op,
        volume=Decimal("500"),
        timestamp=ts,
    )


def test_n1_full_75_bar_series_on_holiday_fails_typed_without_crash() -> None:
    """Verify that a full 75-bar intraday series on a declared holiday returns typed failure without crashing."""
    # Tuesday Nov 3, 2026 is a declared holiday (Diwali)
    holiday_d = date(2026, 11, 3)
    t0 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    records = []
    for i in range(75):
        ts = t0 + timedelta(minutes=5 * i)
        records.append({
            "timestamp": ts.isoformat(),
            "open": "1500.00",
            "high": "1510.00",
            "low": "1490.00",
            "close": "1505.00",
            "volume": "1000",
            "interval": "5m",
            "symbol": "INFY",
            "exchange": "NSE",
        })

    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({holiday_d}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        complete=True,
    )

    req = HistoricalDataRequest(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=5 * 75),
    )
    eval_now = t0 + timedelta(days=2)

    # Ingestion MUST NOT crash with ValueError; must return typed failure result
    result = pipeline.ingest_historical(req, now=eval_now, calendar=calendar)
    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.coverage_status == CoverageStatus.COVERAGE_UNVERIFIED.value
    assert result.validation_result is not None
    assert result.validation_result.is_valid is False
    assert result.validation_result.has_error(DataQualityErrorCode.OUTSIDE_SESSION)
    assert any("holiday" in issue.message.lower() for issue in result.validation_result.issues)


def test_n1_single_m5_candle_on_holiday_fails_typed() -> None:
    """Verify that a single M5 candle on a declared holiday returns typed failure without crashing."""
    holiday_d = date(2026, 11, 3)
    t0 = datetime(2026, 11, 3, 10, 0, tzinfo=IST)
    records = [{
        "timestamp": t0.isoformat(),
        "open": "1500.00",
        "high": "1510.00",
        "low": "1490.00",
        "close": "1505.00",
        "volume": "1000",
        "interval": "5m",
        "symbol": "INFY",
        "exchange": "NSE",
    }]

    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({holiday_d}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        complete=True,
    )

    req = HistoricalDataRequest(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t0 + timedelta(minutes=5),
    )
    eval_now = t0 + timedelta(days=2)

    result = pipeline.ingest_historical(req, now=eval_now, calendar=calendar)
    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.coverage_status == CoverageStatus.COVERAGE_UNVERIFIED.value
    assert result.validation_result.has_error(DataQualityErrorCode.OUTSIDE_SESSION)


def test_n1_d1_candle_on_holiday_fails_typed() -> None:
    """Verify that a D1 candle on a declared holiday returns typed failure without crashing."""
    holiday_d = date(2026, 11, 3)
    t0 = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    records = [{
        "timestamp": t0.isoformat(),
        "open": "1500.00",
        "high": "1550.00",
        "low": "1480.00",
        "close": "1530.00",
        "volume": "50000",
        "interval": "1d",
        "symbol": "INFY",
        "exchange": "NSE",
    }]

    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({holiday_d}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        complete=True,
    )

    req = HistoricalDataRequest(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        start_time=t0,
        end_time=t0.replace(hour=15, minute=30),
    )
    eval_now = t0 + timedelta(days=2)

    result = pipeline.ingest_historical(req, now=eval_now, calendar=calendar)
    assert result.success is False
    assert result.error_code == "QUALITY_GATE_REJECTED"
    assert result.coverage_status == CoverageStatus.COVERAGE_UNVERIFIED.value
    assert result.validation_result.has_error(DataQualityErrorCode.OUTSIDE_SESSION)


# ==============================================================================
# 3. H-2: Exchange Calendar Authoritative Completeness Contract Tests
# ==============================================================================

def test_h2_empty_calendar_has_no_evidence() -> None:
    """Verify that an empty calendar has is_populated=False and provides no evidence."""
    cal = ExchangeCalendar(exchange=Exchange.NSE)
    assert cal.is_populated is False
    assert cal.has_evidence_for_date(date(2026, 6, 15)) is False
    assert cal.has_evidence_for_range(date(2026, 6, 1), date(2026, 6, 5)) is False
    assert cal.is_verified_trading_day(date(2026, 6, 15)) is False
    assert cal.is_verified_non_trading_day(date(2026, 6, 15)) is False


def test_h2_explicit_bounds_without_completeness_evidence() -> None:
    """Verify that coverage_start and coverage_end without complete=True provide no completeness authority."""
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        complete=False,
    )
    assert cal.is_populated is False
    assert cal.has_evidence_for_date(date(2026, 6, 15)) is False
    assert cal.has_evidence_for_range(date(2026, 6, 1), date(2026, 6, 5)) is False
    assert cal.is_verified_trading_day(date(2026, 6, 15)) is False


def test_h2_complete_calendar_with_no_holidays() -> None:
    """Verify that a complete calendar with no holidays authoritatively verifies standard weekdays."""
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 6, 1),
        coverage_end=date(2026, 6, 30),
        complete=True,
    )
    assert cal.is_populated is True
    # Monday June 15, 2026 is in range
    assert cal.has_evidence_for_date(date(2026, 6, 15)) is True
    assert cal.is_verified_trading_day(date(2026, 6, 15)) is True
    assert cal.is_verified_non_trading_day(date(2026, 6, 15)) is False

    # Saturday June 20, 2026 is a weekend in range
    assert cal.has_evidence_for_date(date(2026, 6, 20)) is True
    assert cal.is_verified_trading_day(date(2026, 6, 20)) is False
    assert cal.is_verified_non_trading_day(date(2026, 6, 20)) is True

    # Date outside range has no evidence
    assert cal.has_evidence_for_date(date(2026, 7, 1)) is False
    assert cal.is_verified_trading_day(date(2026, 7, 1)) is False

    # Subrange within bounds has evidence
    assert cal.has_evidence_for_range(date(2026, 6, 1), date(2026, 6, 15)) is True
    # Range crossing outside bounds does NOT have evidence
    assert cal.has_evidence_for_range(date(2026, 5, 25), date(2026, 6, 15)) is False


def test_h2_calendar_with_one_unrelated_holiday_has_no_year_inference() -> None:
    """Verify that a single holiday does NOT grant year-level evidence to unrelated dates."""
    diwali_d = date(2026, 11, 3)
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({diwali_d}),
        complete=False,
    )
    assert cal.is_populated is True
    # Declared holiday has explicit evidence
    assert cal.has_evidence_for_date(diwali_d) is True
    assert cal.is_verified_non_trading_day(diwali_d) is True

    # Unrelated dates in 2026 MUST NOT receive evidence via year-level inference
    unrelated_d = date(2026, 6, 15)
    assert cal.has_evidence_for_date(unrelated_d) is False
    assert cal.is_verified_trading_day(unrelated_d) is False
    assert cal.has_evidence_for_range(date(2026, 6, 1), date(2026, 6, 5)) is False


def test_h2_partial_date_range_evidence_fails_closed() -> None:
    """Verify that a query window exceeding partial calendar coverage fails closed."""
    # Calendar only complete through Jan 15
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 1, 15),
        complete=True,
    )
    # Query window for whole month of January
    assert cal.has_evidence_for_range(date(2026, 1, 1), date(2026, 1, 31)) is False


def test_h2_calendar_post_init_validation() -> None:
    """Verify ExchangeCalendar post_init validation rules."""
    # coverage_start > coverage_end raises ValueError
    with pytest.raises(ValueError, match="coverage_start .* cannot be after coverage_end"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            coverage_start=date(2026, 12, 31),
            coverage_end=date(2026, 1, 1),
        )

    # complete=True without bounds or trading_days raises ValueError
    with pytest.raises(ValueError, match="complete ExchangeCalendar without explicit trading_days must specify"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            complete=True,
        )


def test_h2_four_exchange_support() -> None:
    """Verify ExchangeCalendar support across NSE, BSE, NYSE, and NASDAQ."""
    exchanges = [Exchange.NSE, Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ]
    for ex in exchanges:
        cal = ExchangeCalendar(
            exchange=ex,
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
            complete=True,
        )
        assert cal.exchange == ex
        assert cal.is_populated is True
        session = cal.get_session(date(2026, 6, 15))
        assert session is not None
        assert session.exchange == ex


# ==============================================================================
# 4. Connector & Wrapper Comprehensive Read Operations & Lifecycle Tests
# ==============================================================================

def test_h1_all_twenty_allowlisted_methods_callable_and_safe() -> None:
    """Verify each of the 20 allowlisted methods on _ReadOnlyKiteWrapper dispatches safely."""
    stub = InstrumentedStubKite()
    connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
    wrapper = connector.client

    # Call each of the 20 read-only allowlisted methods
    assert wrapper.quote("NSE:INFY") == {"quote": "success"}
    assert wrapper.ltp("NSE:INFY") == {"ltp": "success"}
    assert wrapper.historical_data(123, "2026-01-01", "2026-01-02", "5m") == {"historical_data": "success"}
    assert wrapper.instruments("NSE") == {"instruments": "success"}
    assert wrapper.profile() == {"profile": "success"}
    assert wrapper.margins("equity") == {"margins": "success"}
    assert wrapper.holdings() == {"holdings": "success"}
    assert wrapper.positions() == {"positions": "success"}
    assert wrapper.trades() == {"trades": "success"}
    assert wrapper.orders() == {"orders": "success"}
    assert wrapper.order_history("123") == {"order_history": "success"}
    assert wrapper.order_trades("123") == {"order_trades": "success"}
    assert wrapper.mf_instruments() == {"mf_instruments": "success"}
    assert wrapper.mf_holdings() == {"mf_holdings": "success"}
    assert wrapper.get_gtts() == {"get_gtts": "success"}
    assert wrapper.get_gtt(123) == {"get_gtt": "success"}
    assert wrapper.generate_session("token", api_secret="secret") == {"access_token": "mock_token"}
    assert wrapper.set_access_token("token") is None
    assert wrapper.invalidate_access_token("token") is None
    assert wrapper.login_url() == "https://kite.zerodha.com/connect/login"

    # Order calls must remain strictly 0
    assert len(stub.order_calls) == 0


def test_h1_connector_read_methods_with_session() -> None:
    """Verify connector read operations (profile, holdings, positions, margins, logout) with session."""
    stub = InstrumentedStubKite()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "valid_session_token"

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        try:
            connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
            assert connector.profile() == {"profile": "success"}
            assert connector.holdings() == {"holdings": "success"}
            assert connector.positions() == {"positions": "success"}
            assert connector.margins() == {"margins": "success"}

            # complete_login
            os.environ["KITE_API_SECRET"] = "mock_secret"
            login_res = connector.complete_login("mock_request_token")
            assert "login_time" in login_res

            # logout
            connector.logout()
            mock_keyring.delete_password.assert_called()
        finally:
            os.environ.pop("KITE_API_SECRET", None)


def test_h1_connector_session_required_raises_without_token() -> None:
    """Verify connector read operations raise KiteConfigurationError when not authenticated."""
    from agentic_trading.zerodha_connector import KiteConfigurationError

    stub = InstrumentedStubKite()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
        with pytest.raises(KiteConfigurationError, match="Not authenticated"):
            connector.profile()

        with pytest.raises(KiteConfigurationError, match="Not authenticated"):
            connector.holdings()

        with pytest.raises(KiteConfigurationError, match="Not authenticated"):
            connector.positions()

        with pytest.raises(KiteConfigurationError, match="Not authenticated"):
            connector.margins()


def test_h1_connector_missing_api_key_raises() -> None:
    """Verify connector raises KiteConfigurationError when no api_key or client is provided."""
    from agentic_trading.zerodha_connector import KiteConfigurationError

    old_key = os.environ.pop("KITE_API_KEY", None)
    try:
        with pytest.raises(KiteConfigurationError, match="Set KITE_API_KEY"):
            ZerodhaReadOnlyConnector()
    finally:
        if old_key is not None:
            os.environ["KITE_API_KEY"] = old_key


def test_h2_verified_trading_and_non_trading_day_methods() -> None:
    """Verify ExchangeCalendar is_verified_trading_day and is_verified_non_trading_day semantics."""
    muhurat_date = date(2026, 11, 8)  # Sunday special session
    muhurat_session = ExchangeSession(
        name="NSE_MUHURAT",
        session_open=time(18, 15),
        session_close=time(19, 15),
        timezone=IST,
        exchange=Exchange.NSE,
        is_special=True,
    )
    holiday_date = date(2026, 11, 3)  # Tuesday holiday

    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        holidays=frozenset({holiday_date}),
        special_sessions={muhurat_date: muhurat_session},
        coverage_start=date(2026, 11, 1),
        coverage_end=date(2026, 11, 30),
        complete=True,
    )

    # 1. Special session on weekend is verified trading day
    assert cal.is_verified_trading_day(muhurat_date) is True
    assert cal.is_verified_non_trading_day(muhurat_date) is False

    # 2. Declared holiday on weekday is verified non-trading day
    assert cal.is_verified_trading_day(holiday_date) is False
    assert cal.is_verified_non_trading_day(holiday_date) is True

    # 3. Standard weekday in complete calendar is verified trading day
    standard_weekday = date(2026, 11, 2)  # Monday
    assert cal.is_verified_trading_day(standard_weekday) is True
    assert cal.is_verified_non_trading_day(standard_weekday) is False

    # 4. Standard weekend without special session is verified non-trading day
    standard_weekend = date(2026, 11, 7)  # Saturday
    assert cal.is_verified_trading_day(standard_weekend) is False
    assert cal.is_verified_non_trading_day(standard_weekend) is True

    # 5. Complete calendar with explicit trading_days set and declared holiday
    trading_days_set = frozenset({date(2026, 11, 2), date(2026, 11, 4)})
    cal_td = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=trading_days_set,
        holidays=frozenset({date(2026, 11, 3)}),
        coverage_start=date(2026, 11, 1),
        coverage_end=date(2026, 11, 5),
        complete=True,
    )
    assert cal_td.is_verified_trading_day(date(2026, 11, 2)) is True
    assert cal_td.is_verified_trading_day(date(2026, 11, 3)) is False
    assert cal_td.is_verified_non_trading_day(date(2026, 11, 3)) is True

    # 6. Complete calendar with unexplained missing weekday: NOT verified as non-trading day without holiday evidence
    cal_unexplained = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=trading_days_set,
        coverage_start=date(2026, 11, 1),
        coverage_end=date(2026, 11, 5),
        complete=True,
    )
    assert cal_unexplained.is_verified_trading_day(date(2026, 11, 3)) is False
    assert cal_unexplained.is_verified_non_trading_day(date(2026, 11, 3)) is False
    assert cal_unexplained.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 4)) is False

    # 7. Incomplete calendar (complete=False): unlisted weekday is NOT a verified non-trading day
    cal_td_incomplete = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=trading_days_set,
        coverage_start=date(2026, 11, 1),
        coverage_end=date(2026, 11, 5),
        complete=False,
    )
    assert cal_td_incomplete.is_verified_trading_day(date(2026, 11, 2)) is True
    assert cal_td_incomplete.is_verified_trading_day(date(2026, 11, 3)) is False
    assert cal_td_incomplete.is_verified_non_trading_day(date(2026, 11, 3)) is False
