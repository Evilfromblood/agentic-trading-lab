"""Strategy, indicator, bar context, and deterministic signal and proposal contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from agentic_trading.market_data.instruments import Instrument, Money
from agentic_trading.market_data.models import Candle, Exchange


class SignalDirection(str, Enum):
    """Directional intention emitted by a trading strategy."""

    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"
    FLAT = "FLAT"

    @classmethod
    def _missing_(cls, value: object) -> SignalDirection | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


@dataclass(frozen=True)
class BarContext:
    """Historical bar window passed to strategy evaluation, enforcing strict causal boundaries."""

    instrument: Instrument
    decision_time: datetime
    bars: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError(f"instrument must be an Instrument instance, got {type(self.instrument).__name__}")

        if not isinstance(self.decision_time, datetime):
            raise TypeError(f"decision_time must be a datetime, got {type(self.decision_time).__name__}")
        if self.decision_time.tzinfo is None or self.decision_time.tzinfo.utcoffset(self.decision_time) is None:
            raise ValueError("decision_time must be timezone-aware")

        if not isinstance(self.bars, tuple):
            object.__setattr__(self, "bars", tuple(self.bars))

        prev_candle: Candle | None = None
        for candle in self.bars:
            if not isinstance(candle, Candle):
                raise TypeError(f"All elements in bars must be Candle instances, got {type(candle).__name__}")
            if candle.exchange != self.instrument.exchange or candle.symbol != self.instrument.symbol:
                raise ValueError(
                    f"Bar {candle.exchange.value}:{candle.symbol} does not match context instrument "
                    f"{self.instrument.exchange.value}:{self.instrument.symbol}"
                )
            if candle.close_time > self.decision_time:
                raise ValueError(
                    f"Look-ahead violation: bar close {candle.close_time.isoformat()} is after "
                    f"decision_time {self.decision_time.isoformat()}"
                )
            if (
                candle.open <= Decimal("0")
                or candle.high <= Decimal("0")
                or candle.low <= Decimal("0")
                or candle.close <= Decimal("0")
            ):
                raise ValueError("Candle OHLC prices must be strictly positive")
            if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
                raise ValueError("Candle high must be >= max(open, close) and low <= min(open, close)")
            if candle.volume < 0:
                raise ValueError("Candle volume must be non-negative")
            if prev_candle is not None:
                if candle.interval != prev_candle.interval:
                    raise ValueError(f"Inconsistent interval in bars: {candle.interval} vs {prev_candle.interval}")
                if candle.timestamp <= prev_candle.timestamp:
                    raise ValueError(
                        f"Bars must have strictly increasing timestamps: "
                        f"{candle.timestamp.isoformat()} <= {prev_candle.timestamp.isoformat()}"
                    )
            prev_candle = candle


@dataclass(frozen=True)
class Signal:
    """Actionable directional signal produced by strategy analysis."""

    exchange: Exchange
    symbol: str
    timestamp: datetime
    direction: SignalDirection
    confidence: Decimal
    stop_loss: Money | None = None
    take_profit: Money | None = None
    rationale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())

        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError("timestamp must be timezone-aware")

        if not isinstance(self.direction, SignalDirection):
            raise TypeError(f"direction must be a SignalDirection enum, got {type(self.direction).__name__}")

        if (
            isinstance(self.confidence, (bool, float))
            or not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not (Decimal("0") <= self.confidence <= Decimal("1"))
        ):
            raise ValueError(f"confidence must be a finite Decimal in [0, 1], got {self.confidence}")

        if self.stop_loss is not None and not isinstance(self.stop_loss, Money):
            raise TypeError(f"stop_loss must be a Money instance, got {type(self.stop_loss).__name__}")

        if self.take_profit is not None and not isinstance(self.take_profit, Money):
            raise TypeError(f"take_profit must be a Money instance, got {type(self.take_profit).__name__}")

        if not isinstance(self.rationale, str):
            raise TypeError(f"rationale must be a string, got {type(self.rationale).__name__}")


@dataclass(frozen=True)
class TradeProposal:
    """Concrete order sizing and routing request submitted to the risk engine."""

    proposal_id: str
    strategy_id: str
    instrument: Instrument
    timestamp: datetime
    side: str
    quantity: int
    order_type: str = "MARKET"
    limit_price: Money | None = None
    stop_loss: Money | None = None
    take_profit: Money | None = None
    signal: Signal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id.strip():
            raise ValueError("proposal_id must be a non-empty string")
        if not isinstance(self.strategy_id, str) or not self.strategy_id.strip():
            raise ValueError("strategy_id must be a non-empty string")
        if not isinstance(self.instrument, Instrument):
            raise TypeError(f"instrument must be an Instrument instance, got {type(self.instrument).__name__}")

        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError("timestamp must be timezone-aware")

        clean_side = self.side.strip().upper() if isinstance(self.side, str) else ""
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side}")
        object.__setattr__(self, "side", clean_side)

        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError(f"quantity must be a positive integer, got {self.quantity}")

        clean_order_type = self.order_type.strip().upper() if isinstance(self.order_type, str) else ""
        if clean_order_type not in ("MARKET", "LIMIT"):
            raise ValueError(f"order_type must be MARKET or LIMIT, got {self.order_type}")
        object.__setattr__(self, "order_type", clean_order_type)

        if clean_order_type == "LIMIT":
            if self.limit_price is None:
                raise ValueError("limit_price is required for LIMIT order proposals")

        if self.limit_price is not None:
            if not isinstance(self.limit_price, Money):
                raise TypeError(f"limit_price must be a Money instance, got {type(self.limit_price).__name__}")
            if self.limit_price.currency != self.instrument.currency:
                raise ValueError(
                    f"limit_price currency {self.limit_price.currency} does not match instrument currency "
                    f"{self.instrument.currency}"
                )

        if self.stop_loss is not None:
            if not isinstance(self.stop_loss, Money):
                raise TypeError(f"stop_loss must be a Money instance, got {type(self.stop_loss).__name__}")
            if self.stop_loss.currency != self.instrument.currency:
                raise ValueError(
                    f"stop_loss currency {self.stop_loss.currency} does not match instrument currency "
                    f"{self.instrument.currency}"
                )

        if self.take_profit is not None:
            if not isinstance(self.take_profit, Money):
                raise TypeError(f"take_profit must be a Money instance, got {type(self.take_profit).__name__}")
            if self.take_profit.currency != self.instrument.currency:
                raise ValueError(
                    f"take_profit currency {self.take_profit.currency} does not match instrument currency "
                    f"{self.instrument.currency}"
                )

        if self.signal is not None and not isinstance(self.signal, Signal):
            raise TypeError(f"signal must be a Signal instance or None, got {type(self.signal).__name__}")


class Strategy(ABC):
    """Abstract interface defining strategy lifecycle and signal production."""

    strategy_id: str
    warmup_bars: int

    @abstractmethod
    def evaluate(self, context: BarContext) -> Signal | None:
        """Evaluate market context and emit directional trading signal or None."""
