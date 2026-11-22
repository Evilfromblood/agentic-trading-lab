"""Deterministic proposal risk gate enforcing portfolio limits and circuit breakers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agentic_trading.market_data.instruments import Money
from agentic_trading.simulation.portfolio import PortfolioSnapshot
from agentic_trading.strategy.contracts import TradeProposal


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    """Pre-trade risk policy parameters controlling position, exposure, and loss limits."""

    max_position_pct: Decimal = Decimal("0.10")
    max_total_exposure_pct: Decimal = Decimal("0.80")
    max_daily_loss_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.05")
    require_stop_loss: bool = True
    max_risk_per_trade_pct: Decimal = Decimal("0.02")

    def __post_init__(self) -> None:
        for name, val in (
            ("max_position_pct", self.max_position_pct),
            ("max_total_exposure_pct", self.max_total_exposure_pct),
            ("max_daily_loss_pct", self.max_daily_loss_pct),
            ("max_drawdown_pct", self.max_drawdown_pct),
            ("max_risk_per_trade_pct", self.max_risk_per_trade_pct),
        ):
            if isinstance(val, (bool, float)) or not isinstance(val, Decimal) or not val.is_finite() or val <= 0:
                raise ValueError(f"{name} must be a positive finite Decimal, got {val}")
        if not isinstance(self.require_stop_loss, bool):
            raise TypeError("require_stop_loss must be a boolean")


@dataclass(frozen=True)
class ProposalRiskDecision:
    """Deterministic result of evaluating a TradeProposal against portfolio risk policy."""

    approved: bool
    proposal_id: str
    reasons: tuple[str, ...]
    max_allowed_quantity: int

    def __post_init__(self) -> None:
        if not isinstance(self.approved, bool):
            raise TypeError("approved must be a boolean")
        if not isinstance(self.proposal_id, str):
            raise TypeError("proposal_id must be a string")
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))
        if isinstance(self.max_allowed_quantity, bool) or not isinstance(self.max_allowed_quantity, int):
            raise TypeError("max_allowed_quantity must be an integer")


def evaluate_trade_proposal(
    proposal: TradeProposal,
    portfolio: PortfolioSnapshot,
    entry_price: Money,
    policy: PortfolioRiskPolicy,
    daily_pnl: Money,
    peak_equity: Money,
) -> ProposalRiskDecision:
    """Evaluate a trade proposal; deterministically fails closed on any policy or boundary violation."""
    reasons: list[str] = []

    if not isinstance(proposal, TradeProposal):
        raise TypeError(f"proposal must be a TradeProposal instance, got {type(proposal).__name__}")
    if not isinstance(portfolio, PortfolioSnapshot):
        raise TypeError(f"portfolio must be a PortfolioSnapshot instance, got {type(portfolio).__name__}")
    if not isinstance(entry_price, Money):
        raise TypeError(f"entry_price must be a Money instance, got {type(entry_price).__name__}")
    if not isinstance(policy, PortfolioRiskPolicy):
        raise TypeError(f"policy must be a PortfolioRiskPolicy instance, got {type(policy).__name__}")
    if not isinstance(daily_pnl, Money):
        raise TypeError(f"daily_pnl must be a Money instance, got {type(daily_pnl).__name__}")
    if not isinstance(peak_equity, Money):
        raise TypeError(f"peak_equity must be a Money instance, got {type(peak_equity).__name__}")

    base_currency = portfolio.currency
    if (
        proposal.instrument.currency != base_currency
        or entry_price.currency != base_currency
        or daily_pnl.currency != base_currency
        or peak_equity.currency != base_currency
    ):
        reasons.append("CURRENCY_MISMATCH")

    if proposal.stop_loss is not None and proposal.stop_loss.currency != base_currency:
        reasons.append("CURRENCY_MISMATCH")

    if proposal.take_profit is not None and proposal.take_profit.currency != base_currency:
        reasons.append("CURRENCY_MISMATCH")

    if proposal.limit_price is not None and proposal.limit_price.currency != base_currency:
        reasons.append("CURRENCY_MISMATCH")

    if peak_equity.amount <= 0:
        reasons.append("INVALID_PEAK_EQUITY")

    if entry_price.amount <= 0:
        reasons.append("INVALID_ENTRY_PRICE")

    lot_size = proposal.instrument.lot_size if proposal.instrument.lot_size > 0 else 1
    key = (proposal.instrument.exchange, proposal.instrument.symbol)
    curr_pos = portfolio.positions.get(key)
    held_qty = curr_pos.quantity if (curr_pos is not None and curr_pos.quantity > 0) else 0
    is_exact_full_exit = (
        proposal.side == "SELL" and held_qty > 0 and proposal.quantity == held_qty
    )
    if proposal.quantity <= 0 or (not is_exact_full_exit and proposal.quantity % lot_size != 0):
        reasons.append("LOT_SIZE_MISMATCH")


    if proposal.side == "SELL":
        if held_qty <= 0:
            reasons.append("UNAUTHORIZED_SHORT")
        elif proposal.quantity > held_qty:
            reasons.append("INSUFFICIENT_POSITION")

    if policy.require_stop_loss:
        if proposal.side == "BUY":
            if proposal.stop_loss is None:
                reasons.append("MISSING_STOP_LOSS")
        elif proposal.side == "SELL" and held_qty <= 0:
            if proposal.stop_loss is None:
                reasons.append("MISSING_STOP_LOSS")

    if proposal.stop_loss is not None:
        if proposal.stop_loss.amount <= 0:
            reasons.append("INVALID_STOP_LOSS")
        elif entry_price.amount > 0:
            if proposal.side == "BUY" and proposal.stop_loss.amount >= entry_price.amount:
                reasons.append("INVALID_STOP_LOSS_DIRECTION")
            elif proposal.side == "SELL" and held_qty > 0 and proposal.stop_loss.amount >= entry_price.amount:
                reasons.append("INVALID_STOP_LOSS_DIRECTION")
            elif proposal.side == "SELL" and held_qty <= 0 and proposal.stop_loss.amount <= entry_price.amount:
                reasons.append("INVALID_STOP_LOSS_DIRECTION")

    if proposal.take_profit is not None:
        if proposal.take_profit.amount <= 0:
            reasons.append("INVALID_TAKE_PROFIT")
        elif entry_price.amount > 0:
            if proposal.side == "BUY" and proposal.take_profit.amount <= entry_price.amount:
                reasons.append("INVALID_TAKE_PROFIT_DIRECTION")
            elif proposal.side == "SELL" and held_qty > 0 and proposal.take_profit.amount <= entry_price.amount:
                reasons.append("INVALID_TAKE_PROFIT_DIRECTION")
            elif proposal.side == "SELL" and held_qty <= 0 and proposal.take_profit.amount >= entry_price.amount:
                reasons.append("INVALID_TAKE_PROFIT_DIRECTION")

    if proposal.limit_price is not None:
        if proposal.limit_price.amount <= 0:
            reasons.append("INVALID_LIMIT_PRICE")
        elif entry_price.amount > 0:
            if proposal.side == "BUY" and proposal.limit_price.amount > entry_price.amount:
                reasons.append("INVALID_LIMIT_PRICE_DIRECTION")
            elif proposal.side == "SELL" and proposal.limit_price.amount < entry_price.amount:
                reasons.append("INVALID_LIMIT_PRICE_DIRECTION")

    if (
        proposal.side == "BUY"
        and proposal.stop_loss is not None
        and "CURRENCY_MISMATCH" not in reasons
        and entry_price.amount > 0
        and proposal.stop_loss.amount > 0
        and entry_price.amount > proposal.stop_loss.amount
    ):
        per_trade_risk = (entry_price.amount - proposal.stop_loss.amount) * Decimal(proposal.quantity)
        max_risk = portfolio.total_equity.amount * policy.max_risk_per_trade_pct
        if per_trade_risk > max_risk:
            reasons.append("PER_TRADE_RISK_LIMIT_EXCEEDED")

    if proposal.side == "BUY" and "CURRENCY_MISMATCH" not in reasons and entry_price.amount > 0:
        new_notional = entry_price.amount * Decimal(held_qty + proposal.quantity)
        max_pos_notional = portfolio.total_equity.amount * policy.max_position_pct
        if new_notional > max_pos_notional:
            reasons.append("POSITION_CONCENTRATION_EXCEEDED")

        proposed_notional = entry_price.amount * Decimal(proposal.quantity)
        total_exposure = portfolio.holdings_value.amount + proposed_notional
        max_exposure = portfolio.total_equity.amount * policy.max_total_exposure_pct
        if total_exposure > max_exposure:
            reasons.append("TOTAL_EXPOSURE_LIMIT_EXCEEDED")

        if proposed_notional > portfolio.cash.amount:
            reasons.append("INSUFFICIENT_CASH")

    if proposal.side == "BUY":
        max_loss = portfolio.total_equity.amount * policy.max_daily_loss_pct
        if daily_pnl.amount <= -max_loss:
            reasons.append("DAILY_LOSS_LIMIT_REACHED")

        if peak_equity.amount > 0:
            drawdown = (peak_equity.amount - portfolio.total_equity.amount) / peak_equity.amount
            if drawdown >= policy.max_drawdown_pct:
                reasons.append("DRAWDOWN_LIMIT_REACHED")

    blocking_reasons = {
        "CURRENCY_MISMATCH",
        "INVALID_PEAK_EQUITY",
        "INVALID_ENTRY_PRICE",
        "INVALID_STOP_LOSS",
        "INVALID_STOP_LOSS_DIRECTION",
        "MISSING_STOP_LOSS",
        "INVALID_TAKE_PROFIT",
        "INVALID_TAKE_PROFIT_DIRECTION",
        "INVALID_LIMIT_PRICE",
        "INVALID_LIMIT_PRICE_DIRECTION",
        "DAILY_LOSS_LIMIT_REACHED",
        "DRAWDOWN_LIMIT_REACHED",
        "UNAUTHORIZED_SHORT",
    }

    if any(r in blocking_reasons for r in reasons):
        max_allowed_qty = 0
    else:
        if proposal.side == "BUY":
            if entry_price.amount > 0:
                max_by_cash = int(portfolio.cash.amount // entry_price.amount)
                max_pos_notional = portfolio.total_equity.amount * policy.max_position_pct
                rem_pos = max_pos_notional - (entry_price.amount * Decimal(held_qty))
                max_by_pos = int(rem_pos // entry_price.amount) if rem_pos > 0 else 0
                max_exposure = portfolio.total_equity.amount * policy.max_total_exposure_pct
                rem_exp = max_exposure - portfolio.holdings_value.amount
                max_by_exp = int(rem_exp // entry_price.amount) if rem_exp > 0 else 0

                candidates = [max_by_cash, max_by_pos, max_by_exp]
                if (
                    proposal.stop_loss is not None
                    and proposal.stop_loss.amount > 0
                    and entry_price.amount > proposal.stop_loss.amount
                ):
                    risk_per_share = entry_price.amount - proposal.stop_loss.amount
                    max_risk = portfolio.total_equity.amount * policy.max_risk_per_trade_pct
                    max_by_risk = int(max_risk // risk_per_share)
                    candidates.append(max_by_risk)

                allowed_buy = max(0, min(candidates))
                allowed_buy = (allowed_buy // lot_size) * lot_size
                max_allowed_qty = min(proposal.quantity, allowed_buy)
            else:
                max_allowed_qty = 0
        else:
            if is_exact_full_exit:
                allowed_sell = held_qty
            else:
                allowed_sell = (held_qty // lot_size) * lot_size
            max_allowed_qty = min(proposal.quantity, allowed_sell)

    if not is_exact_full_exit:
        max_allowed_qty = max(0, (max_allowed_qty // lot_size) * lot_size)

    if reasons:
        unique_reasons = tuple(dict.fromkeys(reasons))
        return ProposalRiskDecision(
            approved=False,
            proposal_id=proposal.proposal_id,
            reasons=unique_reasons,
            max_allowed_quantity=max_allowed_qty,
        )

    return ProposalRiskDecision(
        approved=True,
        proposal_id=proposal.proposal_id,
        reasons=(),
        max_allowed_quantity=max_allowed_qty,
    )
