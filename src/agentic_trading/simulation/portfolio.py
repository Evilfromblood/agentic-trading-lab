"""Multi-currency portfolio state, holding projections, and balance snapshot generator."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from agentic_trading.market_data.instruments import Currency, CurrencyMismatchError, Money
from agentic_trading.market_data.models import Exchange
from agentic_trading.simulation.costs import (
    BasisPointsSlippageModel,
    FeeModel,
    SlippageModel,
    ZeroFeeModel,
)
from agentic_trading.simulation.ledger import (
    AccountingLedger,
    LedgerEntry,
    LedgerEventType,
)


class InsufficientFundsError(ValueError):
    """Raised when an operation would cause an illegal cash overdraft."""


class InsufficientPositionError(ValueError):
    """Raised when attempting to sell more shares than held without shorting permission."""


@dataclass(frozen=True)
class Position:
    """Immutable single-instrument holding state."""

    exchange: Exchange
    symbol: str
    currency: Currency
    quantity: int
    average_cost: Money
    realized_pnl: Money

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())

        if not isinstance(self.currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(self.currency).__name__}")

        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError(f"quantity must be an integer, got {type(self.quantity).__name__}")

        if not isinstance(self.average_cost, Money) or self.average_cost.currency != self.currency:
            raise ValueError("average_cost must be a Money instance matching holding currency")

        if not isinstance(self.realized_pnl, Money) or self.realized_pnl.currency != self.currency:
            raise ValueError("realized_pnl must be a Money instance matching holding currency")

    @property
    def cost_basis(self) -> Money:
        return Money(self.average_cost.amount * Decimal(self.quantity), self.currency)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Comprehensive point-in-time portfolio evaluation."""

    timestamp: datetime
    currency: Currency
    cash: Money
    holdings_value: Money
    total_equity: Money
    realized_pnl: Money
    unrealized_pnl: Money
    positions: Mapping[tuple[Exchange, str], Position]

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError("timestamp must be timezone-aware")
        if not isinstance(self.currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(self.currency).__name__}")
        for m in (self.cash, self.holdings_value, self.total_equity, self.realized_pnl, self.unrealized_pnl):
            if not isinstance(m, Money) or m.currency != self.currency:
                raise ValueError(f"Monetary value {m} does not match portfolio currency {self.currency}")


class PortfolioEngine:
    """Deterministic simulation portfolio tracker backed by an append-only accounting ledger."""

    def __init__(
        self,
        currency: Currency,
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
        ledger: AccountingLedger | None = None,
    ) -> None:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        self.currency = currency
        self.fee_model = fee_model or ZeroFeeModel()
        self.slippage_model = slippage_model or BasisPointsSlippageModel(Decimal("0"))
        self.ledger = ledger or AccountingLedger()
        self._positions: dict[tuple[Exchange, str], Position] = {}
        self._realized_pnl_by_symbol: dict[tuple[Exchange, str], Decimal] = {}
        self._total_cost_basis: dict[tuple[Exchange, str], Decimal] = {}

        if ledger is not None and ledger.entries:
            self._replay_ledger(ledger.entries)

    def _apply_trade_to_position(
        self,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        exec_price_amount: Decimal,
        allow_short: bool = False,
    ) -> None:
        key = (exchange, symbol)
        curr_pos = self._positions.get(key)
        curr_qty = curr_pos.quantity if curr_pos is not None else 0
        curr_basis = self._total_cost_basis.get(key, Decimal("0"))

        if curr_qty == 0:
            if side == "BUY":
                new_basis = Decimal(quantity) * exec_price_amount
                self._total_cost_basis[key] = new_basis
                avg_cost = new_basis / Decimal(quantity)
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=symbol,
                    currency=self.currency,
                    quantity=quantity,
                    average_cost=Money(avg_cost, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )
            else:
                if not allow_short:
                    raise InsufficientPositionError(
                        f"Cannot short sell {quantity} shares of {symbol}; allow_short is False"
                    )
                new_basis = Decimal(quantity) * exec_price_amount
                self._total_cost_basis[key] = new_basis
                avg_cost = new_basis / Decimal(quantity)
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=symbol,
                    currency=self.currency,
                    quantity=-quantity,
                    average_cost=Money(avg_cost, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )
        elif curr_qty > 0:
            if side == "BUY":
                add_cost = Decimal(quantity) * exec_price_amount
                new_qty = curr_qty + quantity
                new_basis = curr_basis + add_cost
                self._total_cost_basis[key] = new_basis
                avg_cost = new_basis / Decimal(new_qty)
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=symbol,
                    currency=self.currency,
                    quantity=new_qty,
                    average_cost=Money(avg_cost, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )
            else:
                if quantity <= curr_qty:
                    if quantity == curr_qty:
                        basis_removed = curr_basis
                        new_basis = Decimal("0")
                        new_qty = 0
                    else:
                        basis_removed = (
                            (curr_basis * Decimal(quantity)) / Decimal(curr_qty)
                        ).quantize(Decimal("1E-12"), rounding=ROUND_HALF_EVEN)
                        new_basis = curr_basis - basis_removed
                        new_qty = curr_qty - quantity
                    proceeds = Decimal(quantity) * exec_price_amount
                    trade_pnl = proceeds - basis_removed
                    self._realized_pnl_by_symbol[key] = (
                        self._realized_pnl_by_symbol.get(key, Decimal("0")) + trade_pnl
                    )
                    if new_qty == 0:
                        self._total_cost_basis.pop(key, None)
                        self._positions.pop(key, None)
                    else:
                        self._total_cost_basis[key] = new_basis
                        avg_cost = new_basis / Decimal(new_qty)
                        self._positions[key] = Position(
                            exchange=exchange,
                            symbol=symbol,
                            currency=self.currency,
                            quantity=new_qty,
                            average_cost=Money(avg_cost, self.currency),
                            realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                        )
                else:
                    if not allow_short:
                        raise InsufficientPositionError(
                            f"Cannot sell {quantity} shares of {symbol}, current position is {curr_qty}"
                        )
                    basis_removed = curr_basis
                    proceeds_long = Decimal(curr_qty) * exec_price_amount
                    trade_pnl = proceeds_long - basis_removed
                    self._realized_pnl_by_symbol[key] = (
                        self._realized_pnl_by_symbol.get(key, Decimal("0")) + trade_pnl
                    )
                    rem_short = quantity - curr_qty
                    new_basis = Decimal(rem_short) * exec_price_amount
                    self._total_cost_basis[key] = new_basis
                    avg_cost = new_basis / Decimal(rem_short)
                    self._positions[key] = Position(
                        exchange=exchange,
                        symbol=symbol,
                        currency=self.currency,
                        quantity=-rem_short,
                        average_cost=Money(avg_cost, self.currency),
                        realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                    )
        else:
            abs_curr = abs(curr_qty)
            if side == "SELL":
                if not allow_short:
                    raise InsufficientPositionError(
                        f"Cannot short sell {quantity} shares of {symbol}; allow_short is False"
                    )
                add_cost = Decimal(quantity) * exec_price_amount
                new_qty = curr_qty - quantity
                new_basis = curr_basis + add_cost
                self._total_cost_basis[key] = new_basis
                avg_cost = new_basis / Decimal(abs(new_qty))
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=symbol,
                    currency=self.currency,
                    quantity=new_qty,
                    average_cost=Money(avg_cost, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )
            else:
                if quantity <= abs_curr:
                    if quantity == abs_curr:
                        basis_removed = curr_basis
                        new_basis = Decimal("0")
                        new_qty = 0
                    else:
                        basis_removed = (
                            (curr_basis * Decimal(quantity)) / Decimal(abs_curr)
                        ).quantize(Decimal("1E-12"), rounding=ROUND_HALF_EVEN)
                        new_basis = curr_basis - basis_removed
                        new_qty = curr_qty + quantity
                    cover_cost = Decimal(quantity) * exec_price_amount
                    trade_pnl = basis_removed - cover_cost
                    self._realized_pnl_by_symbol[key] = (
                        self._realized_pnl_by_symbol.get(key, Decimal("0")) + trade_pnl
                    )
                    if new_qty == 0:
                        self._total_cost_basis.pop(key, None)
                        self._positions.pop(key, None)
                    else:
                        self._total_cost_basis[key] = new_basis
                        avg_cost = new_basis / Decimal(abs(new_qty))
                        self._positions[key] = Position(
                            exchange=exchange,
                            symbol=symbol,
                            currency=self.currency,
                            quantity=new_qty,
                            average_cost=Money(avg_cost, self.currency),
                            realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                        )
                else:
                    basis_removed = curr_basis
                    cover_cost = Decimal(abs_curr) * exec_price_amount
                    trade_pnl = basis_removed - cover_cost
                    self._realized_pnl_by_symbol[key] = (
                        self._realized_pnl_by_symbol.get(key, Decimal("0")) + trade_pnl
                    )
                    rem_long = quantity - abs_curr
                    new_basis = Decimal(rem_long) * exec_price_amount
                    self._total_cost_basis[key] = new_basis
                    avg_cost = new_basis / Decimal(rem_long)
                    self._positions[key] = Position(
                        exchange=exchange,
                        symbol=symbol,
                        currency=self.currency,
                        quantity=rem_long,
                        average_cost=Money(avg_cost, self.currency),
                        realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                    )

    def _replay_ledger(self, entries: tuple[LedgerEntry, ...]) -> None:
        for entry in entries:
            if entry.currency != self.currency:
                continue
            if entry.event_type == LedgerEventType.BUY_FILL and entry.exchange and entry.symbol and entry.execution_price:
                self._apply_trade_to_position(
                    exchange=entry.exchange,
                    symbol=entry.symbol,
                    side="BUY",
                    quantity=entry.quantity_delta,
                    exec_price_amount=entry.execution_price.amount,
                    allow_short=True,
                )
            elif entry.event_type == LedgerEventType.SELL_FILL and entry.exchange and entry.symbol and entry.execution_price:
                self._apply_trade_to_position(
                    exchange=entry.exchange,
                    symbol=entry.symbol,
                    side="SELL",
                    quantity=abs(entry.quantity_delta),
                    exec_price_amount=entry.execution_price.amount,
                    allow_short=True,
                )

    def deposit(self, amount: Money, timestamp: datetime, reference_id: str = "") -> LedgerEntry:
        if not isinstance(amount, Money):
            raise TypeError(f"amount must be a Money instance, got {type(amount).__name__}")
        if amount.currency != self.currency:
            raise CurrencyMismatchError(
                f"Deposit currency {amount.currency} does not match portfolio currency {self.currency}"
            )
        if amount.amount <= Decimal("0"):
            raise ValueError(f"Deposit amount must be strictly positive, got {amount.amount}")

        return self.ledger.append(
            timestamp=timestamp,
            event_type=LedgerEventType.DEPOSIT,
            currency=self.currency,
            cash_delta=amount,
            reference_id=reference_id,
        )

    def withdraw(self, amount: Money, timestamp: datetime, reference_id: str = "") -> LedgerEntry:
        if not isinstance(amount, Money):
            raise TypeError(f"amount must be a Money instance, got {type(amount).__name__}")
        if amount.currency != self.currency:
            raise CurrencyMismatchError(
                f"Withdrawal currency {amount.currency} does not match portfolio currency {self.currency}"
            )
        if amount.amount <= Decimal("0"):
            raise ValueError(f"Withdrawal amount must be strictly positive, got {amount.amount}")

        current_cash = self.ledger.get_cash_balance(self.currency)
        if current_cash.amount < amount.amount:
            raise InsufficientFundsError(
                f"Cannot withdraw {amount.amount} {self.currency.value}, available cash is {current_cash.amount}"
            )

        return self.ledger.append(
            timestamp=timestamp,
            event_type=LedgerEventType.WITHDRAWAL,
            currency=self.currency,
            cash_delta=-amount,
            reference_id=reference_id,
        )

    def apply_dividend(
        self,
        timestamp: datetime,
        exchange: Exchange,
        symbol: str,
        amount: Money,
        reference_id: str = "",
    ) -> LedgerEntry:
        if not isinstance(exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = symbol.strip().upper()

        if not isinstance(amount, Money):
            raise TypeError(f"amount must be a Money instance, got {type(amount).__name__}")
        if amount.currency != self.currency:
            raise CurrencyMismatchError(
                f"Dividend currency {amount.currency} does not match portfolio {self.currency}"
            )
        if amount.amount <= Decimal("0"):
            raise ValueError(f"Dividend amount must be strictly positive, got {amount.amount}")

        return self.ledger.append(
            timestamp=timestamp,
            event_type=LedgerEventType.DIVIDEND_CREDIT,
            currency=self.currency,
            cash_delta=amount,
            exchange=exchange,
            symbol=clean_symbol,
            reference_id=reference_id,
        )

    def apply_fill(
        self,
        timestamp: datetime,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        execution_price: Money,
        tick_size: Decimal = Decimal("0.01"),
        reference_id: str = "",
        allow_short: bool = False,
    ) -> tuple[LedgerEntry, LedgerEntry | None]:
        if not isinstance(exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = symbol.strip().upper()

        if not isinstance(execution_price, Money):
            raise TypeError(f"execution_price must be a Money instance, got {type(execution_price).__name__}")
        if execution_price.currency != self.currency:
            raise CurrencyMismatchError(
                f"Fill price currency {execution_price.currency} does not match portfolio {self.currency}"
            )
        if execution_price.amount <= Decimal("0"):
            raise ValueError(f"Fill price must be strictly positive, got {execution_price.amount}")

        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(f"quantity must be a positive integer, got {quantity}")

        clean_side = side.strip().upper()
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")

        slipped_price = self.slippage_model.calculate_slippage(execution_price, clean_side, tick_size)
        fee = self.fee_model.calculate_fees(exchange, clean_symbol, clean_side, quantity, slipped_price)

        if clean_side == "BUY":
            fill_cost = slipped_price.amount * Decimal(quantity)
            total_required_cash = fill_cost + fee.amount
            avail_cash = self.ledger.get_cash_balance(self.currency)

            if avail_cash.amount < total_required_cash:
                raise InsufficientFundsError(
                    f"Insufficient cash for BUY fill: required {total_required_cash}, available {avail_cash.amount}"
                )

            self._apply_trade_to_position(
                exchange=exchange,
                symbol=clean_symbol,
                side="BUY",
                quantity=quantity,
                exec_price_amount=slipped_price.amount,
                allow_short=allow_short,
            )

            fill_entry = self.ledger.append(
                timestamp=timestamp,
                event_type=LedgerEventType.BUY_FILL,
                currency=self.currency,
                cash_delta=Money(-fill_cost, self.currency),
                exchange=exchange,
                symbol=clean_symbol,
                quantity_delta=quantity,
                execution_price=slipped_price,
                reference_id=reference_id,
            )

            fee_entry = None
            if fee.amount > Decimal("0"):
                fee_entry = self.ledger.append(
                    timestamp=timestamp,
                    event_type=LedgerEventType.FEE_CHARGE,
                    currency=self.currency,
                    cash_delta=-fee,
                    exchange=exchange,
                    symbol=clean_symbol,
                    reference_id=reference_id,
                )

            return fill_entry, fee_entry

        proceeds = slipped_price.amount * Decimal(quantity)
        avail_cash = self.ledger.get_cash_balance(self.currency)
        net_cash_after = avail_cash.amount + proceeds - fee.amount
        if net_cash_after < Decimal("0"):
            raise InsufficientFundsError(
                f"Insufficient funds for SELL fee: cash {avail_cash.amount} + proceeds {proceeds} < fee {fee.amount}"
            )

        self._apply_trade_to_position(
            exchange=exchange,
            symbol=clean_symbol,
            side="SELL",
            quantity=quantity,
            exec_price_amount=slipped_price.amount,
            allow_short=allow_short,
        )

        fill_entry = self.ledger.append(
            timestamp=timestamp,
            event_type=LedgerEventType.SELL_FILL,
            currency=self.currency,
            cash_delta=Money(proceeds, self.currency),
            exchange=exchange,
            symbol=clean_symbol,
            quantity_delta=-quantity,
            execution_price=slipped_price,
            reference_id=reference_id,
        )

        fee_entry = None
        if fee.amount > Decimal("0"):
            fee_entry = self.ledger.append(
                timestamp=timestamp,
                event_type=LedgerEventType.FEE_CHARGE,
                currency=self.currency,
                cash_delta=-fee,
                exchange=exchange,
                symbol=clean_symbol,
                reference_id=reference_id,
            )

        return fill_entry, fee_entry

    def snapshot(
        self,
        currency: Currency,
        mark_prices: Mapping[tuple[Exchange, str], Money],
        timestamp: datetime,
    ) -> PortfolioSnapshot:
        if currency != self.currency:
            raise CurrencyMismatchError(
                f"Snapshot currency {currency} does not match portfolio currency {self.currency}"
            )

        cash = self.ledger.get_cash_balance(self.currency)
        holdings_val = Decimal("0")
        unrealized = Decimal("0")
        realized = sum(self._realized_pnl_by_symbol.values(), Decimal("0"))

        positions_dict: dict[tuple[Exchange, str], Position] = {}
        for key, pos in self._positions.items():
            if pos.quantity != 0:
                mark = mark_prices.get(key)
                if mark is None:
                    raise ValueError(f"Missing mark price for open position {key}")
                if mark.currency != self.currency:
                    raise CurrencyMismatchError(
                        f"Mark price currency {mark.currency} mismatch with portfolio {self.currency}"
                    )
                basis = self._total_cost_basis.get(key, Decimal("0"))
                avg_cost_amount = basis / Decimal(abs(pos.quantity))
                pos_with_avg = Position(
                    exchange=pos.exchange,
                    symbol=pos.symbol,
                    currency=pos.currency,
                    quantity=pos.quantity,
                    average_cost=Money(avg_cost_amount, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )
                positions_dict[key] = pos_with_avg
                hv = mark.amount * Decimal(pos.quantity)
                if pos.quantity > 0:
                    ur = mark.amount * Decimal(pos.quantity) - basis
                else:
                    ur = basis - mark.amount * abs(Decimal(pos.quantity))
                holdings_val += hv
                unrealized += ur

        tot_equity = cash.amount + holdings_val

        return PortfolioSnapshot(
            timestamp=timestamp,
            currency=self.currency,
            cash=cash,
            holdings_value=Money(holdings_val, self.currency),
            total_equity=Money(tot_equity, self.currency),
            realized_pnl=Money(realized, self.currency),
            unrealized_pnl=Money(unrealized, self.currency),
            positions=positions_dict,
        )
