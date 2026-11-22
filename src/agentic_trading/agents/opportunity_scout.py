"""Agent 4 — Opportunity Scout: deterministic filtering, alignment scoring, and shortlist ranking."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from agentic_trading.agents.envelope import AgentEnvelope
from agentic_trading.market_data.instruments import Instrument
from agentic_trading.market_data.models import Candle


@dataclass(frozen=True)
class CandidateProfile:
    instrument: Instrument
    current_candle: Candle
    market_envelope: AgentEnvelope
    data_envelope: AgentEnvelope
    news_envelope: AgentEnvelope


@dataclass(frozen=True)
class ShortlistResult:
    shortlist: tuple[str, ...]
    dropped: Mapping[str, str]
    scores: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.shortlist, tuple):
            object.__setattr__(self, "shortlist", tuple(self.shortlist))


class OpportunityScout:
    """Filters, scores, and ranks watchlist opportunities into an audited shortlist."""

    def __init__(
        self,
        min_avg_volume: int = 10000,
        min_price: Decimal = Decimal("5.0"),
        max_shortlist: int = 3,
    ) -> None:
        self.min_avg_volume = min_avg_volume
        self.min_price = min_price
        self.max_shortlist = max_shortlist

    def scout(self, candidates: Sequence[CandidateProfile]) -> ShortlistResult:
        dropped: dict[str, str] = {}
        scores: dict[str, Decimal] = {}
        scored_candidates: list[tuple[str, Decimal]] = []

        for c in candidates:
            ticker = c.instrument.symbol
            close = c.current_candle.close
            vol = c.current_candle.volume

            if close < self.min_price:
                dropped[ticker] = f"PRICE_BELOW_MINIMUM ({close} < {self.min_price})"
                continue

            if vol < self.min_avg_volume:
                dropped[ticker] = f"VOLUME_BELOW_MINIMUM ({vol} < {self.min_avg_volume})"
                continue

            news_out = c.news_envelope.output
            if news_out.get("blackout_suggested", False):
                dropped[ticker] = "EVENT_BLACKOUT"
                continue

            market_out = c.market_envelope.output
            view = str(market_out.get("view", "neutral")).lower()
            try:
                m_conf = Decimal(str(market_out.get("confidence", "0.5")))
            except (ValueError, TypeError, ArithmeticError):
                m_conf = Decimal("0.5")

            data_out = c.data_envelope.output
            try:
                q_score = Decimal(str(data_out.get("quality", 3)))
                g_score = Decimal(str(data_out.get("growth", 3)))
                fund_factor = (q_score + g_score) / Decimal("10")
            except (ValueError, TypeError, ArithmeticError):
                fund_factor = Decimal("0.5")

            try:
                news_sent = Decimal(str(news_out.get("net_sentiment", "0.0")))
            except (ValueError, TypeError, ArithmeticError):
                news_sent = Decimal("0.0")

            if view == "bearish":
                dropped[ticker] = "BEARISH_MARKET_ALIGNMENT"
                continue

            view_weight = Decimal("1.0") if view == "bullish" else Decimal("0.2")
            composite = (view_weight * m_conf) + (fund_factor * Decimal("0.5")) + (news_sent * Decimal("0.3"))

            if composite <= Decimal("0.3"):
                dropped[ticker] = f"LOW_ALIGNMENT_SCORE ({composite:.2f})"
                continue

            scores[ticker] = composite
            scored_candidates.append((ticker, composite))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        shortlist: list[str] = []
        for rank, (ticker, _) in enumerate(scored_candidates):
            if rank < self.max_shortlist:
                shortlist.append(ticker)
            else:
                dropped[ticker] = f"RANK_EXCEEDED_SHORTLIST_CAP (Rank {rank + 1} > {self.max_shortlist})"

        return ShortlistResult(
            shortlist=tuple(shortlist),
            dropped=dropped,
            scores=scores,
        )
