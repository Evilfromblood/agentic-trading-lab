"""Concrete deterministic quantitative trading strategies for the Time Machine backtest engine."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from agentic_trading.market_data.instruments import Money
from agentic_trading.strategy.contracts import (
    BarContext,
    Signal,
    SignalDirection,
    Strategy,
)
from agentic_trading.strategy.indicators import atr, ema, rsi


class EMAPullbackStrategy(Strategy):
    """Exponential Moving Average pullback strategy with dynamic ATR-based protective brackets."""

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        atr_period: int = 14,
        strategy_id: str = "ema_pullback",
    ) -> None:
        self.strategy_id = strategy_id
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.warmup_bars = max(slow_period, atr_period) + 2

    def evaluate(self, context: BarContext) -> Signal | None:
        if len(context.bars) < self.warmup_bars:
            return None

        fast_val = ema(context.bars, self.fast_period)
        slow_val = ema(context.bars, self.slow_period)
        atr_val = atr(context.bars, self.atr_period)

        if fast_val is None or slow_val is None:
            return None

        last_bar = context.bars[-1]
        currency = context.instrument.currency
        volatility = atr_val if (atr_val is not None and atr_val > Decimal("0")) else (last_bar.close * Decimal("0.02"))

        if fast_val > slow_val:
            pullback_tolerance = fast_val * Decimal("1.015")
            if last_bar.low <= pullback_tolerance and last_bar.close >= slow_val:
                stop_amount = max(Decimal("0.01"), last_bar.close - (volatility * Decimal("1.5")))
                target_amount = last_bar.close + (volatility * Decimal("3.0"))
                return Signal(
                    exchange=context.instrument.exchange,
                    symbol=context.instrument.symbol,
                    timestamp=context.decision_time,
                    direction=SignalDirection.LONG,
                    confidence=Decimal("0.85"),
                    stop_loss=Money(stop_amount, currency),
                    take_profit=Money(target_amount, currency),
                    rationale="Bullish EMA trend with pullback to fast average",
                )

        if fast_val < slow_val and last_bar.close < slow_val:
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.EXIT,
                confidence=Decimal("0.85"),
                rationale="Bearish EMA crossover exit signal",
            )

        return None


class RSIMeanReversionStrategy(Strategy):
    """Wilder RSI mean reversion strategy buying oversold dips with volatility stops."""

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: Decimal = Decimal("32"),
        overbought_threshold: Decimal = Decimal("70"),
        atr_period: int = 14,
        strategy_id: str = "rsi_mean_reversion",
    ) -> None:
        self.strategy_id = strategy_id
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.atr_period = atr_period
        self.warmup_bars = max(rsi_period, atr_period) + 2

    def evaluate(self, context: BarContext) -> Signal | None:
        if len(context.bars) < self.warmup_bars:
            return None

        rsi_val = rsi(context.bars, self.rsi_period)
        atr_val = atr(context.bars, self.atr_period)

        if rsi_val is None:
            return None

        last_bar = context.bars[-1]
        currency = context.instrument.currency
        volatility = atr_val if (atr_val is not None and atr_val > Decimal("0")) else (last_bar.close * Decimal("0.02"))

        if rsi_val <= self.oversold_threshold:
            stop_amount = max(Decimal("0.01"), last_bar.close - (volatility * Decimal("1.5")))
            target_amount = last_bar.close + (volatility * Decimal("2.5"))
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.LONG,
                confidence=Decimal("0.80"),
                stop_loss=Money(stop_amount, currency),
                take_profit=Money(target_amount, currency),
                rationale=f"Oversold Wilder RSI dip ({rsi_val:.1f}) mean reversion entry",
            )

        if rsi_val >= self.overbought_threshold:
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.EXIT,
                confidence=Decimal("0.80"),
                rationale=f"Overbought Wilder RSI ({rsi_val:.1f}) mean reversion exit",
            )

        return None


class ATRBreakoutStrategy(Strategy):
    """Donchian channel breakout strategy filtered by expanding Average True Range."""

    def __init__(
        self,
        channel_period: int = 20,
        atr_period: int = 14,
        strategy_id: str = "atr_breakout",
    ) -> None:
        self.strategy_id = strategy_id
        self.channel_period = channel_period
        self.atr_period = atr_period
        self.warmup_bars = max(channel_period, atr_period) + 2

    def evaluate(self, context: BarContext) -> Signal | None:
        if len(context.bars) < self.warmup_bars:
            return None

        prior_bars = context.bars[-(self.channel_period + 1) : -1]
        prior_high = max(b.high for b in prior_bars)
        prior_low = min(b.low for b in prior_bars)

        atr_val = atr(context.bars, self.atr_period)
        last_bar = context.bars[-1]
        currency = context.instrument.currency
        volatility = atr_val if (atr_val is not None and atr_val > Decimal("0")) else (last_bar.close * Decimal("0.02"))

        if last_bar.close > prior_high:
            stop_amount = max(Decimal("0.01"), last_bar.close - (volatility * Decimal("1.5")))
            target_amount = last_bar.close + (volatility * Decimal("3.0"))
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.LONG,
                confidence=Decimal("0.85"),
                stop_loss=Money(stop_amount, currency),
                take_profit=Money(target_amount, currency),
                rationale="Donchian upper channel breakout with expanding volatility",
            )

        if last_bar.close < prior_low:
            return Signal(
                exchange=context.instrument.exchange,
                symbol=context.instrument.symbol,
                timestamp=context.decision_time,
                direction=SignalDirection.EXIT,
                confidence=Decimal("0.85"),
                rationale="Donchian lower channel breakdown exit",
            )

        return None


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
        return None


STRATEGY_REGISTRY: dict[str, Callable[[], Strategy]] = {
    "ema_pullback": EMAPullbackStrategy,
    "rsi_mean_reversion": RSIMeanReversionStrategy,
    "atr_breakout": ATRBreakoutStrategy,
    "sma_cross": SmaCrossStrategy,
}
