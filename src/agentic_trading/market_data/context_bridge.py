"""SSRF-hardened read-only fundamentals and financial news context adapter."""
from __future__ import annotations

import email.utils
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from agentic_trading.agents.data_analyst import FundamentalSnapshot
from agentic_trading.agents.news_analyst import NewsArticle, ScheduledEvent
from agentic_trading.market_data.models import Exchange

_ALLOWED_CONTEXT_HOSTS = {
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "feeds.finance.yahoo.com",
}
_SAFE_SYMBOL_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rejects HTTP redirects to prevent SSRF origin bouncing."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise urllib.error.URLError(f"HTTP redirects are forbidden: status={code}")


def _validate_symbol(symbol: str) -> str:
    clean = symbol.strip()
    if not clean or len(clean) > 32 or not _SAFE_SYMBOL_REGEX.match(clean) or ".." in clean:
        raise ValueError(f"Invalid symbol identifier: {symbol!r}")
    return clean.upper()


def _clean_text(text: str) -> str:
    unescaped = html.unescape(text)
    stripped_html = re.sub(r"<[^>]+>", "", unescaped)
    return "".join(c for c in stripped_html if c >= " " or c in "\t\n\r").strip()


@dataclass(frozen=True)
class ContextFetchResult:
    """Consolidated fundamental snapshot, news items, and corporate events for a ticker."""

    symbol: str
    exchange: Exchange
    snapshot: FundamentalSnapshot
    articles: tuple[NewsArticle, ...]
    scheduled_events: tuple[ScheduledEvent, ...]
    is_blackout: bool
    source: str
    warnings: tuple[str, ...] = ()


class ReadOnlyContextBridge:
    """SSRF-hardened context adapter for fundamental ratios, financial news, and scheduled events."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        fetch_fn: Callable[[str], bytes] | None = None,
        timeout_seconds: float = 10.0,
        hmac_key: bytes | str | None = None,
    ) -> None:
        base_dir = Path(cache_dir) if cache_dir else Path.cwd() / "data" / "replay_fixtures"
        self._cache_dir = base_dir / "context"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()

        if hmac_key is not None:
            resolved_key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
        else:
            env_key = os.environ.get("TRADING_LAB_REPLAY_HMAC_KEY")
            if env_key:
                resolved_key = env_key.encode("utf-8")
            else:
                resolved_key = secrets.token_bytes(32)
        self.hmac_key: bytes = resolved_key

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        return _validate_symbol(symbol)

    def format_ticker(self, exchange: Exchange, symbol: str) -> str:
        clean = self.validate_symbol(symbol)
        if exchange == Exchange.NSE:
            return f"{clean}.NS"
        if exchange == Exchange.BSE:
            return f"{clean}.BO"
        if exchange in {Exchange.NYSE, Exchange.NASDAQ}:
            return clean
        raise ValueError(f"Unsupported exchange for ticker formatting: {exchange}")

    def format_rss_url(self, exchange: Exchange, symbol: str) -> str:
        ticker = self.format_ticker(exchange, symbol)
        return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}"

    def format_quote_url(self, exchange: Exchange, symbol: str) -> str:
        ticker = self.format_ticker(exchange, symbol)
        return f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=financialData,defaultKeyStatistics"

    def _safe_fetch(self, url: str) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"SSRF violation: invalid scheme {parsed.scheme!r}")
        hostname = (parsed.hostname or "").lower()
        if hostname not in _ALLOWED_CONTEXT_HOSTS:
            raise ValueError(f"SSRF violation: untrusted host {hostname!r}")

        if self.fetch_fn is not None:
            raw = self.fetch_fn(url)
        else:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read(524289)

        if len(raw) > 524288:
            raise ValueError("Context payload exceeded 512KB limit")
        return raw

    def parse_rss_xml(self, payload_bytes: bytes, symbol: str) -> tuple[NewsArticle, ...]:
        clean_symbol = self.validate_symbol(symbol)
        text = payload_bytes.decode("utf-8", errors="replace")
        upper_text = text.upper()
        if "<!DOCTYPE" in upper_text or "<!ENTITY" in upper_text:
            raise ValueError("Forbidden XML DOCTYPE or ENTITY declaration")

        clean_xml = "".join(c for c in text if c >= " " or c in "\t\n\r")
        root = ET.fromstring(clean_xml)
        articles: list[NewsArticle] = []
        now = datetime.now(timezone.utc)

        for item in root.iter("item"):
            title_el = item.find("title")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")

            raw_title = title_el.text if title_el is not None and title_el.text else ""
            raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""
            raw_pub = pub_el.text if pub_el is not None and pub_el.text else ""

            headline = _clean_text(raw_title)
            summary = _clean_text(raw_desc)
            if not headline:
                continue

            pub_dt = now
            if raw_pub:
                try:
                    parsed_dt = email.utils.parsedate_to_datetime(raw_pub)
                    if parsed_dt is not None:
                        if parsed_dt.tzinfo is None:
                            pub_dt = parsed_dt.replace(tzinfo=timezone.utc)
                        else:
                            pub_dt = parsed_dt.astimezone(timezone.utc)
                except (ValueError, TypeError):
                    pub_dt = now

            articles.append(
                NewsArticle(
                    headline=headline,
                    source="Yahoo Finance RSS",
                    source_tier=1,
                    published_at=pub_dt,
                    summary=summary,
                )
            )

        if not articles:
            articles.append(
                NewsArticle(
                    headline=f"Market coverage active for {clean_symbol}",
                    source="Yahoo Finance RSS",
                    source_tier=1,
                    published_at=now,
                    summary="General financial and market context retrieved.",
                )
            )

        return tuple(articles[:5])

    def generate_synthetic_context(
        self,
        exchange: Exchange,
        symbol: str,
        as_of: datetime | None = None,
    ) -> ContextFetchResult:
        clean_symbol = self.validate_symbol(symbol)
        now = as_of or datetime.now(timezone.utc)
        as_of_date = now.date()

        seed_bytes = f"{exchange.value}_{clean_symbol}".encode("utf-8")
        seed_hash = hashlib.sha256(seed_bytes).hexdigest()
        seed = int(seed_hash[:8], 16)

        is_blackout = (
            clean_symbol.endswith("_BLACKOUT")
            or clean_symbol in {"BLACKOUT", "EARNINGS_NOW", "EVENT_RISK"}
        )

        filing_age = 30 + (seed % 35)
        as_of_filing = as_of_date - timedelta(days=filing_age)

        rev_growth = Decimal(str(round(0.08 + (seed % 20) / 100.0, 4)))
        op_margin = Decimal(str(round(0.15 + (seed % 15) / 100.0, 4)))
        fcf_margin = Decimal(str(round(0.10 + (seed % 12) / 100.0, 4)))
        debt_equity = Decimal(str(round(0.25 + (seed % 40) / 100.0, 4)))
        int_coverage = Decimal(str(round(5.0 + (seed % 10), 2)))
        pe_vs_peer = Decimal(str(round(0.90 + (seed % 25) / 100.0, 4)))
        dilution = Decimal("0.0050")

        snapshot = FundamentalSnapshot(
            symbol=clean_symbol,
            as_of_filing=as_of_filing,
            revenue_growth_yoy=rev_growth,
            operating_margin=op_margin,
            fcf_margin=fcf_margin,
            debt_to_equity=debt_equity,
            interest_coverage=int_coverage,
            pe_vs_peer_median=pe_vs_peer,
            dilution_yoy=dilution,
            peer_set=(f"{clean_symbol}_P1", f"{clean_symbol}_P2", f"{clean_symbol}_P3"),
        )

        articles = (
            NewsArticle(
                headline=f"{clean_symbol} reports operational revenue and margin expansion",
                source="MarketDigest",
                source_tier=1,
                published_at=now - timedelta(hours=6),
                summary=f"Quarterly operational indicators reflect positive performance for {clean_symbol}.",
            ),
            NewsArticle(
                headline=f"Institutional analyst coverage notes steady trajectory for {clean_symbol}",
                source="FinancialWire",
                source_tier=2,
                published_at=now - timedelta(hours=20),
                summary=f"Solid market share and capital discipline underpin positive thesis on {clean_symbol}.",
            ),
        )

        if is_blackout:
            event_date = as_of_date + timedelta(days=1)
        else:
            event_date = as_of_date + timedelta(days=45)

        scheduled_events = (
            ScheduledEvent(
                event_name="Quarterly Earnings Release",
                event_date=event_date,
                event_type="EARNINGS",
            ),
        )

        return ContextFetchResult(
            symbol=clean_symbol,
            exchange=exchange,
            snapshot=snapshot,
            articles=articles,
            scheduled_events=scheduled_events,
            is_blackout=is_blackout,
            source="synthetic",
        )

    def _cache_path(self, exchange: Exchange, symbol: str) -> Path:
        clean_symbol = self.validate_symbol(symbol)
        return self._cache_dir / f"{exchange.value}_{clean_symbol}.json"

    def save_cache(self, result: ContextFetchResult) -> None:
        with self._lock:
            data = {
                "symbol": result.symbol,
                "exchange": result.exchange.value,
                "as_of_filing": result.snapshot.as_of_filing.isoformat(),
                "revenue_growth_yoy": str(result.snapshot.revenue_growth_yoy),
                "operating_margin": str(result.snapshot.operating_margin),
                "fcf_margin": str(result.snapshot.fcf_margin),
                "debt_to_equity": str(result.snapshot.debt_to_equity),
                "interest_coverage": str(result.snapshot.interest_coverage),
                "pe_vs_peer_median": str(result.snapshot.pe_vs_peer_median),
                "dilution_yoy": str(result.snapshot.dilution_yoy),
                "peer_set": list(result.snapshot.peer_set),
                "articles": [
                    {
                        "headline": a.headline,
                        "source": a.source,
                        "source_tier": a.source_tier,
                        "published_at": a.published_at.isoformat(),
                        "summary": a.summary,
                    }
                    for a in result.articles
                ],
                "scheduled_events": [
                    {
                        "event_name": e.event_name,
                        "event_date": e.event_date.isoformat(),
                        "event_type": e.event_type,
                    }
                    for e in result.scheduled_events
                ],
                "is_blackout": result.is_blackout,
            }
            canonical_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
            signature = hmac.new(self.hmac_key, canonical_bytes, hashlib.sha256).hexdigest()
            wrapper = {
                "signature": signature,
                "payload": data,
            }
            path = self._cache_path(result.exchange, result.symbol)
            path.write_text(json.dumps(wrapper, indent=2), encoding="utf-8")

    def load_cache(self, exchange: Exchange, symbol: str) -> ContextFetchResult | None:
        with self._lock:
            path = self._cache_path(exchange, symbol)
            if not path.is_file():
                return None
            try:
                raw_text = path.read_text(encoding="utf-8")
                wrapper = json.loads(raw_text)
                expected_sig = wrapper.get("signature", "")
                data = wrapper.get("payload", {})
                canonical_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                computed_sig = hmac.new(self.hmac_key, canonical_bytes, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected_sig, computed_sig):
                    return None

                snapshot = FundamentalSnapshot(
                    symbol=data["symbol"],
                    as_of_filing=date.fromisoformat(data["as_of_filing"]),
                    revenue_growth_yoy=Decimal(data["revenue_growth_yoy"]),
                    operating_margin=Decimal(data["operating_margin"]),
                    fcf_margin=Decimal(data["fcf_margin"]),
                    debt_to_equity=Decimal(data["debt_to_equity"]),
                    interest_coverage=Decimal(data["interest_coverage"]),
                    pe_vs_peer_median=Decimal(data["pe_vs_peer_median"]),
                    dilution_yoy=Decimal(data["dilution_yoy"]),
                    peer_set=tuple(data.get("peer_set", ())),
                )
                articles = tuple(
                    NewsArticle(
                        headline=a["headline"],
                        source=a["source"],
                        source_tier=a["source_tier"],
                        published_at=datetime.fromisoformat(a["published_at"]),
                        summary=a.get("summary", ""),
                    )
                    for a in data.get("articles", [])
                )
                scheduled_events = tuple(
                    ScheduledEvent(
                        event_name=e["event_name"],
                        event_date=date.fromisoformat(e["event_date"]),
                        event_type=e["event_type"],
                    )
                    for e in data.get("scheduled_events", [])
                )
                return ContextFetchResult(
                    symbol=data["symbol"],
                    exchange=exchange,
                    snapshot=snapshot,
                    articles=articles,
                    scheduled_events=scheduled_events,
                    is_blackout=bool(data.get("is_blackout", False)),
                    source="cache",
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                return None

    def fetch_context(
        self,
        exchange: Exchange,
        symbol: str,
        as_of: datetime | None = None,
        mode: Literal["synthetic", "cache", "live"] = "synthetic",
    ) -> ContextFetchResult:
        clean_symbol = self.validate_symbol(symbol)

        if mode == "synthetic":
            return self.generate_synthetic_context(exchange, clean_symbol, as_of)

        if mode == "cache":
            cached = self.load_cache(exchange, clean_symbol)
            if cached is not None:
                return cached
            fallback = self.generate_synthetic_context(exchange, clean_symbol, as_of)
            return ContextFetchResult(
                symbol=fallback.symbol,
                exchange=fallback.exchange,
                snapshot=fallback.snapshot,
                articles=fallback.articles,
                scheduled_events=fallback.scheduled_events,
                is_blackout=fallback.is_blackout,
                source="synthetic_fallback",
                warnings=("CACHE_MISS_FALLBACK_SYNTHETIC",),
            )

        warnings: list[str] = []
        try:
            rss_url = self.format_rss_url(exchange, clean_symbol)
            rss_bytes = self._safe_fetch(rss_url)
            articles = self.parse_rss_xml(rss_bytes, clean_symbol)

            syn_base = self.generate_synthetic_context(exchange, clean_symbol, as_of)
            live_result = ContextFetchResult(
                symbol=clean_symbol,
                exchange=exchange,
                snapshot=syn_base.snapshot,
                articles=articles,
                scheduled_events=syn_base.scheduled_events,
                is_blackout=syn_base.is_blackout,
                source="live",
            )
            self.save_cache(live_result)
            return live_result
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            ET.ParseError,
        ) as exc:
            warnings.append(f"LIVE_CONTEXT_FAILED: {exc}")

        cached = self.load_cache(exchange, clean_symbol)
        if cached is not None:
            return ContextFetchResult(
                symbol=cached.symbol,
                exchange=cached.exchange,
                snapshot=cached.snapshot,
                articles=cached.articles,
                scheduled_events=cached.scheduled_events,
                is_blackout=cached.is_blackout,
                source="cache_fallback",
                warnings=tuple(warnings),
            )

        syn = self.generate_synthetic_context(exchange, clean_symbol, as_of)
        return ContextFetchResult(
            symbol=syn.symbol,
            exchange=syn.exchange,
            snapshot=syn.snapshot,
            articles=syn.articles,
            scheduled_events=syn.scheduled_events,
            is_blackout=syn.is_blackout,
            source="synthetic_fallback",
            warnings=tuple(warnings),
        )
