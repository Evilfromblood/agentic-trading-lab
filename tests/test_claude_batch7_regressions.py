from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from agentic_trading.zerodha_connector import (
    KiteConfigurationError,
    ReadOnlyKiteConnect,
    ZerodhaReadOnlyConnector,
    _ReadOnlyKiteWrapper,
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
    ExchangeSession,
)
from agentic_trading.market_data.provider import SyntheticMarketDataProvider
from agentic_trading.market_data.quality import DataQualityErrorCode

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

IST = timezone(timedelta(hours=5, minutes=30), "IST")
ET = timezone(timedelta(hours=-5), "EST")
UTC = timezone.utc


class MockKiteClient:
    def __init__(self, api_key: str = "mock_key") -> None:
        self.api_key = api_key
        self.access_token: str | None = None
        self.order_calls: list[dict[str, Any]] = []

    def profile(self) -> dict[str, Any]:
        return {"user_id": "TEST_USER", "user_name": "Test User"}

    def margins(self) -> dict[str, Any]:
        return {"equity": {"available": 100000.0}}

    def holdings(self) -> list[dict[str, Any]]:
        return [{"tradingsymbol": "INFY", "quantity": 10}]

    def positions(self) -> dict[str, Any]:
        return {"net": [], "day": []}

    def orders(self) -> list[dict[str, Any]]:
        return []

    def trades(self) -> list[dict[str, Any]]:
        return []

    def quote(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"NSE:INFY": {"last_price": 1500.0}}

    def ltp(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"NSE:INFY": {"last_price": 1500.0}}

    def ohlc(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"NSE:INFY": {"ohlc": {"open": 1500.0}}}

    def historical_data(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def instruments(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def place_order(self, *args: Any, **kwargs: Any) -> str:
        self.order_calls.append({"method": "place_order", "args": args, "kwargs": kwargs})
        return "ORDER_123"

    def modify_order(self, *args: Any, **kwargs: Any) -> str:
        self.order_calls.append({"method": "modify_order", "args": args, "kwargs": kwargs})
        return "ORDER_123"

    def cancel_order(self, *args: Any, **kwargs: Any) -> str:
        self.order_calls.append({"method": "cancel_order", "args": args, "kwargs": kwargs})
        return "ORDER_123"

    def place_gtt(self, *args: Any, **kwargs: Any) -> str:
        self.order_calls.append({"method": "place_gtt", "args": args, "kwargs": kwargs})
        return "GTT_123"

    def generate_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"access_token": "token_gen"}

    def set_access_token(self, token: str) -> None:
        self.access_token = token


def test_d1_raw_client_hidden_completely() -> None:
    raw = MockKiteClient()
    raw.access_token = "token_abc"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    assert "_target" not in _ReadOnlyKiteWrapper.__slots__
    assert "_target" not in ZerodhaReadOnlyConnector.__slots__
    assert _ReadOnlyKiteWrapper.__slots__ == ("__weakref__",)
    assert ZerodhaReadOnlyConnector.__slots__ == ("__weakref__",)

    prohibited = (
        "_target",
        "_client",
        "__client",
        "_raw_client",
        "raw_client",
        "__raw_client",
        "_underlying",
        "_dispatch",
        "__dict__",
        "reqsession",
    )
    for attr in prohibited:
        with pytest.raises(PermissionError):
            getattr(wrapper, attr)
        with pytest.raises(PermissionError):
            getattr(connector, attr)

    with pytest.raises(AttributeError):
        object.__getattribute__(wrapper, "_target")
    with pytest.raises(AttributeError):
        object.__getattribute__(connector, "_target")

    with pytest.raises(PermissionError):
        vars(wrapper)
    with pytest.raises(PermissionError):
        vars(connector)

    class SubWrapper(_ReadOnlyKiteWrapper):
        pass

    sub = SubWrapper(raw)
    with pytest.raises(PermissionError):
        _ = sub._target

    q_method = wrapper.quote
    assert q_method.__self__ is wrapper
    res = q_method("NSE:INFY")
    assert "NSE:INFY" in res

    assert len(raw.order_calls) == 0


@pytest.mark.skipif(KiteConnect is None, reason="kiteconnect library required")
def test_d1_injected_genuine_kiteconnect_remains_unmutated() -> None:
    raw = KiteConnect(api_key="genuine_key")
    raw_dict_before = dict(raw.__dict__)
    orig_place_order = raw.place_order
    orig_generate_session = raw.generate_session

    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        _ = wrapper._target

    assert raw.place_order.__func__ is orig_place_order.__func__
    assert raw.generate_session.__func__ is orig_generate_session.__func__
    assert raw.__dict__ == raw_dict_before


def test_d2_d3_session_mutation_and_complete_login_blocked() -> None:
    raw = MockKiteClient()
    raw.access_token = "test_tok"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        wrapper.generate_session("req_tok")
    with pytest.raises(PermissionError):
        wrapper.renew_access_token()
    with pytest.raises(PermissionError):
        wrapper.invalidate_access_token("tok")
    with pytest.raises(PermissionError):
        wrapper.invalidate_refresh_token("ref")
    with pytest.raises(PermissionError):
        wrapper.set_access_token("tok")

    with pytest.raises(PermissionError):
        connector.generate_session("req_tok")
    with pytest.raises(PermissionError):
        connector.renew_access_token()
    with pytest.raises(PermissionError):
        connector.invalidate_access_token("tok")
    with pytest.raises(PermissionError):
        connector.invalidate_refresh_token("ref")
    with pytest.raises(PermissionError):
        connector.set_access_token("tok")
    with pytest.raises(PermissionError):
        connector.complete_login("request_token_123")


@pytest.mark.skipif(KiteConnect is None, reason="kiteconnect library required")
def test_d2_default_readonly_kiteconnect_blocks_mutations() -> None:
    rok = ReadOnlyKiteConnect(api_key="test_key")
    with pytest.raises(PermissionError):
        rok.generate_session("token")
    with pytest.raises(PermissionError):
        rok.renew_access_token()
    with pytest.raises(PermissionError):
        rok.invalidate_access_token()
    with pytest.raises(PermissionError):
        rok.invalidate_refresh_token()
    with pytest.raises(PermissionError):
        rok.set_access_token("tok")


def test_d4_in_memory_token_bypasses_locked_keyring() -> None:
    raw = MockKiteClient()
    raw.access_token = "valid_in_memory_token"

    failing_keyring = MagicMock()
    failing_keyring.get_password.side_effect = RuntimeError("Keyring locked or inaccessible")

    with patch.dict("sys.modules", {"keyring": failing_keyring}):
        connector = ZerodhaReadOnlyConnector(client=raw)

        prof = connector.profile()
        assert prof["user_id"] == "TEST_USER"

        m = connector.margins()
        assert "equity" in m

        h = connector.holdings()
        assert len(h) == 1

        p = connector.positions()
        assert "net" in p

        q = connector.quote("NSE:INFY")
        assert "NSE:INFY" in q

        failing_keyring.get_password.assert_not_called()


def test_d4_missing_token_with_locked_keyring_raises_kite_configuration_error() -> None:
    raw = MockKiteClient()
    raw.access_token = None

    failing_keyring = MagicMock()
    failing_keyring.get_password.side_effect = RuntimeError("Keyring locked or inaccessible")

    with patch.dict("sys.modules", {"keyring": failing_keyring}):
        connector = ZerodhaReadOnlyConnector(client=raw)
        with pytest.raises(KiteConfigurationError, match="pre-authenticated"):
            connector.profile()

    failing_keyring.get_password.assert_not_called()


def test_d4_keyboard_interrupt_in_keyring_not_swallowed() -> None:
    from agentic_trading.zerodha_connector import _safe_get_stored_token

    interrupt_keyring = MagicMock()
    interrupt_keyring.get_password.side_effect = KeyboardInterrupt()

    with patch.dict("sys.modules", {"keyring": interrupt_keyring}):
        raised = False
        try:
            _safe_get_stored_token(raise_on_error=True)
        except KeyboardInterrupt:
            raised = True
        except KiteConfigurationError:
            pass
    assert raised, "KeyboardInterrupt was swallowed instead of propagating"


class StubSequenceProvider(SyntheticMarketDataProvider):
    def __init__(self, records: list[dict[str, Any]], retrieval_ts: datetime) -> None:
        super().__init__()
        self._records = records
        self._retrieval_ts = retrieval_ts

    def fetch_historical(self, request: HistoricalDataRequest) -> Any:
        from agentic_trading.market_data.provider import ProviderResponse
        return ProviderResponse(
            success=True,
            source=self.source_name,
            records=tuple(self._records),
            retrieval_timestamp=self._retrieval_ts,
        )


@pytest.mark.parametrize("ex", [Exchange.NSE, Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ])
def test_d5_missing_intermediate_trading_day_d1_returns_truncated_coverage(ex: Exchange) -> None:
    from agentic_trading.market_data.adapters import StandardDictAdapter

    session = ExchangeSession.for_exchange(ex)

    d1 = date(2026, 11, 2)
    d2 = date(2026, 11, 3)
    d3 = date(2026, 11, 4)
    if ex in (Exchange.NSE, Exchange.BSE):
        c_open_time = time(9, 15)
        c_close_time = time(15, 30)
    else:
        c_open_time = time(9, 30)
        c_close_time = time(16, 0)

    cal = ExchangeCalendar(
        exchange=ex,
        trading_days=frozenset({d1, d2, d3}),
        coverage_start=d1,
        coverage_end=d3,
        complete=True,
    )

    t1 = datetime.combine(d1, c_open_time, tzinfo=session.timezone)
    t3 = datetime.combine(d3, c_open_time, tzinfo=session.timezone)
    c3_close = datetime.combine(d3, c_close_time, tzinfo=session.timezone)

    records = [
        {
            "symbol": "TEST",
            "exchange": ex.value,
            "interval": CandleInterval.D1.value,
            "timestamp": t1.isoformat(),
            "open": "100",
            "high": "105",
            "low": "95",
            "close": "102",
            "volume": 1000,
        },
        {
            "symbol": "TEST",
            "exchange": ex.value,
            "interval": CandleInterval.D1.value,
            "timestamp": t3.isoformat(),
            "open": "102",
            "high": "108",
            "low": "101",
            "close": "106",
            "volume": 1200,
        },
    ]

    req = HistoricalDataRequest(
        symbol="TEST",
        exchange=ex,
        interval=CandleInterval.D1,
        start_time=t1,
        end_time=c3_close,
    )

    eval_now = datetime.combine(d3, c_close_time, tzinfo=session.timezone) + timedelta(hours=1)
    prov = StubSequenceProvider(records, eval_now)
    adapter = StandardDictAdapter(source_name=prov.source_name)
    pipe = MarketDataIngestionPipeline(provider=prov, adapter=adapter)

    res = pipe.ingest_historical(req, now=eval_now, calendar=cal, check_gaps=True)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value
    assert res.validation_result is not None
    assert res.validation_result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


@pytest.mark.parametrize("ex", [Exchange.NSE, Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ])
def test_d5_missing_intermediate_candle_m5_returns_truncated_coverage(ex: Exchange) -> None:
    from agentic_trading.market_data.adapters import StandardDictAdapter

    session = ExchangeSession.for_exchange(ex)
    d = date(2026, 11, 2)
    if ex in (Exchange.NSE, Exchange.BSE):
        c_open_time = time(9, 15)
    else:
        c_open_time = time(9, 30)

    t0 = datetime.combine(d, c_open_time, tzinfo=session.timezone)
    t2 = t0 + timedelta(minutes=10)

    cal = ExchangeCalendar(
        exchange=ex,
        trading_days=frozenset({d}),
        coverage_start=d,
        coverage_end=d,
        complete=True,
    )

    records = [
        {
            "symbol": "TEST",
            "exchange": ex.value,
            "interval": CandleInterval.M5.value,
            "timestamp": t0.isoformat(),
            "open": "100",
            "high": "105",
            "low": "95",
            "close": "102",
            "volume": 1000,
        },
        {
            "symbol": "TEST",
            "exchange": ex.value,
            "interval": CandleInterval.M5.value,
            "timestamp": t2.isoformat(),
            "open": "102",
            "high": "108",
            "low": "101",
            "close": "106",
            "volume": 1200,
        },
    ]

    req = HistoricalDataRequest(
        symbol="TEST",
        exchange=ex,
        interval=CandleInterval.M5,
        start_time=t0,
        end_time=t2 + timedelta(minutes=5),
    )

    eval_now = t2 + timedelta(hours=1)
    prov = StubSequenceProvider(records, eval_now)
    adapter = StandardDictAdapter(source_name=prov.source_name)
    pipe = MarketDataIngestionPipeline(provider=prov, adapter=adapter)

    res = pipe.ingest_historical(req, now=eval_now, calendar=cal, check_gaps=True)
    assert res.success is False
    assert res.error_code == "TRUNCATED_COVERAGE"
    assert res.coverage_status == CoverageStatus.TRUNCATED_COVERAGE.value
    assert res.validation_result is not None
    assert res.validation_result.has_error(DataQualityErrorCode.MISSING_INTERVAL)


def test_d6_detect_secrets_scans_requirements_lock() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_lock = os.path.join(tmp_dir, "requirements.lock")
        with open(fake_lock, "w", encoding="utf-8") as f:
            f.write("AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")

        res = subprocess.run(
            ["detect-secrets-hook", "--baseline", ".secrets.baseline", fake_lock],
            capture_output=True,
            text=True,
            shell=True,
        )
        assert res.returncode != 0


def test_d7_pinned_dependencies_in_requirements_lock() -> None:
    expected_pins = {
        "kiteconnect": "5.2.2",
        "keyring": "25.7.0",
        "requests": "2.34.2",
        "ruff": "0.17.3",
        "pytest": "9.2.0",
        "pytest-cov": "7.1.0",
        "detect-secrets": "1.5.0",
    }
    with open("requirements.lock", "r", encoding="utf-8") as f:
        content = f.read()

    for pkg, version in expected_pins.items():
        assert f"{pkg}=={version}" in content, f"Missing pinned dependency {pkg}=={version}"


def test_f1_injected_client_not_mutated_by_require_session() -> None:
    raw = MockKiteClient()
    raw.access_token = "pre_authed_token"
    raw_access_token_before = raw.access_token

    mutating_keyring = MagicMock()
    mutating_keyring.get_password.return_value = "keyring_token"

    with patch.dict("sys.modules", {"keyring": mutating_keyring}):
        connector = ZerodhaReadOnlyConnector(client=raw)
        connector.profile()

    assert raw.access_token == raw_access_token_before
    mutating_keyring.get_password.assert_not_called()


def test_f1_injected_client_not_mutated_by_logout() -> None:
    raw = MockKiteClient()
    raw.access_token = "pre_authed_token"

    connector = ZerodhaReadOnlyConnector(client=raw)
    connector.logout()

    assert raw.access_token == "pre_authed_token"


def test_f1_unauthenticated_injected_client_raises_kite_configuration_error() -> None:
    raw = MockKiteClient()
    raw.access_token = None

    connector = ZerodhaReadOnlyConnector(client=raw)
    with pytest.raises(KiteConfigurationError, match="pre-authenticated"):
        connector.profile()

    assert raw.access_token is None


@pytest.mark.skipif(KiteConnect is None, reason="kiteconnect library required")
def test_f1_genuine_injected_kiteconnect_not_mutated_across_session_and_logout() -> None:
    raw = KiteConnect(api_key="genuine_key")
    raw.access_token = "pre_authed_token"
    dict_before = dict(raw.__dict__)
    headers_before = dict(raw.reqsession.headers)

    connector = ZerodhaReadOnlyConnector(client=raw)
    connector.logout()

    assert raw.__dict__ == dict_before
    assert dict(raw.reqsession.headers) == headers_before


def test_f3_order_margins_blocked_on_mock_wrapper() -> None:
    raw = MockKiteClient()
    raw.access_token = "tok"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        wrapper.order_margins()
    with pytest.raises(PermissionError):
        wrapper.basket_order_margins()
    with pytest.raises(PermissionError):
        wrapper.get_virtual_contract_note()


def test_f3_order_margins_blocked_on_connector() -> None:
    raw = MockKiteClient()
    raw.access_token = "tok"
    connector = ZerodhaReadOnlyConnector(client=raw)

    with pytest.raises(PermissionError):
        connector.order_margins()
    with pytest.raises(PermissionError):
        connector.basket_order_margins()
    with pytest.raises(PermissionError):
        connector.get_virtual_contract_note()


@pytest.mark.skipif(KiteConnect is None, reason="kiteconnect library required")
def test_f3_order_margins_blocked_on_genuine_kiteconnect_wrapper() -> None:
    raw = KiteConnect(api_key="genuine_key")
    raw.access_token = "tok"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        wrapper.order_margins()
    with pytest.raises(PermissionError):
        wrapper.basket_order_margins()
    with pytest.raises(PermissionError):
        wrapper.get_virtual_contract_note()


@pytest.mark.skipif(KiteConnect is None, reason="kiteconnect library required")
def test_f3_order_margins_blocked_on_readonly_kiteconnect_instance() -> None:
    rok = ReadOnlyKiteConnect(api_key="test_key")
    with pytest.raises(PermissionError):
        rok.order_margins([])
    with pytest.raises(PermissionError):
        rok.basket_order_margins([])
    with pytest.raises(PermissionError):
        rok.get_virtual_contract_note([])


def test_wrapper_getattr_unknown_method_raises_permission_error() -> None:
    raw = MockKiteClient()
    raw.access_token = "tok"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        _ = wrapper.some_unknown_method_xyz


def test_wrapper_getattr_blocked_method_raises_permission_error_via_getattr() -> None:
    raw = MockKiteClient()
    raw.access_token = "tok"
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(PermissionError):
        wrapper.order_margins()
    with pytest.raises(PermissionError):
        wrapper.basket_order_margins()
    with pytest.raises(PermissionError):
        wrapper.get_virtual_contract_note()


def test_wrapper_getattr_underlying_missing_attribute_raises_attribute_error() -> None:
    class MinimalClient:
        access_token = "tok"

    raw = MinimalClient()
    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    with pytest.raises(AttributeError):
        wrapper.get_auction_instruments()
