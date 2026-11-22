"""Market-specific transaction fee models and adverse slippage calculators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from agentic_trading.market_data.instruments import Currency, CurrencyMismatchError, Money
from agentic_trading.market_data.models import Exchange


class FeeModel(ABC):
    """Abstract interface for exchange and broker transaction cost computation."""

    @abstractmethod
    def calculate_fees(
        self,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        price: Money,
    ) -> Money:
        """Calculate total transaction costs for a filled execution."""


class IndiaEquityFeeModel(FeeModel):
    """Statutory and broker fee calculator for Indian equity transactions (NSE/BSE)."""

    def __init__(
        self,
        brokerage_rate: Decimal = Decimal("0.0003"),
        brokerage_cap: Money | None = None,
        stt_rate: Decimal = Decimal("0.001"),
        exchange_txn_fee_rate: Decimal = Decimal("0.0000345"),
        sebi_turnover_rate: Decimal = Decimal("0.000001"),
        stamp_duty_rate: Decimal = Decimal("0.00015"),
        gst_rate: Decimal = Decimal("0.18"),
    ) -> None:
        for name, rate in (
            ("brokerage_rate", brokerage_rate),
            ("stt_rate", stt_rate),
            ("exchange_txn_fee_rate", exchange_txn_fee_rate),
            ("sebi_turnover_rate", sebi_turnover_rate),
            ("stamp_duty_rate", stamp_duty_rate),
            ("gst_rate", gst_rate),
        ):
            if isinstance(rate, (bool, float)) or not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise ValueError(f"{name} must be a non-negative finite Decimal, got {rate}")

        if brokerage_cap is not None:
            if not isinstance(brokerage_cap, Money):
                raise TypeError(f"brokerage_cap must be a Money instance, got {type(brokerage_cap).__name__}")
            if brokerage_cap.currency != Currency.INR:
                raise CurrencyMismatchError(f"brokerage_cap currency must be INR, got {brokerage_cap.currency}")
            if brokerage_cap.amount < 0:
                raise ValueError(f"brokerage_cap amount must be non-negative, got {brokerage_cap.amount}")

        self.brokerage_rate = brokerage_rate
        self.brokerage_cap = brokerage_cap or Money(Decimal("20.00"), Currency.INR)
        self.stt_rate = stt_rate
        self.exchange_txn_fee_rate = exchange_txn_fee_rate
        self.sebi_turnover_rate = sebi_turnover_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.gst_rate = gst_rate

    def calculate_fees(
        self,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        price: Money,
    ) -> Money:
        if not isinstance(price, Money):
            raise TypeError(f"price must be a Money instance, got {type(price).__name__}")
        if price.amount <= Decimal("0"):
            raise ValueError(f"price must be strictly positive, got {price.amount}")
        if price.currency != Currency.INR:
            raise CurrencyMismatchError(f"IndiaEquityFeeModel requires INR, got {price.currency}")
        if exchange not in (Exchange.NSE, Exchange.BSE):
            raise ValueError(f"IndiaEquityFeeModel unsupported exchange: {exchange}")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError(f"quantity must be a positive integer, got {quantity}")

        clean_side = side.strip().upper()
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")

        turnover = price.amount * Decimal(quantity)
        brokerage = min(turnover * self.brokerage_rate, self.brokerage_cap.amount)
        stt = turnover * self.stt_rate
        exchange_fee = turnover * self.exchange_txn_fee_rate
        sebi_fee = turnover * self.sebi_turnover_rate
        stamp_duty = (turnover * self.stamp_duty_rate) if clean_side == "BUY" else Decimal("0")
        gst = (brokerage + exchange_fee + sebi_fee) * self.gst_rate

        total = (brokerage + stt + exchange_fee + sebi_fee + stamp_duty + gst).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        return Money(total, Currency.INR)


class USEquityFeeModel(FeeModel):
    """Commission and regulatory fee model for US equity markets (NYSE/NASDAQ)."""

    def __init__(
        self,
        per_share_rate: Decimal = Decimal("0.005"),
        min_commission: Money | None = None,
        max_commission_pct: Decimal = Decimal("0.005"),
        sec_fee_rate: Decimal = Decimal("0.0000278"),
        taf_rate: Decimal = Decimal("0.000166"),
    ) -> None:
        for name, rate in (
            ("per_share_rate", per_share_rate),
            ("max_commission_pct", max_commission_pct),
            ("sec_fee_rate", sec_fee_rate),
            ("taf_rate", taf_rate),
        ):
            if isinstance(rate, (bool, float)) or not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise ValueError(f"{name} must be a non-negative finite Decimal, got {rate}")

        if min_commission is not None:
            if not isinstance(min_commission, Money):
                raise TypeError(f"min_commission must be a Money instance, got {type(min_commission).__name__}")
            if min_commission.currency != Currency.USD:
                raise CurrencyMismatchError(f"min_commission currency must be USD, got {min_commission.currency}")
            if min_commission.amount < 0:
                raise ValueError(f"min_commission amount must be non-negative, got {min_commission.amount}")

        self.per_share_rate = per_share_rate
        self.min_commission = min_commission or Money(Decimal("1.00"), Currency.USD)
        self.max_commission_pct = max_commission_pct
        self.sec_fee_rate = sec_fee_rate
        self.taf_rate = taf_rate

    def calculate_fees(
        self,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        price: Money,
    ) -> Money:
        if not isinstance(price, Money):
            raise TypeError(f"price must be a Money instance, got {type(price).__name__}")
        if price.amount <= Decimal("0"):
            raise ValueError(f"price must be strictly positive, got {price.amount}")
        if price.currency != Currency.USD:
            raise CurrencyMismatchError(f"USEquityFeeModel requires USD, got {price.currency}")
        if exchange not in (Exchange.NYSE, Exchange.NASDAQ):
            raise ValueError(f"USEquityFeeModel unsupported exchange: {exchange}")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError(f"quantity must be a positive integer, got {quantity}")

        clean_side = side.strip().upper()
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")

        turnover = price.amount * Decimal(quantity)
        raw_comm = Decimal(quantity) * self.per_share_rate
        capped_comm = min(raw_comm, turnover * self.max_commission_pct)
        commission = max(self.min_commission.amount, capped_comm)

        sec_fee = (turnover * self.sec_fee_rate) if clean_side == "SELL" else Decimal("0")
        taf_fee = min(Decimal(quantity) * self.taf_rate, Decimal("8.30")) if clean_side == "SELL" else Decimal("0")

        total = (commission + sec_fee + taf_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        return Money(total, Currency.USD)


class ZeroFeeModel(FeeModel):
    """Frictionless fee model returning zero costs for idealized baseline simulations."""

    def calculate_fees(
        self,
        exchange: Exchange,
        symbol: str,
        side: str,
        quantity: int,
        price: Money,
    ) -> Money:
        return Money(Decimal("0.00"), price.currency)


class SlippageModel(ABC):
    """Abstract interface for simulated adverse price impact."""

    @abstractmethod
    def calculate_slippage(self, price: Money, side: str, tick_size: Decimal) -> Money:
        """Compute execution price after incorporating adverse slippage."""


class BasisPointsSlippageModel(SlippageModel):
    """Adverse price movement parameterized in basis points and quantized to tick size."""

    def __init__(self, basis_points: Decimal = Decimal("5")) -> None:
        if (
            isinstance(basis_points, (bool, float))
            or not isinstance(basis_points, Decimal)
            or not basis_points.is_finite()
            or basis_points < 0
        ):
            raise ValueError(f"basis_points must be a non-negative finite Decimal, got {basis_points}")
        self.basis_points = basis_points

    def calculate_slippage(self, price: Money, side: str, tick_size: Decimal) -> Money:
        if not isinstance(price, Money):
            raise TypeError(f"price must be a Money instance, got {type(price).__name__}")
        if (
            isinstance(tick_size, (bool, float))
            or not isinstance(tick_size, Decimal)
            or not tick_size.is_finite()
            or tick_size <= 0
        ):
            raise ValueError(f"tick_size must be a positive finite Decimal, got {tick_size}")

        clean_side = side.strip().upper()
        if clean_side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")

        factor = self.basis_points / Decimal("10000")
        if clean_side == "BUY":
            effective = price.amount * (Decimal("1") + factor)
            ticks = (effective / tick_size).to_integral_value(rounding=ROUND_CEILING)
            q_effective = max(tick_size, ticks * tick_size)
        else:
            effective = price.amount * (Decimal("1") - factor)
            ticks = (effective / tick_size).to_integral_value(rounding=ROUND_FLOOR)
            q_effective = max(tick_size, ticks * tick_size)

        return Money(q_effective, price.currency)
