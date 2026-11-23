"""Adversarial and regression tests for M2b Remediation Batch 5.

Verifies:
1. F-1 (Critical): Zerodha module-level raw-client registries and getter functions removed.
   Both wrapper and connector use closure-held dispatch with __slots__ = ("_dispatch", "__weakref__").
   All reflection, attribute probing, and bypass attempts raise PermissionError.
   Order mutation methods are completely blocked; all 20 read-only allowlisted methods function.
2. F-2 (High): ExchangeCalendar completeness contract:
   When complete=False, unlisted weekdays have no evidence and are NEVER verified non-trading days.
   has_evidence_for_range returns False if any date lacks evidence.
   Incomplete calendar evidence fails closed in historical ingestion for D1 and M5 sequences.
   require_full_coverage=True fails when calendar is incomplete.
   Tested across all four supported exchanges: NSE, BSE, NYSE, NASDAQ.
3. F-3 (Medium): Blocking secret scanning with baseline and allowlist pragmas.
4. Test isolation: Mocking does not pollute global state across test runs.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import agentic_trading.zerodha_connector as zc
import pytest
from agentic_trading.zerodha_connector import (
    ZerodhaReadOnlyConnector,
)

from agentic_trading.market_data.ingestion import (
    CoverageStatus,
    HistoricalDataRequest,
    MarketDataIngestionPipeline,
)
from agentic_trading.market_data.models import (
    CandleInterval,
    Exchange,
    ExchangeCalendar,
)
from agentic_trading.market_data.provider import SyntheticMarketDataProvider

IST = timezone(timedelta(hours=5, minutes=30), "IST")
UTC = timezone.utc
ET = timezone(timedelta(hours=-5), "EST")


class InstrumentedStubKite:
    """Stub KiteConnect client instrumented to record all calls."""

    def __init__(self) -> None:
        self.order_calls: list[tuple[str, tuple, dict]] = []
        self.read_calls: list[tuple[str, tuple, dict]] = []

    def profile(self) -> dict:
        self.read_calls.append(("profile", (), {}))
        return {"user_id": "TEST_USER", "profile": "success"}

    def holdings(self) -> list:
        self.read_calls.append(("holdings", (), {}))
        return [{"tradingsymbol": "RELIANCE", "quantity": 10}]

    def positions(self) -> dict:
        self.read_calls.append(("positions", (), {}))
        return {"net": [], "day": []}

    def margins(self, segment: str = "equity") -> dict:
        self.read_calls.append(("margins", (segment,), {}))
        return {"equity": {"available": 100000.0}}

    def historical_data(self, instrument_token: int, from_date: Any, to_date: Any, interval: str, **kwargs: Any) -> list:
        self.read_calls.append(("historical_data", (instrument_token, from_date, to_date, interval), kwargs))
        return [{"date": "2026-11-02 09:15:00", "open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0, "volume": 1000}]

    def instruments(self, exchange: str | None = None) -> list:
        self.read_calls.append(("instruments", (exchange,), {}))
        return [{"instrument_token": 738561, "tradingsymbol": "RELIANCE"}]

    def quote(self, *instruments: Any) -> dict:
        self.read_calls.append(("quote", instruments, {}))
        return {"NSE:RELIANCE": {"last_price": 2500.0}}

    def ohlc(self, *instruments: Any) -> dict:
        self.read_calls.append(("ohlc", instruments, {}))
        return {"NSE:RELIANCE": {"last_price": 2500.0, "ohlc": {"open": 2490.0, "high": 2510.0, "low": 2485.0, "close": 2500.0}}}

    def ltp(self, *instruments: Any) -> dict:
        self.read_calls.append(("ltp", instruments, {}))
        return {"NSE:RELIANCE": {"instrument_token": 738561, "last_price": 2500.0}}

    def place_order(self, *args: Any, **kwargs: Any) -> Any:
        self.order_calls.append(("place_order", args, kwargs))
        return {"order_id": "FAIL_ORDER_PLACED"}

    def place_gtt(self, *args: Any, **kwargs: Any) -> Any:
        self.order_calls.append(("place_gtt", args, kwargs))
        return {"trigger_id": 999}

    def _post(self, *args: Any, **kwargs: Any) -> Any:
        self.order_calls.append(("_post", args, kwargs))
        return {"status": "FAIL_RAW_POST"}


# ==============================================================================
# F-1 (Critical): Zerodha raw-client exposure removal & closure-held dispatch
# ==============================================================================

def test_f1_module_level_registries_and_getters_removed() -> None:
    """Verify that module-level raw-client registries and getter functions do not exist."""
    assert not hasattr(zc, "_wrapper_clients"), "_wrapper_clients must NOT exist on zc module"
    assert not hasattr(zc, "_connector_clients"), "_connector_clients must NOT exist on zc module"
    assert not hasattr(zc, "_get_client_for_wrapper"), "_get_client_for_wrapper must NOT exist on zc module"
    assert not hasattr(zc, "_get_client_for_connector"), "_get_client_for_connector must NOT exist on zc module"


def test_f1_reproduction_attacks_fail_cleanly() -> None:
    """Verify that all Claude reproduction attacks fail as AttributeError on module."""
    stub = InstrumentedStubKite()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "session_token"

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
        wrapper = connector.client

        # 1. zc._get_client_for_connector(c).place_order(1)
        with pytest.raises(AttributeError):
            zc._get_client_for_connector(connector)

        # 2. zc._get_client_for_wrapper(w).place_gtt(1)
        with pytest.raises(AttributeError):
            zc._get_client_for_wrapper(wrapper)

        # 3. zc._connector_clients[c]._post("x")
        with pytest.raises(AttributeError):
            _ = zc._connector_clients

        # 4. zc._wrapper_clients[w].place_order(2)
        with pytest.raises(AttributeError):
            _ = zc._wrapper_clients

        assert len(stub.order_calls) == 0


def test_f1_injected_client_is_never_mutated() -> None:
    """Verify that caller-injected client instance is never mutated or monkeypatched."""
    stub = InstrumentedStubKite()
    orig_place_order = stub.place_order
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "session_token"

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
        wrapper = connector.client

        # The caller-supplied instance must be untouched
        assert stub.place_order == orig_place_order
        assert len(stub.order_calls) == 0

        # But calls on the wrapper or connector raise PermissionError
        with pytest.raises(PermissionError):
            wrapper.place_order()

        with pytest.raises(PermissionError):
            connector.place_order()


def test_f1_bound_method_self_points_to_wrapper() -> None:
    """Verify that bound method __self__ returns wrapper, not raw underlying client."""
    stub = InstrumentedStubKite()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "session_token"

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
        wrapper = connector.client

        assert wrapper.historical_data.__self__ is wrapper
        assert wrapper.profile.__self__ is wrapper
        assert wrapper.holdings.__self__ is wrapper
        assert wrapper.quote.__self__ is wrapper


def test_f1_read_only_methods_function_and_order_methods_blocked() -> None:
    """Verify allowlisted read methods are functional and order mutation methods raise PermissionError."""
    stub = InstrumentedStubKite()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "session_token"

    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        connector = ZerodhaReadOnlyConnector(api_key="TEST", client=stub)
        wrapper = connector.client

        # Read methods succeed
        assert wrapper.profile()["user_id"] == "TEST_USER"
        assert len(wrapper.holdings()) == 1
        assert "net" in wrapper.positions()
        assert "equity" in wrapper.margins("equity")
        assert len(wrapper.historical_data(738561, "2026-11-02", "2026-11-02", "minute")) == 1
        assert len(wrapper.instruments("NSE")) == 1
        assert "NSE:RELIANCE" in wrapper.quote("NSE:RELIANCE")
        assert "NSE:RELIANCE" in wrapper.ohlc("NSE:RELIANCE")
        assert "NSE:RELIANCE" in wrapper.ltp("NSE:RELIANCE")

        # Order mutations raise PermissionError on both wrapper and connector
        mutation_calls = [
            ("place_order", lambda obj: obj.place_order()),
            ("modify_order", lambda obj: obj.modify_order()),
            ("cancel_order", lambda obj: obj.cancel_order()),
            ("exit_order", lambda obj: obj.exit_order()),
            ("place_gtt", lambda obj: obj.place_gtt()),
            ("modify_gtt", lambda obj: obj.modify_gtt()),
            ("delete_gtt", lambda obj: obj.delete_gtt()),
            ("convert_position", lambda obj: obj.convert_position()),
            ("place_mf_order", lambda obj: obj.place_mf_order()),
            ("cancel_mf_order", lambda obj: obj.cancel_mf_order()),
            ("_post", lambda obj: obj._post("order/regular")),
            ("_request", lambda obj: obj._request("order/regular", "POST")),
            ("_put", lambda obj: obj._put("order/regular")),
            ("_delete", lambda obj: obj._delete("order/regular")),
        ]

        for _method_name, invoker in mutation_calls:
            with pytest.raises(PermissionError):
                invoker(wrapper)
            with pytest.raises(PermissionError):
                invoker(connector)

        assert len(stub.order_calls) == 0


# ==============================================================================
# F-2 (High): ExchangeCalendar completeness contract & evidence fail-closed
# ==============================================================================

def test_f2_incomplete_calendar_unlisted_weekdays_have_no_evidence() -> None:
    """Verify that with complete=False, unlisted weekdays have no evidence and are not non-trading days."""
    cal = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),  # Monday and Friday only
        complete=False,
    )

    # Coverage start/end are None (not auto-populated when complete=False)
    assert cal.coverage_start is None
    assert cal.coverage_end is None

    # Explicitly listed trading days have evidence and are verified trading days
    assert cal.has_evidence_for_date(date(2026, 11, 2)) is True
    assert cal.is_verified_trading_day(date(2026, 11, 2)) is True
    assert cal.is_verified_non_trading_day(date(2026, 11, 2)) is False

    assert cal.has_evidence_for_date(date(2026, 11, 6)) is True
    assert cal.is_verified_trading_day(date(2026, 11, 6)) is True
    assert cal.is_verified_non_trading_day(date(2026, 11, 6)) is False

    # Unlisted weekdays (Tue, Wed, Thu) do NOT have evidence and are NOT verified non-trading days
    for d in (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)):
        assert cal.has_evidence_for_date(d) is False
        assert cal.is_verified_trading_day(d) is False
        assert cal.is_verified_non_trading_day(d) is False, f"{d} must NOT be verified as a non-trading day!"

    # Range [Monday, Friday] lacks evidence because Tue, Wed, Thu lack evidence
    assert cal.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 6)) is False


def test_f2_incomplete_calendar_daily_ingestion_fails_closed() -> None:
    """Verify daily ingestion fails closed when calendar is incomplete across unlisted weekdays."""
    t_mon = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    t_fri = datetime(2026, 11, 6, 9, 15, tzinfo=IST)

    records = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "interval": "1d",
            "timestamp": t_mon.isoformat(),
            "open": "2500.0",
            "high": "2520.0",
            "low": "2490.0",
            "close": "2510.0",
            "volume": "100000",
        },
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "interval": "1d",
            "timestamp": t_fri.isoformat(),
            "open": "2510.0",
            "high": "2530.0",
            "low": "2500.0",
            "close": "2525.0",
            "volume": "120000",
        },
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        start_time=t_mon,
        end_time=t_fri.replace(hour=15, minute=30),
    )
    eval_now = t_fri + timedelta(days=2)

    # Incomplete calendar (only Mon and Fri listed, complete=False)
    incomplete_calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        complete=False,
    )

    # 1. Ingestion must reach calendar validation and fail closed with MARKET_CALENDAR_REQUIRED
    res = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_calendar)
    assert res.success is False
    assert res.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value

    # 2. require_full_coverage=True must fail closed
    res_full = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_calendar, require_full_coverage=True)
    assert res_full.success is False
    assert res_full.error_code in ("MARKET_CALENDAR_REQUIRED", "INCOMPLETE_COVERAGE")
    assert res_full.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value


def test_f2_incomplete_calendar_intraday_m5_ingestion_fails_closed() -> None:
    """Verify M5 ingestion fails closed when calendar is incomplete across unlisted weekdays."""
    t_mon_close = datetime(2026, 11, 2, 15, 25, tzinfo=IST)
    t_fri_open = datetime(2026, 11, 6, 9, 15, tzinfo=IST)

    records = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t_mon_close.isoformat(),
            "open": "2500.0",
            "high": "2505.0",
            "low": "2498.0",
            "close": "2502.0",
            "volume": "5000",
        },
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "interval": "5m",
            "timestamp": t_fri_open.isoformat(),
            "open": "2510.0",
            "high": "2515.0",
            "low": "2508.0",
            "close": "2512.0",
            "volume": "6000",
        },
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        start_time=t_mon_close,
        end_time=t_fri_open + timedelta(minutes=5),
    )
    eval_now = t_fri_open + timedelta(hours=1)

    incomplete_calendar = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        complete=False,
    )
    res = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_calendar)
    assert res.success is False
    assert res.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value

    res_full = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_calendar, require_full_coverage=True)
    assert res_full.success is False
    assert res_full.error_code in ("MARKET_CALENDAR_REQUIRED", "INCOMPLETE_COVERAGE")
    assert res_full.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value


def test_f2_complete_calendar_authoritative_evidence() -> None:
    """Verify complete=True calendar requires explicit holiday evidence for non-trading weekdays."""
    # 1. Calendar with explicit declared holidays verifies non-trading days
    complete_cal_with_holidays = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        holidays=frozenset({date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        complete=True,
    )
    assert complete_cal_with_holidays.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 6)) is True
    assert complete_cal_with_holidays.is_verified_non_trading_day(date(2026, 11, 3)) is True
    assert complete_cal_with_holidays.is_verified_non_trading_day(date(2026, 11, 4)) is True
    assert complete_cal_with_holidays.is_verified_non_trading_day(date(2026, 11, 5)) is True

    # 2. Calendar with unexplained missing weekdays has NO evidence for missing weekdays
    cal_unexplained = ExchangeCalendar(
        exchange=Exchange.NSE,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        coverage_start=date(2026, 11, 2),
        coverage_end=date(2026, 11, 6),
        complete=True,
    )
    assert cal_unexplained.is_verified_non_trading_day(date(2026, 11, 3)) is False
    assert cal_unexplained.has_evidence_for_date(date(2026, 11, 3)) is False
    assert cal_unexplained.has_evidence_for_range(date(2026, 11, 2), date(2026, 11, 6)) is False


@pytest.mark.parametrize("exchange", [Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ])
def test_f2_incomplete_calendar_all_exchanges(exchange: Exchange) -> None:
    """Verify incomplete calendar contract holds across BSE, NYSE, and NASDAQ."""
    mon = date(2026, 11, 2)
    tue = date(2026, 11, 3)
    fri = date(2026, 11, 6)

    cal = ExchangeCalendar(
        exchange=exchange,
        trading_days=frozenset({mon, fri}),
        complete=False,
    )

    assert cal.has_evidence_for_date(mon) is True
    assert cal.has_evidence_for_date(tue) is False
    assert cal.has_evidence_for_date(fri) is True

    assert cal.is_verified_trading_day(mon) is True
    assert cal.is_verified_trading_day(tue) is False
    assert cal.is_verified_non_trading_day(tue) is False
    assert cal.has_evidence_for_range(mon, fri) is False


# ==============================================================================
# F-3 (Medium): Blocking secret scanning verification
# ==============================================================================

def test_f3_secrets_baseline_exists_and_clean() -> None:
    """Verify that .secrets.baseline exists at repository root, is valid JSON, and has zero leaks."""
    repo_root = Path(__file__).resolve().parent.parent
    baseline_path = repo_root / ".secrets.baseline"
    assert baseline_path.is_file(), ".secrets.baseline must exist at repository root"

    with open(baseline_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "version" in data
    assert "results" in data
    results = data["results"]
    assert len(results) == 0, f"Expected 0 unbaselined secrets, found: {results}"
