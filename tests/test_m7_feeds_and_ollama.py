"""Comprehensive adversarial tests for Milestone 7 market data feeds and loopback Ollama desk."""
from __future__ import annotations

import concurrent.futures
import json
import tokenize
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_import_boundaries import (
    test_market_data_has_no_broker_or_risk_engine_imports,
    test_risk_engine_has_no_live_broker_imports,
)

from agentic_trading.agents.llm_client import (
    DeterministicStubLLMClient,
    FailoverLLMClient,
    LocalOllamaJSONClient,
)
from agentic_trading.agents.llm_client import (
    _NoRedirectHandler as LLMNoRedirectHandler,
)
from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.feed_bridge import (
    MarketDataQualityGate,
    ReadOnlyMarketFeedBridge,
    ReplayFixtureStore,
)
from agentic_trading.market_data.feed_bridge import (
    _NoRedirectHandler as FeedNoRedirectHandler,
)
from agentic_trading.market_data.models import (
    Candle,
    CandleInterval,
    Exchange,
    get_exchange_timezone,
)


def _make_mock_yahoo_payload(
    symbol: str = "RELIANCE.NS",
    timestamps: list[int] | None = None,
    prices: list[float] | None = None,
) -> bytes:
    ts_list = timestamps or [1700000000 + i * 86400 for i in range(5)]
    p_list = prices or [2400.0, 2410.0, 2420.0, 2415.0, 2430.0]
    opens = [p - 5.0 for p in p_list]
    highs = [p + 10.0 for p in p_list]
    lows = [p - 10.0 for p in p_list]
    closes = p_list
    volumes = [100000 for _ in p_list]
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "INR", "symbol": symbol},
                    "timestamp": ts_list,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    return json.dumps(payload).encode("utf-8")


def test_feed_bridge_parses_valid_delayed_chart_and_caches_to_store(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    raw_payload = _make_mock_yahoo_payload("RELIANCE.NS")

    def mock_fetch(url: str) -> bytes:
        assert "RELIANCE.NS" in url
        return raw_payload

    bridge = ReadOnlyMarketFeedBridge(cache_dir=cache_dir, fetch_fn=mock_fetch)
    res = bridge.fetch_candles(
        exchange=Exchange.NSE,
        symbol="RELIANCE",
        interval=CandleInterval.D1,
        bars_count=5,
        mode="delayed_feed",
    )

    assert res.source == "delayed_feed"
    assert len(res.candles) == 5
    assert len(res.warnings) == 0
    assert res.candles[-1].close == Decimal("2430.0")

    res_cache = bridge.fetch_candles(
        exchange=Exchange.NSE,
        symbol="RELIANCE",
        interval=CandleInterval.D1,
        bars_count=5,
        mode="cache",
    )
    assert res_cache.source == "cache"
    assert len(res_cache.candles) == 5
    assert res_cache.candles[-1].close == Decimal("2430.0")


def test_feed_bridge_rejects_corrupted_ohlc_and_fails_over(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"

    def mock_fetch(url: str) -> bytes:
        corrupted_payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "INR", "symbol": "TCS.NS"},
                        "timestamp": [1700000000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [3500.0],
                                    "high": [3400.0],
                                    "low": [3600.0],
                                    "close": [3550.0],
                                    "volume": [50000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
        return json.dumps(corrupted_payload).encode("utf-8")

    bridge = ReadOnlyMarketFeedBridge(cache_dir=cache_dir, fetch_fn=mock_fetch)
    res = bridge.fetch_candles(
        exchange=Exchange.NSE,
        symbol="TCS",
        interval=CandleInterval.D1,
        bars_count=10,
        mode="delayed_feed",
    )

    assert res.source == "synthetic_fallback"
    assert len(res.warnings) > 0
    assert any("FEED_FAILED" in w for w in res.warnings)
    assert len(res.candles) == 10


def test_feed_bridge_fails_over_to_cache_on_network_error(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    store = ReplayFixtureStore(cache_dir)
    syn_candles = ReadOnlyMarketFeedBridge().generate_synthetic_candles(
        exchange=Exchange.NSE,
        symbol="INFY",
        interval=CandleInterval.D1,
        bars_count=10,
    )
    store.save_candles(
        exchange=Exchange.NSE,
        symbol="INFY",
        interval=CandleInterval.D1,
        candles=syn_candles,
        source="seed_cache",
    )

    def failing_fetch(url: str) -> bytes:
        raise urllib.error.URLError("Connection refused to feed server")

    bridge = ReadOnlyMarketFeedBridge(cache_dir=cache_dir, fetch_fn=failing_fetch)
    res = bridge.fetch_candles(
        exchange=Exchange.NSE,
        symbol="INFY",
        interval=CandleInterval.D1,
        bars_count=10,
        mode="delayed_feed",
    )

    assert res.source == "cache_fallback"
    assert len(res.candles) == 10
    assert any("FEED_FAILED" in w for w in res.warnings)


def test_quality_gate_invariants() -> None:
    tz = get_exchange_timezone(Exchange.NSE)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=tz)

    bad_high_low = Candle(
        symbol="TEST",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("100.00"),
        high=Decimal("90.00"),
        low=Decimal("110.00"),
        close=Decimal("100.00"),
        volume=1000,
        timestamp=now,
        source="test",
        retrieval_timestamp=now,
    )
    valid, issues = MarketDataQualityGate.validate_batch([bad_high_low])
    assert not valid
    assert any("less than low" in issue for issue in issues)

    bad_neg_price = Candle(
        symbol="TEST",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("-5.00"),
        high=Decimal("10.00"),
        low=Decimal("-10.00"),
        close=Decimal("5.00"),
        volume=1000,
        timestamp=now,
        source="test",
        retrieval_timestamp=now,
    )
    valid_neg, issues_neg = MarketDataQualityGate.validate_batch([bad_neg_price])
    assert not valid_neg
    assert any("Non-positive" in issue for issue in issues_neg)


def test_ssrf_and_security_guards(tmp_path: Path) -> None:
    bridge = ReadOnlyMarketFeedBridge(cache_dir=tmp_path)

    with pytest.raises(ValueError, match="SSRF violation: untrusted feed host"):
        bridge._safe_fetch("https://attacker.example.com/v8/finance/chart/TCS")

    with pytest.raises(ValueError, match="SSRF violation: invalid scheme"):
        bridge._safe_fetch("http://query1.finance.yahoo.com/v8/finance/chart/TCS")

    with pytest.raises(ValueError, match="LocalOllamaJSONClient requires a loopback host"):
        LocalOllamaJSONClient(base_url="http://remote.server.internal:11434")

    with pytest.raises(ValueError, match="LocalOllamaJSONClient requires a loopback host"):
        LocalOllamaJSONClient(base_url="https://api.openai.com/v1")

    with pytest.raises(ValueError, match="Invalid model identifier"):
        LocalOllamaJSONClient(default_model="rm -rf /; malicious")


def test_local_ollama_client_and_failover() -> None:
    def mock_ollama_transport(req: urllib.request.Request, timeout: float) -> bytes:
        data = json.loads(req.data.decode("utf-8"))
        assert data["model"] == "gemma4:12b"
        return json.dumps({"response": '{"view": "bullish", "confidence": 0.9}'}).encode("utf-8")

    ollama_client = LocalOllamaJSONClient(
        base_url="http://127.0.0.1:11434",
        default_model="gemma4:12b",
        transport_fn=mock_ollama_transport,
    )
    resp = ollama_client.complete_json("test system", {"ticker": "RELIANCE"}, "gemma4:12b")
    parsed = json.loads(resp)
    assert parsed["view"] == "bullish"
    assert parsed["confidence"] == 0.9

    def failing_transport(req: urllib.request.Request, timeout: float) -> bytes:
        raise ConnectionRefusedError("Ollama daemon offline on port 11434")

    offline_ollama = LocalOllamaJSONClient(
        base_url="http://localhost:11434",
        transport_fn=failing_transport,
    )
    stub_fallback = DeterministicStubLLMClient()
    failover_client = FailoverLLMClient(primary=offline_ollama, fallback=stub_fallback)

    fallback_resp = failover_client.complete_json(
        "Market Analyst",
        {"ticker": "TCS", "close": "3500.0", "support": "3400.0", "resistance": "3600.0"},
        "gemma4:12b",
    )
    parsed_fallback = json.loads(fallback_resp)
    assert parsed_fallback["view"] == "bullish"
    assert parsed_fallback["confidence"] == 0.85

    failover_no_fallback = FailoverLLMClient(primary=offline_ollama, fallback=None)
    missing_resp = failover_no_fallback.complete_json("Test", {"ticker": "XYZ"}, "gemma4:12b")
    parsed_missing = json.loads(missing_resp)
    assert parsed_missing["data_quality"] == "missing"
    assert parsed_missing["fallback_reason"] == "primary_unreachable"


def test_fastapi_endpoints_for_feed_backtest_and_desk(tmp_path: Path) -> None:
    cache_dir = tmp_path / "fixtures"
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        fixture_dir=cache_dir,
    )
    app = create_app(state=state)

    with TestClient(app) as client:
        feed_syn = client.get("/api/feed/NSE/RELIANCE?source=synthetic&bars=20")
        assert feed_syn.status_code == 200
        data_syn = feed_syn.json()
        assert data_syn["paper_only"] is True
        assert data_syn["symbol"] == "RELIANCE"
        assert data_syn["exchange"] == "NSE"
        assert data_syn["candle_count"] == 20
        assert data_syn["source"] == "synthetic"

        feed_bad = client.get("/api/feed/INVALID_EXCHANGE/RELIANCE")
        assert feed_bad.status_code == 400

        bt_res = client.post(
            "/api/backtest",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "initial_capital": "1000000",
                "currency": "INR",
                "bars_count": 30,
                "feed_source": "synthetic",
            },
        )
        assert bt_res.status_code == 200
        bt_data = bt_res.json()
        assert bt_data["paper_only"] is True
        assert bt_data["feed_source"] == "synthetic"
        assert Decimal(str(bt_data["conservation_residual"])) == Decimal("0")

        desk_res = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE", "TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "m7-desk-ollama-run",
                "llm_backend": "ollama",
                "ollama_model": "gemma4:12b",
                "feed_source": "synthetic",
            },
        )
        assert desk_res.status_code == 200
        desk_data = desk_res.json()
        assert desk_data["paper_only"] is True
        assert desk_data["llm_backend"] == "ollama"
        assert desk_data["feed_source"] == "synthetic"
        assert desk_data["reconciled"] is True
        assert len(desk_data["shortlist"]) > 0


def test_feed_bridge_and_ollama_client_reject_http_redirects() -> None:
    feed_handler = FeedNoRedirectHandler()
    with pytest.raises(urllib.error.URLError) as exc_info:
        feed_handler.redirect_request(
            req=urllib.request.Request("https://query1.finance.yahoo.com"),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://169.254.169.254/latest/meta-data",
        )
    assert "HTTP redirects are forbidden" in str(exc_info.value)

    llm_handler = LLMNoRedirectHandler()
    with pytest.raises(urllib.error.URLError) as exc_info_llm:
        llm_handler.redirect_request(
            req=urllib.request.Request("http://127.0.0.1:11434/api/generate"),
            fp=None,
            code=301,
            msg="Moved Permanently",
            headers={},
            newurl="http://internal-vault:8200",
        )
    assert "HTTP redirects are forbidden" in str(exc_info_llm.value)


def test_path_traversal_symbol_rejection_in_feed_bridge_and_route(tmp_path: Path) -> None:
    bridge = ReadOnlyMarketFeedBridge(cache_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.validate_symbol("../secret")

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.validate_symbol("RELIANCE/../../x")

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.validate_symbol("A" * 33)

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.validate_symbol("RELIANCE\0x")

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.fetch_candles(exchange=Exchange.NSE, symbol="../secret")

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.fetch_candles(exchange=Exchange.NSE, symbol="RELIANCE/../../x")

    with pytest.raises(ValueError, match="Invalid symbol identifier"):
        bridge.store.fixture_id_for(Exchange.NSE, "../secret", CandleInterval.D1)

    app = create_app(state=TradingLabState(db_path=tmp_path / "test_api.db"))
    with TestClient(app) as client:
        r1 = client.get("/api/feed/NSE/..secret")
        assert r1.status_code == 400
        assert "symbol must match" in r1.json()["detail"]

        r2 = client.get("/api/feed/NSE/RELIANCE..x")
        assert r2.status_code == 400
        assert "symbol must match" in r2.json()["detail"]

        r3 = client.get("/api/feed/NSE/" + "A" * 33)
        assert r3.status_code == 400
        assert "symbol must match" in r3.json()["detail"]

        r4 = client.get("/api/feed/NSE/..%2Fsecret")
        assert r4.status_code in {400, 404, 422}


def test_concurrent_feed_bridge_cache_access_thread_safety(tmp_path: Path) -> None:
    cache_dir = tmp_path / "concurrent_cache"
    raw_payload = _make_mock_yahoo_payload("INFY.NS")
    bridge = ReadOnlyMarketFeedBridge(
        cache_dir=cache_dir,
        fetch_fn=lambda url: raw_payload,
    )

    def worker(i: int) -> int:
        mode = "delayed_feed" if i % 2 == 0 else "cache"
        res = bridge.fetch_candles(
            exchange=Exchange.NSE,
            symbol="INFY",
            interval=CandleInterval.D1,
            bars_count=5,
            mode=mode,
        )
        return len(res.candles)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(16)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 16
    assert all(count == 5 for count in results)

    loaded = bridge.store.load_candles(Exchange.NSE, "INFY", CandleInterval.D1)
    assert len(loaded) == 5
    assert loaded[-1].close == Decimal("2430.0")


def test_ollama_markdown_fences_and_non_finite_rejection_with_failover() -> None:
    fenced_payload = {
        "model": "gemma4:12b",
        "response": "```json\n{\"action\": \"buy\", \"score\": 95}\n```",
    }
    client = LocalOllamaJSONClient(
        transport_fn=lambda req, timeout: json.dumps(fenced_payload).encode("utf-8")
    )
    res = client.complete_json("system", {"ticker": "TEST"}, "gemma4:12b")
    parsed = json.loads(res)
    assert parsed == {"action": "buy", "score": 95}

    generic_fenced = {
        "model": "gemma4:12b",
        "response": "```\n{\"action\": \"sell\", \"score\": 40}\n```",
    }
    client_gen = LocalOllamaJSONClient(
        transport_fn=lambda req, timeout: json.dumps(generic_fenced).encode("utf-8")
    )
    res_gen = client_gen.complete_json("system", {"ticker": "TEST"}, "gemma4:12b")
    assert json.loads(res_gen) == {"action": "sell", "score": 40}

    non_finite_inner = b'{"model": "gemma4:12b", "response": "{\\"score\\": NaN}"}'
    client_nan = LocalOllamaJSONClient(transport_fn=lambda req, timeout: non_finite_inner)
    with pytest.raises(ValueError):
        client_nan.complete_json("system", {"ticker": "TEST"}, "gemma4:12b")

    stub = DeterministicStubLLMClient()
    failover = FailoverLLMClient(primary=client_nan, fallback=stub)
    failover_res = failover.complete_json(
        "Strategist system prompt",
        {"mandate": "test", "current_price": "100.0"},
        "gemma4:12b",
    )
    failover_parsed = json.loads(failover_res)
    assert failover_parsed["action"] == "buy"
    assert "thesis" in failover_parsed


def test_no_inline_comments_in_m7_code() -> None:
    api_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading" / "api"
    market_data_dir = (
        Path(__file__).resolve().parent.parent / "src" / "agentic_trading" / "market_data"
    )
    agents_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading" / "agents"
    test_file = Path(__file__).resolve()

    files_to_check = [
        test_file,
        market_data_dir / "feed_bridge.py",
        agents_dir / "llm_client.py",
        api_dir / "schemas.py",
        api_dir / "state.py",
        api_dir / "routes.py",
        api_dir / "dashboard.py",
    ]

    for file_path in files_to_check:
        with open(file_path, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    raise AssertionError(
                        f"Inline comment found in {file_path.name} at line {tok.start[0]}: {tok.string}"
                    )


def test_import_boundaries_maintained() -> None:
    test_market_data_has_no_broker_or_risk_engine_imports()
    test_risk_engine_has_no_live_broker_imports()
