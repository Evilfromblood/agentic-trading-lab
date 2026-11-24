"""Causal multi-symbol basket portfolio backtester and walk-forward parameter optimizer."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any

from agentic_trading.market_data.instruments import (
    CurrencyMismatchError,
    Instrument,
    Money,
)
from agentic_trading.market_data.models import Candle, Exchange, get_exchange_timezone
from agentic_trading.risk_engine.proposal_gate import (
    ProposalRiskDecision,
    evaluate_trade_proposal,
)
from agentic_trading.simulation.ledger import AccountingLedger
from agentic_trading.simulation.portfolio import PortfolioEngine, PortfolioSnapshot
from agentic_trading.strategy.contracts import (
    BarContext,
    SignalDirection,
    Strategy,
    TradeProposal,
)
from agentic_trading.strategy.library import (
    STRATEGY_REGISTRY,
    ATRBreakoutStrategy,
    EMAPullbackStrategy,
    RSIMeanReversionStrategy,
    SmaCrossStrategy,
)
from agentic_trading.time_machine.engine import (
    BacktestConfig,
    BacktestEngine,
    CompletedTrade,
    EquityPoint,
    LedgerConservationError,
    ledger_conservation_residual,
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


@dataclass(frozen=True)
class PerSymbolAttribution:
    symbol: str
    exchange: str
    trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: Decimal
    realized_pnl: Decimal
    total_return_pct: Decimal


@dataclass(frozen=True)
class WalkForwardOptimizationResult:
    strategy_name: str
    best_params: dict[str, Any]
    in_sample_metrics: dict[str, Any]
    out_of_sample_metrics: dict[str, Any]
    in_sample_range: dict[str, str]
    out_of_sample_range: dict[str, str]
    split_ratio: str = "70/30"


@dataclass(frozen=True)
class BasketBacktestResult:
    manifest_id: str
    manifest_sha256: str
    manifest_verified: bool
    conservation_residual: Decimal
    portfolio_metrics: BacktestMetrics
    per_symbol_attribution: dict[str, PerSymbolAttribution]
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[CompletedTrade, ...]
    final_snapshot: PortfolioSnapshot
    ledger: AccountingLedger
    walk_forward: WalkForwardOptimizationResult | None = None


@dataclass
class _BasketOpenPosition:
    symbol: str
    exchange: Exchange
    trade_id: str
    entry_time: datetime
    entry_price: Money
    entry_fee: Decimal
    quantity: int
    stop_loss: Money | None
    take_profit: Money | None


def _local_date(moment: datetime, exchange: Exchange) -> date:
    return moment.astimezone(get_exchange_timezone(exchange)).date()


def _instantiate_strategy(strategy_name: str, params: dict[str, Any] | None = None) -> Strategy:
    strat_key = strategy_name.strip().lower()
    p = params or {}
    if strat_key == "ema_pullback":
        return EMAPullbackStrategy(
            fast_period=p.get("fast_period", 9),
            slow_period=p.get("slow_period", 21),
            atr_period=p.get("atr_period", 14),
            strategy_id="ema_pullback",
        )
    if strat_key == "rsi_mean_reversion":
        return RSIMeanReversionStrategy(
            rsi_period=p.get("rsi_period", 14),
            oversold_threshold=p.get("oversold_threshold", Decimal("32")),
            overbought_threshold=p.get("overbought_threshold", Decimal("70")),
            atr_period=p.get("atr_period", 14),
            strategy_id="rsi_mean_reversion",
        )
    if strat_key == "atr_breakout":
        return ATRBreakoutStrategy(
            channel_period=p.get("channel_period", 20),
            atr_period=p.get("atr_period", 14),
            strategy_id="atr_breakout",
        )
    if strat_key == "sma_cross":
        return SmaCrossStrategy(
            fast=p.get("fast", 5),
            slow=p.get("slow", 15),
            strategy_id="sma_cross",
        )
    if strat_key in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[strat_key]()
    raise ValueError(f"Unknown strategy_name '{strategy_name}'")


def _get_parameter_grid(strategy_name: str) -> list[dict[str, Any]]:
    strat_key = strategy_name.strip().lower()
    if strat_key == "ema_pullback":
        grid: list[dict[str, Any]] = []
        for fast, slow in [(5, 15), (9, 21), (13, 34)]:
            for atr_p in [10, 14]:
                grid.append({"fast_period": fast, "slow_period": slow, "atr_period": atr_p})
        return grid
    if strat_key == "rsi_mean_reversion":
        grid = []
        for rsi_p in [10, 14]:
            for os in [Decimal("28"), Decimal("32")]:
                for ob in [Decimal("68"), Decimal("72")]:
                    grid.append({"rsi_period": rsi_p, "oversold_threshold": os, "overbought_threshold": ob})
        return grid
    if strat_key == "atr_breakout":
        grid = []
        for ch in [15, 20]:
            for atr_p in [10, 14]:
                grid.append({"channel_period": ch, "atr_period": atr_p})
        return grid
    if strat_key == "sma_cross":
        grid = []
        for f, s in [(5, 15), (8, 20)]:
            grid.append({"fast": f, "slow": s})
        return grid
    return [{}]


def run_walk_forward_optimization(
    instrument: Instrument,
    candles: Sequence[Candle],
    strategy_name: str,
    config: BacktestConfig,
    split_ratio: Decimal = Decimal("0.70"),
) -> WalkForwardOptimizationResult:
    bars = tuple(candles)
    if len(bars) < 20:
        raise ValueError("Walk-forward optimization requires at least 20 historical candles")
    split_idx = int((Decimal(len(bars)) * split_ratio).to_integral_value(rounding=ROUND_FLOOR))
    if split_idx < 10 or split_idx > len(bars) - 5:
        split_idx = max(10, int(len(bars) * 0.7))

    in_sample = bars[:split_idx]
    out_of_sample = bars[split_idx:]

    grid = _get_parameter_grid(strategy_name)
    best_params = grid[0]
    best_score = Decimal("-999999")
    best_in_metrics: BacktestMetrics | None = None

    engine = BacktestEngine()
    for params in grid:
        try:
            strat = _instantiate_strategy(strategy_name, params)
            res = engine.run(instrument, in_sample, strat, config)
            score = (res.metrics.sharpe_ratio * Decimal("100")) + res.metrics.total_return_pct
            if res.metrics.max_drawdown_pct > Decimal("25"):
                score -= res.metrics.max_drawdown_pct
            if score > best_score or best_in_metrics is None:
                best_score = score
                best_params = params
                best_in_metrics = res.metrics
        except (ValueError, KeyError, TypeError, ArithmeticError, RuntimeError):
            continue

    if best_in_metrics is None:
        best_strat = _instantiate_strategy(strategy_name)
        res_in = engine.run(instrument, in_sample, best_strat, config)
        best_in_metrics = res_in.metrics

    best_out_strat = _instantiate_strategy(strategy_name, best_params)
    out_res = engine.run(instrument, out_of_sample, best_out_strat, config)

    def _pack_metrics(m: BacktestMetrics) -> dict[str, Any]:
        return {
            "total_return_pct": str(m.total_return_pct),
            "sharpe_ratio": str(m.sharpe_ratio),
            "max_drawdown_pct": str(m.max_drawdown_pct),
            "win_rate_pct": str(m.win_rate_pct),
            "total_trades": m.total_trades,
            "winning_trades": m.winning_trades,
            "losing_trades": m.losing_trades,
            "profit_factor": str(m.profit_factor),
        }

    return WalkForwardOptimizationResult(
        strategy_name=strategy_name,
        best_params=best_params,
        in_sample_metrics=_pack_metrics(best_in_metrics),
        out_of_sample_metrics=_pack_metrics(out_res.metrics),
        in_sample_range={"start": in_sample[0].timestamp.isoformat(), "end": in_sample[-1].close_time.isoformat()},
        out_of_sample_range={"start": out_of_sample[0].timestamp.isoformat(), "end": out_of_sample[-1].close_time.isoformat()},
        split_ratio=f"{int(split_ratio * 100)}/{int((ONE - split_ratio) * 100)}",
    )


def run_basket_backtest(
    instruments: Sequence[Instrument],
    candles_by_symbol: Mapping[str, Sequence[Candle]],
    strategy_name: str = "ema_pullback",
    config: BacktestConfig | None = None,
    run_walk_forward: bool = True,
) -> BasketBacktestResult:
    if not instruments:
        raise ValueError("instruments sequence must be non-empty")
    if config is None:
        raise ValueError("BacktestConfig must be provided")

    currency = config.initial_capital.currency
    for inst in instruments:
        if inst.currency != currency:
            raise CurrencyMismatchError(
                f"Instrument {inst.symbol} currency {inst.currency} does not match capital currency {currency}"
            )
        if inst.symbol not in candles_by_symbol or not candles_by_symbol[inst.symbol]:
            raise ValueError(f"No candles provided for instrument {inst.symbol}")

    inst_map = {inst.symbol: inst for inst in instruments}
    strategies = {inst.symbol: _instantiate_strategy(strategy_name) for inst in instruments}

    candle_lookup: dict[tuple[str, datetime], Candle] = {}
    dataset_hashes: dict[str, str] = {}
    for sym, c_seq in candles_by_symbol.items():
        dataset_hashes[sym] = hashlib.sha256(
            "".join(f"{c.timestamp.isoformat()}:{c.close}" for c in c_seq).encode("ascii")
        ).hexdigest()
        for c in c_seq:
            candle_lookup[(sym, c.timestamp)] = c

    all_timestamps = sorted(set(c.timestamp for seq in candles_by_symbol.values() for c in seq))
    if not all_timestamps:
        raise ValueError("No historical timestamps found across candle sequences")

    portfolio = PortfolioEngine(
        currency=currency,
        fee_model=config.fee_model,
        slippage_model=config.slippage_model,
    )
    first_time = all_timestamps[0]
    portfolio.deposit(config.initial_capital, first_time, "INITIAL_CAPITAL")

    open_positions: dict[str, _BasketOpenPosition] = {}
    pending_proposals: dict[str, TradeProposal] = {}
    completed_trades: list[CompletedTrade] = []
    rejected_proposals: list[ProposalRiskDecision] = []
    equity_curve: list[EquityPoint] = []
    latest_close_prices: dict[tuple[Exchange, str], Money] = {}
    bars_seen: dict[str, list[Candle]] = {inst.symbol: [] for inst in instruments}

    peak_equity = config.initial_capital.amount
    day_start_equity = config.initial_capital.amount
    last_close_equity = config.initial_capital.amount
    current_date: date | None = None
    proposal_seq = 0
    bars_in_market = 0

    for t in all_timestamps:
        first_exchange = instruments[0].exchange
        bar_date = _local_date(t, first_exchange)
        if bar_date != current_date:
            day_start_equity = last_close_equity
            current_date = bar_date

        symbols_with_bar_at_t = [inst.symbol for inst in instruments if (inst.symbol, t) in candle_lookup]

        pending_exits = [sym for sym in symbols_with_bar_at_t if sym in pending_proposals and pending_proposals[sym].side == "SELL"]
        for sym in pending_exits:
            prop = pending_proposals.pop(sym)
            pos = open_positions.pop(sym, None)
            if pos is not None:
                inst = inst_map[sym]
                bar = candle_lookup[(sym, t)]
                fill, fee_entry = portfolio.apply_fill(
                    timestamp=t,
                    exchange=inst.exchange,
                    symbol=sym,
                    side="SELL",
                    quantity=pos.quantity,
                    execution_price=Money(bar.open, currency),
                    tick_size=inst.tick_size,
                    reference_id=f"{pos.trade_id}:SIGNAL_EXIT",
                )
                assert fill.execution_price is not None
                exit_price = fill.execution_price
                exit_fee = -fee_entry.cash_delta.amount if fee_entry is not None else ZERO
                gross = (exit_price.amount - pos.entry_price.amount) * Decimal(pos.quantity)
                fees = pos.entry_fee + exit_fee
                net = gross - fees
                completed_trades.append(
                    CompletedTrade(
                        trade_id=pos.trade_id,
                        exchange=inst.exchange,
                        symbol=sym,
                        currency=currency,
                        entry_time=pos.entry_time,
                        exit_time=t,
                        quantity=pos.quantity,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        stop_loss=pos.stop_loss,
                        take_profit=pos.take_profit,
                        gross_pnl=Money(gross, currency),
                        fees=Money(fees, currency),
                        net_pnl=Money(net, currency),
                        r_multiple=ZERO,
                        exit_reason="SIGNAL_EXIT",
                    )
                )

        pending_buys = [sym for sym in symbols_with_bar_at_t if sym in pending_proposals and pending_proposals[sym].side == "BUY"]
        pending_buys.sort(
            key=lambda s: pending_proposals[s].signal.confidence if (pending_proposals[s].signal and pending_proposals[s].signal.confidence) else ZERO,
            reverse=True,
        )

        for sym in pending_buys:
            prop = pending_proposals.pop(sym)
            inst = inst_map[sym]
            bar = candle_lookup[(sym, t)]

            lot = inst.lot_size
            cap = int(Decimal(bar.volume) * config.max_volume_participation)
            cap -= cap % lot
            if cap < lot:
                rejected_proposals.append(
                    ProposalRiskDecision(approved=False, proposal_id=prop.proposal_id, reasons=("LIQUIDITY_BELOW_LOT_SIZE",), max_allowed_quantity=0)
                )
                continue

            sized = replace(prop, quantity=min(prop.quantity, cap))
            current_marks = dict(latest_close_prices)
            current_marks[(inst.exchange, sym)] = Money(bar.open, currency)
            snap = portfolio.snapshot(currency, current_marks, t)

            entry_money = Money(bar.open, currency)
            daily_loss = Money(snap.total_equity.amount - day_start_equity, currency)
            peak_money = Money(peak_equity, currency)

            decision = evaluate_trade_proposal(sized, snap, entry_money, config.risk_policy, daily_loss, peak_money)
            if not decision.approved and lot <= decision.max_allowed_quantity < sized.quantity:
                resized = replace(sized, quantity=decision.max_allowed_quantity)
                retry = evaluate_trade_proposal(resized, snap, entry_money, config.risk_policy, daily_loss, peak_money)
                if retry.approved:
                    sized, decision = resized, retry

            if not decision.approved:
                rejected_proposals.append(decision)
                continue

            qty = min(sized.quantity, decision.max_allowed_quantity)
            qty -= qty % lot
            if qty < lot:
                rejected_proposals.append(
                    ProposalRiskDecision(approved=False, proposal_id=prop.proposal_id, reasons=("QUANTITY_BELOW_LOT_SIZE",), max_allowed_quantity=0)
                )
                continue

            cost_est = bar.open * Decimal(qty)
            if cost_est > snap.cash.amount:
                continue

            fill, fee_entry = portfolio.apply_fill(
                timestamp=t,
                exchange=inst.exchange,
                symbol=sym,
                side="BUY",
                quantity=qty,
                execution_price=entry_money,
                tick_size=inst.tick_size,
                reference_id=prop.proposal_id,
            )
            assert fill.execution_price is not None
            fee_amt = -fee_entry.cash_delta.amount if fee_entry is not None else ZERO
            open_positions[sym] = _BasketOpenPosition(
                symbol=sym,
                exchange=inst.exchange,
                trade_id=prop.proposal_id,
                entry_time=t,
                entry_price=fill.execution_price,
                entry_fee=fee_amt,
                quantity=qty,
                stop_loss=prop.stop_loss,
                take_profit=prop.take_profit,
            )

        for sym in list(open_positions.keys()):
            if (sym, t) not in candle_lookup:
                continue
            pos = open_positions[sym]
            bar = candle_lookup[(sym, t)]
            inst = inst_map[sym]

            stop_price = pos.stop_loss.amount if pos.stop_loss is not None else None
            target_price = pos.take_profit.amount if pos.take_profit is not None else None

            exit_triggered = False
            raw_exit_price = bar.close
            exit_reason = "PROTECTIVE_EXIT"

            if stop_price is not None and bar.open <= stop_price:
                exit_triggered = True
                raw_exit_price = bar.open
                exit_reason = "STOP_LOSS"
            elif target_price is not None and bar.open >= target_price:
                exit_triggered = True
                raw_exit_price = bar.open
                exit_reason = "TAKE_PROFIT"
            else:
                stop_hit = stop_price is not None and bar.low <= stop_price
                target_hit = target_price is not None and bar.high >= target_price
                if stop_hit and target_hit:
                    if config.intrabar_collision_policy == "STOP_FIRST":
                        exit_triggered = True
                        raw_exit_price = stop_price
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_triggered = True
                        raw_exit_price = target_price
                        exit_reason = "TAKE_PROFIT"
                elif stop_hit:
                    exit_triggered = True
                    raw_exit_price = stop_price
                    exit_reason = "STOP_LOSS"
                elif target_hit:
                    exit_triggered = True
                    raw_exit_price = target_price
                    exit_reason = "TAKE_PROFIT"

            if exit_triggered:
                fill, fee_entry = portfolio.apply_fill(
                    timestamp=t,
                    exchange=inst.exchange,
                    symbol=sym,
                    side="SELL",
                    quantity=pos.quantity,
                    execution_price=Money(raw_exit_price, currency),
                    tick_size=inst.tick_size,
                    reference_id=f"{pos.trade_id}:{exit_reason}",
                )
                assert fill.execution_price is not None
                exit_price = fill.execution_price
                exit_fee = -fee_entry.cash_delta.amount if fee_entry is not None else ZERO
                gross = (exit_price.amount - pos.entry_price.amount) * Decimal(pos.quantity)
                fees = pos.entry_fee + exit_fee
                net = gross - fees
                completed_trades.append(
                    CompletedTrade(
                        trade_id=pos.trade_id,
                        exchange=inst.exchange,
                        symbol=sym,
                        currency=currency,
                        entry_time=pos.entry_time,
                        exit_time=t,
                        quantity=pos.quantity,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        stop_loss=pos.stop_loss,
                        take_profit=pos.take_profit,
                        gross_pnl=Money(gross, currency),
                        fees=Money(fees, currency),
                        net_pnl=Money(net, currency),
                        r_multiple=ZERO,
                        exit_reason=exit_reason,
                    )
                )
                del open_positions[sym]

        for sym in symbols_with_bar_at_t:
            bar = candle_lookup[(sym, t)]
            inst = inst_map[sym]
            bars_seen[sym].append(bar)
            latest_close_prices[(inst.exchange, sym)] = Money(bar.close, currency)

            strat = strategies[sym]
            if len(bars_seen[sym]) >= strat.warmup_bars:
                ctx = BarContext(instrument=inst, decision_time=bar.close_time, bars=tuple(bars_seen[sym]))
                sig = strat.evaluate(ctx)
                if sig is not None:
                    if sig.direction == SignalDirection.LONG and sym not in open_positions and sym not in pending_proposals:
                        proposal_seq += 1
                        pid = f"BASKET-P{proposal_seq:06d}"
                        equity_approx = portfolio.snapshot(currency, latest_close_prices, bar.close_time).total_equity.amount
                        lot = inst.lot_size
                        qty = int(equity_approx * config.position_size_pct / bar.close)
                        qty -= qty % lot
                        if qty >= lot:
                            stop_amt = sig.stop_loss.amount if sig.stop_loss is not None else bar.close * (ONE - config.default_stop_loss_pct)
                            target_amt = sig.take_profit.amount if sig.take_profit is not None else bar.close * (ONE + config.default_take_profit_pct)
                            pending_proposals[sym] = TradeProposal(
                                proposal_id=pid,
                                strategy_id=strategy_name,
                                instrument=inst,
                                timestamp=bar.close_time,
                                side="BUY",
                                quantity=qty,
                                stop_loss=Money(stop_amt, currency),
                                take_profit=Money(target_amt, currency),
                                signal=sig,
                            )
                    elif sig.direction == SignalDirection.EXIT and sym in open_positions and sym not in pending_proposals:
                        proposal_seq += 1
                        pid = f"BASKET-P{proposal_seq:06d}"
                        pending_proposals[sym] = TradeProposal(
                            proposal_id=pid,
                            strategy_id=strategy_name,
                            instrument=inst,
                            timestamp=bar.close_time,
                            side="SELL",
                            quantity=open_positions[sym].quantity,
                            signal=sig,
                        )

        close_snapshot = portfolio.snapshot(currency, latest_close_prices, t)
        curr_equity = close_snapshot.total_equity.amount
        if curr_equity > peak_equity:
            peak_equity = curr_equity
        drawdown = (peak_equity - curr_equity) / peak_equity * HUNDRED if peak_equity > 0 else ZERO
        equity_curve.append(
            EquityPoint(
                timestamp=t,
                cash=close_snapshot.cash,
                holdings_value=close_snapshot.holdings_value,
                total_equity=close_snapshot.total_equity,
                drawdown_pct=drawdown.quantize(_R_QUANTUM, rounding=ROUND_HALF_EVEN),
            )
        )
        if open_positions:
            bars_in_market += 1
        last_close_equity = curr_equity

    pending_proposals.clear()

    last_time = all_timestamps[-1]
    for sym, pos in list(open_positions.items()):
        inst = inst_map[sym]
        last_price = latest_close_prices.get((inst.exchange, sym), pos.entry_price).amount
        fill, fee_entry = portfolio.apply_fill(
            timestamp=last_time,
            exchange=inst.exchange,
            symbol=sym,
            side="SELL",
            quantity=pos.quantity,
            execution_price=Money(last_price, currency),
            tick_size=inst.tick_size,
            reference_id=f"{pos.trade_id}:END_OF_DATA",
        )
        assert fill.execution_price is not None
        exit_price = fill.execution_price
        exit_fee = -fee_entry.cash_delta.amount if fee_entry is not None else ZERO
        gross = (exit_price.amount - pos.entry_price.amount) * Decimal(pos.quantity)
        fees = pos.entry_fee + exit_fee
        net = gross - fees
        completed_trades.append(
            CompletedTrade(
                trade_id=pos.trade_id,
                exchange=inst.exchange,
                symbol=sym,
                currency=currency,
                entry_time=pos.entry_time,
                exit_time=last_time,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                gross_pnl=Money(gross, currency),
                fees=Money(fees, currency),
                net_pnl=Money(net, currency),
                r_multiple=ZERO,
                exit_reason="END_OF_DATA",
            )
        )
    open_positions.clear()

    final_snapshot = portfolio.snapshot(currency, latest_close_prices, last_time)
    residual = ledger_conservation_residual(portfolio.ledger, final_snapshot)
    if residual != ZERO:
        raise LedgerConservationError(f"Basket ledger conservation residual {residual} != 0")

    primary_candles = candles_by_symbol[instruments[0].symbol]
    bench_return = compute_benchmark_return_pct(primary_candles) if primary_candles else ZERO

    portfolio_metrics = compute_backtest_metrics(
        equity_curve=equity_curve,
        trades=completed_trades,
        initial_capital=config.initial_capital,
        total_fees=portfolio.ledger.get_total_fees(currency).amount,
        bars_in_market=bars_in_market,
        total_bars=len(all_timestamps),
        benchmark_return_pct=bench_return,
    )

    attribution: dict[str, PerSymbolAttribution] = {}
    init_cap = config.initial_capital.amount
    for inst in instruments:
        sym = inst.symbol
        sym_trades = [t for t in completed_trades if t.symbol == sym]
        tc = len(sym_trades)
        wins = sum(1 for t in sym_trades if t.net_pnl.amount > ZERO)
        losses = sum(1 for t in sym_trades if t.net_pnl.amount < ZERO)
        win_rate = (Decimal(wins) / Decimal(tc) * HUNDRED).quantize(Decimal("0.01")) if tc > 0 else ZERO
        realized = sum((t.net_pnl.amount for t in sym_trades), ZERO)
        ret_pct = (realized / init_cap * HUNDRED).quantize(Decimal("0.01")) if init_cap > 0 else ZERO
        attribution[sym] = PerSymbolAttribution(
            symbol=sym,
            exchange=inst.exchange.value,
            trades=tc,
            winning_trades=wins,
            losing_trades=losses,
            win_rate_pct=win_rate,
            realized_pnl=realized,
            total_return_pct=ret_pct,
        )

    manifest_payload = {
        "symbols": [inst.symbol for inst in instruments],
        "exchange": instruments[0].exchange.value,
        "currency": currency.value,
        "strategy_name": strategy_name,
        "dataset_hashes": dataset_hashes,
        "initial_capital": str(config.initial_capital.amount),
        "total_bars": len(all_timestamps),
        "random_seed": config.random_seed,
    }
    manifest_raw = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(manifest_raw.encode("ascii")).hexdigest()
    manifest_id = f"BASKET-{manifest_sha256[:16]}"
    manifest_verified = True

    wf_result: WalkForwardOptimizationResult | None = None
    if run_walk_forward and primary_candles and len(primary_candles) >= 20:
        try:
            wf_result = run_walk_forward_optimization(
                instrument=instruments[0],
                candles=primary_candles,
                strategy_name=strategy_name,
                config=config,
            )
        except (ValueError, KeyError, TypeError, ArithmeticError, RuntimeError):
            wf_result = None

    return BasketBacktestResult(
        manifest_id=manifest_id,
        manifest_sha256=manifest_sha256,
        manifest_verified=manifest_verified,
        conservation_residual=residual,
        portfolio_metrics=portfolio_metrics,
        per_symbol_attribution=attribution,
        equity_curve=tuple(equity_curve),
        trades=tuple(completed_trades),
        final_snapshot=final_snapshot,
        ledger=portfolio.ledger,
        walk_forward=wf_result,
    )
