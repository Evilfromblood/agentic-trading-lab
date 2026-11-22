"""Multi-currency portfolio state, holding projections, and balance snapshot generator."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

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

        if ledger is not None and ledger.entries:
            self._replay_ledger(ledger.entries)

    def _replay_ledger(self, entries: tuple[LedgerEntry, ...]) -> None:
        for entry in entries:
            if entry.currency != self.currency:
                continue
            if entry.event_type == LedgerEventType.BUY_FILL and entry.exchange and entry.symbol:
                key = (entry.exchange, entry.symbol)
                curr = self._positions.get(key)
                curr_qty = curr.quantity if curr else 0
                curr_avg = curr.average_cost.amount if curr else Decimal("0")
                price = entry.execution_price.amount if entry.execution_price else Decimal("0")
                qty = entry.quantity_delta
                if curr_qty < 0:
                    covering = min(qty, abs(curr_qty))
                    pnl = (curr_avg - price) * Decimal(covering)
                    self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + pnl
                    rem = qty - covering
                    if rem == 0:
                        new_q = curr_qty + covering
                        if new_q == 0:
                            self._positions.pop(key, None)
                        else:
                            self._positions[key] = Position(
                                entry.exchange,
                                entry.symbol,
                                self.currency,
                                new_q,
                                Money(curr_avg, self.currency),
                                Money(self._realized_pnl_by_symbol[key], self.currency),
                            )
                    else:
                        self._positions[key] = Position(
                            entry.exchange,
                            entry.symbol,
                            self.currency,
                            rem,
                            Money(price, self.currency),
                            Money(self._realized_pnl_by_symbol[key], self.currency),
                        )
                else:
                    new_q = curr_qty + qty
                    prior_cost = curr_avg * Decimal(curr_qty)
                    add_cost = price * Decimal(qty)
                    new_avg = (prior_cost + add_cost) / Decimal(new_q) if new_q > 0 else Decimal("0")
                    self._positions[key] = Position(
                        entry.exchange,
                        entry.symbol,
                        self.currency,
                        new_q,
                        Money(new_avg, self.currency),
                        Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                    )
            elif entry.event_type == LedgerEventType.SELL_FILL and entry.exchange and entry.symbol:
                key = (entry.exchange, entry.symbol)
                curr = self._positions.get(key)
                curr_qty = curr.quantity if curr else 0
                curr_avg = curr.average_cost.amount if curr else Decimal("0")
                price = entry.execution_price.amount if entry.execution_price else Decimal("0")
                qty = abs(entry.quantity_delta)
                if curr_qty <= 0:
                    exist_cost = curr_avg * abs(Decimal(curr_qty))
                    add_cost = price * Decimal(qty)
                    new_q = curr_qty - qty
                    new_avg = (exist_cost + add_cost) / abs(Decimal(new_q)) if new_q != 0 else Decimal("0")
                    self._positions[key] = Position(
                        entry.exchange,
                        entry.symbol,
                        self.currency,
                        new_q,
                        Money(new_avg, self.currency),
                        Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                    )
                else:
                    if qty > curr_qty:
                        pnl = (price - curr_avg) * Decimal(curr_qty)
                        self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + pnl
                        rem = qty - curr_qty
                        self._positions[key] = Position(
                            entry.exchange,
                            entry.symbol,
                            self.currency,
                            -rem,
                            Money(price, self.currency),
                            Money(self._realized_pnl_by_symbol[key], self.currency),
                        )
                    else:
                        pnl = (price - curr_avg) * Decimal(qty)
                        self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + pnl
                        new_q = curr_qty - qty
                        if new_q == 0:
                            self._positions.pop(key, None)
                        else:
                            self._positions[key] = Position(
                                entry.exchange,
                                entry.symbol,
                                self.currency,
                                new_q,
                                Money(curr_avg, self.currency),
                                Money(self._realized_pnl_by_symbol[key], self.currency),
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

        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(f"quantity must be a positive integer, got {quantity}")

        clean_side = side.strip().upper()
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")

        slipped_price = self.slippage_model.calculate_slippage(execution_price, clean_side, tick_size)
        fee = self.fee_model.calculate_fees(exchange, clean_symbol, clean_side, quantity, slipped_price)

        key = (exchange, clean_symbol)
        curr_pos = self._positions.get(key)
        curr_qty = curr_pos.quantity if curr_pos is not None else 0
        curr_avg = curr_pos.average_cost.amount if curr_pos is not None else Decimal("0")

        if clean_side == "BUY":
            fill_cost = slipped_price.amount * Decimal(quantity)
            total_required_cash = fill_cost + fee.amount
            avail_cash = self.ledger.get_cash_balance(self.currency)

            if avail_cash.amount < total_required_cash:
                raise InsufficientFundsError(
                    f"Insufficient cash for BUY fill: required {total_required_cash}, available {avail_cash.amount}"
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

            if curr_qty < 0:
                covering = min(quantity, abs(curr_qty))
                short_pnl = (curr_avg - slipped_price.amount) * Decimal(covering)
                self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + short_pnl
                rem = quantity - covering
                if rem == 0:
                    new_q = curr_qty + covering
                    if new_q == 0:
                        self._positions.pop(key, None)
                    else:
                        self._positions[key] = Position(
                            exchange=exchange,
                            symbol=clean_symbol,
                            currency=self.currency,
                            quantity=new_q,
                            average_cost=Money(curr_avg, self.currency),
                            realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                        )
                else:
                    self._positions[key] = Position(
                        exchange=exchange,
                        symbol=clean_symbol,
                        currency=self.currency,
                        quantity=rem,
                        average_cost=slipped_price,
                        realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                    )
            else:
                new_q = curr_qty + quantity
                prior_cost = curr_avg * Decimal(curr_qty)
                add_cost = fill_cost
                new_avg = (prior_cost + add_cost) / Decimal(new_q)
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=clean_symbol,
                    currency=self.currency,
                    quantity=new_q,
                    average_cost=Money(new_avg, self.currency),
                    realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
                )

            return fill_entry, fee_entry

        proceeds = slipped_price.amount * Decimal(quantity)
        avail_cash = self.ledger.get_cash_balance(self.currency)
        net_cash_after = avail_cash.amount + proceeds - fee.amount
        if net_cash_after < Decimal("0"):
            raise InsufficientFundsError(
                f"Insufficient funds for SELL fee: cash {avail_cash.amount} + proceeds {proceeds} < fee {fee.amount}"
            )

        if curr_qty <= 0:
            if not allow_short:
                raise InsufficientPositionError(
                    f"Cannot short sell {quantity} shares of {clean_symbol}; allow_short is False"
                )
            exist_cost = curr_avg * abs(Decimal(curr_qty))
            add_cost = proceeds
            new_q = curr_qty - quantity
            new_avg = (exist_cost + add_cost) / abs(Decimal(new_q))
            self._positions[key] = Position(
                exchange=exchange,
                symbol=clean_symbol,
                currency=self.currency,
                quantity=new_q,
                average_cost=Money(new_avg, self.currency),
                realized_pnl=Money(self._realized_pnl_by_symbol.get(key, Decimal("0")), self.currency),
            )
        else:
            if quantity > curr_qty:
                if not allow_short:
                    raise InsufficientPositionError(
                        f"Cannot sell {quantity} shares of {clean_symbol}, current position is {curr_qty}"
                    )
                long_pnl = (slipped_price.amount - curr_avg) * Decimal(curr_qty)
                self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + long_pnl
                rem_short = quantity - curr_qty
                self._positions[key] = Position(
                    exchange=exchange,
                    symbol=clean_symbol,
                    currency=self.currency,
                    quantity=-rem_short,
                    average_cost=slipped_price,
                    realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
                )
            else:
                trade_pnl = (slipped_price.amount - curr_avg) * Decimal(quantity)
                self._realized_pnl_by_symbol[key] = self._realized_pnl_by_symbol.get(key, Decimal("0")) + trade_pnl
                new_q = curr_qty - quantity
                if new_q == 0:
                    self._positions.pop(key, None)
                else:
                    self._positions[key] = Position(
                        exchange=exchange,
                        symbol=clean_symbol,
                        currency=self.currency,
                        quantity=new_q,
                        average_cost=Money(curr_avg, self.currency),
                        realized_pnl=Money(self._realized_pnl_by_symbol[key], self.currency),
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

        for key, pos in self._positions.items():
            if pos.quantity != 0:
                mark = mark_prices.get(key)
                if mark is None:
                    raise ValueError(f"Missing mark price for open position {key}")
                if mark.currency != self.currency:
                    raise CurrencyMismatchError(
                        f"Mark price currency {mark.currency} mismatch with portfolio {self.currency}"
                    )
                hv = mark.amount * Decimal(pos.quantity)
                if pos.quantity > 0:
                    ur = (mark.amount - pos.average_cost.amount) * Decimal(pos.quantity)
                else:
                    ur = (pos.average_cost.amount - mark.amount) * abs(Decimal(pos.quantity))
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
            positions=dict(self._positions),
        )
