"""Thread-safe isolated state container for the Agentic Trading Lab FastAPI application."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from agentic_trading.agents.data_analyst import DataAnalyst
from agentic_trading.agents.llm_client import (
    DeterministicStubLLMClient,
    FailoverLLMClient,
    LocalOllamaJSONClient,
)
from agentic_trading.agents.market_analyst import MarketAnalyst
from agentic_trading.agents.memory import DecisionLog, HumanLessonsStore
from agentic_trading.agents.news_analyst import NewsAnalyst
from agentic_trading.agents.opportunity_scout import OpportunityScout
from agentic_trading.agents.orchestrator import (
    TradingDeskOrchestrator,
    WatchlistTarget,
)
from agentic_trading.agents.strategist import Strategist, TradingMandate
from agentic_trading.api.schemas import (
    AgentChatEntry,
    BacktestRequest,
    BacktestResponse,
    BasketBacktestRequest,
    BasketBacktestResponse,
    CandleBarItem,
    ClosedTradeRecord,
    ClosePositionRequest,
    ContextResponse,
    CycleDetailResponse,
    CycleSummaryItem,
    DecisionRecordItem,
    DeskRunRequest,
    DeskRunResponse,
    FeedCandlesResponse,
    FundamentalSnapshotItem,
    NewsArticleItem,
    OrderResponse,
    PerSymbolAttributionItem,
    PnlBreakdownItem,
    PnlSummaryResponse,
    PortfolioSummaryResponse,
    PositionItem,
    PositionsListResponse,
    PositionSummary,
    ScenarioResponse,
    ScheduledEventItem,
    SubmitOrderRequest,
    SweepTriggerEvent,
    TradePlanItem,
    WalkForwardSummary,
)
from agentic_trading.market_data.context_bridge import ReadOnlyContextBridge
from agentic_trading.market_data.feed_bridge import ReadOnlyMarketFeedBridge
from agentic_trading.market_data.instruments import (
    Currency,
    CurrencyMismatchError,
    Instrument,
    Money,
)
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange
from agentic_trading.paper_trading.broker import PaperBroker
from agentic_trading.paper_trading.kill_switch import KillSwitch, KillSwitchError
from agentic_trading.risk_engine.proposal_gate import (
    PortfolioRiskPolicy,
    evaluate_trade_proposal,
)
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
from agentic_trading.strategy.library import STRATEGY_REGISTRY
from agentic_trading.time_machine.basket import run_basket_backtest
from agentic_trading.time_machine.engine import (
    BacktestConfig,
    BacktestEngine,
    ledger_conservation_residual,
)
from agentic_trading.time_machine.manifest import verify_manifest_integrity
from agentic_trading.time_machine.monte_carlo import run_seeded_monte_carlo


class ProposalRiskRejectionError(ValueError):
    """Raised when a trade proposal fails risk validation."""
    pass


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
        fixture_dir: Path | str | None = None,
        initial_inr_deposit: Decimal = Decimal("1000000"),
        initial_usd_deposit: Decimal = Decimal("25000"),
    ) -> None:
        self._lock = threading.RLock()
        self._mark_prices: dict[tuple[Exchange, str], Money] = {}
        self.stop_file = Path(stop_file)
        self.kill_switch = KillSwitch(stop_file=self.stop_file)
        self.db_path = Path(db_path) if db_path else None
        self.initial_inr_deposit = initial_inr_deposit
        self.initial_usd_deposit = initial_usd_deposit
        self.decision_log = DecisionLog(db_path=self.db_path)
        self.lessons_store = (
            HumanLessonsStore.from_file(lessons_path, db_path=self.db_path)
            if lessons_path
            else HumanLessonsStore(db_path=self.db_path)
        )
        self.fixture_dir = Path(fixture_dir) if fixture_dir else Path.cwd() / "data" / "replay_fixtures"
        self.feed_bridge = ReadOnlyMarketFeedBridge(cache_dir=self.fixture_dir)
        self.context_bridge = ReadOnlyContextBridge(
            cache_dir=self.fixture_dir,
            hmac_key=self.feed_bridge.hmac_key,
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
        self._sim_step: int = 0
        self._scenario_bias: Literal["normal", "bull_rally", "sudden_crash", "sideways_chop"] = "normal"
        self._closed_trades: list[dict[str, Any]] = []
        self._position_brackets: dict[tuple[Exchange, str], dict[str, Money | None]] = {}

    def get_broker(self, currency_str: str) -> PaperBroker:
        curr = currency_str.strip().upper()
        if curr == "INR":
            return self.inr_broker
        if curr == "USD":
            return self.usd_broker
        raise ValueError(f"Unsupported currency: {currency_str}")

    def set_kill_switch(self, active: bool, reason: str = "MANUAL_UI_STOP") -> bool:
        if active:
            self.stop_file.write_text(reason, encoding="utf-8")
        else:
            if self.stop_file.exists():
                self.stop_file.unlink()
        return self.kill_switch.is_active()

    def _get_or_fetch_mark_price(
        self,
        exchange: Exchange,
        symbol: str,
        currency: Currency,
    ) -> Money:
        key = (exchange, symbol)
        if key in self._mark_prices:
            return self._mark_prices[key]
        fetch_res = self.feed_bridge.fetch_candles(
            exchange=exchange,
            symbol=symbol,
            interval=CandleInterval.D1,
            bars_count=1,
            mode="synthetic",
            sim_step=self._sim_step,
            scenario_bias=self._scenario_bias,
        )
        if fetch_res.candles:
            price = fetch_res.candles[-1].close
        else:
            price = Decimal("100.00")
        m = Money(price, currency)
        self._mark_prices[key] = m
        return m

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
            for (ex, sym), pos in broker.portfolio._positions.items():
                if pos.quantity != 0:
                    marks[(ex, sym)] = self._get_or_fetch_mark_price(ex, sym, currency)
            snapshot = broker.portfolio.snapshot(currency, marks, moment)

            positions_list: list[PositionSummary] = []
            for (ex, sym), pos in snapshot.positions.items():
                if pos.quantity != 0:
                    mark_amount = marks[(ex, sym)].amount
                    mkt_val = mark_amount * Decimal(str(pos.quantity))
                    unrealized = mkt_val - pos.cost_basis.amount
                    positions_list.append(
                        PositionSummary(
                            symbol=sym,
                            exchange=ex.value,
                            quantity=pos.quantity,
                            average_cost=pos.average_cost.amount,
                            market_price=mark_amount,
                            market_value=mkt_val,
                            unrealized_pnl=unrealized,
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
        if self.kill_switch.is_active():
            raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

        exchange = Exchange(request.exchange)
        symbol = request.symbol.strip().upper()
        side = request.side.strip().upper()

        if exchange in {Exchange.NSE, Exchange.BSE}:
            currency = Currency.INR
            broker = self.inr_broker
            risk_policy = self.inr_risk_policy
        elif exchange in {Exchange.NYSE, Exchange.NASDAQ}:
            currency = Currency.USD
            broker = self.usd_broker
            risk_policy = self.usd_risk_policy
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

        feed_res = self.feed_bridge.fetch_candles(
            exchange=exchange,
            symbol=symbol,
            interval=CandleInterval.D1,
            bars_count=1,
            mode="synthetic",
            sim_step=self._sim_step,
            scenario_bias=self._scenario_bias,
        )
        feed_price = feed_res.candles[-1].close

        if request.quote_price is not None:
            deviation = abs(request.quote_price - feed_price) / feed_price
            if deviation > Decimal("0.05"):
                raise ValueError("quote_price deviates from market feed")
            effective_price = request.quote_price
        else:
            effective_price = feed_price

        with self._lock:
            self._mark_prices[(exchange, symbol)] = Money(effective_price, currency)
            now = datetime.now(timezone.utc)
            if broker.portfolio.ledger.entries:
                last_ts = broker.portfolio.ledger.entries[-1].timestamp
                if now < last_ts:
                    now = last_ts

            candle = Candle(
                symbol=symbol,
                exchange=exchange,
                interval=CandleInterval.M1,
                open=effective_price,
                high=max(effective_price, request.limit_price or effective_price),
                low=min(effective_price, request.limit_price or effective_price),
                close=effective_price,
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

            mark_prices = dict(self._mark_prices)
            current_snapshot = broker.portfolio.snapshot(currency, mark_prices, now)
            daily_pnl = Money(
                current_snapshot.realized_pnl.amount + current_snapshot.unrealized_pnl.amount,
                currency,
            )
            peak_equity = Money(
                max(current_snapshot.total_equity.amount, Decimal("1.0")),
                currency,
            )
            decision = evaluate_trade_proposal(
                proposal=proposal,
                portfolio=current_snapshot,
                entry_price=Money(effective_price, currency),
                policy=risk_policy,
                daily_pnl=daily_pnl,
                peak_equity=peak_equity,
            )
            if not decision.approved:
                raise ProposalRiskRejectionError(
                    f"Order rejected by risk policy: {', '.join(decision.reasons)}"
                )
            if decision.max_allowed_quantity < proposal.quantity:
                raise ProposalRiskRejectionError(
                    f"Order rejected by risk policy: requested quantity {proposal.quantity} exceeds max allowed {decision.max_allowed_quantity}"
                )

            order = broker.submit_order(
                run_id=request.run_id,
                proposal=proposal,
                current_candle=candle,
                client_order_id=request.client_order_id,
                tick_size=instrument.tick_size,
            )

            if order.status.value == "FILLED" and order.side == "BUY":
                self._position_brackets[(order.exchange, order.symbol)] = {
                    "stop_loss": order.stop_loss,
                    "take_profit": order.take_profit,
                }
            elif order.status.value == "FILLED" and order.side == "SELL":
                sold_price = order.average_fill_price.amount if order.average_fill_price else effective_price
                prev_pos = current_snapshot.positions.get((order.exchange, order.symbol))
                avg_cost = prev_pos.average_cost.amount if prev_pos else sold_price
                gross_pnl = (sold_price - avg_cost) * Decimal(str(order.filled_quantity))
                net_pnl = gross_pnl - order.fees.amount
                pnl_pct = (
                    ((sold_price - avg_cost) / avg_cost * Decimal("100")).quantize(Decimal("0.01"))
                    if avg_cost > Decimal("0")
                    else Decimal("0.00")
                )
                self._closed_trades.append({
                    "symbol": order.symbol,
                    "exchange": order.exchange.value,
                    "currency": currency.value,
                    "quantity": order.filled_quantity,
                    "bought_at": avg_cost,
                    "sold_at": sold_price,
                    "net_pnl": net_pnl,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "MANUAL_SELL",
                    "closed_at": now.isoformat(),
                })
                if prev_pos and prev_pos.quantity - order.filled_quantity <= 0:
                    self._position_brackets.pop((order.exchange, order.symbol), None)

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

        fetch_res = self.feed_bridge.fetch_candles(
            exchange=exchange,
            symbol=symbol,
            interval=CandleInterval.D1,
            bars_count=request.bars_count,
            mode=request.feed_source,
        )
        candles = list(fetch_res.candles)

        strat_key = request.strategy_name.strip().lower()
        if strat_key == "sma_cross":
            strategy: Strategy = SmaCrossStrategy(fast=5, slow=15)
        elif strat_key in STRATEGY_REGISTRY:
            strategy = STRATEGY_REGISTRY[strat_key]()
        else:
            raise ValueError(f"Unknown strategy_name '{request.strategy_name}'")

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

        equity_curve = [
            {
                "timestamp": pt.timestamp.isoformat(),
                "equity": str(pt.total_equity.amount),
                "drawdown_pct": str(pt.drawdown_pct),
            }
            for pt in result.equity_curve
        ]

        total_pnl = sum((t.net_pnl.amount for t in result.trades), Decimal("0"))
        exp_per_trade = (
            (total_pnl / Decimal(len(result.trades))).quantize(Decimal("0.01"))
            if result.trades
            else Decimal("0.00")
        )
        bars_eval = len(fetch_res.candles)

        return BacktestResponse(
            manifest_id=result.manifest.manifest_id,
            manifest_sha256=result.manifest.manifest_sha256,
            manifest_verified=manifest_verified,
            metrics=metrics_dict,
            monte_carlo=monte_carlo_dict,
            trade_count=len(result.trades),
            conservation_residual=residual,
            feed_source=fetch_res.source,
            strategy_name=request.strategy_name,
            equity_curve=equity_curve,
            expectancy=exp_per_trade,
            bars_evaluated=bars_eval,
            total_return_pct=result.metrics.total_return_pct,
            sharpe_ratio=result.metrics.sharpe_ratio,
            max_drawdown_pct=result.metrics.max_drawdown_pct,
            win_rate=result.metrics.win_rate_pct,
            profit_factor=result.metrics.profit_factor,
            total_trades=result.metrics.total_trades,
            mc_var_95_pct=Decimal(str(monte_carlo_dict.get("max_drawdown_pct_p95", "0"))),
        )

    def run_basket_backtest(self, request: BasketBacktestRequest) -> BasketBacktestResponse:
        exchange = Exchange(request.exchange)
        currency = Currency(request.currency)

        if exchange in {Exchange.NSE, Exchange.BSE} and currency != Currency.INR:
            raise CurrencyMismatchError("NSE/BSE exchange requires INR currency")
        if exchange in {Exchange.NYSE, Exchange.NASDAQ} and currency != Currency.USD:
            raise CurrencyMismatchError("NYSE/NASDAQ exchange requires USD currency")

        tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
        instruments: list[Instrument] = []
        candles_by_symbol: dict[str, list[Candle]] = {}

        for sym in request.symbols:
            clean_sym = sym.strip().upper()
            inst = Instrument(
                exchange=exchange,
                symbol=clean_sym,
                currency=currency,
                tick_size=tick,
                lot_size=1,
            )
            instruments.append(inst)
            fetch_res = self.feed_bridge.fetch_candles(
                exchange=exchange,
                symbol=clean_sym,
                interval=CandleInterval.D1,
                bars_count=request.bars_count,
                mode=request.feed_source,
            )
            candles_by_symbol[clean_sym] = list(fetch_res.candles)

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

        res = run_basket_backtest(
            instruments=instruments,
            candles_by_symbol=candles_by_symbol,
            strategy_name=request.strategy_name,
            config=config,
            run_walk_forward=request.run_walk_forward,
        )

        metrics_dict: dict[str, Any] = {
            "total_trades": res.portfolio_metrics.total_trades,
            "winning_trades": res.portfolio_metrics.winning_trades,
            "losing_trades": res.portfolio_metrics.losing_trades,
            "win_rate_pct": str(res.portfolio_metrics.win_rate_pct),
            "profit_factor": str(res.portfolio_metrics.profit_factor),
            "total_return_pct": str(res.portfolio_metrics.total_return_pct),
            "max_drawdown_pct": str(res.portfolio_metrics.max_drawdown_pct),
            "sharpe_ratio": str(res.portfolio_metrics.sharpe_ratio),
            "expectancy_r": str(res.portfolio_metrics.expectancy_r),
        }

        attribution_dict: dict[str, PerSymbolAttributionItem] = {}
        for sym, attr in res.per_symbol_attribution.items():
            attribution_dict[sym] = PerSymbolAttributionItem(
                symbol=attr.symbol,
                exchange=attr.exchange,
                trades=attr.trades,
                winning_trades=attr.winning_trades,
                losing_trades=attr.losing_trades,
                win_rate_pct=str(attr.win_rate_pct),
                realized_pnl=str(attr.realized_pnl),
                total_return_pct=str(attr.total_return_pct),
            )

        wf_summary: WalkForwardSummary | None = None
        if res.walk_forward is not None:
            wf_summary = WalkForwardSummary(
                strategy_name=res.walk_forward.strategy_name,
                best_params=res.walk_forward.best_params,
                in_sample_metrics=res.walk_forward.in_sample_metrics,
                out_of_sample_metrics=res.walk_forward.out_of_sample_metrics,
                in_sample_range=res.walk_forward.in_sample_range,
                out_of_sample_range=res.walk_forward.out_of_sample_range,
                split_ratio=res.walk_forward.split_ratio,
            )

        equity_curve = [
            {
                "timestamp": pt.timestamp.isoformat(),
                "equity": str(pt.total_equity.amount),
                "drawdown_pct": str(pt.drawdown_pct),
            }
            for pt in res.equity_curve
        ]

        return BasketBacktestResponse(
            manifest_id=res.manifest_id,
            manifest_sha256=res.manifest_sha256,
            manifest_verified=res.manifest_verified,
            conservation_residual=res.conservation_residual,
            strategy_name=request.strategy_name,
            feed_source=request.feed_source,
            portfolio_metrics=metrics_dict,
            per_symbol_attribution=attribution_dict,
            walk_forward_summary=wf_summary,
            equity_curve=equity_curve,
            trade_count=len(res.trades),
        )

    def run_desk(self, request: DeskRunRequest) -> DeskRunResponse:
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

        if request.llm_backend == "ollama":
            active_llm = FailoverLLMClient(
                LocalOllamaJSONClient(default_model=request.ollama_model),
                fallback=self.llm_client,
            )
        else:
            active_llm = self.llm_client

        orchestrator = TradingDeskOrchestrator(
            paper_broker=broker,
            risk_policy=risk_policy,
            mandate=self.mandate,
            market_analyst=MarketAnalyst(active_llm),
            data_analyst=DataAnalyst(active_llm),
            news_analyst=NewsAnalyst(active_llm),
            opportunity_scout=OpportunityScout(),
            strategist=Strategist(active_llm),
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
            fetch_res = self.feed_bridge.fetch_candles(
                exchange=exchange,
                symbol=sym,
                interval=CandleInterval.D1,
                bars_count=25,
                mode=request.feed_source,
                as_of=as_of,
                sim_step=self._sim_step,
                scenario_bias=self._scenario_bias,
            )
            bars = list(fetch_res.candles)
            context = BarContext(
                instrument=instrument,
                decision_time=bars[-1].close_time,
                bars=tuple(bars),
            )
            with self._lock:
                self._mark_prices[(exchange, sym)] = Money(bars[-1].close, currency)

            ctx_res = self.context_bridge.fetch_context(
                exchange=exchange,
                symbol=sym,
                as_of=as_of,
                mode=request.context_source,
            )
            watchlist_targets.append(
                WatchlistTarget(
                    instrument=instrument,
                    current_candle=bars[-1],
                    context=context,
                    fundamental_snapshot=ctx_res.snapshot,
                    news_articles=ctx_res.articles,
                    scheduled_events=ctx_res.scheduled_events,
                )
            )

        result = orchestrator.run_cycle(
            run_id=run_id,
            as_of=as_of,
            watchlist=watchlist_targets,
            auto_execute=request.auto_buy,
        )

        with self._lock:
            if request.feed_source == "synthetic":
                self._sim_step += 1
            for o in result.orders:
                if o.status.value == "FILLED" and o.side == "BUY":
                    self._position_brackets[(o.exchange, o.symbol)] = {
                        "stop_loss": o.stop_loss,
                        "take_profit": o.take_profit,
                    }

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

        chat_trace = [
            AgentChatEntry(
                step=entry["step"],
                stage=entry["stage"],
                agent=entry["agent"],
                symbol=entry.get("symbol"),
                model=entry["model"],
                input_context=entry.get("input_context", {}),
                output_message=entry.get("output_message", {}),
                status=entry["status"],
            )
            for entry in result.chat_trace
        ]

        trade_plans = [TradePlanItem(**tp) for tp in result.trade_plans]
        candle_series = {
            sym: [CandleBarItem(**b) for b in bars]
            for sym, bars in result.candle_series.items()
        }

        cycle_record = {
            "run_id": run_id,
            "timestamp": as_of.isoformat(),
            "currency": request.currency,
            "watchlist": request.watchlist,
            "feed_source": request.feed_source,
            "context_source": request.context_source,
            "llm_backend": request.llm_backend,
            "ollama_model": request.ollama_model,
            "auto_buy": request.auto_buy,
            "shortlist": list(result.shortlist),
            "dropped": dict(result.dropped_candidates),
            "approved_orders": approved_orders,
            "rejected_proposals": rejected_proposals,
            "chat_trace": [entry.model_dump() for entry in chat_trace],
            "trade_plans": [p.model_dump(mode="json") for p in trade_plans],
            "candle_series": {
                sym: [b.model_dump(mode="json") for b in bars]
                for sym, bars in candle_series.items()
            },
            "report_markdown": result.report,
            "reconciled": result.reconciliation.is_reconciled,
        }
        with self._lock:
            self.decision_log.save_cycle_run(cycle_record)

        return DeskRunResponse(
            run_id=run_id,
            currency=request.currency,
            shortlist=list(result.shortlist),
            dropped=dict(result.dropped_candidates),
            approved_orders=approved_orders,
            rejected_proposals=rejected_proposals,
            report_markdown=result.report,
            reconciled=result.reconciliation.is_reconciled,
            llm_backend=request.llm_backend,
            feed_source=request.feed_source,
            context_source=request.context_source,
            timestamp=as_of,
            watchlist=request.watchlist,
            ollama_model=request.ollama_model,
            chat_trace=chat_trace,
            auto_buy=request.auto_buy,
            trade_plans=trade_plans,
            candle_series=candle_series,
        )

    def list_cycles(self, limit: int = 20) -> list[CycleSummaryItem]:
        with self._lock:
            runs = self.decision_log.list_cycle_runs(limit=limit)
            items: list[CycleSummaryItem] = []
            for r in runs:
                items.append(
                    CycleSummaryItem(
                        run_id=r["run_id"],
                        timestamp=datetime.fromisoformat(r["timestamp"]),
                        currency=r["currency"],
                        watchlist=list(r["watchlist"]),
                        feed_source=r["feed_source"],
                        context_source=r.get("context_source", "synthetic"),
                        llm_backend=r["llm_backend"],
                        ollama_model=r["ollama_model"],
                        approved_count=r["approved_count"],
                        rejected_count=r["rejected_count"],
                        reconciled=r["reconciled"],
                        auto_buy=r.get("auto_buy", True),
                    )
                )
            return items

    def get_cycle_detail(self, run_id: str) -> CycleDetailResponse | None:
        with self._lock:
            data = self.decision_log.get_cycle_run(run_id)
            if not data:
                return None
            chat_entries = [
                AgentChatEntry(
                    step=c["step"],
                    stage=c["stage"],
                    agent=c["agent"],
                    symbol=c.get("symbol"),
                    model=c["model"],
                    input_context=c.get("input_context", {}),
                    output_message=c.get("output_message", {}),
                    status=c["status"],
                )
                for c in data.get("chat_trace", [])
            ]
            trade_plans = [
                TradePlanItem(**tp) for tp in data.get("trade_plans", [])
            ]
            candle_series = {
                sym: [CandleBarItem(**b) for b in bars]
                for sym, bars in data.get("candle_series", {}).items()
            }
            return CycleDetailResponse(
                run_id=data["run_id"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                currency=data["currency"],
                watchlist=list(data["watchlist"]),
                feed_source=data["feed_source"],
                context_source=data.get("context_source", "synthetic"),
                llm_backend=data["llm_backend"],
                ollama_model=data["ollama_model"],
                shortlist=list(data["shortlist"]),
                dropped=dict(data["dropped"]),
                approved_orders=list(data["approved_orders"]),
                rejected_proposals=list(data["rejected_proposals"]),
                chat_trace=chat_entries,
                report_markdown=data["report_markdown"],
                reconciled=data["reconciled"],
                auto_buy=data.get("auto_buy", True),
                trade_plans=trade_plans,
                candle_series=candle_series,
            )

    def get_feed_candles(
        self,
        exchange_str: str,
        symbol_str: str,
        source: str = "synthetic",
        bars: int = 30,
    ) -> FeedCandlesResponse:
        with self._lock:
            ex = Exchange(exchange_str.strip().upper())
            sym = symbol_str.strip().upper()
            curr = "INR" if ex in {Exchange.NSE, Exchange.BSE} else "USD"
            res = self.feed_bridge.fetch_candles(
                exchange=ex,
                symbol=sym,
                interval=CandleInterval.D1,
                bars_count=bars,
                mode=source,
            )
            latest = res.candles[-1]
            candles = [
                CandleBarItem(
                    timestamp=b.timestamp.isoformat(),
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
                for b in res.candles
            ]
            return FeedCandlesResponse(
                paper_only=True,
                exchange=ex.value,
                symbol=sym,
                currency=curr,
                interval=CandleInterval.D1.value,
                source=res.source,
                candle_count=len(res.candles),
                latest_close=latest.close,
                latest_timestamp=latest.timestamp,
                warnings=list(res.warnings),
                candles=candles,
            )

    def get_context(
        self,
        exchange_str: str,
        symbol_str: str,
        source: str = "synthetic",
    ) -> ContextResponse:
        ex = Exchange(exchange_str.strip().upper())
        sym = symbol_str.strip().upper()
        curr = "INR" if ex in {Exchange.NSE, Exchange.BSE} else "USD"
        res = self.context_bridge.fetch_context(
            exchange=ex,
            symbol=sym,
            mode=source,
        )
        snap_item = FundamentalSnapshotItem(
            symbol=res.snapshot.symbol,
            as_of_filing=res.snapshot.as_of_filing.isoformat(),
            revenue_growth_yoy=res.snapshot.revenue_growth_yoy,
            operating_margin=res.snapshot.operating_margin,
            fcf_margin=res.snapshot.fcf_margin,
            debt_to_equity=res.snapshot.debt_to_equity,
            interest_coverage=res.snapshot.interest_coverage,
            pe_vs_peer_median=res.snapshot.pe_vs_peer_median,
            dilution_yoy=res.snapshot.dilution_yoy,
            peer_set=list(res.snapshot.peer_set),
        )
        art_items = [
            NewsArticleItem(
                headline=a.headline,
                source=a.source,
                source_tier=a.source_tier,
                published_at=a.published_at.isoformat(),
                summary=a.summary,
            )
            for a in res.articles
        ]
        evt_items = [
            ScheduledEventItem(
                event_name=e.event_name,
                event_date=e.event_date.isoformat(),
                event_type=e.event_type,
            )
            for e in res.scheduled_events
        ]
        return ContextResponse(
            paper_only=True,
            symbol=sym,
            exchange=ex.value,
            currency=curr,
            source=res.source,
            is_blackout=res.is_blackout,
            snapshot=snap_item,
            articles=art_items,
            scheduled_events=evt_items,
            warnings=list(res.warnings),
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

    def get_positions(
        self,
        currency: str | None = None,
        currency_str: str | None = None,
    ) -> PositionsListResponse:
        effective_currency = currency or currency_str
        with self._lock:
            brokers = []
            if effective_currency is None:
                brokers = [self.inr_broker, self.usd_broker]
            else:
                brokers = [self.get_broker(effective_currency)]

            items: list[PositionItem] = []
            for b in brokers:
                curr = b.portfolio.currency
                for (ex, sym), pos in b.portfolio._positions.items():
                    if pos.quantity != 0:
                        mark_money = self._get_or_fetch_mark_price(ex, sym, curr)
                        mark_amount = mark_money.amount
                        mkt_val = mark_amount * Decimal(str(pos.quantity))
                        unrealized = mkt_val - pos.cost_basis.amount
                        pnl_pct = (
                            (unrealized / pos.cost_basis.amount * Decimal("100"))
                            if pos.cost_basis.amount > Decimal("0")
                            else Decimal("0")
                        )
                        brackets = self._position_brackets.get((ex, sym), {})
                        sl_obj = brackets.get("stop_loss")
                        tp_obj = brackets.get("take_profit")
                        tick = Decimal("0.05") if curr == Currency.INR else Decimal("0.01")
                        sl_val = sl_obj.amount if sl_obj else (pos.average_cost.amount * Decimal("0.96")).quantize(tick)
                        tp_val = tp_obj.amount if tp_obj else (pos.average_cost.amount * Decimal("1.08")).quantize(tick)
                        items.append(
                            PositionItem(
                                currency=curr.value,
                                exchange=ex.value,
                                symbol=sym,
                                quantity=pos.quantity,
                                average_cost=pos.average_cost.amount,
                                mark_price=mark_amount,
                                market_value=mkt_val,
                                unrealized_pnl=unrealized,
                                unrealized_pnl_pct=round(pnl_pct, 2),
                                stop_loss=sl_val,
                                take_profit=tp_val,
                            )
                        )
            return PositionsListResponse(positions=items)

    def close_position(self, request: ClosePositionRequest) -> OrderResponse:
        if self.kill_switch.is_active():
            raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

        exchange = Exchange(request.exchange)
        symbol = request.symbol.strip().upper()
        broker = self.get_broker(request.currency)

        with self._lock:
            pos = broker.portfolio._positions.get((exchange, symbol))
            if pos is None or pos.quantity <= 0:
                raise ValueError(f"No open position found for {exchange.value}:{symbol}")

            qty_to_sell = pos.quantity
            currency = broker.portfolio.currency
            tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
            instrument = Instrument(
                exchange=exchange,
                symbol=symbol,
                currency=currency,
                tick_size=tick,
                lot_size=1,
            )

            if (exchange, symbol) in self._mark_prices:
                feed_price = self._mark_prices[(exchange, symbol)].amount
            else:
                feed_price = self._get_or_fetch_mark_price(exchange, symbol, currency).amount
            now = datetime.now(timezone.utc)
            if broker.portfolio.ledger.entries:
                last_ts = broker.portfolio.ledger.entries[-1].timestamp
                if now < last_ts:
                    now = last_ts

            candle = Candle(
                symbol=symbol,
                exchange=exchange,
                interval=CandleInterval.M1,
                open=feed_price,
                high=feed_price,
                low=feed_price,
                close=feed_price,
                volume=100000,
                timestamp=now - timedelta(minutes=1),
                source="api_close_position",
                retrieval_timestamp=now,
            )

            proposal = TradeProposal(
                proposal_id=f"close-{symbol}-{now.strftime('%H%M%S%f')}",
                strategy_id="manual_close",
                instrument=instrument,
                timestamp=now,
                side="SELL",
                quantity=qty_to_sell,
                order_type="MARKET",
            )

            order = broker.submit_order(
                run_id=f"close-{now.strftime('%Y%m%d%H%M%S')}",
                proposal=proposal,
                current_candle=candle,
                tick_size=instrument.tick_size,
            )

            sold_price = order.average_fill_price.amount if order.average_fill_price else feed_price
            avg_cost = pos.average_cost.amount
            gross_pnl = (sold_price - avg_cost) * Decimal(str(qty_to_sell))
            net_pnl = gross_pnl - order.fees.amount
            pnl_pct = (
                ((sold_price - avg_cost) / avg_cost * Decimal("100")).quantize(Decimal("0.01"))
                if avg_cost > Decimal("0")
                else Decimal("0.00")
            )
            self._closed_trades.append({
                "symbol": symbol,
                "exchange": exchange.value,
                "currency": currency.value,
                "quantity": qty_to_sell,
                "bought_at": avg_cost,
                "sold_at": sold_price,
                "net_pnl": net_pnl,
                "pnl_pct": pnl_pct,
                "exit_reason": "MANUAL_SELL",
                "closed_at": now.isoformat(),
            })
            if (exchange, symbol) in self._position_brackets and pos.quantity - qty_to_sell <= 0:
                self._position_brackets.pop((exchange, symbol), None)
            if pos.quantity - qty_to_sell <= 0:
                self._mark_prices.pop((exchange, symbol), None)

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
            average_fill_price=order.average_fill_price.amount if order.average_fill_price else None,
            fees=order.fees.amount,
            slippage=order.slippage.amount,
            reject_reason=order.reject_reason,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
        )

    def get_lessons(self) -> list[str]:
        return list(self.lessons_store.load_lessons())

    def add_lesson(self, lesson: str) -> str:
        return self.lessons_store.add_lesson(lesson)

    def reset_sandbox(self) -> dict[str, Any]:
        if self.kill_switch.is_active():
            raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

        with self._lock:
            deposit_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
            self.inr_portfolio = PortfolioEngine(
                Currency.INR,
                fee_model=IndiaEquityFeeModel(),
                slippage_model=BasisPointsSlippageModel(),
            )
            self.inr_portfolio.deposit(
                Money(self.initial_inr_deposit, Currency.INR),
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
                Money(self.initial_usd_deposit, Currency.USD),
                deposit_time,
                "INITIAL_USD_DEPOSIT",
            )
            self.usd_broker = PaperBroker(self.usd_portfolio, kill_switch=self.kill_switch)
            self._mark_prices.clear()
            self._closed_trades.clear()
            self._position_brackets.clear()
            self._sim_step = 0
            self._scenario_bias = "normal"

            return {
                "status": "ok",
                "message": "Sandbox reset successfully",
                "paper_only": True,
            }

    def export_journal(
        self, format: Literal["json", "csv"] = "json", currency: str = "ALL"
    ) -> dict[str, Any] | str:
        with self._lock:
            eff_curr = currency.strip().upper() if isinstance(currency, str) else "ALL"
            if eff_curr == "INR":
                brokers = [self.inr_broker]
            elif eff_curr == "USD":
                brokers = [self.usd_broker]
            else:
                brokers = [self.inr_broker, self.usd_broker]

            ledger_items: list[dict[str, Any]] = []
            order_items: list[dict[str, Any]] = []

            for b in brokers:
                for entry in b.portfolio.ledger.entries:
                    ledger_items.append({
                        "sequence_id": entry.sequence_id,
                        "timestamp": entry.timestamp.isoformat(),
                        "currency": entry.currency.value,
                        "event_type": entry.event_type.value,
                        "exchange": entry.exchange.value if entry.exchange else "",
                        "symbol": entry.symbol or "",
                        "quantity_delta": entry.quantity_delta,
                        "execution_price": str(entry.execution_price.amount) if entry.execution_price else "",
                        "cash_delta": str(entry.cash_delta.amount),
                        "reference_id": entry.reference_id or "",
                    })
                for ord_obj in b.list_orders():
                    order_items.append({
                        "client_order_id": ord_obj.client_order_id,
                        "run_id": ord_obj.run_id,
                        "submitted_at": ord_obj.submitted_at.isoformat(),
                        "filled_at": ord_obj.filled_at.isoformat() if ord_obj.filled_at else "",
                        "exchange": ord_obj.exchange.value,
                        "symbol": ord_obj.symbol,
                        "side": ord_obj.side,
                        "quantity": ord_obj.quantity,
                        "filled_quantity": ord_obj.filled_quantity,
                        "status": ord_obj.status.value,
                        "average_fill_price": str(ord_obj.average_fill_price.amount) if ord_obj.average_fill_price else "",
                        "fees": str(ord_obj.fees.amount),
                        "slippage": str(ord_obj.slippage.amount),
                        "reject_reason": ord_obj.reject_reason or "",
                    })

            ledger_items.sort(key=lambda x: (x["timestamp"], x["sequence_id"]))
            order_items.sort(key=lambda x: x["submitted_at"])

            if format == "json":
                return {
                    "paper_only": True,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "total_ledger_entries": len(ledger_items),
                    "total_orders": len(order_items),
                    "ledger_entries": ledger_items,
                    "trade_orders": order_items,
                }

            def _clean(val: Any) -> str:
                s = "" if val is None else str(val)
                if s.startswith(("=", "+", "-", "@", "\t", "\r")):
                    s = "'" + s
                if '"' in s or "," in s or "\n" in s or "\r" in s:
                    s = '"' + s.replace('"', '""') + '"'
                return s

            csv_lines = [
                "SECTION,LEDGER_ENTRIES",
                "Sequence,Timestamp,Currency,Event Type,Exchange,Symbol,Quantity Delta,Execution Price,Cash Delta,Reference ID",
            ]
            for item in ledger_items:
                csv_lines.append(
                    ",".join([
                        _clean(item["sequence_id"]),
                        _clean(item["timestamp"]),
                        _clean(item["currency"]),
                        _clean(item["event_type"]),
                        _clean(item["exchange"]),
                        _clean(item["symbol"]),
                        _clean(item["quantity_delta"]),
                        _clean(item["execution_price"]),
                        _clean(item["cash_delta"]),
                        _clean(item["reference_id"]),
                    ])
                )

            csv_lines.append("")
            csv_lines.append("SECTION,PAPER_ORDERS")
            csv_lines.append(
                "Client Order ID,Run ID,Submitted At,Filled At,Exchange,Symbol,Side,Quantity,Filled Quantity,Status,Avg Price,Fees,Slippage,Reject Reason"
            )
            for item in order_items:
                csv_lines.append(
                    ",".join([
                        _clean(item["client_order_id"]),
                        _clean(item["run_id"]),
                        _clean(item["submitted_at"]),
                        _clean(item["filled_at"]),
                        _clean(item["exchange"]),
                        _clean(item["symbol"]),
                        _clean(item["side"]),
                        _clean(item["quantity"]),
                        _clean(item["filled_quantity"]),
                        _clean(item["status"]),
                        _clean(item["average_fill_price"]),
                        _clean(item["fees"]),
                        _clean(item["slippage"]),
                        _clean(item["reject_reason"]),
                    ])
                )

            return "\r\n".join(csv_lines)

    def sweep_positions(
        self,
        feed_source: Literal["synthetic", "cache", "delayed_feed"] = "synthetic",
    ) -> list[dict[str, Any]]:
        if self.kill_switch.is_active():
            return []

        triggered_events: list[dict[str, Any]] = []

        with self._lock:
            for broker in (self.inr_broker, self.usd_broker):
                for (exchange, symbol), pos in list(broker.portfolio._positions.items()):
                    if pos.quantity <= 0:
                        continue

                    currency = broker.portfolio.currency
                    tick = Decimal("0.05") if currency == Currency.INR else Decimal("0.01")
                    inst = Instrument(
                        exchange=exchange,
                        symbol=symbol,
                        currency=currency,
                        tick_size=tick,
                        lot_size=1,
                    )

                    fetch_res = self.feed_bridge.fetch_candles(
                        exchange=exchange,
                        symbol=symbol,
                        interval=CandleInterval.D1,
                        bars_count=1,
                        mode=feed_source,
                        sim_step=self._sim_step,
                        scenario_bias=self._scenario_bias,
                    )
                    if not fetch_res.candles:
                        continue
                    current_bar = fetch_res.candles[-1]
                    current_price = current_bar.close
                    self._mark_prices[(exchange, symbol)] = Money(current_price, currency)

                    brackets = self._position_brackets.get((exchange, symbol), {})
                    sl_obj = brackets.get("stop_loss")
                    tp_obj = brackets.get("take_profit")

                    avg_cost = pos.average_cost.amount
                    sl_price = sl_obj.amount if sl_obj else (avg_cost * Decimal("0.96")).quantize(tick)
                    tp_price = tp_obj.amount if tp_obj else (avg_cost * Decimal("1.08")).quantize(tick)

                    is_stop_loss = current_price <= sl_price
                    is_take_profit = current_price >= tp_price

                    if not (is_stop_loss or is_take_profit):
                        continue

                    exit_reason = "STOP_LOSS_TRIGGERED" if is_stop_loss else "TAKE_PROFIT_TRIGGERED"
                    trigger_price = sl_price if is_stop_loss else tp_price

                    now = datetime.now(timezone.utc)
                    if broker.portfolio.ledger.entries:
                        last_ts = broker.portfolio.ledger.entries[-1].timestamp
                        if now < last_ts:
                            now = last_ts

                    candle = Candle(
                        symbol=symbol,
                        exchange=exchange,
                        interval=CandleInterval.M1,
                        open=current_price,
                        high=current_price,
                        low=current_price,
                        close=current_price,
                        volume=100000,
                        timestamp=now - timedelta(minutes=1),
                        source="sweep_positions",
                        retrieval_timestamp=now,
                    )

                    proposal = TradeProposal(
                        proposal_id=f"sweep-{symbol}-{now.strftime('%H%M%S%f')}",
                        strategy_id="position_sweeper",
                        instrument=inst,
                        timestamp=now,
                        side="SELL",
                        quantity=pos.quantity,
                        order_type="MARKET",
                    )

                    order = broker.submit_order(
                        run_id=f"sweep-{now.strftime('%Y%m%d%H%M%S')}",
                        proposal=proposal,
                        current_candle=candle,
                        tick_size=inst.tick_size,
                    )

                    sold_price = order.average_fill_price.amount if order.average_fill_price else current_price
                    gross_pnl = (sold_price - avg_cost) * Decimal(str(pos.quantity))
                    net_pnl = gross_pnl - order.fees.amount
                    pnl_pct = (
                        ((sold_price - avg_cost) / avg_cost * Decimal("100")).quantize(Decimal("0.01"))
                        if avg_cost > Decimal("0")
                        else Decimal("0.00")
                    )

                    trade_record = {
                        "symbol": symbol,
                        "exchange": exchange.value,
                        "currency": currency.value,
                        "quantity": pos.quantity,
                        "bought_at": avg_cost,
                        "sold_at": sold_price,
                        "net_pnl": net_pnl,
                        "pnl_pct": pnl_pct,
                        "exit_reason": exit_reason,
                        "closed_at": now.isoformat(),
                    }
                    self._closed_trades.append(trade_record)
                    self._position_brackets.pop((exchange, symbol), None)
                    self._mark_prices.pop((exchange, symbol), None)

                    triggered_events.append({
                        "symbol": symbol,
                        "exchange": exchange.value,
                        "currency": currency.value,
                        "trigger_type": exit_reason,
                        "trigger_price": trigger_price,
                        "mark_price": current_price,
                        "quantity": pos.quantity,
                        "net_pnl": net_pnl,
                        "client_order_id": order.client_order_id,
                    })

        return triggered_events

    def apply_scenario(
        self,
        scenario: Literal["normal", "bull_rally", "sudden_crash", "sideways_chop"],
    ) -> ScenarioResponse:
        if self.kill_switch.is_active():
            raise KillSwitchError(self.kill_switch.reason() or "Kill switch active")

        with self._lock:
            self._scenario_bias = scenario
            self._sim_step += 1
            events = self.sweep_positions(feed_source="synthetic")

            msg = f"Scenario '{scenario}' applied at simulation step {self._sim_step}"
            if events:
                msg += f" with {len(events)} position protection triggers"

            trigger_items = [
                SweepTriggerEvent(
                    symbol=e["symbol"],
                    exchange=e["exchange"],
                    currency=e["currency"],
                    trigger_type=e["trigger_type"],
                    trigger_price=e["trigger_price"],
                    mark_price=e["mark_price"],
                    quantity=e["quantity"],
                    net_pnl=e["net_pnl"],
                    client_order_id=e["client_order_id"],
                )
                for e in events
            ]

            return ScenarioResponse(
                scenario=scenario,
                sim_step=self._sim_step,
                paper_only=True,
                message=msg,
                sweep_events=trigger_items,
            )

    def get_pnl_summary(self) -> PnlSummaryResponse:
        with self._lock:
            def _build_breakdown(
                currency: Currency, broker: PaperBroker, initial_capital: Decimal
            ) -> PnlBreakdownItem:
                curr_str: Literal["INR", "USD"] = "INR" if currency == Currency.INR else "USD"
                moment = datetime.now(timezone.utc)
                marks: dict[tuple[Exchange, str], Money] = {}
                for (ex, sym), pos in broker.portfolio._positions.items():
                    if pos.quantity != 0:
                        marks[(ex, sym)] = self._get_or_fetch_mark_price(ex, sym, currency)
                snap = broker.portfolio.snapshot(currency, marks, moment)
                total_equity = snap.total_equity.amount
                net_pnl = total_equity - initial_capital
                net_ret_pct = (
                    ((total_equity - initial_capital) / initial_capital * Decimal("100")).quantize(Decimal("0.01"))
                    if initial_capital > Decimal("0")
                    else Decimal("0.00")
                )
                realized_pnl = snap.realized_pnl.amount
                total_fees = broker.portfolio.ledger.get_total_fees(currency).amount

                curr_closed = [t for t in self._closed_trades if t["currency"] == curr_str]
                closed_count = len(curr_closed)
                realized_gains = sum((t["net_pnl"] for t in curr_closed if t["net_pnl"] > Decimal("0")), Decimal("0.00"))
                realized_losses = sum((t["net_pnl"] for t in curr_closed if t["net_pnl"] < Decimal("0")), Decimal("0.00"))
                win_count = sum(1 for t in curr_closed if t["net_pnl"] > Decimal("0"))
                loss_count = sum(1 for t in curr_closed if t["net_pnl"] < Decimal("0"))
                win_rate = (
                    (Decimal(win_count) / Decimal(closed_count) * Decimal("100")).quantize(Decimal("0.01"))
                    if closed_count > 0
                    else Decimal("0.00")
                )
                best_pnl = max((t["net_pnl"] for t in curr_closed), default=Decimal("0.00"))
                worst_pnl = min((t["net_pnl"] for t in curr_closed), default=Decimal("0.00"))

                open_pnls: list[Decimal] = []
                for (ex, sym), pos in broker.portfolio._positions.items():
                    if pos.quantity != 0:
                        mk = marks[(ex, sym)].amount
                        p_pnl = (mk - pos.average_cost.amount) * Decimal(str(pos.quantity))
                        open_pnls.append(p_pnl)

                unrealized_pnl = sum(open_pnls, Decimal("0.00"))
                unrealized_gains = sum((p for p in open_pnls if p > Decimal("0")), Decimal("0.00"))
                unrealized_losses = sum((p for p in open_pnls if p < Decimal("0")), Decimal("0.00"))

                return PnlBreakdownItem(
                    currency=curr_str,
                    starting_capital=initial_capital,
                    current_equity=total_equity,
                    net_pnl=net_pnl,
                    net_return_pct=net_ret_pct,
                    realized_pnl=realized_pnl,
                    realized_gains=realized_gains,
                    realized_losses=realized_losses,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_gains=unrealized_gains,
                    unrealized_losses=unrealized_losses,
                    total_fees=total_fees,
                    closed_trades_count=closed_count,
                    winning_trades=win_count,
                    losing_trades=loss_count,
                    win_rate_pct=win_rate,
                    best_trade_pnl=best_pnl,
                    worst_trade_pnl=worst_pnl,
                )

            inr_item = _build_breakdown(Currency.INR, self.inr_broker, self.initial_inr_deposit)
            usd_item = _build_breakdown(Currency.USD, self.usd_broker, self.initial_usd_deposit)

            closed_records = [
                ClosedTradeRecord(
                    symbol=t["symbol"],
                    exchange=t["exchange"],
                    currency=t["currency"],
                    quantity=t["quantity"],
                    bought_at=t["bought_at"],
                    sold_at=t["sold_at"],
                    net_pnl=t["net_pnl"],
                    pnl_pct=t["pnl_pct"],
                    exit_reason=t["exit_reason"],
                    closed_at=t["closed_at"],
                )
                for t in reversed(self._closed_trades)
            ]

            return PnlSummaryResponse(
                paper_only=True,
                inr=inr_item,
                usd=usd_item,
                closed_trades=closed_records,
            )

    def close(self) -> None:
        pass
