"""Market data foundation for Indian equities (NSE/BSE).

Provides canonical data models, strict quality gates, and deterministic
data validation mechanisms.
"""
from __future__ import annotations

from agentic_trading.market_data.models import (
    IST,
    Candle,
    CandleInterval,
    Exchange,
)
from agentic_trading.market_data.quality import (
    DataQualityErrorCode,
    QualityIssue,
    ValidationResult,
    check_duplicate_timestamps,
    check_missing_intervals,
    check_ohlc_relationships,
    check_price_positivity,
    check_sequence_consistency,
    check_sequence_integrity,
    check_sequence_monotonicity,
    check_staleness,
    check_timezone_awareness,
    check_volume,
    validate_candle,
    validate_candle_sequence,
)

__all__ = [
    "IST",
    "Candle",
    "CandleInterval",
    "DataQualityErrorCode",
    "Exchange",
    "QualityIssue",
    "ValidationResult",
    "check_duplicate_timestamps",
    "check_missing_intervals",
    "check_ohlc_relationships",
    "check_price_positivity",
    "check_sequence_consistency",
    "check_sequence_integrity",
    "check_sequence_monotonicity",
    "check_staleness",
    "check_timezone_awareness",
    "check_volume",
    "validate_candle",
    "validate_candle_sequence",
]
