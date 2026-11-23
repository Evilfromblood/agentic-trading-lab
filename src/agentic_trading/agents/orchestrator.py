"""4-stage trading desk orchestrator managing multi-agent pipeline and paper execution."""
from __future__ import annotations

import concurrent.futures
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from agentic_trading.agents.data_analyst import DataAnalyst, FundamentalSnapshot
from agentic_trading.agents.envelope import AgentEnvelope
from agentic_trading.agents.market_analyst import MarketAnalyst
from agentic_trading.agents.memory import DecisionLog, DecisionRecord, HumanLessonsStore
from agentic_trading.agents.news_analyst import NewsAnalyst, NewsArticle, ScheduledEvent
from agentic_trading.agents.opportunity_scout import CandidateProfile, OpportunityScout
from agentic_trading.agents.reporter import DailyReporter
from agentic_trading.agents.strategist import Strategist, TradingMandate
from agentic_trading.market_data.instruments import Instrument, Money
from agentic_trading.market_data.models import Candle
from agentic_trading.paper_trading.broker import PaperBroker, PaperOrder, ReconciliationReport
from agentic_trading.risk_engine.proposal_gate import (
    PortfolioRiskPolicy,
    ProposalRiskDecision,
    evaluate_trade_proposal,
)
from agentic_trading.strategy.contracts import BarContext, TradeProposal


@dataclass(frozen=True)
class WatchlistTarget:
    instrument: Instrument
    current_candle: Candle
    context: BarContext
    fundamental_snapshot: FundamentalSnapshot | None = None
    news_articles: tuple[NewsArticle, ...] = ()
    scheduled_events: tuple[ScheduledEvent, ...] = ()
    sector: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.news_articles, tuple):
            object.__setattr__(self, "news_articles", tuple(self.news_articles))
        if not isinstance(self.scheduled_events, tuple):
            object.__setattr__(self, "scheduled_events", tuple(self.scheduled_events))


@dataclass(frozen=True)
class DeskCycleResult:
    run_id: str
    as_of: datetime
    envelopes: Mapping[tuple[str, str], AgentEnvelope]
    shortlist: tuple[str, ...]
    dropped_candidates: Mapping[str, str]
    proposals: tuple[TradeProposal, ...]
    decisions: tuple[ProposalRiskDecision, ...]
    orders: tuple[PaperOrder, ...]
    reconciliation: ReconciliationReport
    report: str
    chat_trace: tuple[dict[str, Any], ...] = ()
    trade_plans: tuple[dict[str, Any], ...] = ()
    candle_series: Mapping[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)


def _strip_control_chars(obj: Any) -> Any:
    if isinstance(obj, str):
        return "".join(ch for ch in obj if ch >= " " or ch in "\n\r\t")
    if isinstance(obj, dict):
        return {str(_strip_control_chars(k)): _strip_control_chars(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_strip_control_chars(x) for x in obj]
    return obj


class TradingDeskOrchestrator:
    """Coordinates the 7-agent AI research desk through strict sequential and parallel stages."""

    def __init__(
        self,
        paper_broker: PaperBroker,
        risk_policy: PortfolioRiskPolicy,
        mandate: TradingMandate,
        market_analyst: MarketAnalyst,
        data_analyst: DataAnalyst,
        news_analyst: NewsAnalyst,
        opportunity_scout: OpportunityScout,
        strategist: Strategist,
        decision_log: DecisionLog | None = None,
        lessons_store: HumanLessonsStore | None = None,
        max_workers: int = 4,
    ) -> None:
        self.paper_broker = paper_broker
        self.risk_policy = risk_policy
        self.mandate = mandate
        self.market_analyst = market_analyst
        self.data_analyst = data_analyst
        self.news_analyst = news_analyst
        self.opportunity_scout = opportunity_scout
        self.strategist = strategist
        self.decision_log = decision_log or DecisionLog()
        self.lessons_store = lessons_store or HumanLessonsStore()
        self.max_workers = max_workers

    def run_cycle(
        self,
        run_id: str,
        as_of: datetime,
        watchlist: Sequence[WatchlistTarget],
        sector_map: Mapping[str, str] | None = None,
        auto_execute: bool = True,
    ) -> DeskCycleResult:
        self.paper_broker.kill_switch.assert_clear()

        currency = self.paper_broker.portfolio.currency
        mark_prices: dict[tuple[Any, str], Money] = {}
        target_by_ticker: dict[str, WatchlistTarget] = {}
        candle_series: dict[str, tuple[dict[str, Any], ...]] = {}
        for t in watchlist:
            key = (t.instrument.exchange, t.instrument.symbol)
            mark_prices[key] = Money(t.current_candle.close, t.instrument.currency)
            target_by_ticker[t.instrument.symbol] = t
            candle_series[t.instrument.symbol] = tuple(
                {
                    "timestamp": b.timestamp.isoformat(),
                    "open": str(b.open),
                    "high": str(b.high),
                    "low": str(b.low),
                    "close": str(b.close),
                    "volume": b.volume,
                }
                for b in t.context.bars
            )

        for pos_key, pos in self.paper_broker.portfolio._positions.items():
            if pos.quantity != 0 and pos_key not in mark_prices:
                mark_prices[pos_key] = pos.average_cost

        snapshot = self.paper_broker.portfolio.snapshot(currency, mark_prices, as_of)
        envelopes: dict[tuple[str, str], AgentEnvelope] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            task_futures: list[tuple[str, str, concurrent.futures.Future[AgentEnvelope]]] = []
            for t in watchlist:
                sym = t.instrument.symbol
                task_futures.append(
                    ("market", sym, executor.submit(self.market_analyst.analyze, t.context, run_id))
                )
                task_futures.append(
                    (
                        "data",
                        sym,
                        executor.submit(
                            self.data_analyst.analyze,
                            t.fundamental_snapshot,
                            sym,
                            as_of,
                            run_id,
                        ),
                    )
                )
                task_futures.append(
                    (
                        "news",
                        sym,
                        executor.submit(
                            self.news_analyst.analyze,
                            t.news_articles,
                            t.scheduled_events,
                            sym,
                            as_of,
                            run_id,
                        ),
                    )
                )

            for agent_type, sym, future in task_futures:
                try:
                    envelope = future.result()
                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    TimeoutError,
                    OSError,
                    ArithmeticError,
                    KeyError,
                    AttributeError,
                ) as exc:
                    envelope = AgentEnvelope(
                        run_id=run_id,
                        agent=agent_type,
                        agent_version="1.0.0",
                        prompt_version="1.0.0",
                        model="error-fallback",
                        ticker=sym,
                        as_of=as_of,
                        inputs_hash=f"sha256:error_{sym}",
                        output={"data_quality": "missing"},
                        errors=(str(exc),),
                        latency_ms=0,
                        cost_usd=Decimal("0"),
                    )
                envelopes[(agent_type, sym)] = envelope

        chat_trace: list[dict[str, Any]] = []
        step_counter = 1

        for t in watchlist:
            sym = t.instrument.symbol
            m_env = envelopes[("market", sym)]
            d_env = envelopes[("data", sym)]
            n_env = envelopes[("news", sym)]

            m_status = "missing" if m_env.errors else "ok"
            chat_trace.append(
                _strip_control_chars(
                    {
                        "step": step_counter,
                        "stage": "Stage 1 · Market Analyst",
                        "agent": "market_analyst",
                        "symbol": sym,
                        "model": m_env.model,
                        "input_context": {
                            "symbol": sym,
                            "bars_count": len(t.context.bars),
                            "close": str(t.current_candle.close),
                            "interval": "1d",
                        },
                        "output_message": dict(m_env.output),
                        "status": m_status,
                    }
                )
            )
            step_counter += 1

            d_status = "missing" if d_env.errors else "ok"
            chat_trace.append(
                _strip_control_chars(
                    {
                        "step": step_counter,
                        "stage": "Stage 1 · Data Analyst",
                        "agent": "data_analyst",
                        "symbol": sym,
                        "model": d_env.model,
                        "input_context": {
                            "symbol": sym,
                            "has_fundamental_snapshot": t.fundamental_snapshot is not None,
                            "as_of": as_of.isoformat(),
                        },
                        "output_message": dict(d_env.output),
                        "status": d_status,
                    }
                )
            )
            step_counter += 1

            n_status = "missing" if n_env.errors else "ok"
            chat_trace.append(
                _strip_control_chars(
                    {
                        "step": step_counter,
                        "stage": "Stage 1 · News Analyst",
                        "agent": "news_analyst",
                        "symbol": sym,
                        "model": n_env.model,
                        "input_context": {
                            "symbol": sym,
                            "news_count": len(t.news_articles),
                            "events_count": len(t.scheduled_events),
                        },
                        "output_message": dict(n_env.output),
                        "status": n_status,
                    }
                )
            )
            step_counter += 1

        candidate_profiles: list[CandidateProfile] = []
        for t in watchlist:
            sym = t.instrument.symbol
            m_env = envelopes[("market", sym)]
            d_env = envelopes[("data", sym)]
            n_env = envelopes[("news", sym)]
            candidate_profiles.append(
                CandidateProfile(
                    instrument=t.instrument,
                    current_candle=t.current_candle,
                    market_envelope=m_env,
                    data_envelope=d_env,
                    news_envelope=n_env,
                )
            )

        scout_result = self.opportunity_scout.scout(candidate_profiles)

        scout_status = "ok" if scout_result.shortlist else "no_trade"
        chat_trace.append(
            _strip_control_chars(
                {
                    "step": step_counter,
                    "stage": "Stage 2 · Opportunity Scout",
                    "agent": "opportunity_scout",
                    "symbol": None,
                    "model": "deterministic_scout",
                    "input_context": {
                        "candidate_symbols": [t.instrument.symbol for t in watchlist]
                    },
                    "output_message": {
                        "shortlist": list(scout_result.shortlist),
                        "dropped": dict(scout_result.dropped),
                    },
                    "status": scout_status,
                }
            )
        )
        step_counter += 1

        proposals: list[TradeProposal] = []
        proposal_by_ticker: dict[str, TradeProposal] = {}
        for sym in scout_result.shortlist:
            target = target_by_ticker[sym]
            m_env = envelopes[("market", sym)]
            d_env = envelopes[("data", sym)]
            n_env = envelopes[("news", sym)]
            strat_env, proposal = self.strategist.propose(
                instrument=target.instrument,
                current_candle=target.current_candle,
                market_env=m_env,
                data_env=d_env,
                news_env=n_env,
                portfolio_snapshot=snapshot,
                mandate=self.mandate,
                lessons_store=self.lessons_store,
                run_id=run_id,
            )
            envelopes[("strategist", sym)] = strat_env
            if proposal is not None:
                proposals.append(proposal)
                proposal_by_ticker[sym] = proposal

            strat_status = "approved" if proposal is not None else "no_trade"
            chat_trace.append(
                _strip_control_chars(
                    {
                        "step": step_counter,
                        "stage": "Stage 3 · Strategist",
                        "agent": "strategist",
                        "symbol": sym,
                        "model": strat_env.model,
                        "input_context": {
                            "symbol": sym,
                            "market_price": str(target.current_candle.close),
                            "regime": m_env.output.get("market_regime"),
                            "sentiment": n_env.output.get("sentiment_score"),
                            "data_quality": d_env.output.get("data_quality"),
                        },
                        "output_message": dict(strat_env.output),
                        "status": strat_status,
                    }
                )
            )
            step_counter += 1

        decisions: list[ProposalRiskDecision] = []
        orders: list[PaperOrder] = []

        sectors = dict(sector_map or {})
        for t in watchlist:
            if t.sector and t.instrument.symbol not in sectors:
                sectors[t.instrument.symbol] = t.sector

        sector_counts: dict[str, int] = {}
        for pos_key in snapshot.positions:
            pos_sym = pos_key[1]
            sec = sectors.get(pos_sym)
            if sec:
                sector_counts[sec] = sector_counts.get(sec, 0) + 1

        daily_pnl = Money(snapshot.realized_pnl.amount + snapshot.unrealized_pnl.amount, currency)
        peak_equity = snapshot.total_equity

        if proposals:
            self.paper_broker.kill_switch.assert_clear()

        decision_by_ticker: dict[str, ProposalRiskDecision] = {}
        order_by_ticker: dict[str, PaperOrder] = {}

        current_snapshot = snapshot
        for proposal in proposals:
            sym = proposal.instrument.symbol
            target = target_by_ticker[sym]
            n_env = envelopes[("news", sym)]
            blackout = bool(n_env.output.get("blackout_suggested", False))
            target_sector = sectors.get(sym)

            decision = evaluate_trade_proposal(
                proposal=proposal,
                portfolio=current_snapshot,
                entry_price=Money(target.current_candle.close, currency),
                policy=self.risk_policy,
                daily_pnl=daily_pnl,
                peak_equity=peak_equity,
                sector=target_sector,
                sector_counts=sector_counts,
                event_blackout=blackout,
            )
            decisions.append(decision)
            decision_by_ticker[sym] = decision

            paper_order: PaperOrder | None = None
            if decision.approved:
                if auto_execute:
                    paper_order = self.paper_broker.submit_order(
                        run_id=run_id,
                        proposal=proposal,
                        current_candle=target.current_candle,
                        tick_size=target.instrument.tick_size,
                    )
                    orders.append(paper_order)
                    order_by_ticker[sym] = paper_order
                    if target_sector:
                        sector_counts[target_sector] = sector_counts.get(target_sector, 0) + 1
                    current_snapshot = self.paper_broker.portfolio.snapshot(currency, mark_prices, as_of)
                    daily_pnl = Money(current_snapshot.realized_pnl.amount + current_snapshot.unrealized_pnl.amount, currency)
                    if current_snapshot.total_equity.amount > peak_equity.amount:
                        peak_equity = current_snapshot.total_equity
                    stage_title = "Stage 4 · Risk & Execution"
                    gate_status = "approved"
                else:
                    stage_title = "Stage 4 · Risk & Plan Preview"
                    gate_status = "planned"
            else:
                stage_title = "Stage 4 · Risk & Execution"
                gate_status = "rejected"

            chat_trace.append(
                _strip_control_chars(
                    {
                        "step": step_counter,
                        "stage": stage_title,
                        "agent": "risk_gate",
                        "symbol": sym,
                        "model": "deterministic_gate",
                        "input_context": {
                            "symbol": sym,
                            "side": proposal.side,
                            "quantity": proposal.quantity,
                            "entry_price": str(target.current_candle.close),
                            "stop_loss": str(proposal.stop_loss.amount) if proposal.stop_loss else None,
                            "take_profit": str(proposal.take_profit.amount) if proposal.take_profit else None,
                            "portfolio_equity": str(current_snapshot.total_equity.amount),
                        },
                        "output_message": {
                            "approved": decision.approved,
                            "reasons": list(decision.reasons),
                            "max_allowed_quantity": decision.max_allowed_quantity,
                            "auto_execute": auto_execute,
                            "paper_order_id": paper_order.client_order_id if paper_order else None,
                            "paper_order_status": paper_order.status.value if paper_order else ("PLANNED" if decision.approved else None),
                        },
                        "status": gate_status,
                    }
                )
            )
            step_counter += 1

            if paper_order:
                paper_order_dict = {
                    "client_order_id": paper_order.client_order_id,
                    "status": paper_order.status.value,
                    "filled_quantity": paper_order.filled_quantity,
                    "average_fill_price": str(paper_order.average_fill_price),
                }
            elif decision.approved and not auto_execute:
                paper_order_dict = {
                    "client_order_id": None,
                    "status": "PLANNED",
                    "filled_quantity": 0,
                    "average_fill_price": None,
                }
            else:
                paper_order_dict = None

            record = DecisionRecord(
                run_id=run_id,
                timestamp=as_of,
                ticker=sym,
                inputs_hash=envelopes[("strategist", sym)].inputs_hash,
                analyst_envelopes={
                    "market": dict(envelopes[("market", sym)].output),
                    "data": dict(envelopes[("data", sym)].output),
                    "news": dict(envelopes[("news", sym)].output),
                    "strategist": dict(envelopes[("strategist", sym)].output),
                },
                shortlist_rank=scout_result.shortlist.index(sym) + 1,
                strategist_proposal=dict(envelopes[("strategist", sym)].output),
                risk_decision={
                    "approved": decision.approved,
                    "reasons": decision.reasons,
                    "max_allowed_quantity": decision.max_allowed_quantity,
                },
                paper_order=paper_order_dict,
            )
            self.decision_log.append(record)

        trade_plans: list[dict[str, Any]] = []
        for t in watchlist:
            sym = t.instrument.symbol
            curr_price = t.current_candle.close
            ex_str = t.instrument.exchange.value
            curr_str = t.instrument.currency.value

            if sym not in scout_result.shortlist:
                trade_plans.append(
                    {
                        "symbol": sym,
                        "exchange": ex_str,
                        "currency": curr_str,
                        "action": "no_trade",
                        "status": "no_trade",
                        "current_price": str(curr_price),
                        "buy_price": None,
                        "sell_target": None,
                        "stop_loss": None,
                        "quantity": 0,
                        "reward_to_risk": None,
                        "confidence": "0",
                        "rationale": str(scout_result.dropped.get(sym, "Dropped during candidate screening")),
                        "risk_reasons": [],
                        "executed_order_id": None,
                    }
                )
            elif sym not in proposal_by_ticker:
                strat_env = envelopes.get(("strategist", sym))
                strat_out = strat_env.output if strat_env else {}
                trade_plans.append(
                    {
                        "symbol": sym,
                        "exchange": ex_str,
                        "currency": curr_str,
                        "action": "no_trade",
                        "status": "no_trade",
                        "current_price": str(curr_price),
                        "buy_price": None,
                        "sell_target": None,
                        "stop_loss": None,
                        "quantity": 0,
                        "reward_to_risk": None,
                        "confidence": str(strat_out.get("confidence", "0")),
                        "rationale": str(strat_out.get("disagreement", "") or strat_out.get("thesis", "No trade proposed")),
                        "risk_reasons": [],
                        "executed_order_id": None,
                    }
                )
            else:
                prop = proposal_by_ticker[sym]
                dec = decision_by_ticker[sym]
                strat_env = envelopes[("strategist", sym)]
                strat_out = strat_env.output
                buy_price = curr_price
                stop_loss = prop.stop_loss.amount if prop.stop_loss else None
                sell_target = prop.take_profit.amount if prop.take_profit else None
                qty = dec.max_allowed_quantity if dec.approved else prop.quantity
                r_to_r_str: str | None = None
                if stop_loss and sell_target and buy_price > stop_loss:
                    risk_amt = buy_price - stop_loss
                    reward_amt = sell_target - buy_price
                    if risk_amt > Decimal("0"):
                        r_to_r_val = reward_amt / risk_amt
                        r_to_r_str = str(round(r_to_r_val, 2))

                conf_str = str(strat_out.get("confidence", "0.85"))
                rat_str = str(strat_out.get("thesis", "") or strat_out.get("reasoning", "Buy proposal formulated"))

                if dec.approved:
                    order = order_by_ticker.get(sym)
                    if auto_execute and order:
                        plan_status = "executed"
                        exec_id = order.client_order_id
                    else:
                        plan_status = "planned"
                        exec_id = None
                    risk_reasons_list: list[str] = []
                else:
                    plan_status = "rejected"
                    exec_id = None
                    risk_reasons_list = list(dec.reasons)

                trade_plans.append(
                    {
                        "symbol": sym,
                        "exchange": ex_str,
                        "currency": curr_str,
                        "action": "buy",
                        "status": plan_status,
                        "current_price": str(curr_price),
                        "buy_price": str(buy_price),
                        "sell_target": str(sell_target) if sell_target else None,
                        "stop_loss": str(stop_loss) if stop_loss else None,
                        "quantity": qty,
                        "reward_to_risk": r_to_r_str,
                        "confidence": conf_str,
                        "rationale": rat_str,
                        "risk_reasons": risk_reasons_list,
                        "executed_order_id": exec_id,
                    }
                )

        reconciliation = self.paper_broker.reconcile(as_of, mark_prices)
        report = DailyReporter.generate_eod_report(
            run_id=run_id,
            as_of=as_of,
            portfolio_snapshot=snapshot,
            executed_orders=orders,
            rejected_decisions=[d for d in decisions if not d.approved],
            dropped_candidates=scout_result.dropped,
            reconciliation=reconciliation,
        )

        return DeskCycleResult(
            run_id=run_id,
            as_of=as_of,
            envelopes=envelopes,
            shortlist=scout_result.shortlist,
            dropped_candidates=scout_result.dropped,
            proposals=tuple(proposals),
            decisions=tuple(decisions),
            orders=tuple(orders),
            reconciliation=reconciliation,
            report=report,
            chat_trace=tuple(chat_trace),
            trade_plans=tuple(trade_plans),
            candle_series=dict(candle_series),
        )
