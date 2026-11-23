"""Strictly causal single-instrument long-only backtest engine."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any

from agentic_trading.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionType,
    adjust_candles_for_corporate_actions,
)
from agentic_trading.market_data.instruments import (
    Currency,
    CurrencyMismatchError,
    Instrument,
    Money,
)
from agentic_trading.market_data.models import Candle, Exchange, get_exchange_timezone
from agentic_trading.risk_engine.proposal_gate import (
    PortfolioRiskPolicy,
    ProposalRiskDecision,
    evaluate_trade_proposal,
)
from agentic_trading.simulation.costs import FeeModel, SlippageModel
from agentic_trading.simulation.ledger import AccountingLedger
from agentic_trading.simulation.portfolio import (
    InsufficientFundsError,
    PortfolioEngine,
    PortfolioSnapshot,
)
from agentic_trading.strategy.contracts import (
    BarContext,
    Signal,
    SignalDirection,
    Strategy,
    TradeProposal,
)
from agentic_trading.time_machine.manifest import (
    ExperimentManifest,
    build_experiment_manifest,
    canonicalize,
    sha256_of,
)
from agentic_trading.time_machine.metrics import (
    BacktestMetrics,
    compute_backtest_metrics,
    compute_benchmark_return_pct,
)

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
_R_QUANTUM = Decimal("0.0001")
_COLLISION_POLICIES = ("STOP_FIRST", "TARGET_FIRST")
_EXIT_REASONS = ("STOP_LOSS", "TAKE_PROFIT", "SIGNAL_EXIT", "END_OF_DATA", "DELISTED")


class LedgerConservationError(RuntimeError):
    """Raised when the accounting conservation residual is not exactly zero."""


class CorporateActionConflictError(ValueError):
    """Raised when a price-rebasing action hits an open position the engine cannot rebase."""


def _is_pct(value: Any, *, allow_one: bool) -> bool:
    if isinstance(value, (bool, float)) or not isinstance(value, Decimal) or not value.is_finite():
        return False
    return value > 0 and (value <= 1 if allow_one else value < 1)


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: Money
    risk_policy: PortfolioRiskPolicy
    fee_model: FeeModel
    slippage_model: SlippageModel
    position_size_pct: Decimal = Decimal("0.10")
    default_stop_loss_pct: Decimal = Decimal("0.02")
    default_take_profit_pct: Decimal = Decimal("0.04")
    max_volume_participation: Decimal = Decimal("0.10")
    intrabar_collision_policy: str = "STOP_FIRST"
    adjust_corporate_actions: bool = True
    random_seed: int = 42
    git_commit: str = "2cac6ca"
    provider_source: str = "replay_fixture"
    hmac_key: bytes | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.initial_capital, Money):
            raise TypeError("initial_capital must be Money")
        if self.initial_capital.amount <= 0:
            raise ValueError("initial_capital must be strictly positive")
        if not isinstance(self.risk_policy, PortfolioRiskPolicy):
            raise TypeError("risk_policy must be PortfolioRiskPolicy")
        if not isinstance(self.fee_model, FeeModel):
            raise TypeError("fee_model must be FeeModel")
        if not isinstance(self.slippage_model, SlippageModel):
            raise TypeError("slippage_model must be SlippageModel")
        if not _is_pct(self.position_size_pct, allow_one=True):
            raise ValueError("position_size_pct must be a Decimal in (0, 1]")
        if not _is_pct(self.default_stop_loss_pct, allow_one=False):
            raise ValueError("default_stop_loss_pct must be a Decimal in (0, 1)")
        if (
            isinstance(self.default_take_profit_pct, (bool, float))
            or not isinstance(self.default_take_profit_pct, Decimal)
            or not self.default_take_profit_pct.is_finite()
            or self.default_take_profit_pct <= 0
        ):
            raise ValueError("default_take_profit_pct must be a positive finite Decimal")
        if not _is_pct(self.max_volume_participation, allow_one=True):
            raise ValueError("max_volume_participation must be a Decimal in (0, 1]")
        if self.intrabar_collision_policy not in _COLLISION_POLICIES:
            raise ValueError("intrabar_collision_policy must be STOP_FIRST or TARGET_FIRST")
        if not isinstance(self.adjust_corporate_actions, bool):
            raise TypeError("adjust_corporate_actions must be a bool")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("random_seed must be an int")
        for name in ("git_commit", "provider_source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.hmac_key is not None:
            if isinstance(self.hmac_key, bool) or not isinstance(self.hmac_key, (bytes, str)):
                raise TypeError("hmac_key must be bytes or str")
            if not self.hmac_key:
                raise ValueError("hmac_key cannot be empty")


@dataclass(frozen=True)
class CompletedTrade:
    trade_id: str
    exchange: Exchange
    symbol: str
    currency: Currency
    entry_time: datetime
    exit_time: datetime
    quantity: int
    entry_price: Money
    exit_price: Money
    stop_loss: Money | None
    take_profit: Money | None
    gross_pnl: Money
    fees: Money
    net_pnl: Money
    r_multiple: Decimal
    exit_reason: str

    def __post_init__(self) -> None:
        if self.exit_reason not in _EXIT_REASONS:
            raise ValueError(f"unknown exit_reason {self.exit_reason!r}")


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    cash: Money
    holdings_value: Money
    total_equity: Money
    drawdown_pct: Decimal


@dataclass(frozen=True)
class BacktestResult:
    manifest: ExperimentManifest
    final_snapshot: PortfolioSnapshot
    ledger: AccountingLedger
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[CompletedTrade, ...]
    rejected_proposals: tuple[ProposalRiskDecision, ...]
    metrics: BacktestMetrics


@dataclass
class _OpenPosition:
    trade_id: str
    entry_time: datetime
    entry_price: Money
    entry_fee: Decimal
    quantity: int
    stop_loss: Money | None
    take_profit: Money | None


def ledger_conservation_residual(
    ledger: AccountingLedger, snapshot: PortfolioSnapshot
) -> Decimal:
    currency = snapshot.currency
    expected_cash = (
        ledger.get_total_deposits(currency).amount
        - ledger.get_total_withdrawals(currency).amount
        + snapshot.realized_pnl.amount
        + ledger.get_total_dividends(currency).amount
        - ledger.get_total_fees(currency).amount
    )
    open_basis = sum((p.cost_basis.amount for p in snapshot.positions.values()), ZERO)
    return expected_cash - (snapshot.cash.amount + open_basis)


def _local_date(moment: datetime, exchange: Exchange) -> date:
    return moment.astimezone(get_exchange_timezone(exchange)).date()


def _describe_model(model: object) -> str:
    params = {k: v for k, v in vars(model).items() if not k.startswith("_")}
    return f"{type(model).__name__}:{sha256_of(params)[:16]}"


def _strategy_params(strategy: Strategy) -> dict[str, Any]:
    raw = {k: v for k, v in getattr(strategy, "__dict__", {}).items() if not k.startswith("_")}
    raw["strategy_id"] = strategy.strategy_id
    raw["warmup_bars"] = strategy.warmup_bars
    return raw


def _validate_inputs(
    instrument: Instrument,
    candles: Sequence[Candle],
    strategy: Strategy,
    config: BacktestConfig,
) -> tuple[Candle, ...]:
    if not isinstance(instrument, Instrument):
        raise TypeError("instrument must be an Instrument")
    if not isinstance(config, BacktestConfig):
        raise TypeError("config must be a BacktestConfig")
    bars = tuple(candles)
    if not bars:
        raise ValueError("candles must be non-empty")
    if instrument.currency != config.initial_capital.currency:
        raise CurrencyMismatchError(
            f"instrument currency {instrument.currency} != capital currency "
            f"{config.initial_capital.currency}"
        )
    if (
        isinstance(strategy.warmup_bars, bool)
        or not isinstance(strategy.warmup_bars, int)
        or strategy.warmup_bars < 0
    ):
        raise ValueError("strategy.warmup_bars must be an integer >= 0")
    if not isinstance(strategy.strategy_id, str) or not strategy.strategy_id.strip():
        raise ValueError("strategy.strategy_id must be a non-empty string")
    previous: Candle | None = None
    for bar in bars:
        if not isinstance(bar, Candle):
            raise TypeError("candles must contain Candle instances")
        if bar.exchange != instrument.exchange or bar.symbol != instrument.symbol:
            raise ValueError(
                f"candle {bar.exchange.value}:{bar.symbol} does not match instrument "
                f"{instrument.exchange.value}:{instrument.symbol}"
            )
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            raise ValueError("candle prices must be strictly positive")
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise ValueError("candle high/low must bound open and close")
        if bar.volume < 0:
            raise ValueError("candle volume must be non-negative")
        if previous is not None:
            if bar.interval != previous.interval:
                raise ValueError("candles must share a single interval")
            if bar.timestamp <= previous.timestamp or bar.timestamp < previous.close_time:
                raise ValueError("candles must be strictly increasing and non-overlapping")
        previous = bar
    return bars


def _corporate_action_policy(
    config: BacktestConfig, actions: Sequence[CorporateAction]
) -> str:
    if not actions:
        return "NONE" if config.adjust_corporate_actions else "DISABLED"
    digest = sha256_of(sorted((canonicalize(a) for a in actions), key=repr))[:32]
    prefix = "POINT_IN_TIME_ADJUSTED" if config.adjust_corporate_actions else "DISABLED"
    return f"{prefix}:{digest}"


class _Session:
    def __init__(
        self,
        instrument: Instrument,
        bars: tuple[Candle, ...],
        strategy: Strategy,
        config: BacktestConfig,
        actions: tuple[CorporateAction, ...],
        manifest: ExperimentManifest,
    ) -> None:
        self.instrument = instrument
        self.bars = bars
        self.strategy = strategy
        self.config = config
        self.actions = actions
        self.manifest = manifest
        self.currency = instrument.currency
        self.key = (instrument.exchange, instrument.symbol)
        self.portfolio = PortfolioEngine(
            self.currency, fee_model=config.fee_model, slippage_model=config.slippage_model
        )
        self.position: _OpenPosition | None = None
        self.pending: TradeProposal | None = None
        self.trades: list[CompletedTrade] = []
        self.rejected: list[ProposalRiskDecision] = []
        self.equity: list[EquityPoint] = []
        self.proposal_seq = 0
        self.bars_in_market = 0
        self.peak_equity = config.initial_capital.amount
        self.day_start_equity = config.initial_capital.amount
        self.last_close_equity = config.initial_capital.amount
        self.current_date: date | None = None
        self.previous_date: date | None = None

    def _money(self, amount: Decimal) -> Money:
        return Money(amount, self.currency)

    def _snapshot(self, mark: Decimal, moment: datetime) -> PortfolioSnapshot:
        return self.portfolio.snapshot(self.currency, {self.key: self._money(mark)}, moment)

    def _reject(self, proposal_id: str, reason: str) -> None:
        self.rejected.append(
            ProposalRiskDecision(
                approved=False, proposal_id=proposal_id, reasons=(reason,), max_allowed_quantity=0
            )
        )

    def execute(self) -> BacktestResult:
        first = self.bars[0]
        self.portfolio.deposit(self.config.initial_capital, first.timestamp, "INITIAL_CAPITAL")
        for index, bar in enumerate(self.bars):
            self._process_bar(index, bar)
        if self.pending is not None:
            self._reject(self.pending.proposal_id, "END_OF_DATA_PENDING_CANCELLED")
            self.pending = None
        last = self.bars[-1]
        if self.position is not None:
            self._exit(last.close, "END_OF_DATA", last.close_time)
            self._append_equity(last, replace_last=True)
        final = self._snapshot(last.close, last.close_time)
        residual = ledger_conservation_residual(self.portfolio.ledger, final)
        if residual != ZERO:
            raise LedgerConservationError(f"ledger conservation residual {residual} != 0")
        metrics = compute_backtest_metrics(
            equity_curve=self.equity,
            trades=self.trades,
            initial_capital=self.config.initial_capital,
            total_fees=self.portfolio.ledger.get_total_fees(self.currency).amount,
            bars_in_market=self.bars_in_market,
            total_bars=len(self.bars),
            benchmark_return_pct=compute_benchmark_return_pct(self.bars),
        )
        return BacktestResult(
            manifest=self.manifest,
            final_snapshot=final,
            ledger=self.portfolio.ledger,
            equity_curve=tuple(self.equity),
            trades=tuple(self.trades),
            rejected_proposals=tuple(self.rejected),
            metrics=metrics,
        )

    def _process_bar(self, index: int, bar: Candle) -> None:
        bar_date = _local_date(bar.timestamp, self.instrument.exchange)
        if bar_date != self.current_date:
            self.day_start_equity = self.last_close_equity
            self.previous_date = self.current_date
            self.current_date = bar_date
        delisted = (
            self.instrument.delisted_date is not None and bar_date >= self.instrument.delisted_date
        )
        tradable = self.instrument.is_active_on(bar_date) and not delisted
        if delisted and self.position is not None:
            self._exit(bar.open, "DELISTED", bar.timestamp)
        if not tradable:
            if self.pending is not None:
                self._reject(self.pending.proposal_id, "INSTRUMENT_NOT_TRADABLE")
                self.pending = None
            self._append_equity(bar)
            return
        self._apply_corporate_actions(bar, bar_date)
        if self.pending is not None:
            if self.pending.side == "BUY":
                self._execute_buy(bar)
            else:
                self._execute_signal_exit(bar)
        if self.position is not None:
            self._check_protective(bar)
        self._evaluate_strategy(index, bar)
        self._append_equity(bar)

    def _apply_corporate_actions(self, bar: Candle, bar_date: date) -> None:
        if not self.config.adjust_corporate_actions or self.previous_date is None:
            return
        seen: set[tuple[Any, ...]] = set()
        for action in self.actions:
            if not (self.previous_date < action.effective_date <= bar_date):
                continue
            key = (action.action_type, action.effective_date, action.adjustment_factor)
            if key in seen:
                continue
            seen.add(key)
            if action.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS):
                if self.position is not None:
                    raise CorporateActionConflictError(
                        f"{action.action_type.value} effective {action.effective_date} with open "
                        f"position in {self.instrument.symbol}; position rebasing is unsupported"
                    )
                if self.pending is not None:
                    self._reject(self.pending.proposal_id, "CORPORATE_ACTION_PENDING_ORDER_CANCELLED")
                    self.pending = None
            elif (
                action.action_type == CorporateActionType.DIVIDEND
                and action.cash_amount is not None
                and self.position is not None
            ):
                self.portfolio.apply_dividend(
                    bar.timestamp,
                    self.instrument.exchange,
                    self.instrument.symbol,
                    self._money(action.cash_amount.amount * Decimal(self.position.quantity)),
                    f"DIV:{action.effective_date.isoformat()}",
                )

    def _execute_buy(self, bar: Candle) -> None:
        proposal = self.pending
        self.pending = None
        assert proposal is not None
        lot = self.instrument.lot_size
        cap = int(Decimal(bar.volume) * self.config.max_volume_participation)
        cap -= cap % lot
        if cap < lot:
            self._reject(proposal.proposal_id, "LIQUIDITY_BELOW_LOT_SIZE")
            return
        sized = replace(proposal, quantity=min(proposal.quantity, cap))
        snapshot = self._snapshot(bar.open, bar.timestamp)
        entry = self._money(bar.open)
        daily = self._money(snapshot.total_equity.amount - self.day_start_equity)
        peak = self._money(self.peak_equity)
        policy = self.config.risk_policy
        decision = evaluate_trade_proposal(sized, snapshot, entry, policy, daily, peak)
        if not decision.approved and lot <= decision.max_allowed_quantity < sized.quantity:
            resized = replace(sized, quantity=decision.max_allowed_quantity)
            retry = evaluate_trade_proposal(resized, snapshot, entry, policy, daily, peak)
            if retry.approved:
                sized, decision = resized, retry
        if not decision.approved:
            self.rejected.append(decision)
            return
        quantity = min(sized.quantity, decision.max_allowed_quantity)
        quantity -= quantity % lot
        if quantity < lot:
            self._reject(proposal.proposal_id, "APPROVED_QUANTITY_BELOW_LOT_SIZE")
            return
        try:
            fill, fee_entry = self.portfolio.apply_fill(
                timestamp=bar.timestamp,
                exchange=self.instrument.exchange,
                symbol=self.instrument.symbol,
                side="BUY",
                quantity=quantity,
                execution_price=entry,
                tick_size=self.instrument.tick_size,
                reference_id=proposal.proposal_id,
            )
        except InsufficientFundsError:
            self._reject(proposal.proposal_id, "INSUFFICIENT_FUNDS_AFTER_COSTS")
            return
        assert fill.execution_price is not None
        self.position = _OpenPosition(
            trade_id=proposal.proposal_id,
            entry_time=bar.timestamp,
            entry_price=fill.execution_price,
            entry_fee=-fee_entry.cash_delta.amount if fee_entry is not None else ZERO,
            quantity=quantity,
            stop_loss=sized.stop_loss,
            take_profit=sized.take_profit,
        )

    def _execute_signal_exit(self, bar: Candle) -> None:
        proposal = self.pending
        self.pending = None
        assert proposal is not None
        if self.position is None:
            self._reject(proposal.proposal_id, "NO_POSITION_TO_EXIT")
            return
        sized = replace(proposal, quantity=self.position.quantity)
        snapshot = self._snapshot(bar.open, bar.timestamp)
        decision = evaluate_trade_proposal(
            sized,
            snapshot,
            self._money(bar.open),
            self.config.risk_policy,
            self._money(snapshot.total_equity.amount - self.day_start_equity),
            self._money(self.peak_equity),
        )
        if not decision.approved:
            self.rejected.append(decision)
            return
        self._exit(bar.open, "SIGNAL_EXIT", bar.timestamp)

    def _check_protective(self, bar: Candle) -> None:
        position = self.position
        assert position is not None
        stop = position.stop_loss.amount if position.stop_loss is not None else None
        target = position.take_profit.amount if position.take_profit is not None else None
        if stop is not None and bar.open <= stop:
            self._exit(bar.open, "STOP_LOSS", bar.timestamp)
        elif target is not None and bar.open >= target:
            self._exit(bar.open, "TAKE_PROFIT", bar.timestamp)
        else:
            stop_hit = stop is not None and bar.low <= stop
            target_hit = target is not None and bar.high >= target
            if stop_hit and target_hit:
                if self.config.intrabar_collision_policy == "STOP_FIRST":
                    assert stop is not None
                    self._exit(stop, "STOP_LOSS", bar.timestamp)
                else:
                    assert target is not None
                    self._exit(target, "TAKE_PROFIT", bar.timestamp)
            elif stop_hit:
                assert stop is not None
                self._exit(stop, "STOP_LOSS", bar.timestamp)
            elif target_hit:
                assert target is not None
                self._exit(target, "TAKE_PROFIT", bar.timestamp)

    def _exit(self, raw_price: Decimal, reason: str, moment: datetime) -> None:
        position = self.position
        assert position is not None
        fill, fee_entry = self.portfolio.apply_fill(
            timestamp=moment,
            exchange=self.instrument.exchange,
            symbol=self.instrument.symbol,
            side="SELL",
            quantity=position.quantity,
            execution_price=self._money(raw_price),
            tick_size=self.instrument.tick_size,
            reference_id=f"{position.trade_id}:{reason}",
        )
        assert fill.execution_price is not None
        exit_price = fill.execution_price
        exit_fee = -fee_entry.cash_delta.amount if fee_entry is not None else ZERO
        quantity = Decimal(position.quantity)
        gross = (exit_price.amount - position.entry_price.amount) * quantity
        fees = position.entry_fee + exit_fee
        net = gross - fees
        risk = ZERO
        if position.stop_loss is not None and position.stop_loss.amount < position.entry_price.amount:
            risk = (position.entry_price.amount - position.stop_loss.amount) * quantity
        r_multiple = (net / risk).quantize(_R_QUANTUM, rounding=ROUND_HALF_EVEN) if risk > 0 else ZERO
        self.trades.append(
            CompletedTrade(
                trade_id=position.trade_id,
                exchange=self.instrument.exchange,
                symbol=self.instrument.symbol,
                currency=self.currency,
                entry_time=position.entry_time,
                exit_time=moment,
                quantity=position.quantity,
                entry_price=position.entry_price,
                exit_price=exit_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                gross_pnl=self._money(gross),
                fees=self._money(fees),
                net_pnl=self._money(net),
                r_multiple=r_multiple,
                exit_reason=reason,
            )
        )
        self.position = None

    def _visible_bars(self, index: int, bar: Candle) -> tuple[Candle, ...]:
        visible = self.bars[: index + 1]
        if not self.config.adjust_corporate_actions or not self.actions:
            return visible
        return adjust_candles_for_corporate_actions(
            visible,
            self.actions,
            tick_size=None,
            as_of_date=_local_date(bar.close_time, self.instrument.exchange),
        )

    def _evaluate_strategy(self, index: int, bar: Candle) -> None:
        if index + 1 < self.strategy.warmup_bars:
            return
        context = BarContext(
            instrument=self.instrument,
            decision_time=bar.close_time,
            bars=self._visible_bars(index, bar),
        )
        signal = self.strategy.evaluate(context)
        if signal is None:
            return
        if (signal.exchange, signal.symbol) != self.key:
            raise ValueError("strategy signal does not match backtest instrument")
        if signal.direction == SignalDirection.LONG:
            if self.position is None and self.pending is None:
                self._queue_buy(bar, signal)
        elif signal.direction == SignalDirection.EXIT:
            if self.position is not None and self.pending is None:
                self._queue_exit(bar, signal)
            elif self.position is None and self.pending is not None:
                self._reject(self.pending.proposal_id, "CANCELLED_BY_EXIT_SIGNAL")
                self.pending = None

    def _next_proposal_id(self) -> str:
        self.proposal_seq += 1
        return f"{self.strategy.strategy_id}-P{self.proposal_seq:06d}"

    def _queue_buy(self, bar: Candle, signal: Signal) -> None:
        tick = self.instrument.tick_size
        close = bar.close
        stop_raw = (
            signal.stop_loss.amount
            if signal.stop_loss is not None
            else close * (ONE - self.config.default_stop_loss_pct)
        )
        target_raw = (
            signal.take_profit.amount
            if signal.take_profit is not None
            else close * (ONE + self.config.default_take_profit_pct)
        )
        stop = (stop_raw / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        target = (target_raw / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        equity = self._snapshot(close, bar.close_time).total_equity.amount
        lot = self.instrument.lot_size
        quantity = int(equity * self.config.position_size_pct / close)
        quantity -= quantity % lot
        if quantity < lot:
            return
        self.pending = TradeProposal(
            proposal_id=self._next_proposal_id(),
            strategy_id=self.strategy.strategy_id,
            instrument=self.instrument,
            timestamp=bar.close_time,
            side="BUY",
            quantity=quantity,
            stop_loss=self._money(stop),
            take_profit=self._money(target),
            signal=signal,
        )

    def _queue_exit(self, bar: Candle, signal: Signal) -> None:
        assert self.position is not None
        self.pending = TradeProposal(
            proposal_id=self._next_proposal_id(),
            strategy_id=self.strategy.strategy_id,
            instrument=self.instrument,
            timestamp=bar.close_time,
            side="SELL",
            quantity=self.position.quantity,
            signal=signal,
        )

    def _append_equity(self, bar: Candle, *, replace_last: bool = False) -> None:
        snapshot = self._snapshot(bar.close, bar.close_time)
        equity = snapshot.total_equity.amount
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (
            (self.peak_equity - equity) / self.peak_equity * HUNDRED if self.peak_equity > 0 else ZERO
        )
        point = EquityPoint(
            timestamp=bar.close_time,
            cash=snapshot.cash,
            holdings_value=snapshot.holdings_value,
            total_equity=snapshot.total_equity,
            drawdown_pct=drawdown.quantize(_R_QUANTUM, rounding=ROUND_HALF_EVEN),
        )
        if replace_last:
            self.equity[-1] = point
        else:
            self.equity.append(point)
            if self.position is not None:
                self.bars_in_market += 1
        self.last_close_equity = equity


class BacktestEngine:
    def run(
        self,
        instrument: Instrument,
        candles: Sequence[Candle],
        strategy: Strategy,
        config: BacktestConfig,
        corporate_actions: Sequence[CorporateAction] = (),
    ) -> BacktestResult:
        bars = _validate_inputs(instrument, candles, strategy, config)
        relevant = tuple(
            a
            for a in corporate_actions
            if a.exchange == instrument.exchange and a.symbol == instrument.symbol
        )
        risk_policy: Mapping[str, Any] = {
            "portfolio": canonicalize(config.risk_policy),
            "engine": {
                "position_size_pct": config.position_size_pct,
                "default_stop_loss_pct": config.default_stop_loss_pct,
                "default_take_profit_pct": config.default_take_profit_pct,
                "max_volume_participation": config.max_volume_participation,
                "intrabar_collision_policy": config.intrabar_collision_policy,
                "adjust_corporate_actions": config.adjust_corporate_actions,
            },
        }
        manifest = build_experiment_manifest(
            instrument=instrument,
            candles=bars,
            provider_source=config.provider_source,
            corporate_action_policy=_corporate_action_policy(config, relevant),
            strategy_id=strategy.strategy_id,
            strategy_params=_strategy_params(strategy),
            fee_model_name=_describe_model(config.fee_model),
            slippage_model_name=_describe_model(config.slippage_model),
            risk_policy=risk_policy,
            initial_capital=config.initial_capital,
            random_seed=config.random_seed,
            git_commit=config.git_commit,
            hmac_key=config.hmac_key,
        )
        return _Session(instrument, bars, strategy, config, relevant, manifest).execute()
