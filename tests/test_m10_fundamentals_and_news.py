"""Adversarial tests for SSRF-hardened fundamentals and financial news ingestion adapters (ADR-041)."""
from __future__ import annotations

import io
import json
import re
import tokenize
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_trading.api.app import create_app
from agentic_trading.api.schemas import DeskRunRequest
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.context_bridge import (
    ContextFetchResult,
    ReadOnlyContextBridge,
    _NoRedirectHandler,
)
from agentic_trading.market_data.models import Exchange


def test_context_bridge_ssrf_and_symbol_validation(tmp_path: Path) -> None:
    bridge = ReadOnlyContextBridge(cache_dir=tmp_path)

    with pytest.raises(ValueError, match="SSRF violation: invalid scheme"):
        bridge._safe_fetch("http://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL")

    with pytest.raises(ValueError, match="SSRF violation: invalid scheme"):
        bridge._safe_fetch("ftp://query1.finance.yahoo.com/data")

    with pytest.raises(ValueError, match="SSRF violation: untrusted host"):
        bridge._safe_fetch("https://evil-attacker.com/v10/finance/quoteSummary/AAPL")

    with pytest.raises(ValueError, match="SSRF violation: untrusted host"):
        bridge._safe_fetch("https://127.0.0.1/v10/finance/quoteSummary/AAPL")

    for bad_sym in ["", "   ", "TOOLONGSYMBOL" * 4, "../ESCAPE", "SYM;DROP", "SYM/BO"]:
        with pytest.raises(ValueError, match="Invalid symbol identifier"):
            bridge.validate_symbol(bad_sym)

    assert bridge.validate_symbol("infy") == "INFY"
    assert bridge.validate_symbol("tcs") == "TCS"
    assert bridge.validate_symbol("brk.b") == "BRK.B"


def test_context_bridge_redirects_and_payload_caps(tmp_path: Path) -> None:
    handler = _NoRedirectHandler()
    with pytest.raises(urllib.error.URLError, match="HTTP redirects are forbidden: status=301"):
        handler.redirect_request(None, None, 301, "Moved Permanently", None, "https://target.com")

    def mock_oversized_fetch(url: str) -> bytes:
        return b"X" * 524289

    bridge = ReadOnlyContextBridge(cache_dir=tmp_path, fetch_fn=mock_oversized_fetch)
    with pytest.raises(ValueError, match="Context payload exceeded 512KB limit"):
        bridge._safe_fetch("https://query1.finance.yahoo.com/v10/test")


def test_context_bridge_xxe_and_html_cleaning(tmp_path: Path) -> None:
    bridge = ReadOnlyContextBridge(cache_dir=tmp_path)

    xxe_doctype = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <rss><channel><item><title>&xxe;</title></item></channel></rss>"""
    with pytest.raises(ValueError, match="Forbidden XML DOCTYPE or ENTITY declaration"):
        bridge.parse_rss_xml(xxe_doctype, "AAPL")

    xxe_entity = b"""<?xml version="1.0"?>
    <rss><channel><item><title>&entity;</title><description><!ENTITY lol "lol"></description></item></channel></rss>"""
    with pytest.raises(ValueError, match="Forbidden XML DOCTYPE or ENTITY declaration"):
        bridge.parse_rss_xml(xxe_entity, "AAPL")

    clean_rss = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Yahoo Finance RSS</title>
        <item>
          <title><![CDATA[<b>Apple</b> Inc. Q4 Reports Record &amp; Steady Growth\x00\x08]]></title>
          <description><![CDATA[<p>Quarterly operating margins expanded <b>strongly</b>.</p>]]></description>
          <pubDate>Mon, 24 Nov 2025 14:30:00 +0000</pubDate>
        </item>
      </channel>
    </rss>"""
    articles = bridge.parse_rss_xml(clean_rss, "AAPL")
    assert len(articles) == 1
    art = articles[0]
    assert art.headline == "Apple Inc. Q4 Reports Record & Steady Growth"
    assert art.summary == "Quarterly operating margins expanded strongly."
    assert art.source == "Yahoo Finance RSS"
    assert art.source_tier == 1
    assert art.published_at.year == 2025
    assert art.published_at.tzinfo is not None


def test_context_bridge_deterministic_synthetic_and_cache(tmp_path: Path) -> None:
    bridge = ReadOnlyContextBridge(cache_dir=tmp_path, hmac_key=b"test-secret-key-32-bytes-long!")

    res = bridge.fetch_context(Exchange.NSE, "RELIANCE", mode="synthetic")
    assert isinstance(res, ContextFetchResult)
    assert res.symbol == "RELIANCE"
    assert res.exchange == Exchange.NSE
    assert res.source == "synthetic"
    assert not res.is_blackout
    assert res.snapshot.operating_margin > Decimal("0")
    assert res.snapshot.revenue_growth_yoy > Decimal("0")
    assert len(res.articles) >= 2
    assert len(res.scheduled_events) == 1

    blk_res = bridge.fetch_context(Exchange.NSE, "EARNINGS_NOW", mode="synthetic")
    assert blk_res.is_blackout
    assert (blk_res.scheduled_events[0].event_date - datetime.now(timezone.utc).date()).days <= 2

    bridge.save_cache(res)
    cached = bridge.fetch_context(Exchange.NSE, "RELIANCE", mode="cache")
    assert cached.source == "cache"
    assert cached.symbol == res.symbol
    assert cached.snapshot.operating_margin == res.snapshot.operating_margin
    assert len(cached.articles) == len(res.articles)

    cache_file = tmp_path / "context" / "NSE_RELIANCE.json"
    assert cache_file.is_file()
    tampered_data = json.loads(cache_file.read_text(encoding="utf-8"))
    tampered_data["payload"]["operating_margin"] = "0.9999"
    cache_file.write_text(json.dumps(tampered_data), encoding="utf-8")

    tampered_load = bridge.load_cache(Exchange.NSE, "RELIANCE")
    assert tampered_load is None

    fallback = bridge.fetch_context(Exchange.NSE, "RELIANCE", mode="cache")
    assert fallback.source == "synthetic_fallback"
    assert "CACHE_MISS_FALLBACK_SYNTHETIC" in fallback.warnings


def test_desk_run_with_synthetic_context_and_analyst_evaluation(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    db_path = tmp_path / "audit.db"
    lessons_path = tmp_path / "lessons.txt"
    fixture_dir = tmp_path / "fixtures"

    state = TradingLabState(
        stop_file=stop_file,
        db_path=db_path,
        lessons_path=lessons_path,
        fixture_dir=fixture_dir,
    )
    app = create_app(state)
    client = TestClient(app)

    req = DeskRunRequest(
        watchlist=["RELIANCE"],
        exchange="NSE",
        currency="INR",
        feed_source="synthetic",
        context_source="synthetic",
        llm_backend="stub",
        auto_buy=True,
    )
    resp = client.post("/api/desk/run", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_source"] == "synthetic"
    assert data["paper_only"] is True

    chat = data["chat_trace"]
    data_entry = next(c for c in chat if c["agent"] == "data_analyst")
    news_entry = next(c for c in chat if c["agent"] == "news_analyst")

    assert data_entry["status"] == "ok"
    assert data_entry["output_message"]["data_quality"] == "ok"
    assert data_entry["output_message"]["quality"] in [1, 2, 3, 4, 5]

    assert news_entry["status"] == "ok"
    assert news_entry["output_message"]["data_quality"] == "ok"
    assert "net_sentiment" in news_entry["output_message"]


def test_desk_run_earnings_blackout_enforcement(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    db_path = tmp_path / "audit_blk.db"
    lessons_path = tmp_path / "lessons_blk.txt"
    fixture_dir = tmp_path / "fixtures_blk"

    state = TradingLabState(
        stop_file=stop_file,
        db_path=db_path,
        lessons_path=lessons_path,
        fixture_dir=fixture_dir,
    )
    app = create_app(state)
    client = TestClient(app)

    req = DeskRunRequest(
        watchlist=["EARNINGS_NOW"],
        exchange="NSE",
        currency="INR",
        feed_source="synthetic",
        context_source="synthetic",
        llm_backend="stub",
        auto_buy=True,
    )
    resp = client.post("/api/desk/run", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()

    chat = data["chat_trace"]
    news_entry = next(c for c in chat if c["agent"] == "news_analyst")
    assert news_entry["output_message"]["blackout_suggested"] is True

    risk_entry = next((c for c in chat if c["agent"] == "risk_gate"), None)
    if risk_entry:
        assert risk_entry["status"] == "rejected"
        assert "EVENT_BLACKOUT" in risk_entry["output_message"]["reasons"]

    for tp in data.get("trade_plans", []):
        if tp["symbol"] == "EARNINGS_NOW":
            assert tp["status"] in ["rejected", "no_trade"]


def test_get_context_endpoint_and_dashboard_elements(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    db_path = tmp_path / "audit_ctx.db"
    lessons_path = tmp_path / "lessons_ctx.txt"
    fixture_dir = tmp_path / "fixtures_ctx"

    state = TradingLabState(
        stop_file=stop_file,
        db_path=db_path,
        lessons_path=lessons_path,
        fixture_dir=fixture_dir,
    )
    app = create_app(state)
    client = TestClient(app)

    valid_resp = client.get("/api/context/NSE/RELIANCE?source=synthetic")
    assert valid_resp.status_code == 200
    data = valid_resp.json()
    assert data["paper_only"] is True
    assert data["symbol"] == "RELIANCE"
    assert data["exchange"] == "NSE"
    assert data["currency"] == "INR"
    assert data["source"] == "synthetic"
    assert not data["is_blackout"]
    assert Decimal(data["snapshot"]["operating_margin"]) > Decimal("0")
    assert len(data["articles"]) >= 2
    assert len(data["scheduled_events"]) == 1

    bad_ex = client.get("/api/context/PARIS/RELIANCE")
    assert bad_ex.status_code == 400

    bad_sym = client.get("/api/context/NSE/TOOLONGSYMBOLTOOLONGSYMBOLTOOLONGSYMBOL")
    assert bad_sym.status_code == 400

    bad_chars = client.get("/api/context/NSE/SYM;DROP")
    assert bad_chars.status_code == 400

    dash_resp = client.get("/")
    assert dash_resp.status_code == 200
    html = dash_resp.text
    assert "contextSourceSelect" in html
    assert "overviewContextContainer" in html
    assert "cycleContextPill" in html
    assert "Fundamental Health" in html

    external_links = re.findall(r'(?:src|href)=["\']https?://[^"\']+', html)
    assert len(external_links) == 0


def test_m10_sources_and_tests_have_zero_inline_comments() -> None:
    targets = [
        Path("src/agentic_trading/market_data/context_bridge.py"),
        Path("src/agentic_trading/market_data/__init__.py"),
        Path("src/agentic_trading/agents/memory.py"),
        Path("src/agentic_trading/api/schemas.py"),
        Path("src/agentic_trading/api/state.py"),
        Path("src/agentic_trading/api/routes.py"),
        Path("src/agentic_trading/api/dashboard.py"),
        Path("tests/test_m10_fundamentals_and_news.py"),
    ]
    for target in targets:
        assert target.is_file(), f"Target missing: {target}"
        content = target.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert len(comments) == 0, f"Found {len(comments)} comments in {target}: {[c.string for c in comments]}"
