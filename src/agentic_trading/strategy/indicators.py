"""Pure deterministic technical indicator functions with explicit warmup verification."""
from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from agentic_trading.market_data.models import Candle


def sma(candles: Sequence[Candle], period: int) -> Decimal | None:
    """Calculate Simple Moving Average over close prices of the specified period."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period}")

    if len(candles) < period:
        return None

    subset = candles[-period:]
    total = sum((c.close for c in subset), Decimal("0"))
    return total / Decimal(period)


def ema(candles: Sequence[Candle], period: int) -> Decimal | None:
    """Calculate Exponential Moving Average over close prices seeded with initial SMA."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period}")

    if len(candles) < period:
        return None

    initial_slice = candles[:period]
    val = sum((c.close for c in initial_slice), Decimal("0")) / Decimal(period)
    multiplier = Decimal("2") / Decimal(period + 1)

    for c in candles[period:]:
        val = (c.close - val) * multiplier + val

    return val


def rsi(candles: Sequence[Candle], period: int = 14) -> Decimal | None:
    """Calculate Relative Strength Index using Wilder's smoothed average technique."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period}")

    if len(candles) < period + 1:
        return None

    changes: list[Decimal] = []
    for i in range(1, len(candles)):
        changes.append(candles[i].close - candles[i - 1].close)

    first_gains = [max(Decimal("0"), ch) for ch in changes[:period]]
    first_losses = [max(Decimal("0"), -ch) for ch in changes[:period]]

    avg_gain = sum(first_gains, Decimal("0")) / Decimal(period)
    avg_loss = sum(first_losses, Decimal("0")) / Decimal(period)

    period_minus_one = Decimal(period - 1)
    period_dec = Decimal(period)

    for ch in changes[period:]:
        gain = max(Decimal("0"), ch)
        loss = max(Decimal("0"), -ch)
        avg_gain = (avg_gain * period_minus_one + gain) / period_dec
        avg_loss = (avg_loss * period_minus_one + loss) / period_dec

    if avg_gain == Decimal("0") and avg_loss == Decimal("0"):
        return Decimal("50")

    if avg_loss == Decimal("0"):
        return Decimal("100")

    rs = avg_gain / avg_loss
    res = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
    return res.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def atr(candles: Sequence[Candle], period: int = 14) -> Decimal | None:
    """Calculate Average True Range measuring historical price volatility."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period}")

    if len(candles) < period + 1:
        return None

    true_ranges: list[Decimal] = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev_close = candles[i - 1].close
        h_l = curr.high - curr.low
        h_pc = abs(curr.high - prev_close)
        l_pc = abs(curr.low - prev_close)
        true_ranges.append(max(h_l, h_pc, l_pc))

    curr_atr = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    period_minus_one = Decimal(period - 1)
    period_dec = Decimal(period)

    for tr in true_ranges[period:]:
        curr_atr = (curr_atr * period_minus_one + tr) / period_dec

    return curr_atr.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
