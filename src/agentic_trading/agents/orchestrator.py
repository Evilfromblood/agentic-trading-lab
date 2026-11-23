"""4-stage trading desk orchestrator managing multi-agent pipeline and paper execution."""
from __future__ import annotations

import concurrent.futures
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    ) -> DeskCycleResult:
        self.paper_broker.kill_switch.assert_clear()

        currency = self.paper_broker.portfolio.currency
        mark_prices: dict[tuple[Any, str], Money] = {}
        target_by_ticker: dict[str, WatchlistTarget] = {}
        for t in watchlist:
            key = (t.instrument.exchange, t.instrument.symbol)
            mark_prices[key] = Money(t.current_candle.close, t.instrument.currency)
            target_by_ticker[t.instrument.symbol] = t

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

            paper_order: PaperOrder | None = None
            if decision.approved:
                paper_order = self.paper_broker.submit_order(
                    run_id=run_id,
                    proposal=proposal,
                    current_candle=target.current_candle,
                    tick_size=target.instrument.tick_size,
                )
                orders.append(paper_order)
                if target_sector:
                    sector_counts[target_sector] = sector_counts.get(target_sector, 0) + 1
                current_snapshot = self.paper_broker.portfolio.snapshot(currency, mark_prices, as_of)
                daily_pnl = Money(current_snapshot.realized_pnl.amount + current_snapshot.unrealized_pnl.amount, currency)
                if current_snapshot.total_equity.amount > peak_equity.amount:
                    peak_equity = current_snapshot.total_equity


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
                paper_order={
                    "client_order_id": paper_order.client_order_id,
                    "status": paper_order.status.value,
                    "filled_quantity": paper_order.filled_quantity,
                    "average_fill_price": str(paper_order.average_fill_price),
                }
                if paper_order
                else None,
            )
            self.decision_log.append(record)

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
        )
