"""Corporate actions modeling, symbol lineage resolution, and historical candle adjustment."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

from agentic_trading.market_data.instruments import Currency, CurrencyMismatchError, Money
from agentic_trading.market_data.models import Candle, Exchange


class CorporateActionType(str, Enum):
    """Types of corporate actions affecting pricing, capitalization, or identity."""

    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"

    @classmethod
    def _missing_(cls, value: object) -> CorporateActionType | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


@dataclass(frozen=True)
class CorporateAction:
    """Immutable specification of a discrete corporate action event."""

    exchange: Exchange
    symbol: str
    action_type: CorporateActionType
    effective_date: date
    adjustment_factor: Decimal = Decimal("1")
    cash_amount: Money | None = None
    new_symbol: str | None = None
    announcement_date: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")

        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", clean_symbol)

        if not isinstance(self.action_type, CorporateActionType):
            raise TypeError(f"action_type must be a CorporateActionType enum, got {type(self.action_type).__name__}")

        if not isinstance(self.effective_date, date):
            raise TypeError(f"effective_date must be a date, got {type(self.effective_date).__name__}")

        if self.announcement_date is not None:
            if not isinstance(self.announcement_date, date):
                raise TypeError(f"announcement_date must be a date, got {type(self.announcement_date).__name__}")
            if self.announcement_date > self.effective_date:
                raise ValueError(
                    f"announcement_date ({self.announcement_date}) cannot be after effective_date ({self.effective_date})"
                )

        if (
            isinstance(self.adjustment_factor, (bool, float))
            or not isinstance(self.adjustment_factor, Decimal)
            or not self.adjustment_factor.is_finite()
            or self.adjustment_factor <= 0
        ):
            raise ValueError(f"adjustment_factor must be a positive finite Decimal, got {self.adjustment_factor}")

        if self.action_type == CorporateActionType.SYMBOL_CHANGE:
            if not isinstance(self.new_symbol, str) or not self.new_symbol.strip():
                raise ValueError("new_symbol must be a non-empty string for SYMBOL_CHANGE actions")
            clean_new_symbol = self.new_symbol.strip().upper()
            if clean_new_symbol == clean_symbol:
                raise ValueError(f"new_symbol '{clean_new_symbol}' cannot be identical to current symbol")
            object.__setattr__(self, "new_symbol", clean_new_symbol)
        elif self.new_symbol is not None:
            clean_new = self.new_symbol.strip().upper()
            object.__setattr__(self, "new_symbol", clean_new)

        if self.cash_amount is not None:
            if not isinstance(self.cash_amount, Money):
                raise TypeError(f"cash_amount must be a Money instance, got {type(self.cash_amount).__name__}")
            expected_currency = Currency.INR if self.exchange in (Exchange.NSE, Exchange.BSE) else Currency.USD
            if self.cash_amount.currency != expected_currency:
                raise CurrencyMismatchError(
                    f"Cash amount currency {self.cash_amount.currency} does not match exchange {self.exchange} "
                    f"expected currency {expected_currency}"
                )


def resolve_symbol_lineage(
    exchange: Exchange,
    symbol: str,
    as_of_date: date,
    actions: Sequence[CorporateAction],
) -> str:
    """Deterministically trace SYMBOL_CHANGE lineage forward or backward with cycle detection."""
    if not isinstance(exchange, Exchange):
        raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")
    if not isinstance(as_of_date, date):
        raise TypeError(f"as_of_date must be a date, got {type(as_of_date).__name__}")

    clean_symbol = symbol.strip().upper()
    relevant_actions = [
        act
        for act in actions
        if act.exchange == exchange and act.action_type == CorporateActionType.SYMBOL_CHANGE and act.new_symbol
    ]

    adj: dict[str, set[str]] = {}
    undirected: dict[str, set[str]] = {}
    for act in relevant_actions:
        assert act.new_symbol is not None
        adj.setdefault(act.symbol, set()).add(act.new_symbol)
        undirected.setdefault(act.symbol, set()).add(act.new_symbol)
        undirected.setdefault(act.new_symbol, set()).add(act.symbol)

    component_nodes: set[str] = set()
    frontier = [clean_symbol]
    while frontier:
        curr = frontier.pop()
        if curr not in component_nodes:
            component_nodes.add(curr)
            frontier.extend(undirected.get(curr, set()) - component_nodes)

    color: dict[str, int] = {}

    for start in component_nodes:
        if start not in adj or color.get(start, 0) != 0:
            continue
        stack = [(start, iter(adj.get(start, ())))]
        color[start] = 1
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if child not in component_nodes:
                    continue
                if color.get(child, 0) == 1:
                    raise ValueError(f"Cyclic symbol change detected involving symbol '{child}'")
                if color.get(child, 0) == 0:
                    color[child] = 1
                    stack.append((child, iter(adj.get(child, ()))))
            except StopIteration:
                color[node] = 2
                stack.pop()

    current_symbol = clean_symbol
    traversal_path: set[str] = {current_symbol}

    while True:
        forward_candidates = [
            act
            for act in relevant_actions
            if act.symbol == current_symbol and act.effective_date <= as_of_date
        ]
        if not forward_candidates:
            break
        forward_candidates.sort(key=lambda a: a.effective_date)
        next_symbol = forward_candidates[0].new_symbol
        assert next_symbol is not None
        if next_symbol in traversal_path:
            raise ValueError(f"Cycle detected during forward symbol lineage resolution: {next_symbol}")
        current_symbol = next_symbol
        traversal_path.add(current_symbol)

    while True:
        backward_candidates = [
            act
            for act in relevant_actions
            if act.new_symbol == current_symbol and act.effective_date > as_of_date
        ]
        if not backward_candidates:
            break
        backward_candidates.sort(key=lambda a: a.effective_date, reverse=True)
        prev_symbol = backward_candidates[0].symbol
        if prev_symbol in traversal_path:
            raise ValueError(f"Cycle detected during backward symbol lineage resolution: {prev_symbol}")
        current_symbol = prev_symbol
        traversal_path.add(current_symbol)

    return current_symbol


def adjust_candles_for_corporate_actions(
    candles: Sequence[Candle],
    actions: Sequence[CorporateAction],
    tick_size: Decimal | None = None,
    as_of_date: date | None = None,
) -> tuple[Candle, ...]:
    """Adjust historical candles for corporate actions (splits, bonuses, dividends)."""
    if as_of_date is not None and not isinstance(as_of_date, date):
        raise TypeError(f"as_of_date must be a date, got {type(as_of_date).__name__}")

    if tick_size is not None:
        if (
            isinstance(tick_size, (bool, float))
            or not isinstance(tick_size, Decimal)
            or not tick_size.is_finite()
            or tick_size <= 0
        ):
            raise ValueError(f"tick_size must be a positive finite Decimal, got {tick_size}")

    adjusted_candles: list[Candle] = []

    for candle in candles:
        candle_date = candle.timestamp.date()
        matching_actions = [
            act
            for act in actions
            if act.exchange == candle.exchange
            and act.symbol == candle.symbol
            and act.effective_date > candle_date
            and (as_of_date is None or (act.announcement_date or act.effective_date) <= as_of_date)
        ]
        seen_keys: dict[tuple, None] = {}
        deduped: list = []
        for _act in matching_actions:
            _key = (
                _act.exchange, _act.symbol, _act.action_type,
                _act.effective_date, _act.adjustment_factor, _act.new_symbol,
            )
            if _key not in seen_keys:
                seen_keys[_key] = None
                deduped.append(_act)
        matching_actions = deduped

        if not matching_actions:
            if tick_size is not None:
                q_open = (candle.open / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
                q_high = (candle.high / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
                q_low = (candle.low / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
                q_close = (candle.close / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
                q_high = max(q_high, q_open, q_close)
                q_low = min(q_low, q_open, q_close)
                adjusted_candles.append(
                    Candle(
                        symbol=candle.symbol,
                        exchange=candle.exchange,
                        interval=candle.interval,
                        open=q_open,
                        high=q_high,
                        low=q_low,
                        close=q_close,
                        volume=candle.volume,
                        timestamp=candle.timestamp,
                        source=candle.source,
                        retrieval_timestamp=candle.retrieval_timestamp,
                    )
                )
            else:
                adjusted_candles.append(candle)
            continue

        cum_factor = Decimal("1")
        for act in matching_actions:
            cum_factor *= act.adjustment_factor

        if cum_factor <= 0:
            raise ValueError(f"Cumulative adjustment factor must be positive, got {cum_factor}")

        adj_open = candle.open * cum_factor
        adj_high = candle.high * cum_factor
        adj_low = candle.low * cum_factor
        adj_close = candle.close * cum_factor

        if tick_size is not None:
            adj_open = (adj_open / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
            adj_high = (adj_high / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
            adj_low = (adj_low / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size
            adj_close = (adj_close / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN) * tick_size

        adj_high = max(adj_high, adj_open, adj_close)
        adj_low = min(adj_low, adj_open, adj_close)

        scaled_vol = Decimal(candle.volume) / cum_factor
        adj_volume = max(0, int(scaled_vol.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)))

        adjusted_candles.append(
            Candle(
                symbol=candle.symbol,
                exchange=candle.exchange,
                interval=candle.interval,
                open=adj_open,
                high=adj_high,
                low=adj_low,
                close=adj_close,
                volume=adj_volume,
                timestamp=candle.timestamp,
                source=candle.source,
                retrieval_timestamp=candle.retrieval_timestamp,
            )
        )

    return tuple(adjusted_candles)
