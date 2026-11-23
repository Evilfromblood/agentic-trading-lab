"""Read-only delayed market data feed bridge, quality gate, and HMAC replay fixture cache."""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from agentic_trading.market_data.models import (
    Candle,
    CandleInterval,
    Exchange,
    get_exchange_timezone,
)
from agentic_trading.market_data.provider import ProviderResponse
from agentic_trading.market_data.replay_fixtures import (
    StoredReplayFixtureProvider,
    _reject_constant,
    save_replay_fixture,
)

_ALLOWED_FEED_HOSTS = {
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
}
_SAFE_SYMBOL_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rejects HTTP redirects to prevent SSRF bouncing and origin escalation."""

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


@dataclass(frozen=True)
class FeedFetchResult:
    """Result of fetching or generating market data candles."""

    exchange: Exchange
    symbol: str
    interval: CandleInterval
    candles: tuple[Candle, ...]
    source: str
    warnings: tuple[str, ...] = ()


class MarketDataQualityGate:
    """Validates structural and geometric consistency of candle batches."""

    @staticmethod
    def validate_candle(candle: Candle) -> list[str]:
        issues: list[str] = []
        if candle.open <= Decimal("0"):
            issues.append(f"Non-positive open: {candle.open}")
        if candle.high <= Decimal("0"):
            issues.append(f"Non-positive high: {candle.high}")
        if candle.low <= Decimal("0"):
            issues.append(f"Non-positive low: {candle.low}")
        if candle.close <= Decimal("0"):
            issues.append(f"Non-positive close: {candle.close}")
        if candle.high < candle.low:
            issues.append(f"High {candle.high} less than low {candle.low}")
        if candle.high < max(candle.open, candle.close):
            issues.append(f"High {candle.high} less than max(open, close)")
        if candle.low > min(candle.open, candle.close):
            issues.append(f"Low {candle.low} greater than min(open, close)")
        if candle.volume < 0:
            issues.append(f"Negative volume: {candle.volume}")
        return issues

    @classmethod
    def validate_batch(cls, candles: Sequence[Candle]) -> tuple[bool, tuple[str, ...]]:
        if not candles:
            return False, ("Empty candle batch",)
        issues: list[str] = []
        prev_ts: datetime | None = None
        for i, candle in enumerate(candles):
            candle_issues = cls.validate_candle(candle)
            if candle_issues:
                issues.extend(f"Bar {i} ({candle.timestamp}): {issue}" for issue in candle_issues)
            if prev_ts is not None and candle.timestamp <= prev_ts:
                issues.append(f"Non-monotonic timestamp at bar {i}: {candle.timestamp} <= {prev_ts}")
            prev_ts = candle.timestamp
        return len(issues) == 0, tuple(issues)


class ReplayFixtureStore:
    """Manages persistent HMAC-verified replay fixtures for market data caching."""

    def __init__(
        self,
        directory: Path | str,
        hmac_key: bytes | str | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.hmac_key = hmac_key

    def fixture_id_for(
        self,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval,
    ) -> str:
        clean_sym = _validate_symbol(symbol)
        return f"{exchange.value}_{clean_sym}_{interval.value}"

    def save_candles(
        self,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval,
        candles: Sequence[Candle],
        source: str = "feed_bridge",
    ) -> None:
        with self._lock:
            if not candles:
                return
            clean_sym = _validate_symbol(symbol)
            fixture_id = self.fixture_id_for(exchange, clean_sym, interval)
            records: list[dict[str, Any]] = []
            for c in candles:
                records.append({
                    "timestamp": c.timestamp.isoformat(),
                    "open": str(c.open),
                    "high": str(c.high),
                    "low": str(c.low),
                    "close": str(c.close),
                    "volume": c.volume,
                    "source": c.source,
                    "retrieval_timestamp": c.retrieval_timestamp.isoformat(),
                })
            now = datetime.now(timezone.utc)
            response = ProviderResponse(
                success=True,
                records=tuple(records),
                source=source,
                retrieval_timestamp=now,
            )
            save_kwargs: dict[str, Any] = {
                "directory": self.directory,
                "fixture_id": fixture_id,
                "response": response,
                "exchange": exchange,
                "symbol": clean_sym,
                "interval": interval,
                "overwrite": True,
            }
            if self.hmac_key is not None:
                save_kwargs["hmac_key"] = self.hmac_key
            save_replay_fixture(**save_kwargs)

    def load_candles(
        self,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval,
    ) -> tuple[Candle, ...]:
        with self._lock:
            clean_sym = _validate_symbol(symbol)
            fixture_id = self.fixture_id_for(exchange, clean_sym, interval)
            provider_kwargs: dict[str, Any] = {
                "directory": self.directory,
                "fixture_id": fixture_id,
            }
            if self.hmac_key is not None:
                provider_kwargs["hmac_key"] = self.hmac_key
            provider = StoredReplayFixtureProvider(**provider_kwargs)
            manifest, records = provider._load_and_verify()
            candles: list[Candle] = []
            for rec in records:
                ts = datetime.fromisoformat(str(rec["timestamp"]))
                ret_raw = rec.get("retrieval_timestamp")
                ret_ts = datetime.fromisoformat(str(ret_raw)) if ret_raw else ts
                candles.append(
                    Candle(
                        symbol=clean_sym,
                        exchange=exchange,
                        interval=interval,
                        open=Decimal(str(rec["open"])),
                        high=Decimal(str(rec["high"])),
                        low=Decimal(str(rec["low"])),
                        close=Decimal(str(rec["close"])),
                        volume=int(rec.get("volume", 0)),
                        timestamp=ts,
                        source=f"replay_cache:{manifest.fixture_id}",
                        retrieval_timestamp=ret_ts,
                    )
                )
            return tuple(candles)


class ReadOnlyMarketFeedBridge:
    """Read-only delayed market data adapter with SSRF protection, quality gate, and failover."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        fetch_fn: Callable[[str], bytes] | None = None,
        timeout_seconds: float = 5.0,
        hmac_key: bytes | str | None = None,
    ) -> None:
        target_dir = Path(cache_dir) if cache_dir else Path.cwd() / "data" / "replay_fixtures"
        if hmac_key is not None:
            resolved_key: bytes | str = hmac_key
        else:
            env_key = os.environ.get("TRADING_LAB_REPLAY_HMAC_KEY")
            if env_key:
                resolved_key = env_key
            else:
                resolved_key = secrets.token_bytes(32)
        self.hmac_key = resolved_key
        self.store = ReplayFixtureStore(target_dir, hmac_key=resolved_key)
        self.fetch_fn = fetch_fn
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()


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

    def format_url(self, exchange: Exchange, symbol: str, interval: CandleInterval) -> str:
        ticker = self.format_ticker(exchange, symbol)
        range_param = "3mo" if interval == CandleInterval.D1 else "5d"
        interval_param = "1d" if interval == CandleInterval.D1 else "1m"
        return f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval_param}&range={range_param}"

    def _safe_fetch(self, url: str) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"SSRF violation: invalid scheme {parsed.scheme!r}")
        hostname = (parsed.hostname or "").lower()
        if hostname not in _ALLOWED_FEED_HOSTS:
            raise ValueError(f"SSRF violation: untrusted feed host {hostname!r}")

        if self.fetch_fn is not None:
            raw = self.fetch_fn(url)
        else:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read(1048577)

        if len(raw) > 1048576:
            raise ValueError("Feed response payload exceeded 1MB limit")
        return raw

    def parse_chart_json(
        self,
        payload_bytes: bytes,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval,
    ) -> tuple[Candle, ...]:
        clean_symbol = self.validate_symbol(symbol)
        tz = get_exchange_timezone(exchange)
        data = json.loads(payload_bytes.decode("utf-8"), parse_constant=_reject_constant)

        chart = data.get("chart", {})
        results = chart.get("result")
        if not results or not isinstance(results, list):
            err = chart.get("error")
            raise ValueError(f"Chart response error: {err}")

        res0 = results[0]
        timestamps = res0.get("timestamp", [])
        indicators = res0.get("indicators", {})
        quotes = indicators.get("quote", [])
        if not quotes or not isinstance(quotes, list):
            raise ValueError("Missing quote indicators in chart JSON")

        q0 = quotes[0]
        opens = q0.get("open", [])
        highs = q0.get("high", [])
        lows = q0.get("low", [])
        closes = q0.get("close", [])
        volumes = q0.get("volume", [])

        now = datetime.now(timezone.utc)
        candles: list[Candle] = []

        for i in range(len(timestamps)):
            o_val = opens[i] if i < len(opens) else None
            h_val = highs[i] if i < len(highs) else None
            l_val = lows[i] if i < len(lows) else None
            c_val = closes[i] if i < len(closes) else None
            if o_val is None or h_val is None or l_val is None or c_val is None:
                continue

            o_dec = Decimal(str(round(float(o_val), 4)))
            h_dec = Decimal(str(round(float(h_val), 4)))
            l_dec = Decimal(str(round(float(l_val), 4)))
            c_dec = Decimal(str(round(float(c_val), 4)))
            v_int = int(volumes[i] or 0) if i < len(volumes) else 0

            bar_ts = datetime.fromtimestamp(timestamps[i], tz=tz)
            candles.append(
                Candle(
                    symbol=clean_symbol,
                    exchange=exchange,
                    interval=interval,
                    open=o_dec,
                    high=h_dec,
                    low=l_dec,
                    close=c_dec,
                    volume=max(0, v_int),
                    timestamp=bar_ts,
                    source="delayed_feed",
                    retrieval_timestamp=now,
                )
            )

        return tuple(candles)

    def generate_synthetic_candles(
        self,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval = CandleInterval.D1,
        bars_count: int = 30,
        as_of: datetime | None = None,
    ) -> tuple[Candle, ...]:
        clean_symbol = self.validate_symbol(symbol)
        tz = get_exchange_timezone(exchange)
        moment = as_of or datetime.now(timezone.utc)
        local_moment = moment.astimezone(tz)
        base_date = local_moment.replace(hour=9, minute=15, second=0, microsecond=0)

        candles: list[Candle] = []
        base_price = Decimal("100.00")

        for i in range(bars_count):
            offset_days = bars_count - 1 - i
            bar_ts = base_date - timedelta(days=offset_days)
            wave = Decimal(str((i % 20) * 2 - (i % 7)))
            c_close = base_price + wave
            c_high = c_close + Decimal("3.00")
            c_low = max(Decimal("1.00"), c_close - Decimal("2.00"))
            c_open = max(Decimal("1.00"), c_close - Decimal("1.00"))
            ret_ts = bar_ts + timedelta(hours=6, minutes=15)

            candles.append(
                Candle(
                    symbol=clean_symbol,
                    exchange=exchange,
                    interval=interval,
                    open=c_open,
                    high=c_high,
                    low=c_low,
                    close=c_close,
                    volume=50000 + (i % 10) * 1000,
                    timestamp=bar_ts,
                    source="synthetic",
                    retrieval_timestamp=ret_ts,
                )
            )

        return tuple(candles)

    def fetch_candles(
        self,
        exchange: Exchange,
        symbol: str,
        interval: CandleInterval = CandleInterval.D1,
        bars_count: int = 30,
        mode: Literal["synthetic", "cache", "delayed_feed"] = "synthetic",
        as_of: datetime | None = None,
    ) -> FeedFetchResult:
        clean_symbol = self.validate_symbol(symbol)

        if mode == "synthetic":
            syn = self.generate_synthetic_candles(
                exchange=exchange,
                symbol=clean_symbol,
                interval=interval,
                bars_count=bars_count,
                as_of=as_of,
            )
            return FeedFetchResult(
                exchange=exchange,
                symbol=clean_symbol,
                interval=interval,
                candles=syn,
                source="synthetic",
            )

        if mode == "cache":
            try:
                with self._lock:
                    cached = self.store.load_candles(exchange, clean_symbol, interval)
                if cached:
                    sliced = cached[-bars_count:] if len(cached) > bars_count else cached
                    return FeedFetchResult(
                        exchange=exchange,
                        symbol=clean_symbol,
                        interval=interval,
                        candles=sliced,
                        source="cache",
                    )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass

            syn = self.generate_synthetic_candles(
                exchange=exchange,
                symbol=clean_symbol,
                interval=interval,
                bars_count=bars_count,
                as_of=as_of,
            )
            return FeedFetchResult(
                exchange=exchange,
                symbol=clean_symbol,
                interval=interval,
                candles=syn,
                source="synthetic_fallback",
                warnings=("CACHE_MISS_FALLBACK_SYNTHETIC",),
            )

        warnings: list[str] = []
        try:
            url = self.format_url(exchange, clean_symbol, interval)
            raw_bytes = self._safe_fetch(url)
            parsed_candles = self.parse_chart_json(raw_bytes, exchange, clean_symbol, interval)
            is_valid, issues = MarketDataQualityGate.validate_batch(parsed_candles)
            if not is_valid:
                raise ValueError(f"Quality gate rejected delayed candles: {'; '.join(issues)}")

            with self._lock:
                self.store.save_candles(exchange, clean_symbol, interval, parsed_candles, source="delayed_feed")
            sliced = parsed_candles[-bars_count:] if len(parsed_candles) > bars_count else parsed_candles
            return FeedFetchResult(
                exchange=exchange,
                symbol=clean_symbol,
                interval=interval,
                candles=sliced,
                source="delayed_feed",
            )
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"FEED_FAILED: {exc}")

        try:
            with self._lock:
                cached = self.store.load_candles(exchange, clean_symbol, interval)
            if cached:
                sliced = cached[-bars_count:] if len(cached) > bars_count else cached
                return FeedFetchResult(
                    exchange=exchange,
                    symbol=clean_symbol,
                    interval=interval,
                    candles=sliced,
                    source="cache_fallback",
                    warnings=tuple(warnings),
                )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as cache_exc:
            warnings.append(f"CACHE_FALLBACK_FAILED: {cache_exc}")

        syn = self.generate_synthetic_candles(
            exchange=exchange,
            symbol=clean_symbol,
            interval=interval,
            bars_count=bars_count,
            as_of=as_of,
        )
        return FeedFetchResult(
            exchange=exchange,
            symbol=clean_symbol,
            interval=interval,
            candles=syn,
            source="synthetic_fallback",
            warnings=tuple(warnings),
        )
