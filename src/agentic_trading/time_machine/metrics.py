"""Deterministic Decimal performance metrics for completed backtests."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from agentic_trading.market_data.instruments import Money
from agentic_trading.market_data.models import Candle

if TYPE_CHECKING:
    from agentic_trading.time_machine.engine import CompletedTrade, EquityPoint

ZERO = Decimal("0")
HUNDRED = Decimal("100")
_QUANTUM = Decimal("0.0001")
_SECONDS_PER_YEAR = Decimal("31557600")
_MIN_ANNUALIZATION_YEARS = Decimal("1") / Decimal("365.25")


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: Decimal
    cagr_pct: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    max_drawdown_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: Decimal
    profit_factor: Decimal
    expectancy_r: Decimal
    average_win: Decimal
    average_loss: Decimal
    total_fees: Decimal
    exposure_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def compute_benchmark_return_pct(candles: Sequence[Candle]) -> Decimal:
    if not candles:
        raise ValueError("candles must be non-empty")
    first_open = candles[0].open
    if first_open <= 0:
        raise ValueError("first open must be strictly positive")
    return _q((candles[-1].close - first_open) / first_open * HUNDRED)


def _max_drawdown_pct(equities: Sequence[Decimal]) -> Decimal:
    peak = equities[0]
    worst = ZERO
    for equity in equities[1:]:
        if equity > peak:
            peak = equity
        if peak > 0:
            worst = max(worst, (peak - equity) / peak * HUNDRED)
    return worst


def _years(equity_curve: Sequence[EquityPoint]) -> Decimal:
    if len(equity_curve) < 2:
        return ZERO
    span = equity_curve[-1].timestamp - equity_curve[0].timestamp
    return Decimal(span.days * 86400 + span.seconds) / _SECONDS_PER_YEAR


def _cagr_pct(initial: Decimal, final: Decimal, years: Decimal) -> Decimal:
    if years < _MIN_ANNUALIZATION_YEARS:
        return ZERO
    if final <= 0:
        return -HUNDRED
    try:
        return (((final / initial) ** (Decimal("1") / years)) - Decimal("1")) * HUNDRED
    except ArithmeticError:
        return ZERO


def _risk_ratios(returns: Sequence[Decimal], years: Decimal) -> tuple[Decimal, Decimal]:
    count = len(returns)
    if count < 2 or years <= 0:
        return ZERO, ZERO
    periods_per_year = Decimal(count - 1) / years
    annualizer = periods_per_year.sqrt()
    mean = _mean(returns)
    variance = sum(((r - mean) ** 2 for r in returns), ZERO) / Decimal(count - 1)
    stdev = variance.sqrt()
    sharpe = mean / stdev * annualizer if stdev > 0 else ZERO
    downside = sum((min(r, ZERO) ** 2 for r in returns), ZERO) / Decimal(count)
    downside_dev = downside.sqrt()
    sortino = mean / downside_dev * annualizer if downside_dev > 0 else ZERO
    return sharpe, sortino


def compute_backtest_metrics(
    equity_curve: Sequence[EquityPoint],
    trades: Sequence[CompletedTrade],
    initial_capital: Money,
    total_fees: Decimal,
    bars_in_market: int,
    total_bars: int,
    benchmark_return_pct: Decimal,
) -> BacktestMetrics:
    initial = initial_capital.amount
    if initial <= 0:
        raise ValueError("initial_capital must be strictly positive")
    if total_bars < 0 or bars_in_market < 0 or bars_in_market > total_bars:
        raise ValueError("bars_in_market must be within [0, total_bars]")

    equities = [initial] + [point.total_equity.amount for point in equity_curve]
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]
    final = equities[-1]
    total_return = (final - initial) / initial * HUNDRED
    years = _years(equity_curve)
    sharpe, sortino = _risk_ratios(returns, years)

    wins = [t.net_pnl.amount for t in trades if t.net_pnl.amount > 0]
    losses = [t.net_pnl.amount for t in trades if t.net_pnl.amount < 0]
    gross_loss = abs(sum(losses, ZERO))
    profit_factor = sum(wins, ZERO) / gross_loss if gross_loss > 0 else ZERO
    total_trades = len(trades)
    win_rate = Decimal(len(wins)) / Decimal(total_trades) * HUNDRED if total_trades else ZERO
    exposure = Decimal(bars_in_market) / Decimal(total_bars) * HUNDRED if total_bars else ZERO

    return BacktestMetrics(
        total_return_pct=_q(total_return),
        cagr_pct=_q(_cagr_pct(initial, final, years)),
        sharpe_ratio=_q(sharpe),
        sortino_ratio=_q(sortino),
        max_drawdown_pct=_q(_max_drawdown_pct(equities)),
        total_trades=total_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate_pct=_q(win_rate),
        profit_factor=_q(profit_factor),
        expectancy_r=_q(_mean([t.r_multiple for t in trades])),
        average_win=_q(_mean(wins)),
        average_loss=_q(_mean(losses)),
        total_fees=_q(total_fees),
        exposure_pct=_q(exposure),
        benchmark_return_pct=_q(benchmark_return_pct),
        excess_return_pct=_q(total_return - benchmark_return_pct),
    )
