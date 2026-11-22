"""Agent 5 — Strategist: synthesizes multi-analyst intelligence into mathematical TradeProposals."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agentic_trading.agents.envelope import AgentEnvelope, invoke_with_schema_guard
from agentic_trading.agents.llm_client import LLMClient
from agentic_trading.agents.memory import HumanLessonsStore
from agentic_trading.market_data.instruments import Instrument, Money
from agentic_trading.market_data.models import Candle, Exchange
from agentic_trading.simulation.portfolio import PortfolioSnapshot
from agentic_trading.strategy.contracts import TradeProposal

AGENT_NAME = "strategist"
AGENT_VERSION = "1.0.0"
PROMPT_VERSION = "1.0.0"
SYSTEM_PROMPT = """You are a Portfolio Strategist.
Evaluate all analyst inputs, portfolio constraints, and human lessons to formulate a trading plan.
Return a structured JSON response with:
- "action": "buy", "sell", or "no_trade"
- "entry": proposed entry price
- "stop": proposed protective stop-loss level (< entry for buy)
- "target": proposed profit-taking target level (> entry for buy)
- "horizon_days": expected holding horizon in trading days
- "confidence": confidence score in [0.0, 1.0]
- "thesis": concise trade rationale
- "disagreement": notes on conflicting analyst views
- "invalidation": fundamental or technical invalidation condition
- "reasoning": detailed execution reasoning
"""


@dataclass(frozen=True)
class TradingMandate:
    horizon_days: int = 5
    allowed_exchanges: tuple[Exchange, ...] = (
        Exchange.NSE,
        Exchange.BSE,
        Exchange.NASDAQ,
        Exchange.NYSE,
    )
    long_only: bool = True
    min_reward_to_risk: Decimal = Decimal("1.5")
    risk_per_trade_pct: Decimal = Decimal("0.02")
    position_size_pct: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_exchanges, tuple):
            object.__setattr__(self, "allowed_exchanges", tuple(self.allowed_exchanges))


class Strategist:
    """Synthesizes analyst outputs into risk-aware, mandate-governed TradeProposals."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: str = "default-strategist",
    ) -> None:
        self.llm_client = llm_client
        self.model = model

    def propose(
        self,
        instrument: Instrument,
        current_candle: Candle,
        market_env: AgentEnvelope,
        data_env: AgentEnvelope,
        news_env: AgentEnvelope,
        portfolio_snapshot: PortfolioSnapshot,
        mandate: TradingMandate,
        lessons_store: HumanLessonsStore | None,
        run_id: str,
    ) -> tuple[AgentEnvelope, TradeProposal | None]:
        ticker = instrument.symbol
        as_of = current_candle.close_time
        lessons = lessons_store.load_lessons() if lessons_store else ()

        user_payload: dict[str, Any] = {
            "ticker": ticker,
            "exchange": instrument.exchange.value,
            "current_price": str(current_candle.close),
            "mandate": {
                "horizon_days": mandate.horizon_days,
                "min_reward_to_risk": str(mandate.min_reward_to_risk),
                "position_size_pct": str(mandate.position_size_pct),
            },
            "market_analysis": market_env.output,
            "fundamental_analysis": data_env.output,
            "news_analysis": news_env.output,
            "human_lessons": list(lessons),
            "portfolio_equity": str(portfolio_snapshot.total_equity.amount),
            "portfolio_cash": str(portfolio_snapshot.cash.amount),
        }

        envelope = invoke_with_schema_guard(
            run_id=run_id,
            agent=AGENT_NAME,
            agent_version=AGENT_VERSION,
            prompt_version=PROMPT_VERSION,
            model=self.model,
            ticker=ticker,
            as_of=as_of,
            user_payload=user_payload,
            caller=self.llm_client.complete_json,
            system_prompt=SYSTEM_PROMPT,
            required_keys=(
                "action",
                "entry",
                "stop",
                "target",
                "horizon_days",
                "confidence",
                "thesis",
                "disagreement",
                "invalidation",
                "reasoning",
            ),
        )

        out = dict(envelope.output)
        action = str(out.get("action", "no_trade")).lower()

        def make_result_env() -> AgentEnvelope:
            return AgentEnvelope(
                run_id=envelope.run_id,
                agent=envelope.agent,
                agent_version=envelope.agent_version,
                prompt_version=envelope.prompt_version,
                model=envelope.model,
                ticker=envelope.ticker,
                as_of=envelope.as_of,
                inputs_hash=envelope.inputs_hash,
                output=out,
                errors=envelope.errors,
                latency_ms=envelope.latency_ms,
                cost_usd=envelope.cost_usd,
            )

        if instrument.exchange not in mandate.allowed_exchanges:
            out["action"] = "no_trade"
            out["disagreement"] = f"Exchange {instrument.exchange.value} not allowed by mandate"
            return make_result_env(), None

        if mandate.long_only and action == "sell":
            out["action"] = "no_trade"
            out["disagreement"] = "Mandate is long-only; sell signals disallowed"
            return make_result_env(), None

        if action != "buy":
            return make_result_env(), None

        try:
            entry = Decimal(str(out.get("entry", current_candle.close)))
            stop = Decimal(str(out.get("stop", "0")))
            target = Decimal(str(out.get("target", "0")))
        except (ValueError, TypeError, ArithmeticError):
            out["action"] = "no_trade"
            out["disagreement"] = "Malformed numeric pricing levels in proposal"
            return make_result_env(), None

        if not (stop < entry < target):
            out["action"] = "no_trade"
            out["disagreement"] = f"Inverted or non-positive brackets: stop={stop}, entry={entry}, target={target}"
            return make_result_env(), None

        risk = entry - stop
        reward = target - entry
        reward_to_risk = reward / risk if risk > Decimal("0") else Decimal("0")

        if reward_to_risk < mandate.min_reward_to_risk:
            out["action"] = "no_trade"
            out["disagreement"] = (
                f"Reward-to-risk {reward_to_risk:.2f} below minimum {mandate.min_reward_to_risk}"
            )
            return make_result_env(), None

        lot = instrument.lot_size if instrument.lot_size > 0 else 1
        target_notional = portfolio_snapshot.total_equity.amount * mandate.position_size_pct
        qty = int(target_notional // entry)
        qty = (qty // lot) * lot

        if qty < lot:
            out["action"] = "no_trade"
            out["disagreement"] = f"Calculated quantity {qty} below lot size {lot}"
            return make_result_env(), None

        proposal = TradeProposal(
            proposal_id=f"P-{run_id}-{instrument.symbol}",
            strategy_id="strategist_agent",
            instrument=instrument,
            timestamp=as_of,
            side="BUY",
            quantity=qty,
            order_type="MARKET",
            limit_price=None,
            stop_loss=Money(stop, instrument.currency),
            take_profit=Money(target, instrument.currency),
        )

        return make_result_env(), proposal
