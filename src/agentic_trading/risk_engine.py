"""Deterministic, fail-closed risk checks for paper orders.

This module intentionally has no broker or network dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderProposal:
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    available_cash: Decimal
    portfolio_equity: Decimal
    current_position_quantity: int = 0
    daily_realized_pnl: Decimal = Decimal("0")
    max_position_fraction: Decimal = Decimal("0.05")
    max_daily_loss_fraction: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_codes: tuple[str, ...]
    order_notional: Decimal


def _decimal(value: Decimal | str | int) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid decimal value") from exc
    if not result.is_finite():
        raise ValueError("Risk inputs must be finite")
    return result


def evaluate_order(proposal: OrderProposal) -> RiskDecision:
    """Evaluate a paper order; any invalid or unsafe input fails closed."""
    reasons: list[str] = []

    symbol = proposal.symbol.strip().upper() if isinstance(proposal.symbol, str) else ""
    if not symbol or any(ch.isspace() for ch in symbol):
        reasons.append("INVALID_SYMBOL")

    try:
        price = _decimal(proposal.limit_price)
        cash = _decimal(proposal.available_cash)
        equity = _decimal(proposal.portfolio_equity)
        pnl = _decimal(proposal.daily_realized_pnl)
        max_position = _decimal(proposal.max_position_fraction)
        max_daily_loss = _decimal(proposal.max_daily_loss_fraction)
    except ValueError:
        return RiskDecision(False, ("INVALID_NUMERIC_INPUT",), Decimal("0"))

    if proposal.side is not Side.BUY:
        reasons.append("SELL_DISABLED_IN_INITIAL_POLICY")
    if not isinstance(proposal.quantity, int) or isinstance(proposal.quantity, bool) or proposal.quantity <= 0:
        reasons.append("INVALID_QUANTITY")
    if price <= 0:
        reasons.append("INVALID_PRICE")
    if cash < 0 or equity <= 0:
        reasons.append("INVALID_PORTFOLIO_VALUES")
    if proposal.current_position_quantity < 0:
        reasons.append("INVALID_EXISTING_POSITION")
    if not (Decimal("0") < max_position <= Decimal("1")):
        reasons.append("INVALID_POSITION_LIMIT")
    if not (Decimal("0") < max_daily_loss < Decimal("1")):
        reasons.append("INVALID_DAILY_LOSS_LIMIT")

    if reasons:
        return RiskDecision(False, tuple(dict.fromkeys(reasons)), Decimal("0"))

    notional = price * proposal.quantity
    max_notional = equity * max_position
    daily_loss_limit = equity * max_daily_loss

    if pnl <= -daily_loss_limit:
        reasons.append("DAILY_LOSS_LIMIT_REACHED")
    if notional > max_notional:
        reasons.append("POSITION_NOTIONAL_LIMIT_EXCEEDED")
    if notional > cash:
        reasons.append("INSUFFICIENT_CASH")

    return RiskDecision(not reasons, tuple(reasons), notional)
