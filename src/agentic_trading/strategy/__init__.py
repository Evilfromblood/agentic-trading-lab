"""Strategy domain interfaces, bar context look-ahead guards, and quantitative strategy library."""
from __future__ import annotations

from agentic_trading.strategy.contracts import (
    BarContext,
    Signal,
    SignalDirection,
    Strategy,
    TradeProposal,
)
from agentic_trading.strategy.indicators import (
    atr,
    ema,
    rsi,
    sma,
)
from agentic_trading.strategy.library import (
    STRATEGY_REGISTRY,
    ATRBreakoutStrategy,
    EMAPullbackStrategy,
    RSIMeanReversionStrategy,
)

__all__ = [
    "ATRBreakoutStrategy",
    "BarContext",
    "EMAPullbackStrategy",
    "RSIMeanReversionStrategy",
    "STRATEGY_REGISTRY",
    "Signal",
    "SignalDirection",
    "Strategy",
    "TradeProposal",
    "atr",
    "ema",
    "rsi",
    "sma",
]
