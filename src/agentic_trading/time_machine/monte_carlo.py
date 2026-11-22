"""Seeded bootstrap resampling of realized trade outcomes."""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from agentic_trading.market_data.instruments import CurrencyMismatchError, Money
from agentic_trading.time_machine.engine import CompletedTrade

ZERO = Decimal("0")
HUNDRED = Decimal("100")
_QUANTUM = Decimal("0.0001")
_DISCLAIMER = (
    "Simulated bootstrap scenarios from historical trade outcomes; "
    "not a guarantee of future performance."
)


@dataclass(frozen=True)
class MonteCarloSummary:
    seed: int
    iterations: int
    trade_count: int
    initial_capital: Money
    return_pct_p05: Decimal
    return_pct_p25: Decimal
    return_pct_p50: Decimal
    return_pct_p75: Decimal
    return_pct_p95: Decimal
    max_drawdown_pct_p50: Decimal
    max_drawdown_pct_p95: Decimal
    probability_of_loss_pct: Decimal
    probability_of_ruin_pct: Decimal
    disclaimer: str = _DISCLAIMER


def _quantile(sorted_values: Sequence[Decimal], q: Decimal) -> Decimal:
    position = Decimal(len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    value = sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (
        position - Decimal(lower)
    )
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def run_seeded_monte_carlo(
    trades: Sequence[CompletedTrade],
    initial_capital: Money,
    iterations: int = 1000,
    seed: int = 42,
    ruin_drawdown_pct: Decimal = Decimal("25"),
) -> MonteCarloSummary:
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ValueError("iterations must be an integer >= 1")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    if not isinstance(initial_capital, Money) or initial_capital.amount <= 0:
        raise ValueError("initial_capital must be Money with a strictly positive amount")
    if (
        isinstance(ruin_drawdown_pct, (bool, float))
        or not isinstance(ruin_drawdown_pct, Decimal)
        or not ruin_drawdown_pct.is_finite()
        or ruin_drawdown_pct <= 0
    ):
        raise ValueError("ruin_drawdown_pct must be a positive finite Decimal")
    outcomes = [t.net_pnl for t in trades]
    if not outcomes:
        zero_pct = ZERO.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
        return MonteCarloSummary(
            seed=seed,
            iterations=iterations,
            trade_count=0,
            initial_capital=initial_capital,
            return_pct_p05=zero_pct,
            return_pct_p25=zero_pct,
            return_pct_p50=zero_pct,
            return_pct_p75=zero_pct,
            return_pct_p95=zero_pct,
            max_drawdown_pct_p50=zero_pct,
            max_drawdown_pct_p95=zero_pct,
            probability_of_loss_pct=zero_pct,
            probability_of_ruin_pct=zero_pct,
        )
    if any(m.currency != initial_capital.currency for m in outcomes):
        raise CurrencyMismatchError("trade currency does not match initial_capital currency")

    pnls = [m.amount for m in outcomes]
    count = len(pnls)
    start = initial_capital.amount
    rng = random.Random(seed)
    returns: list[Decimal] = []
    drawdowns: list[Decimal] = []
    losses = 0
    ruins = 0
    for _ in range(iterations):
        equity = start
        peak = start
        worst = ZERO
        ruined = False
        for _draw in range(count):
            equity += pnls[rng.randrange(count)]
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * HUNDRED
            if drawdown > worst:
                worst = drawdown
            if equity <= 0 or drawdown >= ruin_drawdown_pct:
                ruined = True
        returns.append((equity - start) / start * HUNDRED)
        drawdowns.append(worst)
        if equity < start:
            losses += 1
        if ruined:
            ruins += 1

    returns.sort()
    drawdowns.sort()
    total = Decimal(iterations)
    return MonteCarloSummary(
        seed=seed,
        iterations=iterations,
        trade_count=count,
        initial_capital=initial_capital,
        return_pct_p05=_quantile(returns, Decimal("0.05")),
        return_pct_p25=_quantile(returns, Decimal("0.25")),
        return_pct_p50=_quantile(returns, Decimal("0.50")),
        return_pct_p75=_quantile(returns, Decimal("0.75")),
        return_pct_p95=_quantile(returns, Decimal("0.95")),
        max_drawdown_pct_p50=_quantile(drawdowns, Decimal("0.50")),
        max_drawdown_pct_p95=_quantile(drawdowns, Decimal("0.95")),
        probability_of_loss_pct=(Decimal(losses) / total * HUNDRED).quantize(
            _QUANTUM, rounding=ROUND_HALF_EVEN
        ),
        probability_of_ruin_pct=(Decimal(ruins) / total * HUNDRED).quantize(
            _QUANTUM, rounding=ROUND_HALF_EVEN
        ),
    )
