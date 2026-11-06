"""Provider adapters for normalizing external market data payloads into domain Candles.

Translates provider-specific records into the canonical internal Candle model,
performing strict raw data validation without silently repairing invalid data
or fabricating missing records.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from agentic_trading.market_data.models import (
    Candle,
    CandleInterval,
    Exchange,
)

# Numeric parsing limits and patterns (Finding L-5)
MAX_PRICE_STR_LENGTH: int = 18
MAX_PRICE: Decimal = Decimal("10000000.00")  # 10 million INR (1 crore per share)
MIN_PRICE: Decimal = Decimal("0.0001")       # Minimum positive price unit
PRICE_ASCII_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

MAX_VOLUME_STR_LENGTH: int = 15
MAX_VOLUME: int = 10_000_000_000_000         # 10 trillion units
MIN_VOLUME: int = 0
VOLUME_ASCII_PATTERN = re.compile(r"^[0-9]+$")


class RawDataValidationError(ValueError):
    """Raised when an external market data payload violates structural or type invariants."""


class ProviderAdapter(ABC):
    """Abstract adapter translating raw provider records to canonical Candle instances."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the data source for provenance tracking."""

    @abstractmethod
    def adapt_record(
        self,
        raw_record: Mapping[str, Any],
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        retrieval_timestamp: datetime,
    ) -> Candle:
        """Normalize a single provider record into a canonical Candle domain model."""


class StandardDictAdapter(ProviderAdapter):
    """Standard adapter normalizing dictionary-based provider payloads into Candle models.

    Args:
        source_name: Name of the data source for provenance tracking.
        require_payload_identity: When True, requires 'symbol', 'exchange', and 'interval'
            to be present in the raw payload and match the request. When False (default),
            omitted identity fields are stamped from the request context, and the caller
            assumes responsibility for ensuring the provider supplied records for the
            correct instrument.
    """

    def __init__(
        self,
        source_name: str = "EXTERNAL_PROVIDER",
        require_payload_identity: bool = False,
    ) -> None:
        self._source_name = source_name
        self._require_payload_identity = require_payload_identity

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def require_payload_identity(self) -> bool:
        return self._require_payload_identity

    def _parse_decimal(self, raw_value: Any, field_name: str) -> Decimal:
        if raw_value is None:
            raise RawDataValidationError(f"Missing required price field '{field_name}' in raw payload")
        if isinstance(raw_value, bool):
            raise RawDataValidationError(f"Price field '{field_name}' cannot be boolean")
        if isinstance(raw_value, bytes):
            raise RawDataValidationError(f"Price field '{field_name}' cannot be bytes")
        if isinstance(raw_value, float):
            raise RawDataValidationError(
                f"Price field '{field_name}' cannot be float in raw payload; "
                "use Decimal, int, or string to preserve exact precision"
            )
        if isinstance(raw_value, Decimal):
            if not raw_value.is_finite():
                raise RawDataValidationError(
                    f"Price field '{field_name}' must be finite, got '{raw_value}'"
                )
            if raw_value < MIN_PRICE or raw_value > MAX_PRICE:
                raise RawDataValidationError(
                    f"Price field '{field_name}' value {raw_value} is outside valid domain limits "
                    f"[{MIN_PRICE}, {MAX_PRICE}]"
                )
            return raw_value

        if isinstance(raw_value, str):
            if raw_value != raw_value.strip():
                raise RawDataValidationError(
                    f"Price field '{field_name}' has invalid numeric format '{raw_value}': "
                    "whitespace padding is not permitted under strict validation"
                )
            raw_str = raw_value
        elif isinstance(raw_value, int):
            raw_str = str(raw_value)
        else:
            raise RawDataValidationError(
                f"Price field '{field_name}' must be Decimal, int, or string, got {type(raw_value).__name__}"
            )

        if len(raw_str) > MAX_PRICE_STR_LENGTH:
            raise RawDataValidationError(
                f"Price field '{field_name}' string length ({len(raw_str)}) exceeds maximum allowed "
                f"length of {MAX_PRICE_STR_LENGTH} characters"
            )

        if not PRICE_ASCII_PATTERN.match(raw_str):
            raise RawDataValidationError(
                f"Price field '{field_name}' has invalid numeric format '{raw_value}': "
                "must contain only ASCII digits with optional single decimal point, "
                "without signs, underscores, scientific notation, NaN, or infinity"
            )

        try:
            val = Decimal(raw_str)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RawDataValidationError(
                f"Invalid decimal string '{raw_value}' for field '{field_name}'"
            ) from exc

        if not val.is_finite():
            raise RawDataValidationError(
                f"Price field '{field_name}' must be finite, got '{raw_value}'"
            )

        if val < MIN_PRICE or val > MAX_PRICE:
            raise RawDataValidationError(
                f"Price field '{field_name}' value {val} is outside valid domain limits "
                f"[{MIN_PRICE}, {MAX_PRICE}]"
            )
        return val

    def _parse_volume(self, raw_value: Any) -> int:
        if raw_value is None:
            raise RawDataValidationError("Missing required field 'volume' in raw payload")
        if isinstance(raw_value, (bool, bytes)):
            raise RawDataValidationError(f"Volume cannot be a {type(raw_value).__name__}")
        if isinstance(raw_value, float):
            raise RawDataValidationError("Volume cannot be a float")
        if isinstance(raw_value, str):
            if raw_value != raw_value.strip():
                raise RawDataValidationError(
                    f"Volume has invalid integer format '{raw_value}': "
                    "whitespace padding is not permitted under strict validation"
                )
            raw_str = raw_value
        elif isinstance(raw_value, int):
            raw_str = str(raw_value)
        elif isinstance(raw_value, Decimal):
            if not raw_value.is_finite() or raw_value % 1 != 0:
                raise RawDataValidationError(
                    f"Volume cannot have fractional units or be non-finite, got '{raw_value}'"
                )
            raw_str = str(int(raw_value))
        else:
            raise RawDataValidationError(
                f"Volume must be an integer, Decimal, or string, got {type(raw_value).__name__}"
            )

        if len(raw_str) > MAX_VOLUME_STR_LENGTH:
            raise RawDataValidationError(
                f"Volume string length ({len(raw_str)}) exceeds maximum allowed "
                f"length of {MAX_VOLUME_STR_LENGTH} characters"
            )

        if not VOLUME_ASCII_PATTERN.match(raw_str):
            raise RawDataValidationError(
                f"Volume has invalid integer format '{raw_value}': "
                "must contain only ASCII digits without signs, underscores, scientific notation, or decimals"
            )

        try:
            vol = int(raw_str)
        except (ValueError, TypeError) as exc:
            raise RawDataValidationError(f"Invalid integer volume '{raw_value}'") from exc

        if vol < MIN_VOLUME or vol > MAX_VOLUME:
            raise RawDataValidationError(
                f"Volume value {vol} is outside valid domain limits [{MIN_VOLUME}, {MAX_VOLUME}]"
            )
        return vol

    def _parse_timestamp(self, raw_value: Any) -> datetime:
        if raw_value is None:
            raise RawDataValidationError("Missing required field 'timestamp' in raw payload")
        if isinstance(raw_value, datetime):
            ts = raw_value
        elif isinstance(raw_value, str):
            try:
                ts = datetime.fromisoformat(raw_value)
            except (ValueError, TypeError) as exc:
                raise RawDataValidationError(
                    f"Invalid ISO timestamp string '{raw_value}'"
                ) from exc
        else:
            raise RawDataValidationError(
                f"Timestamp must be a datetime or ISO string, got {type(raw_value).__name__}"
            )

        if ts.tzinfo is None:
            raise RawDataValidationError(
                f"Timestamp must be timezone-aware (tzinfo is None), got {ts}"
            )
        try:
            offset = ts.tzinfo.utcoffset(ts)
        except (AttributeError, ValueError, TypeError, OverflowError, RuntimeError) as exc:
            raise RawDataValidationError(f"Timestamp timezone calculation failed: {exc}") from exc

        if offset is None:
            raise RawDataValidationError("Timestamp has invalid timezone (utcoffset returned None)")
        return ts

    def adapt_record(
        self,
        raw_record: Mapping[str, Any],
        symbol: str,
        exchange: Exchange,
        interval: CandleInterval,
        retrieval_timestamp: datetime,
    ) -> Candle:
        if not isinstance(raw_record, Mapping):
            raise RawDataValidationError(
                f"raw_record must be a Mapping, got {type(raw_record).__name__}"
            )
        if isinstance(symbol, bytes):
            raise RawDataValidationError("symbol argument cannot be bytes")
        if isinstance(exchange, bytes):
            raise RawDataValidationError("exchange argument cannot be bytes")
        if isinstance(interval, bytes):
            raise RawDataValidationError("interval argument cannot be bytes")

        # Enforce payload identity when require_payload_identity is enabled (Finding M-1)
        if self._require_payload_identity:
            for ident_field in ("symbol", "exchange", "interval"):
                if ident_field not in raw_record:
                    raise RawDataValidationError(
                        f"Required identity field '{ident_field}' is missing from raw payload "
                        "(adapter configured with require_payload_identity=True)"
                    )

        # Validate identity fields if present in raw payload (Finding M-1)
        if "symbol" in raw_record:
            raw_sym = raw_record["symbol"]
            if isinstance(raw_sym, bytes) or not isinstance(raw_sym, str) or not raw_sym.strip():
                raise RawDataValidationError(
                    f"Payload contains invalid symbol value: {raw_sym!r}"
                )
            clean_raw_sym = raw_sym.strip().upper()
            clean_expected_sym = (
                symbol.strip().upper() if isinstance(symbol, str) else str(symbol).strip().upper()
            )
            if clean_raw_sym != clean_expected_sym:
                raise RawDataValidationError(
                    f"Payload symbol '{clean_raw_sym}' contradicts requested symbol '{clean_expected_sym}'"
                )

        if "exchange" in raw_record:
            raw_ex = raw_record["exchange"]
            if isinstance(raw_ex, Exchange):
                clean_raw_ex = raw_ex
            elif isinstance(raw_ex, str) and raw_ex.strip():
                try:
                    clean_raw_ex = Exchange(raw_ex.strip().upper())
                except ValueError as exc:
                    raise RawDataValidationError(
                        f"Payload contains unrecognized exchange: {raw_ex!r}"
                    ) from exc
            else:
                raise RawDataValidationError(
                    f"Payload contains invalid exchange value: {raw_ex!r}"
                )
            if clean_raw_ex != exchange:
                raise RawDataValidationError(
                    f"Payload exchange '{clean_raw_ex.value}' contradicts requested exchange '{exchange.value}'"
                )

        if "interval" in raw_record:
            raw_iv = raw_record["interval"]
            if isinstance(raw_iv, CandleInterval):
                clean_raw_iv = raw_iv
            elif isinstance(raw_iv, str) and raw_iv.strip():
                try:
                    clean_raw_iv = CandleInterval(raw_iv.strip())
                except ValueError as exc:
                    raise RawDataValidationError(
                        f"Payload contains unrecognized interval: {raw_iv!r}"
                    ) from exc
            else:
                raise RawDataValidationError(
                    f"Payload contains invalid interval value: {raw_iv!r}"
                )
            if clean_raw_iv != interval:
                raise RawDataValidationError(
                    f"Payload interval '{clean_raw_iv.value}' contradicts requested interval '{interval.value}'"
                )

        # Validate provenance / source field if present in raw payload (Finding M-4)
        if "source" in raw_record:
            raw_source = raw_record["source"]
            if not isinstance(raw_source, str) or not raw_source.strip():
                raise RawDataValidationError(
                    f"Payload contains invalid source value: {raw_source!r}"
                )
            clean_raw_source = raw_source.strip()
            clean_expected_source = self._source_name.strip()
            if clean_raw_source.upper() != clean_expected_source.upper():
                raise RawDataValidationError(
                    f"Payload source '{clean_raw_source}' contradicts expected source '{clean_expected_source}'"
                )
            effective_source = clean_expected_source
        else:
            effective_source = self._source_name

        # Check required price and volume fields
        for req in ("open", "high", "low", "close", "volume"):
            if req not in raw_record:
                raise RawDataValidationError(f"Missing required field '{req}' in raw payload")

        # Extract and parse timestamp aliases, rejecting contradictory timestamps (Finding 4)
        present_ts_fields = [f for f in ("timestamp", "date", "datetime") if f in raw_record]
        if not present_ts_fields:
            raise RawDataValidationError("Missing timestamp/date field in raw payload")

        parsed_tss: dict[str, datetime] = {}
        for f in present_ts_fields:
            parsed_tss[f] = self._parse_timestamp(raw_record[f])

        unique_tss = set(parsed_tss.values())
        if len(unique_tss) > 1:
            conflicts_repr = ", ".join(f"{f}={parsed_tss[f].isoformat()}" for f in present_ts_fields)
            raise RawDataValidationError(
                f"Conflicting timestamp fields in raw payload: {conflicts_repr}"
            )

        ts = next(iter(unique_tss))

        open_price = self._parse_decimal(raw_record["open"], "open")
        high_price = self._parse_decimal(raw_record["high"], "high")
        low_price = self._parse_decimal(raw_record["low"], "low")
        close_price = self._parse_decimal(raw_record["close"], "close")
        vol = self._parse_volume(raw_record["volume"])

        return Candle(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=vol,
            timestamp=ts,
            source=effective_source,
            retrieval_timestamp=retrieval_timestamp,
        )
