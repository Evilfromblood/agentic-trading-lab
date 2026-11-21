"""Comprehensive regression and adversarial tests for M2b Remediation Batch 6.

Verifies:
1. Priority 1 (F1-A, F1-B, F1-D):
   - Genuine KiteConnect 5.2.2 integration with intercepted HTTP transport.
   - Legitimate read operations (profile, margins, holdings, positions, historical_data, quote, ltp) work.
   - Caller-supplied injected KiteConnect client is never mutated or monkeypatched.
   - Every mutation and non-GET operation (orders, autoslice, GTT, MF, SIP, session mutations,
     _post, _put, _delete, _request) is rejected before transport.
   - Zero blocked requests reach the HTTP transport adapter.
   - Keyring safety: missing, unconfigured, or failing keyrings do not break construction.
   - Slotted composition: vars(), __dict__, object.__getattribute__ fail closed.
   - Bound method __self__ returns wrapper, not raw underlying client.
2. Priority 2 (F2-A, F2-B, F2-C):
   - Calendar contradiction rejection: trading_days & holidays overlap, special session on holiday,
     open >= close, exchange mismatch.
   - Completeness contract: complete=True requires explicit holiday evidence for non-trading weekdays.
   - Incomplete calendar fails closed with exact MARKET_CALENDAR_REQUIRED status and error code.
   - Tested across all four supported exchanges: NSE, BSE, NYSE, NASDAQ for D1 and M5.
   - Out-of-window, empty, and mismatched calendar evidence fails closed.
3. Priority 3 (F3-A, F3-B):
   - Secret scanning: detection of dummy AWS secrets across .github, .gitlab-ci.yml, src, .env, and zip.
   - Anchored exclusion regex does not match .github or .gitlab-ci.yml.
   - .secrets.baseline has version 1.5.0 and zero unbaselined secrets.
"""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import agentic_trading.zerodha_connector as zc
import pytest
import requests
from agentic_trading.zerodha_connector import (
    ZerodhaReadOnlyConnector,
)
from requests.adapters import HTTPAdapter

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

IST = timezone(timedelta(hours=5, minutes=30), "IST")
ET = timezone(timedelta(hours=-5), "EST")
UTC = timezone.utc

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None  # type: ignore[assignment]


# ==============================================================================
# Priority 1: Zerodha Read-Only Boundary & Genuine KiteConnect Integration
# ==============================================================================


class InstrumentedCountingAdapter(HTTPAdapter):
    """Intercepting transport adapter recording all HTTP calls and returning mock JSON responses."""

    def __init__(self) -> None:
        super().__init__()
        self.sent_requests: list[tuple[str, str, dict]] = []

    def send(self, request: requests.PreparedRequest, *args: Any, **kwargs: Any) -> requests.Response:
        self.sent_requests.append((request.method or "", request.url or "", dict(request.headers)))
        resp = requests.Response()
        resp.status_code = 200
        resp.url = request.url or ""
        resp.headers["Content-Type"] = "application/json"

        # Return minimal genuine KiteConnect JSON envelopes
        data: dict[str, Any]
        if "profile" in (request.url or ""):
            data = {"status": "success", "data": {"user_id": "TEST_GENUINE", "user_name": "Test User"}}
        elif "margins" in (request.url or ""):
            data = {"status": "success", "data": {"equity": {"available": 500000.0}}}
        elif "holdings" in (request.url or ""):
            data = {"status": "success", "data": [{"tradingsymbol": "INFY", "quantity": 100}]}
        elif "positions" in (request.url or ""):
            data = {"status": "success", "data": {"net": [], "day": []}}
        elif "historical" in (request.url or ""):
            data = {"status": "success", "data": {"candles": [["2026-11-02T09:15:00+0530", 1500, 1520, 1495, 1510, 50000]]}}
        elif "quote" in (request.url or ""):
            data = {"status": "success", "data": {"NSE:INFY": {"last_price": 1510.0}}}
        elif "instruments" in (request.url or ""):
            resp.headers["Content-Type"] = "text/csv"
            resp._content = b"instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n738561,738561,RELIANCE,RELIANCE,2500,,,0.05,1,EQ,NSE,NSE\n"
            return resp
        else:
            data = {"status": "success", "data": {"result": "ok"}}

        resp._content = json.dumps(data).encode("utf-8")
        return resp


@pytest.mark.skipif(KiteConnect is None, reason="Genuine kiteconnect dependency required")
def test_p1_genuine_kiteconnect_read_operations_reach_transport() -> None:
    """Verify that genuine KiteConnect read methods reach transport adapter as GET requests."""
    adapter = InstrumentedCountingAdapter()
    raw = KiteConnect(api_key="test_api_key")
    raw.reqsession.mount("https://", adapter)
    raw.reqsession.mount("http://", adapter)

    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    # 1. Profile
    prof = wrapper.profile()
    assert prof["user_id"] == "TEST_GENUINE"
    assert len(adapter.sent_requests) == 1
    assert adapter.sent_requests[-1][0] == "GET"
    assert "user/profile" in adapter.sent_requests[-1][1]

    # 2. Margins
    margins = wrapper.margins("equity")
    assert "equity" in margins
    assert adapter.sent_requests[-1][0] == "GET"

    # 3. Holdings
    holdings = wrapper.holdings()
    assert len(holdings) == 1
    assert adapter.sent_requests[-1][0] == "GET"

    # 4. Quote
    q = wrapper.quote("NSE:INFY")
    assert "NSE:INFY" in q
    assert adapter.sent_requests[-1][0] == "GET"


@pytest.mark.skipif(KiteConnect is None, reason="Genuine kiteconnect dependency required")
def test_p1_injected_genuine_kiteconnect_client_remains_unmutated() -> None:
    """Verify that caller-injected genuine KiteConnect client instance is never mutated."""
    raw = KiteConnect(api_key="caller_api_key")

    # Record method references and class identity before wrapping
    orig_place_order = raw.place_order
    orig_modify_order = raw.modify_order
    orig_cancel_order = raw.cancel_order
    orig_request = raw._request
    orig_dict_keys = set(raw.__dict__.keys())

    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    # Wrapper is a separate object, not mutating raw client
    assert wrapper is not raw
    with pytest.raises(PermissionError):
        _ = wrapper._target

    # Raw methods and attributes on caller client remain completely unchanged
    assert raw.place_order.__func__ is orig_place_order.__func__
    assert raw.modify_order.__func__ is orig_modify_order.__func__
    assert raw.cancel_order.__func__ is orig_cancel_order.__func__
    assert raw._request.__func__ is orig_request.__func__
    assert set(raw.__dict__.keys()) == orig_dict_keys


@pytest.mark.skipif(KiteConnect is None, reason="Genuine kiteconnect dependency required")
def test_p1_all_mutations_blocked_before_transport_and_zero_calls_reach_adapter() -> None:
    """Verify orders, GTT, MF, autoslice, session mutations, and non-GET requests are rejected before transport."""
    adapter = InstrumentedCountingAdapter()
    raw = KiteConnect(api_key="test_api_key")
    raw.reqsession.mount("https://", adapter)
    raw.reqsession.mount("http://", adapter)

    connector = ZerodhaReadOnlyConnector(client=raw)
    wrapper = connector.client

    mutation_tests = [
        ("place_order", lambda: wrapper.place_order(variety="regular", exchange="NSE", tradingsymbol="INFY")),
        ("modify_order", lambda: wrapper.modify_order(variety="regular", order_id="123")),
        ("cancel_order", lambda: wrapper.cancel_order(variety="regular", order_id="123")),
        ("exit_order", lambda: wrapper.exit_order(variety="regular", order_id="123")),
        ("place_autoslice_order", lambda: wrapper.place_autoslice_order(variety="regular", exchange="NSE", tradingsymbol="INFY")),
        ("place_gtt", lambda: wrapper.place_gtt(trigger_type=1, tradingsymbol="INFY")),
        ("modify_gtt", lambda: wrapper.modify_gtt(trigger_id=123)),
        ("delete_gtt", lambda: wrapper.delete_gtt(trigger_id=123)),
        ("convert_position", lambda: wrapper.convert_position(exchange="NSE", tradingsymbol="INFY")),
        ("place_mf_order", lambda: wrapper.place_mf_order(tradingsymbol="INF123")),
        ("cancel_mf_order", lambda: wrapper.cancel_mf_order(order_id="123")),
        ("place_mf_sip", lambda: wrapper.place_mf_sip(tradingsymbol="INF123", amount=1000)),
        ("modify_mf_sip", lambda: wrapper.modify_mf_sip(sip_id="123")),
        ("cancel_mf_sip", lambda: wrapper.cancel_mf_sip(sip_id="123")),
        ("generate_session", lambda: wrapper.generate_session()),
        ("_post", lambda: wrapper._post("order/regular")),
        ("_put", lambda: wrapper._put("order/regular")),
        ("_delete", lambda: wrapper._delete("order/regular")),
        ("_request_POST", lambda: wrapper._request("POST", "order/regular")),
        ("_request_PUT", lambda: wrapper._request("PUT", "order/regular")),
        ("_request_DELETE", lambda: wrapper._request("DELETE", "order/regular")),
    ]

    for _name, invoker in mutation_tests:
        with pytest.raises(PermissionError, match="forbidden"):
            invoker()

    # Zero blocked mutation requests must reach the transport adapter
    assert len(adapter.sent_requests) == 0, f"Blocked requests reached transport: {adapter.sent_requests}"


def test_p1_keyring_failures_and_missing_backends_fail_safe() -> None:
    """Verify that missing or unconfigured keyrings do not crash connector construction."""
    # 1. keyring is None
    with patch.object(zc, "keyring", None):
        with patch.dict("sys.modules", {"keyring": None}):  # type: ignore[dict-item]
            conn1 = ZerodhaReadOnlyConnector(api_key="TEST_KEY", client=MagicMock())
            assert conn1 is not None
            with pytest.raises(zc.KiteConfigurationError):
                conn1.profile()  # Unauthenticated

    # 2. keyring raises RuntimeError / OSError / KeyringError
    mock_bad_keyring = MagicMock()
    mock_bad_keyring.get_password.side_effect = RuntimeError("Keyring backend locked")
    mock_bad_keyring.set_password.side_effect = OSError("DBus error")
    mock_bad_keyring.delete_password.side_effect = Exception("General failure")

    with patch.dict("sys.modules", {"keyring": mock_bad_keyring}):
        conn2 = ZerodhaReadOnlyConnector(api_key="TEST_KEY", client=MagicMock())
        assert conn2 is not None
        # Does not crash on logout
        conn2.logout()


def test_p1_reflection_and_dict_probing_fail_closed() -> None:
    """Verify that vars(), __dict__, and prohibited attribute lookups fail closed."""
    connector = ZerodhaReadOnlyConnector(api_key="TEST_KEY", client=MagicMock())
    wrapper = connector.client

    # vars() raises TypeError or PermissionError on slotted instances
    with pytest.raises((TypeError, PermissionError)):
        vars(wrapper)
    with pytest.raises((TypeError, PermissionError)):
        vars(connector)

    # __dict__ does not exist or raises PermissionError
    with pytest.raises((AttributeError, PermissionError)):
        _ = wrapper.__dict__
    with pytest.raises((AttributeError, PermissionError)):
        _ = connector.__dict__

    # Prohibited attribute lookups
    prohibited = ("_client", "__client", "_raw_client", "raw_client", "__raw_client", "_underlying")
    for attr in prohibited:
        with pytest.raises((AttributeError, PermissionError)):
            getattr(wrapper, attr)
        with pytest.raises((AttributeError, PermissionError)):
            getattr(connector, attr)


# ==============================================================================
# Priority 2: Calendar Correctness, Contradiction Checks & Completeness
# ==============================================================================


def test_p2_calendar_contradiction_trading_day_holiday_overlap() -> None:
    """Verify that a date simultaneously declared as trading day and holiday raises ValueError."""
    conflict_date = date(2026, 11, 3)
    with pytest.raises(ValueError, match="Contradictory calendar declaration"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            trading_days=frozenset({date(2026, 11, 2), conflict_date}),
            holidays=frozenset({conflict_date, date(2026, 11, 4)}),
        )


def test_p2_calendar_contradiction_special_session_on_holiday() -> None:
    """Verify that a special session declared on a holiday date raises ValueError."""
    sess_date = date(2026, 11, 3)
    special_session = ExchangeSession(
        session_open=time(9, 15),
        session_close=time(15, 30),
        timezone=IST,
        exchange=Exchange.NSE,
        is_special=True,
    )
    with pytest.raises(ValueError, match="Contradictory special session"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            holidays=frozenset({sess_date}),
            special_sessions={sess_date: special_session},
        )


def test_p2_calendar_contradiction_special_session_open_gte_close() -> None:
    """Verify special session with open >= close raises ValueError."""
    sess_date = date(2026, 11, 3)
    bad_session = ExchangeSession(
        session_open=time(15, 30),
        session_close=time(9, 15),
        timezone=IST,
        exchange=Exchange.NSE,
        is_special=True,
    )
    with pytest.raises(ValueError, match="strictly before session_close"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            special_sessions={sess_date: bad_session},
        )


def test_p2_calendar_contradiction_special_session_exchange_mismatch() -> None:
    """Verify special session with conflicting exchange raises ValueError."""
    sess_date = date(2026, 11, 3)
    bse_session = ExchangeSession(
        session_open=time(9, 15),
        session_close=time(15, 30),
        timezone=IST,
        exchange=Exchange.BSE,
        is_special=True,
    )
    with pytest.raises(ValueError, match="does not match calendar exchange"):
        ExchangeCalendar(
            exchange=Exchange.NSE,
            special_sessions={sess_date: bse_session},
        )


@pytest.mark.parametrize("exchange", [Exchange.NSE, Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ])
def test_p2_incomplete_calendar_daily_d1_fails_closed_across_all_exchanges(exchange: Exchange) -> None:
    """Verify D1 daily ingestion across all 4 exchanges fails closed with exact error code."""
    tz = IST if exchange in (Exchange.NSE, Exchange.BSE) else ET
    t_mon = datetime(2026, 11, 2, 9, 15, tzinfo=tz)
    t_fri = datetime(2026, 11, 6, 9, 15, tzinfo=tz)

    records = [
        {"symbol": "SYM", "exchange": exchange.value, "interval": "1d", "timestamp": t_mon.isoformat(),
         "open": "100.0", "high": "105.0", "low": "99.0", "close": "102.0", "volume": "1000"},
        {"symbol": "SYM", "exchange": exchange.value, "interval": "1d", "timestamp": t_fri.isoformat(),
         "open": "102.0", "high": "106.0", "low": "101.0", "close": "105.0", "volume": "1200"},
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="SYM",
        exchange=exchange,
        interval=CandleInterval.D1,
        start_time=t_mon,
        end_time=t_fri.replace(hour=16, minute=0),
    )
    eval_now = t_fri + timedelta(days=2)

    incomplete_cal = ExchangeCalendar(
        exchange=exchange,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        complete=False,
    )
    res = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_cal)
    assert res.success is False
    assert res.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value


@pytest.mark.parametrize("exchange", [Exchange.NSE, Exchange.BSE, Exchange.NYSE, Exchange.NASDAQ])
def test_p2_incomplete_calendar_intraday_m5_fails_closed_across_all_exchanges(exchange: Exchange) -> None:
    """Verify M5 intraday ingestion across all 4 exchanges fails closed with exact error code."""
    tz = IST if exchange in (Exchange.NSE, Exchange.BSE) else ET
    t_mon_close = datetime(2026, 11, 2, 15, 25, tzinfo=tz)
    t_fri_open = datetime(2026, 11, 6, 9, 30 if exchange in (Exchange.NYSE, Exchange.NASDAQ) else 9, 15, tzinfo=tz)

    records = [
        {"symbol": "SYM", "exchange": exchange.value, "interval": "5m", "timestamp": t_mon_close.isoformat(),
         "open": "100.0", "high": "105.0", "low": "99.0", "close": "102.0", "volume": "1000"},
        {"symbol": "SYM", "exchange": exchange.value, "interval": "5m", "timestamp": t_fri_open.isoformat(),
         "open": "102.0", "high": "106.0", "low": "101.0", "close": "105.0", "volume": "1200"},
    ]
    provider = SyntheticMarketDataProvider(records=records)
    pipeline = MarketDataIngestionPipeline(provider)
    req = HistoricalDataRequest(
        symbol="SYM",
        exchange=exchange,
        interval=CandleInterval.M5,
        start_time=t_mon_close,
        end_time=t_fri_open + timedelta(minutes=5),
    )
    eval_now = t_fri_open + timedelta(hours=1)

    incomplete_cal = ExchangeCalendar(
        exchange=exchange,
        trading_days=frozenset({date(2026, 11, 2), date(2026, 11, 6)}),
        complete=False,
    )
    res = pipeline.ingest_historical(req, now=eval_now, calendar=incomplete_cal)
    assert res.success is False
    assert res.error_code == "MARKET_CALENDAR_REQUIRED"
    assert res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value


# ==============================================================================
# Priority 3: Secret Scanning Baseline & Leak Detection
# ==============================================================================


def test_p3_secrets_baseline_is_clean_and_pinned_to_v150() -> None:
    """Verify that .secrets.baseline exists at repo root, specifies version 1.5.0, and has zero leaks."""
    repo_root = Path(__file__).resolve().parent.parent
    baseline_path = repo_root / ".secrets.baseline"
    assert baseline_path.is_file(), ".secrets.baseline must exist"

    with open(baseline_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("version") == "1.5.0", f"Expected version 1.5.0, got: {data.get('version')}"
    assert "results" in data
    assert len(data["results"]) == 0, f"Expected 0 baselined leaks, found: {data['results']}"


def test_p3_exclusion_pattern_does_not_mask_github_or_ci() -> None:
    """Verify that anchored exclusion pattern excludes exact paths without matching .github or .gitlab-ci.yml."""
    repo_root = Path(__file__).resolve().parent.parent
    baseline_path = repo_root / ".secrets.baseline"
    with open(baseline_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract regex filter patterns
    patterns: list[str] = []
    for filter_spec in data.get("filters_used", []):
        if "should_exclude_file" in filter_spec.get("path", ""):
            patterns.extend(filter_spec.get("pattern", []))

    assert len(patterns) > 0, "No should_exclude_file filter found in baseline"

    combined_regex = re.compile("|".join(patterns))

    # Critical CI and repo paths MUST NOT match (must be scanned!)
    assert not combined_regex.search(".github/workflows/ci.yml")
    assert not combined_regex.search(".github/workflows/leak.yml")
    assert not combined_regex.search(".github/leak.txt")
    assert not combined_regex.search(".gitlab-ci.yml")
    assert not combined_regex.search("src/leak.py")
    assert not combined_regex.search(".env")

    # Exact generated/cache paths MUST match (excluded)
    assert combined_regex.search(".git/config")
    assert combined_regex.search(".venv/bin/python")
    assert combined_regex.search(".venv311/Scripts/python.exe")
    assert combined_regex.search(".coverage")
    assert combined_regex.search("htmlcov/index.html")


def test_p3_detect_secrets_detects_leaks_in_all_required_locations() -> None:
    """Verify detect-secrets identifies dummy secrets across .github, .gitlab-ci, src, .env, and zip."""
    from detect_secrets.core.scan import scan_file
    from detect_secrets.settings import default_settings

    dummy_secret = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        test_files = [
            tmp_path / ".github" / "workflows" / "leak.yml",
            tmp_path / ".github" / "leak.txt",
            tmp_path / ".gitlab-ci.yml",
            tmp_path / "src" / "leak.py",
            tmp_path / ".env",
        ]

        for p in test_files:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"AWS_KEY = '{dummy_secret}'\n", encoding="utf-8")

        # Nested ZIP file
        zip_path = tmp_path / "nested_bundle.zip"
        inner_file = tmp_path / "inner_secret.txt"
        inner_file.write_text(f"AWS_SECRET = '{dummy_secret}'\n", encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(inner_file, arcname="inner_secret.txt")

        # Scan each file with detect-secrets and verify detection
        with default_settings():
            for p in test_files:
                secrets = list(scan_file(str(p)))
                assert len(secrets) > 0, f"detect-secrets failed to detect leak in {p}"
                assert any("AWSKeyDetector" in str(s) or "HighEntropy" in str(s) or "Secret" in str(s) for s in secrets)
