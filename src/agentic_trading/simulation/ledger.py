"""Append-only accounting ledger for simulation auditability and deterministic cash projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from agentic_trading.market_data.instruments import Currency, Money
from agentic_trading.market_data.models import Exchange


class LedgerEventType(str, Enum):
    """Categorization of discrete monetary and position ledger events."""

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY_FILL = "BUY_FILL"
    SELL_FILL = "SELL_FILL"
    FEE_CHARGE = "FEE_CHARGE"
    DIVIDEND_CREDIT = "DIVIDEND_CREDIT"

    @classmethod
    def _missing_(cls, value: object) -> LedgerEventType | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


@dataclass(frozen=True)
class LedgerEntry:
    """Immutable single accounting event record."""

    sequence_id: int
    timestamp: datetime
    event_type: LedgerEventType
    currency: Currency
    cash_delta: Money
    exchange: Exchange | None = None
    symbol: str | None = None
    quantity_delta: int = 0
    execution_price: Money | None = None
    reference_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.sequence_id, bool) or not isinstance(self.sequence_id, int) or self.sequence_id < 1:
            raise ValueError(f"sequence_id must be an integer >= 1, got {self.sequence_id}")

        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError("timestamp must be timezone-aware")

        if not isinstance(self.event_type, LedgerEventType):
            raise TypeError(f"event_type must be a LedgerEventType enum, got {type(self.event_type).__name__}")

        if not isinstance(self.currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(self.currency).__name__}")

        if not isinstance(self.cash_delta, Money):
            raise TypeError(f"cash_delta must be a Money instance, got {type(self.cash_delta).__name__}")
        if self.cash_delta.currency != self.currency:
            raise ValueError(f"cash_delta currency {self.cash_delta.currency} does not match entry {self.currency}")

        if self.exchange is not None and not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum or None, got {type(self.exchange).__name__}")

        if self.symbol is not None:
            if not isinstance(self.symbol, str) or not self.symbol.strip():
                raise ValueError("symbol must be a non-empty string when provided")
            object.__setattr__(self, "symbol", self.symbol.strip().upper())

        if isinstance(self.quantity_delta, bool) or not isinstance(self.quantity_delta, int):
            raise TypeError(f"quantity_delta must be an integer, got {type(self.quantity_delta).__name__}")

        if self.execution_price is not None:
            if not isinstance(self.execution_price, Money):
                raise TypeError(f"execution_price must be a Money instance, got {type(self.execution_price).__name__}")
            if self.execution_price.currency != self.currency:
                raise ValueError(
                    f"execution_price currency {self.execution_price.currency} does not match entry {self.currency}"
                )

        if not isinstance(self.reference_id, str):
            raise TypeError(f"reference_id must be a string, got {type(self.reference_id).__name__}")


class AccountingLedger:
    """Strictly append-only accounting ledger enforcing temporal ordering and deterministic projection."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def append(
        self,
        timestamp: datetime,
        event_type: LedgerEventType,
        currency: Currency,
        cash_delta: Money,
        exchange: Exchange | None = None,
        symbol: str | None = None,
        quantity_delta: int = 0,
        execution_price: Money | None = None,
        reference_id: str = "",
    ) -> LedgerEntry:
        if self._entries and timestamp < self._entries[-1].timestamp:
            raise ValueError(
                f"Out-of-order ledger timestamp {timestamp.isoformat()} is before previous entry "
                f"{self._entries[-1].timestamp.isoformat()}"
            )

        if event_type == LedgerEventType.DEPOSIT:
            if cash_delta.amount <= Decimal("0") or quantity_delta != 0:
                raise ValueError("DEPOSIT requires positive cash_delta and zero quantity_delta")
        elif event_type == LedgerEventType.WITHDRAWAL:
            if cash_delta.amount >= Decimal("0") or quantity_delta != 0:
                raise ValueError("WITHDRAWAL requires negative cash_delta and zero quantity_delta")
        elif event_type == LedgerEventType.BUY_FILL:
            if cash_delta.amount >= Decimal("0") or quantity_delta <= 0:
                raise ValueError("BUY_FILL requires negative cash_delta and positive quantity_delta")
            if execution_price is None or execution_price.amount <= Decimal("0"):
                raise ValueError("BUY_FILL requires positive execution_price")
        elif event_type == LedgerEventType.SELL_FILL:
            if cash_delta.amount <= Decimal("0") or quantity_delta >= 0:
                raise ValueError("SELL_FILL requires positive cash_delta and negative quantity_delta")
            if execution_price is None or execution_price.amount <= Decimal("0"):
                raise ValueError("SELL_FILL requires positive execution_price")
        elif event_type == LedgerEventType.FEE_CHARGE:
            if cash_delta.amount > Decimal("0") or quantity_delta != 0:
                raise ValueError("FEE_CHARGE requires non-positive cash_delta and zero quantity_delta")
        elif event_type == LedgerEventType.DIVIDEND_CREDIT:
            if cash_delta.amount <= Decimal("0") or quantity_delta != 0:
                raise ValueError("DIVIDEND_CREDIT requires positive cash_delta and zero quantity_delta")

        seq_id = len(self._entries) + 1
        entry = LedgerEntry(
            sequence_id=seq_id,
            timestamp=timestamp,
            event_type=event_type,
            currency=currency,
            cash_delta=cash_delta,
            exchange=exchange,
            symbol=symbol,
            quantity_delta=quantity_delta,
            execution_price=execution_price,
            reference_id=reference_id,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def get_cash_balance(self, currency: Currency) -> Money:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        total = sum(
            (entry.cash_delta.amount for entry in self._entries if entry.currency == currency),
            Decimal("0"),
        )
        return Money(total, currency)

    def get_position_quantity(self, exchange: Exchange, symbol: str) -> int:
        if not isinstance(exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_sym = symbol.strip().upper()
        return sum(
            entry.quantity_delta
            for entry in self._entries
            if entry.exchange == exchange and entry.symbol == clean_sym
        )

    def get_total_fees(self, currency: Currency) -> Money:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        total = -sum(
            (
                entry.cash_delta.amount
                for entry in self._entries
                if entry.currency == currency and entry.event_type == LedgerEventType.FEE_CHARGE
            ),
            Decimal("0"),
        )
        return Money(total, currency)

    def get_total_deposits(self, currency: Currency) -> Money:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        total = sum(
            (
                entry.cash_delta.amount
                for entry in self._entries
                if entry.currency == currency and entry.event_type == LedgerEventType.DEPOSIT
            ),
            Decimal("0"),
        )
        return Money(total, currency)

    def get_total_withdrawals(self, currency: Currency) -> Money:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        total = -sum(
            (
                entry.cash_delta.amount
                for entry in self._entries
                if entry.currency == currency and entry.event_type == LedgerEventType.WITHDRAWAL
            ),
            Decimal("0"),
        )
        return Money(total, currency)

    def get_total_dividends(self, currency: Currency) -> Money:
        if not isinstance(currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(currency).__name__}")
        total = sum(
            (
                entry.cash_delta.amount
                for entry in self._entries
                if entry.currency == currency and entry.event_type == LedgerEventType.DIVIDEND_CREDIT
            ),
            Decimal("0"),
        )
        return Money(total, currency)
