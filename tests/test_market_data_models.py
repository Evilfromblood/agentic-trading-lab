"""Unit tests for market data models (NSE/BSE equities).

Verifies immutability, timing semantics, Decimal precision preservation,
timezone enforcement, and rejection of non-finite or invalid numeric values.
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
    """Helper fixture providing a valid canonical completed candle."""
    open_time = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    close_time = open_time + timedelta(minutes=5)
    values = {
        "symbol": "RELIANCE",
        "exchange": Exchange.NSE,
        "interval": CandleInterval.M5,
        "open": Decimal("2450.00"),
        "high": Decimal("2455.50"),
        "low": Decimal("2448.25"),
        "close": Decimal("2452.10"),
        "volume": 12500,
        "timestamp": open_time,
        "source": "ZERODHA",
        "retrieval_timestamp": close_time + timedelta(seconds=1),
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


def test_candle_timing_semantics() -> None:
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    candle = sample_candle(timestamp=open_t, interval=CandleInterval.M5)
    assert candle.open_time == open_t
    assert candle.close_time == open_t + timedelta(minutes=5)
    assert candle.close_time - candle.open_time == timedelta(minutes=5)

    # 1-hour bar
    candle_1h = sample_candle(
        timestamp=open_t,
        interval=CandleInterval.H1,
        retrieval_timestamp=open_t + timedelta(hours=1, seconds=1),
    )
    assert candle_1h.close_time == open_t + timedelta(hours=1)


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


def test_rejection_of_float_prices_in_constructor() -> None:
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(open=2450.50)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(high=2455.50)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(low=2448.25)
    with pytest.raises(TypeError, match="cannot be float"):
        sample_candle(close=2452.10)


def test_rejection_of_float_prices_in_candle_create() -> None:
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_t = open_t + timedelta(minutes=5, seconds=1)

    with pytest.raises(TypeError, match="cannot be float"):
        Candle.create(
            symbol="INFY",
            exchange="NSE",
            interval="5m",
            open=1500.50,  # float rejected!
            high=Decimal("1510.00"),
            low=Decimal("1495.00"),
            close=Decimal("1505.00"),
            volume=1000,
            timestamp=open_t,
            source="ZERODHA",
            retrieval_timestamp=ret_t,
        )

    with pytest.raises(TypeError, match="cannot be float"):
        Candle.create(
            symbol="INFY",
            exchange="NSE",
            interval="5m",
            open=Decimal("1500.00"),
            high=1510.50,  # float rejected!
            low=Decimal("1495.00"),
            close=Decimal("1505.00"),
            volume=1000,
            timestamp=open_t,
            source="ZERODHA",
            retrieval_timestamp=ret_t,
        )


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


def test_rejection_of_tzinfo_with_none_offset() -> None:
    from datetime import tzinfo

    class DummyNoneOffset(tzinfo):
        def utcoffset(self, dt):
            return None

        def tzname(self, dt):
            return "DUMMY"

        def dst(self, dt):
            return timedelta(0)

    dt_bad = datetime(2026, 11, 2, 9, 15, tzinfo=DummyNoneOffset())
    with pytest.raises(ValueError, match="utcoffset returned None"):
        sample_candle(timestamp=dt_bad)


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

    candle_1h = sample_candle(
        interval=CandleInterval.H1,
        retrieval_timestamp=datetime(2026, 11, 2, 10, 16, tzinfo=IST),
    )
    assert candle_1h.interval.duration == timedelta(hours=1)

    candle_1d = sample_candle(
        interval=CandleInterval.D1,
        retrieval_timestamp=datetime(2026, 11, 3, 9, 16, tzinfo=IST),
    )
    assert candle_1d.interval.duration == timedelta(days=1)

    with pytest.raises(ValueError, match="Invalid interval"):
        sample_candle(interval="42m")

    with pytest.raises(TypeError, match="interval must be CandleInterval or str"):
        sample_candle(interval=5)


def test_symbol_character_restrictions_and_validation() -> None:
    # Valid symbols
    assert sample_candle(symbol="tcs").symbol == "TCS"
    assert sample_candle(symbol="m&m").symbol == "M&M"
    assert sample_candle(symbol="bajaj-auto").symbol == "BAJAJ-AUTO"
    assert sample_candle(symbol="nifty_50").symbol == "NIFTY_50"

    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        sample_candle(symbol="")

    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        sample_candle(symbol="   ")

    with pytest.raises(ValueError, match="symbol contains invalid characters"):
        sample_candle(symbol="RELIANCE IND")

    with pytest.raises(ValueError, match="symbol contains invalid characters"):
        sample_candle(symbol="TCS$")


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


def test_source_provenance_required() -> None:
    candle = sample_candle(source="  kite_connect  ")
    assert candle.source == "KITE_CONNECT"

    with pytest.raises(ValueError, match="source must be a non-empty string"):
        sample_candle(source="")

    # Candle.create requires explicit source and retrieval_timestamp
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_t = open_t + timedelta(minutes=5, seconds=1)

    with pytest.raises(ValueError, match="Explicit source provenance is required"):
        Candle.create(
            symbol="INFY",
            exchange="NSE",
            interval="5m",
            open=Decimal(1500),
            high=Decimal(1510),
            low=Decimal(1495),
            close=Decimal(1505),
            volume=1000,
            timestamp=open_t,
            source="",  # Empty source rejected!
            retrieval_timestamp=ret_t,
        )


def test_candle_helper_properties() -> None:
    bullish_candle = sample_candle(
        open=Decimal(100), close=Decimal(105), high=Decimal(110), low=Decimal(95)
    )
    assert bullish_candle.is_bullish is True
    assert bullish_candle.is_bearish is False
    assert bullish_candle.spread == Decimal(15)

    bearish_candle = sample_candle(
        open=Decimal(105), close=Decimal(100), high=Decimal(110), low=Decimal(95)
    )
    assert bearish_candle.is_bullish is False
    assert bearish_candle.is_bearish is True

    flat_candle = sample_candle(
        open=Decimal(100), close=Decimal(100), high=Decimal(100), low=Decimal(100)
    )
    assert flat_candle.is_bullish is True
    assert flat_candle.is_bearish is False
    assert flat_candle.spread == Decimal(0)


def test_candle_create_factory_valid() -> None:
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_t = open_t + timedelta(minutes=15, seconds=2)
    candle = Candle.create(
        symbol="infy",
        exchange="nse",
        interval="15m",
        open="1500.00",
        high="1510.00",
        low="1495.00",
        close="1505.50",
        volume=25000,
        candle_timestamp=open_t,
        source="NSE_FEED",
        retrieval_timestamp=ret_t,
    )
    assert candle.symbol == "INFY"
    assert candle.exchange == Exchange.NSE
    assert candle.interval == CandleInterval.M15
    assert candle.open == Decimal("1500.00")
    assert candle.volume == 25000
    assert candle.source == "NSE_FEED"
    assert candle.open_time == open_t
    assert candle.close_time == open_t + timedelta(minutes=15)
    assert candle.retrieval_timestamp == ret_t


def test_models_timezone_calculation_exception_safety() -> None:
    """Ensure _validate_timezone_aware wraps unexpected tzinfo exceptions in ValueError."""
    from datetime import tzinfo

    from agentic_trading.market_data.models import _validate_timezone_aware

    class CrashingTz(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("Corrupt timezone implementation")

        def tzname(self, dt):
            return "CRASH"

        def dst(self, dt):
            return timedelta(0)

    dt_bad = datetime(2026, 11, 2, 9, 15, tzinfo=CrashingTz())
    with pytest.raises(ValueError, match="timezone calculation failed"):
        _validate_timezone_aware(dt_bad, "test_field")


def test_candle_create_rejects_boolean_prices() -> None:
    """Ensure Candle.create strictly rejects boolean prices with TypeError."""
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_t = open_t + timedelta(minutes=5, seconds=1)

    for bad_field in ["open", "high", "low", "close"]:
        kwargs = {
            "symbol": "TCS",
            "exchange": "NSE",
            "interval": "5m",
            "open": Decimal("3500.00"),
            "high": Decimal("3510.00"),
            "low": Decimal("3495.00"),
            "close": Decimal("3505.00"),
            "volume": 5000,
            "timestamp": open_t,
            "source": "ZERODHA",
            "retrieval_timestamp": ret_t,
        }
        kwargs[bad_field] = True
        with pytest.raises(TypeError, match="cannot be a boolean"):
            Candle.create(**kwargs)


def test_candle_create_factory_validation_and_bypass_rejections() -> None:
    """Ensure Candle.create enforces explicit provenance, timestamps, and rejects floats."""
    open_t = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    ret_t = open_t + timedelta(minutes=5, seconds=1)

    base = {
        "symbol": "TCS",
        "exchange": "NSE",
        "interval": "5m",
        "open": Decimal("3500.00"),
        "high": Decimal("3510.00"),
        "low": Decimal("3495.00"),
        "close": Decimal("3505.00"),
        "volume": 5000,
        "source": "ZERODHA",
        "retrieval_timestamp": ret_t,
        "timestamp": open_t,
    }

    # Missing retrieval_timestamp
    kw_no_ret = dict(base)
    kw_no_ret["retrieval_timestamp"] = None
    with pytest.raises(ValueError, match="Explicit retrieval_timestamp is required"):
        Candle.create(**kw_no_ret)

    # Missing source / data_source
    kw_no_src = dict(base)
    kw_no_src["source"] = ""
    with pytest.raises(ValueError, match="Explicit source provenance is required"):
        Candle.create(**kw_no_src)

    # Missing timestamp
    kw_no_ts = dict(base)
    kw_no_ts["timestamp"] = None
    with pytest.raises(ValueError, match="Candle timestamp.*must be explicitly provided"):
        Candle.create(**kw_no_ts)

    # Rejection of float prices
    kw_float = dict(base)
    kw_float["open"] = 3500.50
    with pytest.raises(TypeError, match="cannot be float"):
        Candle.create(**kw_float)
