"""Unit tests for market data models (NSE/BSE equities).

Verifies immutability, Decimal precision preservation, timezone enforcement,
and rejection of non-finite or invalid numeric values.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
)


def sample_candle(**overrides) -> Candle:
    """Helper fixture providing a valid canonical candle."""
    base_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    values = {
        "symbol": "RELIANCE",
        "exchange": Exchange.NSE,
        "interval": CandleInterval.M5,
        "open": Decimal("2450.00"),
        "high": Decimal("2455.50"),
        "low": Decimal("2448.25"),
        "close": Decimal("2452.10"),
        "volume": 12500,
        "timestamp": base_time,
        "source": "ZERODHA",
        "retrieval_timestamp": base_time + timedelta(seconds=1),
    }
    values.update(overrides)
    return Candle(**values)


def test_valid_candle_creation_and_attributes() -> None:
    candle = sample_candle()
    assert candle.symbol == "RELIANCE"
    assert candle.exchange == Exchange.NSE
    assert candle.interval == CandleInterval.M5
    assert candle.open == Decimal("2450.00")
    assert candle.high == Decimal("2455.50")
    assert candle.low == Decimal("2448.25")
    assert candle.close == Decimal("2452.10")
    assert candle.volume == 12500
    assert candle.source == "ZERODHA"
    assert candle.timestamp.tzinfo is not None
    assert candle.candle_timestamp == candle.timestamp
    assert candle.data_source == "ZERODHA"


def test_candle_immutability() -> None:
    candle = sample_candle()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        candle.open = Decimal("2500.00")  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        candle.volume = 99999  # type: ignore[misc]


def test_decimal_precision_preservation() -> None:
    high_precision_val = Decimal("2450.1234567890123456789")
    candle = sample_candle(open=high_precision_val)
    assert candle.open == high_precision_val
    assert str(candle.open) == "2450.1234567890123456789"


def test_rejection_of_float_prices() -> None:
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(open=2450.50)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(high=2455.50)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(low=2448.25)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(close=2452.10)


def test_rejection_of_boolean_prices() -> None:
    with pytest.raises(TypeError, match="cannot be a boolean"):
        sample_candle(open=True)


def test_rejection_of_non_finite_numeric_values() -> None:
    with pytest.raises(ValueError, match="must be a finite number"):
        sample_candle(open=Decimal("NaN"))
    with pytest.raises(ValueError, match="must be a finite number"):
        sample_candle(high=Decimal("Infinity"))
    with pytest.raises(ValueError, match="must be a finite number"):
        sample_candle(low=Decimal("-Infinity"))


def test_rejection_of_invalid_decimal_strings() -> None:
    with pytest.raises(ValueError, match="Invalid decimal value"):
        sample_candle(close="not-a-valid-price")


def test_rejection_of_naive_datetimes() -> None:
    naive_dt = datetime(2026, 11, 2, 9, 15)  # tzinfo=None
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        sample_candle(timestamp=naive_dt)

    aware_dt = datetime(2026, 11, 2, 9, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="retrieval_timestamp must be timezone-aware"):
        sample_candle(timestamp=aware_dt, retrieval_timestamp=naive_dt)


def test_rejection_of_invalid_datetime_types() -> None:
    with pytest.raises(TypeError, match="timestamp must be a datetime"):
        sample_candle(timestamp="2026-11-02T09:15:00Z")


def test_exchange_enum_and_string_normalization() -> None:
    candle_bse = sample_candle(exchange="bse")
    assert candle_bse.exchange == Exchange.BSE

    with pytest.raises(ValueError, match="Invalid exchange"):
        sample_candle(exchange="NASDAQ")

    with pytest.raises(TypeError, match="exchange must be Exchange or str"):
        sample_candle(exchange=123)


def test_interval_enum_and_duration_property() -> None:
    candle_1m = sample_candle(interval="1m")
    assert candle_1m.interval == CandleInterval.M1
    assert candle_1m.interval.duration == timedelta(minutes=1)

    candle_1h = sample_candle(interval=CandleInterval.H1)
    assert candle_1h.interval.duration == timedelta(hours=1)

    candle_1d = sample_candle(interval=CandleInterval.D1)
    assert candle_1d.interval.duration == timedelta(days=1)

    with pytest.raises(ValueError, match="Invalid interval"):
        sample_candle(interval="42m")

    with pytest.raises(TypeError, match="interval must be CandleInterval or str"):
        sample_candle(interval=5)


def test_symbol_normalization_and_validation() -> None:
    candle = sample_candle(symbol="  tcs  ")
    assert candle.symbol == "TCS"

    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        sample_candle(symbol="")

    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        sample_candle(symbol="   ")

    with pytest.raises(ValueError, match="symbol must not contain whitespace"):
        sample_candle(symbol="RELIANCE IND")


def test_volume_validation_rules() -> None:
    candle_zero_vol = sample_candle(volume=0)
    assert candle_zero_vol.volume == 0

    with pytest.raises(TypeError, match="volume cannot be a boolean"):
        sample_candle(volume=True)

    with pytest.raises(TypeError, match="volume cannot be float"):
        sample_candle(volume=100.5)

    with pytest.raises(ValueError, match="volume must be an integer"):
        sample_candle(volume=Decimal("100.25"))

    candle_dec_int = sample_candle(volume=Decimal(5000))
    assert candle_dec_int.volume == 5000


def test_source_normalization_and_validation() -> None:
    candle = sample_candle(source="  kite_connect  ")
    assert candle.source == "KITE_CONNECT"

    with pytest.raises(ValueError, match="source must be a non-empty string"):
        sample_candle(source="")


def test_candle_helper_properties() -> None:
    bullish_candle = sample_candle(open=Decimal(100), close=Decimal(105), high=Decimal(110), low=Decimal(95))
    assert bullish_candle.is_bullish is True
    assert bullish_candle.is_bearish is False
    assert bullish_candle.spread == Decimal(15)

    bearish_candle = sample_candle(open=Decimal(105), close=Decimal(100), high=Decimal(110), low=Decimal(95))
    assert bearish_candle.is_bullish is False
    assert bearish_candle.is_bearish is True

    flat_candle = sample_candle(open=Decimal(100), close=Decimal(100), high=Decimal(100), low=Decimal(100))
    assert flat_candle.is_bullish is True
    assert flat_candle.is_bearish is False
    assert flat_candle.spread == Decimal(0)


def test_candle_create_factory() -> None:
    ts = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = Candle.create(
        symbol="infy",
        exchange="nse",
        interval="15m",
        open="1500.00",
        high="1510.00",
        low="1495.00",
        close="1505.50",
        volume=25000,
        candle_timestamp=ts,
        data_source="NSE_FEED",
    )
    assert candle.symbol == "INFY"
    assert candle.exchange == Exchange.NSE
    assert candle.interval == CandleInterval.M15
    assert candle.open == Decimal("1500.00")
    assert candle.volume == 25000
    assert candle.source == "NSE_FEED"
    assert candle.candle_timestamp == ts
    assert candle.retrieval_timestamp == ts
