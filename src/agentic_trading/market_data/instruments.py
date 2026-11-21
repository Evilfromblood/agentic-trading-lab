"""Cross-market instrument and currency core models and registry."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from agentic_trading.market_data.models import Exchange, _deep_freeze


class Currency(str, Enum):
    """Supported trading currencies."""

    INR = "INR"
    USD = "USD"

    @classmethod
    def _missing_(cls, value: object) -> Currency | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


class CurrencyMismatchError(ValueError):
    """Raised when an operation combines incompatible currencies."""


@dataclass(frozen=True)
class Money:
    """Immutable monetary representation enforcing strict currency discipline."""

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.amount, (float, bool, bytes)):
            raise TypeError(f"amount cannot be of type {type(self.amount).__name__}")
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"amount must be a Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError(f"amount must be finite, got {self.amount}")
        if not isinstance(self.currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(self.currency).__name__}")

    def __add__(self, other: Any) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Cannot add monetary amounts with mismatched currencies: {self.currency} and {other.currency}"
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Any) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Cannot subtract monetary amounts with mismatched currencies: {self.currency} and {other.currency}"
            )
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def __mul__(self, scalar: Any) -> Money:
        if isinstance(scalar, (bool, float)):
            raise TypeError(f"Cannot multiply Money by scalar of type {type(scalar).__name__}")
        if isinstance(scalar, (Decimal, int)):
            dec_scalar = Decimal(scalar) if isinstance(scalar, int) else scalar
            if not dec_scalar.is_finite():
                raise ValueError(f"Scalar must be finite, got {dec_scalar}")
            return Money(amount=self.amount * dec_scalar, currency=self.currency)
        return NotImplemented

    def __rmul__(self, scalar: Any) -> Money:
        return self.__mul__(scalar)


class AssetClass(str, Enum):
    """Supported asset classes."""

    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"

    @classmethod
    def _missing_(cls, value: object) -> AssetClass | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


@dataclass(frozen=True)
class Instrument:
    """Canonical cross-market financial instrument definition."""

    symbol: str
    exchange: Exchange
    currency: Currency
    asset_class: AssetClass = AssetClass.EQUITY
    tick_size: Decimal = Decimal("0.01")
    lot_size: int = 1
    isin: str | None = None
    provider_tokens: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", clean_symbol)

        if not isinstance(self.exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(self.exchange).__name__}")
        if not isinstance(self.currency, Currency):
            raise TypeError(f"currency must be a Currency enum, got {type(self.currency).__name__}")
        if not isinstance(self.asset_class, AssetClass):
            raise TypeError(f"asset_class must be an AssetClass enum, got {type(self.asset_class).__name__}")

        if self.exchange in (Exchange.NSE, Exchange.BSE):
            if self.currency != Currency.INR:
                raise CurrencyMismatchError(
                    f"Exchange {self.exchange} requires Currency.INR, got {self.currency}"
                )
        elif self.exchange in (Exchange.NYSE, Exchange.NASDAQ):
            if self.currency != Currency.USD:
                raise CurrencyMismatchError(
                    f"Exchange {self.exchange} requires Currency.USD, got {self.currency}"
                )
        else:
            raise ValueError(f"Unsupported exchange: {self.exchange}")

        if (
            isinstance(self.tick_size, (bool, float))
            or not isinstance(self.tick_size, Decimal)
            or not self.tick_size.is_finite()
            or self.tick_size <= 0
        ):
            raise ValueError(f"tick_size must be a positive finite Decimal, got {self.tick_size}")

        if isinstance(self.lot_size, bool) or not isinstance(self.lot_size, int) or self.lot_size < 1:
            raise ValueError(f"lot_size must be an integer >= 1, got {self.lot_size}")

        if self.isin is not None:
            if not isinstance(self.isin, str) or not self.isin.strip():
                raise ValueError("isin must be a non-empty string when provided")
            object.__setattr__(self, "isin", self.isin.strip().upper())

        object.__setattr__(self, "provider_tokens", _deep_freeze(dict(self.provider_tokens)))


class UnknownInstrumentError(KeyError):
    """Raised when an instrument is not found in the registry."""


class DuplicateInstrumentError(ValueError):
    """Raised when registering an instrument with an existing identity or token."""


class InstrumentRegistry:
    """Thread-safe in-memory registry of traded instruments."""

    def __init__(self) -> None:
        self._by_exchange_symbol: dict[tuple[Exchange, str], Instrument] = {}
        self._by_provider_token: dict[tuple[str, str], Instrument] = {}

    def register(self, instrument: Instrument) -> None:
        if not isinstance(instrument, Instrument):
            raise TypeError(f"instrument must be an Instrument instance, got {type(instrument).__name__}")
        key = (instrument.exchange, instrument.symbol)
        if key in self._by_exchange_symbol:
            raise DuplicateInstrumentError(
                f"Instrument already registered for exchange and symbol: {instrument.exchange.value}:{instrument.symbol}"
            )
        for provider, token in instrument.provider_tokens.items():
            pt_key = (provider, token)
            if pt_key in self._by_provider_token:
                raise DuplicateInstrumentError(
                    f"Provider token already registered: provider '{provider}', token '{token}'"
                )
        self._by_exchange_symbol[key] = instrument
        for provider, token in instrument.provider_tokens.items():
            self._by_provider_token[(provider, token)] = instrument

    def get(self, exchange: Exchange, symbol: str) -> Instrument:
        if not isinstance(exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = symbol.strip().upper()
        inst = self._by_exchange_symbol.get((exchange, clean_symbol))
        if inst is None:
            raise UnknownInstrumentError(f"No instrument found for {exchange.value}:{clean_symbol}")
        return inst

    def get_by_token(self, provider: str, token: str) -> Instrument:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        inst = self._by_provider_token.get((provider.strip(), token.strip()))
        if inst is None:
            raise UnknownInstrumentError(f"No instrument found for provider '{provider}' and token '{token}'")
        return inst

    def list_by_exchange(self, exchange: Exchange) -> tuple[Instrument, ...]:
        if not isinstance(exchange, Exchange):
            raise TypeError(f"exchange must be an Exchange enum, got {type(exchange).__name__}")
        return tuple(inst for (ex, _), inst in self._by_exchange_symbol.items() if ex == exchange)
