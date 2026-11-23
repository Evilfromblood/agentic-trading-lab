"""Idempotent paper trading broker, realistic execution model, and position reconciliation."""
from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from agentic_trading.market_data.instruments import CurrencyMismatchError, Money
from agentic_trading.market_data.models import Candle, Exchange, ExchangeCalendar
from agentic_trading.paper_trading.kill_switch import KillSwitch
from agentic_trading.simulation.costs import FeeModel, SlippageModel
from agentic_trading.simulation.portfolio import (
    InsufficientFundsError,
    InsufficientPositionError,
    PortfolioEngine,
)
from agentic_trading.strategy.contracts import TradeProposal


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PaperOrder:
    client_order_id: str
    run_id: str
    exchange: Exchange
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    limit_price: Money | None
    stop_loss: Money | None
    take_profit: Money | None
    status: OrderStatus
    submitted_at: datetime
    filled_at: datetime | None
    average_fill_price: Money | None
    fees: Money
    slippage: Money
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OrderStatus):
            raise TypeError("status must be an OrderStatus enum")
        if not isinstance(self.submitted_at, datetime) or self.submitted_at.tzinfo is None:
            raise ValueError("submitted_at must be a timezone-aware datetime")
        if self.filled_at is not None and (
            not isinstance(self.filled_at, datetime) or self.filled_at.tzinfo is None
        ):
            raise ValueError("filled_at must be a timezone-aware datetime")


@dataclass(frozen=True)
class ReconciliationReport:
    checked_at: datetime
    is_reconciled: bool
    discrepancies: tuple[str, ...]
    ledger_cash: Money
    portfolio_cash: Money
    open_positions: Mapping[tuple[Exchange, str], int]

    def __post_init__(self) -> None:
        if not isinstance(self.checked_at, datetime) or self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be a timezone-aware datetime")
        if not isinstance(self.is_reconciled, bool):
            raise TypeError("is_reconciled must be a boolean")
        if not isinstance(self.discrepancies, tuple):
            object.__setattr__(self, "discrepancies", tuple(self.discrepancies))


class PaperBroker:
    """Deterministic, idempotent paper trading broker executing against market candles."""

    def __init__(
        self,
        portfolio: PortfolioEngine,
        slippage_model: SlippageModel | None = None,
        fee_model: FeeModel | None = None,
        kill_switch: KillSwitch | None = None,
        enforce_market_hours: bool = False,
        exchange_calendar: ExchangeCalendar | None = None,
    ) -> None:
        if not isinstance(portfolio, PortfolioEngine):
            raise TypeError("portfolio must be a PortfolioEngine instance")
        self.portfolio = portfolio
        if slippage_model is not None:
            self.portfolio.slippage_model = slippage_model
        if fee_model is not None:
            self.portfolio.fee_model = fee_model
        self.slippage_model = self.portfolio.slippage_model
        self.fee_model = self.portfolio.fee_model
        self.kill_switch = kill_switch or KillSwitch()
        self.enforce_market_hours = enforce_market_hours
        self.exchange_calendar = exchange_calendar
        self._lock = threading.RLock()
        self._orders: dict[str, PaperOrder] = {}

    def get_order(self, client_order_id: str) -> PaperOrder | None:
        with self._lock:
            return self._orders.get(client_order_id)

    def list_orders(self, run_id: str | None = None) -> tuple[PaperOrder, ...]:
        with self._lock:
            if run_id is None:
                return tuple(self._orders.values())
            return tuple(o for o in self._orders.values() if o.run_id == run_id)

    def cancel_order(self, client_order_id: str) -> PaperOrder:
        with self._lock:
            if client_order_id not in self._orders:
                raise KeyError(f"Order {client_order_id} not found")
            curr = self._orders[client_order_id]
            if curr.status in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                cancelled = PaperOrder(
                    client_order_id=curr.client_order_id,
                    run_id=curr.run_id,
                    exchange=curr.exchange,
                    symbol=curr.symbol,
                    side=curr.side,
                    quantity=curr.quantity,
                    filled_quantity=curr.filled_quantity,
                    limit_price=curr.limit_price,
                    stop_loss=curr.stop_loss,
                    take_profit=curr.take_profit,
                    status=OrderStatus.CANCELLED,
                    submitted_at=curr.submitted_at,
                    filled_at=curr.filled_at,
                    average_fill_price=curr.average_fill_price,
                    fees=curr.fees,
                    slippage=curr.slippage,
                    reject_reason="ORDER_CANCELLED",
                )
                self._orders[client_order_id] = cancelled
                return cancelled
            if curr.status in {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED}:
                raise ValueError(f"Cannot cancel order in terminal status {curr.status.value}")
            if curr.status == OrderStatus.PARTIALLY_FILLED:
                cancelled = PaperOrder(
                    client_order_id=curr.client_order_id,
                    run_id=curr.run_id,
                    exchange=curr.exchange,
                    symbol=curr.symbol,
                    side=curr.side,
                    quantity=curr.quantity,
                    filled_quantity=curr.filled_quantity,
                    limit_price=curr.limit_price,
                    stop_loss=curr.stop_loss,
                    take_profit=curr.take_profit,
                    status=OrderStatus.CANCELLED,
                    submitted_at=curr.submitted_at,
                    filled_at=curr.filled_at,
                    average_fill_price=curr.average_fill_price,
                    fees=curr.fees,
                    slippage=curr.slippage,
                    reject_reason="ORDER_CANCELLED",
                )
                self._orders[client_order_id] = cancelled
                return cancelled
            raise ValueError(f"Unhandled order status {curr.status}")

    def submit_order(
        self,
        run_id: str,
        proposal: TradeProposal,
        current_candle: Candle,
        max_fill_ratio: Decimal = Decimal("1.0"),
        client_order_id: str | None = None,
        tick_size: Decimal = Decimal("0.01"),
    ) -> PaperOrder:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(proposal, TradeProposal):
            raise TypeError("proposal must be a TradeProposal instance")
        if not isinstance(current_candle, Candle):
            raise TypeError("current_candle must be a Candle instance")
        if (
            isinstance(max_fill_ratio, (bool, float))
            or not isinstance(max_fill_ratio, Decimal)
            or not max_fill_ratio.is_finite()
            or not (Decimal("0") <= max_fill_ratio <= Decimal("1"))
        ):
            raise ValueError("max_fill_ratio must be a finite Decimal in [0, 1]")

        if proposal.limit_price is not None:
            if proposal.limit_price.amount <= Decimal("0"):
                raise ValueError("limit_price must be positive")
            if proposal.limit_price.currency != proposal.instrument.currency:
                raise CurrencyMismatchError(
                    f"Limit price currency {proposal.limit_price.currency} does not match instrument currency {proposal.instrument.currency}"
                )

        cid = (
            client_order_id.strip()
            if (client_order_id and client_order_id.strip())
            else f"{run_id}-{proposal.instrument.exchange.value}-{proposal.instrument.symbol}-{proposal.side}"
        )

        with self._lock:
            if cid in self._orders:
                return self._orders[cid]

            currency = proposal.instrument.currency
            zero_money = Money(Decimal("0"), currency)
            submitted_at = current_candle.close_time

            if self.kill_switch.is_active():
                order = PaperOrder(
                    client_order_id=cid,
                    run_id=run_id,
                    exchange=proposal.instrument.exchange,
                    symbol=proposal.instrument.symbol,
                    side=proposal.side,
                    quantity=proposal.quantity,
                    filled_quantity=0,
                    limit_price=proposal.limit_price,
                    stop_loss=proposal.stop_loss,
                    take_profit=proposal.take_profit,
                    status=OrderStatus.REJECTED,
                    submitted_at=submitted_at,
                    filled_at=None,
                    average_fill_price=None,
                    fees=zero_money,
                    slippage=zero_money,
                    reject_reason="KILL_SWITCH_ACTIVE",
                )
                self._orders[cid] = order
                return order

            if self.enforce_market_hours and self.exchange_calendar is not None:
                if not self.exchange_calendar.is_trading_minute(current_candle.timestamp):
                    order = PaperOrder(
                        client_order_id=cid,
                        run_id=run_id,
                        exchange=proposal.instrument.exchange,
                        symbol=proposal.instrument.symbol,
                        side=proposal.side,
                        quantity=proposal.quantity,
                        filled_quantity=0,
                        limit_price=proposal.limit_price,
                        stop_loss=proposal.stop_loss,
                        take_profit=proposal.take_profit,
                        status=OrderStatus.REJECTED,
                        submitted_at=submitted_at,
                        filled_at=None,
                        average_fill_price=None,
                        fees=zero_money,
                        slippage=zero_money,
                        reject_reason="OUTSIDE_MARKET_HOURS",
                    )
                    self._orders[cid] = order
                    return order

            ref_price = Money(current_candle.close, currency)
            fill_qty = int(Decimal(proposal.quantity) * max_fill_ratio)
            lot = proposal.instrument.lot_size if proposal.instrument.lot_size > 0 else 1
            fill_qty = (fill_qty // lot) * lot
            if fill_qty <= 0:
                order = PaperOrder(
                    client_order_id=cid,
                    run_id=run_id,
                    exchange=proposal.instrument.exchange,
                    symbol=proposal.instrument.symbol,
                    side=proposal.side,
                    quantity=proposal.quantity,
                    filled_quantity=0,
                    limit_price=proposal.limit_price,
                    stop_loss=proposal.stop_loss,
                    take_profit=proposal.take_profit,
                    status=OrderStatus.REJECTED,
                    submitted_at=submitted_at,
                    filled_at=None,
                    average_fill_price=None,
                    fees=zero_money,
                    slippage=zero_money,
                    reject_reason="FILL_QUANTITY_ZERO",
                )
                self._orders[cid] = order
                return order

            slipped_price = self.slippage_model.calculate_slippage(ref_price, proposal.side, tick_size)
            slipped_exec_price = slipped_price.amount

            if proposal.limit_price is not None:
                if proposal.side == "BUY" and slipped_exec_price > proposal.limit_price.amount:
                    order = PaperOrder(
                        client_order_id=cid,
                        run_id=run_id,
                        exchange=proposal.instrument.exchange,
                        symbol=proposal.instrument.symbol,
                        side=proposal.side,
                        quantity=proposal.quantity,
                        filled_quantity=0,
                        limit_price=proposal.limit_price,
                        stop_loss=proposal.stop_loss,
                        take_profit=proposal.take_profit,
                        status=OrderStatus.PENDING,
                        submitted_at=submitted_at,
                        filled_at=None,
                        average_fill_price=None,
                        fees=zero_money,
                        slippage=zero_money,
                        reject_reason="LIMIT_PRICE_UNMET",
                    )
                    self._orders[cid] = order
                    return order
                if proposal.side == "SELL" and slipped_exec_price < proposal.limit_price.amount:
                    order = PaperOrder(
                        client_order_id=cid,
                        run_id=run_id,
                        exchange=proposal.instrument.exchange,
                        symbol=proposal.instrument.symbol,
                        side=proposal.side,
                        quantity=proposal.quantity,
                        filled_quantity=0,
                        limit_price=proposal.limit_price,
                        stop_loss=proposal.stop_loss,
                        take_profit=proposal.take_profit,
                        status=OrderStatus.PENDING,
                        submitted_at=submitted_at,
                        filled_at=None,
                        average_fill_price=None,
                        fees=zero_money,
                        slippage=zero_money,
                        reject_reason="LIMIT_PRICE_UNMET",
                    )
                    self._orders[cid] = order
                    return order

            try:
                fill_entry, fee_entry = self.portfolio.apply_fill(
                    timestamp=submitted_at,
                    exchange=proposal.instrument.exchange,
                    symbol=proposal.instrument.symbol,
                    side=proposal.side,
                    quantity=fill_qty,
                    execution_price=ref_price,
                    tick_size=tick_size,
                    reference_id=cid,
                    allow_short=False,
                )
            except InsufficientFundsError:
                order = PaperOrder(
                    client_order_id=cid,
                    run_id=run_id,
                    exchange=proposal.instrument.exchange,
                    symbol=proposal.instrument.symbol,
                    side=proposal.side,
                    quantity=proposal.quantity,
                    filled_quantity=0,
                    limit_price=proposal.limit_price,
                    stop_loss=proposal.stop_loss,
                    take_profit=proposal.take_profit,
                    status=OrderStatus.REJECTED,
                    submitted_at=submitted_at,
                    filled_at=None,
                    average_fill_price=None,
                    fees=zero_money,
                    slippage=zero_money,
                    reject_reason="INSUFFICIENT_FUNDS",
                )
                self._orders[cid] = order
                return order
            except InsufficientPositionError:
                order = PaperOrder(
                    client_order_id=cid,
                    run_id=run_id,
                    exchange=proposal.instrument.exchange,
                    symbol=proposal.instrument.symbol,
                    side=proposal.side,
                    quantity=proposal.quantity,
                    filled_quantity=0,
                    limit_price=proposal.limit_price,
                    stop_loss=proposal.stop_loss,
                    take_profit=proposal.take_profit,
                    status=OrderStatus.REJECTED,
                    submitted_at=submitted_at,
                    filled_at=None,
                    average_fill_price=None,
                    fees=zero_money,
                    slippage=zero_money,
                    reject_reason="INSUFFICIENT_POSITION",
                )
                self._orders[cid] = order
                return order

            actual_price = fill_entry.execution_price or ref_price
            slippage_amount = abs(actual_price.amount - ref_price.amount) * Decimal(fill_qty)
            fee_amount = -fee_entry.cash_delta.amount if fee_entry is not None else Decimal("0")
            status = (
                OrderStatus.FILLED if fill_qty == proposal.quantity else OrderStatus.PARTIALLY_FILLED
            )

            order = PaperOrder(
                client_order_id=cid,
                run_id=run_id,
                exchange=proposal.instrument.exchange,
                symbol=proposal.instrument.symbol,
                side=proposal.side,
                quantity=proposal.quantity,
                filled_quantity=fill_qty,
                limit_price=proposal.limit_price,
                stop_loss=proposal.stop_loss,
                take_profit=proposal.take_profit,
                status=status,
                submitted_at=submitted_at,
                filled_at=submitted_at,
                average_fill_price=actual_price,
                fees=Money(fee_amount, currency),
                slippage=Money(slippage_amount, currency),
                reject_reason=None,
            )
            self._orders[cid] = order
            return order

    def reconcile(
        self,
        as_of: datetime,
        mark_prices: Mapping[tuple[Exchange, str], Money] | None = None,
    ) -> ReconciliationReport:
        with self._lock:
            currency = self.portfolio.currency
            ledger_cash = self.portfolio.ledger.get_cash_balance(currency)
            complete_marks = dict(mark_prices or {})
            for key, pos in self.portfolio._positions.items():
                if pos.quantity != 0 and key not in complete_marks:
                    complete_marks[key] = pos.average_cost

            snapshot = self.portfolio.snapshot(currency, complete_marks, as_of)
            discrepancies: list[str] = []
            if ledger_cash.amount != snapshot.cash.amount:
                discrepancies.append(
                    f"Cash mismatch: ledger={ledger_cash.amount} snapshot={snapshot.cash.amount}"
                )

            open_positions = {k: p.quantity for k, p in snapshot.positions.items() if p.quantity != 0}
            expected_cash = (
                self.portfolio.ledger.get_total_deposits(currency).amount
                - self.portfolio.ledger.get_total_withdrawals(currency).amount
                + snapshot.realized_pnl.amount
                + self.portfolio.ledger.get_total_dividends(currency).amount
                - self.portfolio.ledger.get_total_fees(currency).amount
            )
            open_basis = sum((p.cost_basis.amount for p in snapshot.positions.values()), Decimal("0"))
            residual = expected_cash - (snapshot.cash.amount + open_basis)
            if residual != Decimal("0"):
                discrepancies.append(f"Conservation residual mismatch: {residual} != 0")

            return ReconciliationReport(
                checked_at=as_of,
                is_reconciled=len(discrepancies) == 0,
                discrepancies=tuple(discrepancies),
                ledger_cash=ledger_cash,
                portfolio_cash=snapshot.cash,
                open_positions=open_positions,
            )
