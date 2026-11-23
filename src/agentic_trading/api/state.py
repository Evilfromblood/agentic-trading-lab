"""Thread-safe isolated state container for the Agentic Trading Lab FastAPI application."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from agentic_trading.agents.data_analyst import DataAnalyst, FundamentalSnapshot
from agentic_trading.agents.llm_client import DeterministicStubLLMClient
from agentic_trading.agents.market_analyst import MarketAnalyst
from agentic_trading.agents.memory import DecisionLog, HumanLessonsStore
from agentic_trading.agents.news_analyst import NewsAnalyst, NewsArticle
from agentic_trading.agents.opportunity_scout import OpportunityScout
from agentic_trading.agents.orchestrator import (
    TradingDeskOrchestrator,
    WatchlistTarget,
)
from agentic_trading.agents.strategist import Strategist, TradingMandate
from agentic_trading.api.schemas import (
    BacktestRequest,
    BacktestResponse,
    DecisionRecordItem,
    DeskRunRequest,
    DeskRunResponse,
    OrderResponse,
    PortfolioSummaryResponse,
    PositionSummary,
    SubmitOrderRequest,
)
from agentic_trading.market_data.instruments import (
    Currency,
    CurrencyMismatchError,
    Instrument,
    Money,
)
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange
from agentic_trading.paper_trading.broker import PaperBroker
from agentic_trading.paper_trading.kill_switch import KillSwitch, KillSwitchError
from agentic_trading.risk_engine.proposal_gate import PortfolioRiskPolicy
from agentic_trading.simulation.costs import (
    BasisPointsSlippageModel,
    IndiaEquityFeeModel,
    USEquityFeeModel,
)
from agentic_trading.simulation.portfolio import PortfolioEngine
from agentic_trading.strategy.contracts import (
    BarContext,
    Signal,
    SignalDirection,
    Strategy,
    TradeProposal,
)
from agentic_trading.time_machine.engine import (
    BacktestConfig,
    BacktestEngine,
    ledger_conservation_residual,
)
from agentic_trading.time_machine.manifest import verify_manifest_integrity
from agentic_trading.time_machine.monte_carlo import run_seeded_monte_carlo


class SmaCrossStrategy(Strategy):
    """Deterministic Moving Average Crossover Strategy for Time Machine verification."""

    def __init__(
        self,
        fast: int = 5,
        slow: int = 15,
        strategy_id: str = "sma_cross_v1",
    ) -> None:
        self.strategy_id = strategy_id
        self.warmup_bars = slow + 1
        self.fast = fast
        self.slow = slow

    def evaluate(self, context: BarContext) -> Signal | None:
        closes = [b.close for b in context.bars]
        if len(closes) < self.warmup_bars:
            return None
        fast_avg = sum(closes[-self.fast :]) / Decimal(self.fast)
        slow_avg = sum(closes[-self.slow :]) / Decimal(self.slow)
        last_bar = context.bars[-1]
        currency = context.instrument.currency
        if fast_avg > slow_avg:
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.LONG,
                confidence=Decimal("0.85"),
                stop_loss=Money(last_bar.close * Decimal("0.97"), currency),
                take_profit=Money(last_bar.close * Decimal("1.05"), currency),
                rationale="Fast SMA above slow SMA",
            )
        if fast_avg < slow_avg:
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.EXIT,
                confidence=Decimal("0.85"),
                rationale="Fast SMA below slow SMA",
            )
        return None


class TradingLabState:
    """Encapsulates multi-currency paper brokers, 7-agent desk orchestrator, and Time Machine."""

    def __init__(
        self,
        stop_file: Path | str = Path("STOP"),
        db_path: Path | str | None = None,
        lessons_path: Path | str | None = None,
        initial_inr_deposit: Decimal = Decimal("1000000"),
        initial_usd_deposit: Decimal = Decimal("25000"),
    ) -> None:
        self._lock = threading.RLock()
        self.stop_file = Path(stop_file)
        self.kill_switch = KillSwitch(stop_file=self.stop_file)
        self.db_path = Path(db_path) if db_path else None
        self.decision_log = DecisionLog(db_path=self.db_path)
        self.lessons_store = (
            HumanLessonsStore.from_file(lessons_path)
            if lessons_path
            else HumanLessonsStore()
        )

        deposit_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.inr_portfolio = PortfolioEngine(
            Currency.INR,
            fee_model=IndiaEquityFeeModel(),
            slippage_model=BasisPointsSlippageModel(),
        )
        self.inr_portfolio.deposit(
            Money(initial_inr_deposit, Currency.INR),
            deposit_time,
            "INITIAL_INR_DEPOSIT",
        )
        self.inr_broker = PaperBroker(self.inr_portfolio, kill_switch=self.kill_switch)

        self.usd_portfolio = PortfolioEngine(
            Currency.USD,
            fee_model=USEquityFeeModel(),
            slippage_model=BasisPointsSlippageModel(),
        )
        self.usd_portfolio.deposit(
            Money(initial_usd_deposit, Currency.USD),
            deposit_time,
            "INITIAL_USD_DEPOSIT",
        )
        self.usd_broker = PaperBroker(self.usd_portfolio, kill_switch=self.kill_switch)

        self.llm_client = DeterministicStubLLMClient()
        self.inr_risk_policy = PortfolioRiskPolicy(
            max_risk_per_trade_pct=Decimal("0.02"),
            max_position_pct=Decimal("0.20"),
        )
        self.usd_risk_policy = PortfolioRiskPolicy(
            max_risk_per_trade_pct=Decimal("0.02"),
            max_position_pct=Decimal("0.20"),
        )
        self.mandate = TradingMandate(
            horizon_days=5,
            min_reward_to_risk=Decimal("1.5"),
        )
        self.backtest_engine = BacktestEngine()

    def get_broker(self, currency_str: str) -> PaperBroker:
        curr = currency_str.strip().upper()
        if curr == "INR":
            return self.inr_broker
        if curr == "USD":
            return self.usd_broker
        raise ValueError(f"Unsupported currency: {currency_str}")

    def set_kill_switch(self, active: bool, reason: str = "MANUAL_UI_STOP") -> bool:
        with self._lock:
            if active:
                self.stop_file.write_text(reason, encoding="utf-8")
            else:
                if self.stop_file.exists():
                    self.stop_file.unlink()
            return self.kill_switch.is_active()

    def get_portfolio_summary(
        self,
        currency_str: str,
        as_of: datetime | None = None,
    ) -> PortfolioSummaryResponse:
        with self._lock:
            broker = self.get_broker(currency_str)
            currency = broker.portfolio.currency
            moment = as_of or datetime.now(timezone.utc)
            report = broker.reconcile(moment)
            marks: dict[tuple[Exchange, str], Money] = {}
            for key, pos in broker.portfolio._positions.items():
                if pos.quantity != 0:
                    marks[key] = pos.average_cost
            snapshot = broker.portfolio.snapshot(currency, marks, moment)

            positions_list: list[PositionSummary] = []
            for (ex, sym), pos in snapshot.positions.items():
                if pos.quantity != 0:
                    positions_list.append(
                        PositionSummary(
                            symbol=sym,
                            exchange=ex.value,
                            quantity=pos.quantity,
                            average_cost=pos.average_cost.amount,
                            market_price=pos.average_cost.amount,
                            market_value=pos.market_value.amount,
                            unrealized_pnl=pos.unrealized_pnl.amount,
                        )
                    )

            recent_events = [
                {
                    "sequence_id": e.sequence_id,
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type.value,
                    "cash_delta": str(e.cash_delta.amount),
                    "reference_id": e.reference_id,
                }
                for e in broker.portfolio.ledger.entries[-20:]
            ]

            expected_cash = (
                broker.portfolio.ledger.get_total_deposits(currency).amount
                - broker.portfolio.ledger.get_total_withdrawals(currency).amount
                + snapshot.realized_pnl.amount
                + broker.portfolio.ledger.get_total_dividends(currency).amount
                - broker.portfolio.ledger.get_total_fees(currency).amount
            )
            open_basis = sum(
                (p.cost_basis.amount for p in snapshot.positions.values()),
                Decimal("0"),
            )
            residual = expected_cash - (snapshot.cash.amount + open_basis)

            return PortfolioSummaryResponse(
                currency="INR" if currency == Currency.INR else "USD",
                cash=snapshot.cash.amount,
                holdings_value=snapshot.holdings_value.amount,
                total_equity=snapshot.total_equity.amount,
                realized_pnl=snapshot.realized_pnl.amount,
                unrealized_pnl=snapshot.unrealized_pnl.amount,
                fees_paid=broker.portfolio.ledger.get_total_fees(currency).amount,
                conservation_residual=residual,
                is_reconciled=report.is_reconciled and residual == Decimal("0"),
                positions=positions_list,
                recent_events=recent_events,
                discrepancies=list(report.discrepancies),
            )

    def submit_order(self, request: SubmitOrderRequest) -> OrderResponse:
        with self._lock:
            if self.kill_switch.is_active():
                raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

            exchange = Exchange(request.exchange)
            symbol = request.symbol.strip().upper()
            side = request.side.strip().upper()

            if exchange in {Exchange.NSE, Exchange.BSE}:
                currency = Currency.INR
                broker = self.inr_broker
            elif exchange in {Exchange.NYSE, Exchange.NASDAQ}:
                currency = Currency.USD
                broker = self.usd_broker
            else:
                raise ValueError(f"Unsupported exchange: {exchange}")

            tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
            instrument = Instrument(
                exchange=exchange,
                symbol=symbol,
                currency=currency,
                tick_size=tick,
                lot_size=1,
            )

            now = datetime.now(timezone.utc)
            candle = Candle(
                symbol=symbol,
                exchange=exchange,
                interval=CandleInterval.M1,
                open=request.quote_price,
                high=max(request.quote_price, request.limit_price or request.quote_price),
                low=min(request.quote_price, request.limit_price or request.quote_price),
                close=request.quote_price,
                volume=100000,
                timestamp=now - timedelta(minutes=1),
                source="api_manual",
                retrieval_timestamp=now,
            )

            limit_money = (
                Money(request.limit_price, currency)
                if request.limit_price is not None
                else None
            )
            stop_money = (
                Money(request.stop_loss, currency)
                if request.stop_loss is not None
                else None
            )
            target_money = (
                Money(request.take_profit, currency)
                if request.take_profit is not None
                else None
            )
            order_type = "LIMIT" if request.limit_price is not None else "MARKET"

            proposal = TradeProposal(
                proposal_id=f"prop-{request.run_id}-{symbol}-{now.strftime('%H%M%S%f')}",
                strategy_id="api_manual",
                instrument=instrument,
                timestamp=now,
                side=side,
                quantity=request.quantity,
                order_type=order_type,
                limit_price=limit_money,
                stop_loss=stop_money,
                take_profit=target_money,
            )

            order = broker.submit_order(
                run_id=request.run_id,
                proposal=proposal,
                current_candle=candle,
                client_order_id=request.client_order_id,
                tick_size=instrument.tick_size,
            )

            return OrderResponse(
                client_order_id=order.client_order_id,
                run_id=order.run_id,
                exchange=order.exchange.value,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                filled_quantity=order.filled_quantity,
                status=order.status.value,
                limit_price=order.limit_price.amount if order.limit_price else None,
                stop_loss=order.stop_loss.amount if order.stop_loss else None,
                take_profit=order.take_profit.amount if order.take_profit else None,
                average_fill_price=order.average_fill_price.amount
                if order.average_fill_price
                else None,
                fees=order.fees.amount,
                slippage=order.slippage.amount,
                reject_reason=order.reject_reason,
                submitted_at=order.submitted_at,
                filled_at=order.filled_at,
            )

    def cancel_order(self, currency_str: str, client_order_id: str) -> OrderResponse:
        with self._lock:
            broker = self.get_broker(currency_str)
            order = broker.cancel_order(client_order_id)
            return OrderResponse(
                client_order_id=order.client_order_id,
                run_id=order.run_id,
                exchange=order.exchange.value,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                filled_quantity=order.filled_quantity,
                status=order.status.value,
                limit_price=order.limit_price.amount if order.limit_price else None,
                stop_loss=order.stop_loss.amount if order.stop_loss else None,
                take_profit=order.take_profit.amount if order.take_profit else None,
                average_fill_price=order.average_fill_price.amount
                if order.average_fill_price
                else None,
                fees=order.fees.amount,
                slippage=order.slippage.amount,
                reject_reason=order.reject_reason,
                submitted_at=order.submitted_at,
                filled_at=order.filled_at,
            )

    def run_backtest(self, request: BacktestRequest) -> BacktestResponse:
        with self._lock:
            exchange = Exchange(request.exchange)
            symbol = request.symbol.strip().upper()
            currency = Currency(request.currency)

            if exchange in {Exchange.NSE, Exchange.BSE} and currency != Currency.INR:
                raise CurrencyMismatchError("NSE/BSE exchange requires INR currency")
            if exchange in {Exchange.NYSE, Exchange.NASDAQ} and currency != Currency.USD:
                raise CurrencyMismatchError("NYSE/NASDAQ exchange requires USD currency")

            tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
            instrument = Instrument(
                exchange=exchange,
                symbol=symbol,
                currency=currency,
                tick_size=tick,
                lot_size=1,
            )

            fee_model = (
                IndiaEquityFeeModel() if currency == Currency.INR else USEquityFeeModel()
            )
            slippage_model = BasisPointsSlippageModel()
            risk_policy = (
                self.inr_risk_policy if currency == Currency.INR else self.usd_risk_policy
            )

            config = BacktestConfig(
                initial_capital=Money(request.initial_capital, currency),
                risk_policy=risk_policy,
                fee_model=fee_model,
                slippage_model=slippage_model,
                position_size_pct=Decimal("0.10"),
                default_stop_loss_pct=Decimal("0.03"),
                default_take_profit_pct=Decimal("0.06"),
                random_seed=request.random_seed,
            )

            base_time = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
            candles: list[Candle] = []
            base_price = Decimal("100.00")
            for i in range(request.bars_count):
                wave = Decimal(str((i % 20) * 2 - (i % 7)))
                close_price = base_price + wave
                high_price = close_price + Decimal("3.00")
                low_price = max(Decimal("1.00"), close_price - Decimal("2.00"))
                open_price = max(Decimal("1.00"), close_price - Decimal("1.00"))
                bar_open_time = base_time + timedelta(days=i)
                bar_retrieval_time = bar_open_time + timedelta(hours=6, minutes=15)
                candles.append(
                    Candle(
                        symbol=symbol,
                        exchange=exchange,
                        interval=CandleInterval.D1,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=100000,
                        timestamp=bar_open_time,
                        source="synthetic_backtest",
                        retrieval_timestamp=bar_retrieval_time,
                    )
                )

            strategy = SmaCrossStrategy(fast=5, slow=15)
            result = self.backtest_engine.run(instrument, candles, strategy, config)

            mc_summary = run_seeded_monte_carlo(
                result.trades,
                initial_capital=config.initial_capital,
                iterations=request.monte_carlo_runs,
                seed=request.random_seed,
            )

            manifest_verified = verify_manifest_integrity(result.manifest)
            residual = ledger_conservation_residual(result.ledger, result.final_snapshot)

            metrics_dict: dict[str, Any] = {
                "total_trades": result.metrics.total_trades,
                "winning_trades": result.metrics.winning_trades,
                "losing_trades": result.metrics.losing_trades,
                "win_rate_pct": str(result.metrics.win_rate_pct),
                "profit_factor": str(result.metrics.profit_factor),
                "total_return_pct": str(result.metrics.total_return_pct),
                "max_drawdown_pct": str(result.metrics.max_drawdown_pct),
                "sharpe_ratio": str(result.metrics.sharpe_ratio),
                "expectancy_r": str(result.metrics.expectancy_r),
            }

            monte_carlo_dict: dict[str, Any] = {
                "iterations": mc_summary.iterations,
                "trade_count": mc_summary.trade_count,
                "return_pct_p50": str(mc_summary.return_pct_p50),
                "return_pct_p05": str(mc_summary.return_pct_p05),
                "return_pct_p95": str(mc_summary.return_pct_p95),
                "max_drawdown_pct_p50": str(mc_summary.max_drawdown_pct_p50),
                "max_drawdown_pct_p95": str(mc_summary.max_drawdown_pct_p95),
                "probability_of_loss_pct": str(mc_summary.probability_of_loss_pct),
                "probability_of_ruin_pct": str(mc_summary.probability_of_ruin_pct),
            }

            return BacktestResponse(
                manifest_id=result.manifest.manifest_id,
                manifest_sha256=result.manifest.manifest_sha256,
                manifest_verified=manifest_verified,
                metrics=metrics_dict,
                monte_carlo=monte_carlo_dict,
                trade_count=len(result.trades),
                conservation_residual=residual,
            )

    def run_desk(self, request: DeskRunRequest) -> DeskRunResponse:
        with self._lock:
            if self.kill_switch.is_active():
                raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

            exchange = Exchange(request.exchange)
            currency = Currency(request.currency)

            if exchange in {Exchange.NSE, Exchange.BSE} and currency != Currency.INR:
                raise CurrencyMismatchError("NSE/BSE exchange requires INR currency")
            if exchange in {Exchange.NYSE, Exchange.NASDAQ} and currency != Currency.USD:
                raise CurrencyMismatchError("NYSE/NASDAQ exchange requires USD currency")

            broker = self.inr_broker if currency == Currency.INR else self.usd_broker
            risk_policy = (
                self.inr_risk_policy if currency == Currency.INR else self.usd_risk_policy
            )

            orchestrator = TradingDeskOrchestrator(
                paper_broker=broker,
                risk_policy=risk_policy,
                mandate=self.mandate,
                market_analyst=MarketAnalyst(self.llm_client),
                data_analyst=DataAnalyst(self.llm_client),
                news_analyst=NewsAnalyst(self.llm_client),
                opportunity_scout=OpportunityScout(),
                strategist=Strategist(self.llm_client),
                decision_log=self.decision_log,
                lessons_store=self.lessons_store,
            )

            as_of = datetime.now(timezone.utc)
            run_id = (
                request.run_id
                if request.run_id and request.run_id.strip()
                else f"desk-{as_of.strftime('%Y%m%d%H%M%S')}"
            )

            tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
            watchlist_targets: list[WatchlistTarget] = []

            for sym in request.watchlist:
                instrument = Instrument(
                    exchange=exchange,
                    symbol=sym,
                    currency=currency,
                    tick_size=tick,
                    lot_size=1,
                )
                bars: list[Candle] = []
                for i in range(25):
                    bar_time = as_of - timedelta(days=24 - i, hours=6, minutes=15)
                    bar_retrieval = bar_time + timedelta(hours=6, minutes=15)
                    bars.append(
                        Candle(
                            symbol=sym,
                            exchange=exchange,
                            interval=CandleInterval.D1,
                            open=Decimal("150.00"),
                            high=Decimal("155.00"),
                            low=Decimal("148.00"),
                            close=Decimal("152.00"),
                            volume=50000,
                            timestamp=bar_time,
                            source="synthetic_desk",
                            retrieval_timestamp=bar_retrieval,
                        )
                    )
                context = BarContext(
                    instrument=instrument,
                    decision_time=bars[-1].close_time,
                    bars=tuple(bars),
                )
                fundamental = FundamentalSnapshot(
                    symbol=sym,
                    as_of_filing=as_of.date(),
                    revenue_growth_yoy=Decimal("0.18"),
                    operating_margin=Decimal("0.22"),
                    fcf_margin=Decimal("0.15"),
                    debt_to_equity=Decimal("0.4"),
                    interest_coverage=Decimal("5.0"),
                    pe_vs_peer_median=Decimal("1.0"),
                    dilution_yoy=Decimal("0.0"),
                    peer_set=(),
                )
                news = (
                    NewsArticle(
                        headline=f"Growth accelerates for {sym}",
                        source="Wire",
                        source_tier=1,
                        published_at=as_of,
                        summary="Solid operational performance in recent quarter.",
                    ),
                )
                watchlist_targets.append(
                    WatchlistTarget(
                        instrument=instrument,
                        current_candle=bars[-1],
                        context=context,
                        fundamental_snapshot=fundamental,
                        news_articles=news,
                        scheduled_events=(),
                    )
                )

            result = orchestrator.run_cycle(
                run_id=run_id,
                as_of=as_of,
                watchlist=watchlist_targets,
            )

            approved_orders = [
                {
                    "client_order_id": o.client_order_id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "status": o.status.value,
                    "average_fill_price": str(o.average_fill_price.amount)
                    if o.average_fill_price
                    else None,
                }
                for o in result.orders
            ]

            rejected_proposals = [
                {
                    "proposal_id": d.proposal_id,
                    "approved": d.approved,
                    "reasons": list(d.reasons),
                }
                for d in result.decisions
                if not d.approved
            ]

            return DeskRunResponse(
                run_id=run_id,
                currency=request.currency,
                shortlist=list(result.shortlist),
                dropped=dict(result.dropped_candidates),
                approved_orders=approved_orders,
                rejected_proposals=rejected_proposals,
                report_markdown=result.report,
                reconciled=result.reconciliation.is_reconciled,
            )

    def get_decisions(self, run_id: str | None = None) -> list[DecisionRecordItem]:
        with self._lock:
            records = self.decision_log.get_records(run_id=run_id)
            items: list[DecisionRecordItem] = []
            for r in records:
                items.append(
                    DecisionRecordItem(
                        run_id=r.run_id,
                        timestamp=r.timestamp,
                        ticker=r.ticker,
                        inputs_hash=r.inputs_hash,
                        shortlist_rank=r.shortlist_rank,
                        analyst_envelopes=dict(r.analyst_envelopes),
                        strategist_proposal=dict(r.strategist_proposal)
                        if r.strategist_proposal
                        else None,
                        risk_decision=dict(r.risk_decision) if r.risk_decision else None,
                        paper_order=dict(r.paper_order) if r.paper_order else None,
                    )
                )
            return items

    def close(self) -> None:
        pass
