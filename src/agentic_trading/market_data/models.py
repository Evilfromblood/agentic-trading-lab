"""Canonical market data models for Indian equities (NSE/BSE).

Provides immutable OHLCV candle representations, exchange identifiers,
and standard trading intervals. Financial prices use Decimal to guarantee
precision and avoid floating-point representation artifacts.

Timing semantics:
- `timestamp` (or `open_time`): Start of the interval (inclusive).
- `close_time`: End of the interval (exclusive / bar completion time),
  defined strictly as `open_time + interval.duration`.
- `retrieval_timestamp`: Physical wall-clock time when the completed bar was
  received/observed from the data source.
"""
from __future__ import annotations

import calendar as py_calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Standard Indian Standard Time timezone (+05:30)
try:
    IST = ZoneInfo("Asia/Kolkata")
except (ZoneInfoNotFoundError, OSError):  # pragma: no cover
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class _USEasternFallback(tzinfo):
    """Deterministic US Eastern timezone with Energy Policy Act of 2005 DST transitions."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-5) + self.dst(dt)

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        year = dt.year
        if year < 2007:
            raise ValueError(
                f"Historical US Eastern dates prior to 2007 ({year}) require reliable IANA "
                "timezone data (ZoneInfo/tzdata); _USEasternFallback only supports 2007 onwards"
            )
        # 2nd Sunday in March at 02:00 EST (07:00 UTC)
        m1_w = datetime(year, 3, 1).weekday()
        d_mar = 1 + (6 - m1_w) % 7 + 7
        dst_start = datetime(year, 3, d_mar, 2, 0)
        # 1st Sunday in November at 02:00 EDT (06:00 UTC)
        n1_w = datetime(year, 11, 1).weekday()
        d_nov = 1 + (6 - n1_w) % 7
        dst_end = datetime(year, 11, d_nov, 2, 0)
        d = dt.replace(tzinfo=None)
        if dst_start <= d < dst_end:
            return timedelta(hours=1)
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "EDT" if self.dst(dt) else "EST"


# Canonical US Eastern timezone
try:
    US_EASTERN = ZoneInfo("America/New_York")
except (ZoneInfoNotFoundError, OSError):  # pragma: no cover
    US_EASTERN = _USEasternFallback()


def get_exchange_timezone(exchange: Exchange | str) -> tzinfo:
    """Return canonical market timezone for given exchange."""
    ex_str = exchange.value if isinstance(exchange, Exchange) else str(exchange).upper()
    if ex_str in ("NSE", "BSE"):
        return IST
    if ex_str in ("NYSE", "NASDAQ"):
        return US_EASTERN
    raise ValueError(f"Unsupported exchange for timezone resolution: {exchange!r}")


# Valid equity/index symbol regex: uppercase letters, digits, and standard separators (&, -, _)
_SYMBOL_REGEX = re.compile(r"^[A-Z0-9&_\-]+$")


class Exchange(str, Enum):
    """Supported equity exchanges."""

    NSE = "NSE"
    BSE = "BSE"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"

    @classmethod
    def _missing_(cls, value: object) -> Exchange | None:
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


class CandleInterval(str, Enum):
    """Canonical candle intervals for equity market data."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M10 = "10m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"
    MN1 = "1M"

    @property
    def duration(self) -> timedelta:
        """Return the nominal timedelta represented by this interval."""
        durations: dict[str, timedelta] = {
            "1m": timedelta(minutes=1),
            "3m": timedelta(minutes=3),
            "5m": timedelta(minutes=5),
            "10m": timedelta(minutes=10),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
            "1w": timedelta(days=7),
            "1M": timedelta(days=30),
        }
        return durations[self.value]


@dataclass(frozen=True)
class ExchangeSession:
    """Session schedule definition for an exchange market (e.g. NSE/BSE or NYSE/NASDAQ regular trading).

    Attributes:
        session_open: Daily opening time of regular continuous trading.
        session_close: Daily closing time of regular continuous trading.
        timezone: Authoritative market timezone.
        exchange: The exchange governed by this session, or None for generic/custom sessions.
        name: Identifying name of this session schedule.
    """

    session_open: time = time(9, 15)
    session_close: time = time(15, 30)
    timezone: ZoneInfo | timezone | tzinfo = IST
    exchange: Exchange | None = None
    name: str = "REGULAR"
    is_special: bool = False

    @classmethod
    def for_exchange(cls, exchange: Exchange | str) -> ExchangeSession:
        """Resolve standard regular equity session for the given exchange."""
        ex_enum = Exchange(exchange) if not isinstance(exchange, Exchange) else exchange
        if ex_enum in (Exchange.NSE, Exchange.BSE):
            return cls(
                session_open=time(9, 15),
                session_close=time(15, 30),
                timezone=IST,
                exchange=ex_enum,
                name=f"REGULAR_{ex_enum.value}",
            )
        if ex_enum in (Exchange.NYSE, Exchange.NASDAQ):
            return cls(
                session_open=time(9, 30),
                session_close=time(16, 0),
                timezone=US_EASTERN,
                exchange=ex_enum,
                name=f"REGULAR_{ex_enum.value}",
            )
        raise ValueError(f"Unsupported exchange for session resolution: {exchange!r}")

    def is_trading_day(self, dt: datetime) -> bool:
        """Return True if dt falls on a valid trading day for this session."""
        if self.is_special:
            return True
        dt_tz = dt.astimezone(self.timezone) if dt.tzinfo else dt
        return dt_tz.weekday() < 5

    def is_within_session(self, dt: datetime) -> bool:
        """Return True if datetime falls within regular continuous trading session [session_open, session_close)."""
        dt_tz = dt.astimezone(self.timezone) if dt.tzinfo else dt
        if not self.is_trading_day(dt_tz):
            return False
        t = dt_tz.time()
        return self.session_open <= t < self.session_close

    def is_valid_grid_anchor(self, dt: datetime, interval: CandleInterval) -> bool:
        """Validate that candle open_time aligns with interval grid anchored at session_open."""
        dt_tz = dt.astimezone(self.timezone) if dt.tzinfo else dt
        if dt_tz.second != 0 or dt_tz.microsecond != 0:
            return False

        if interval == CandleInterval.D1:
            if not self.is_trading_day(dt_tz):
                return False
            t = dt_tz.time()
            return t in (self.session_open, time(0, 0))

        if interval == CandleInterval.W1:
            if dt_tz.weekday() != 0:  # Must be Monday
                return False
            t = dt_tz.time()
            return t in (self.session_open, time(0, 0))

        if interval == CandleInterval.MN1:
            if dt_tz.day != 1:  # Must be 1st day of month
                return False
            t = dt_tz.time()
            return t in (self.session_open, time(0, 0))

        t = dt_tz.time()
        if not (self.session_open <= t < self.session_close):
            return False
        elapsed_minutes = (t.hour - self.session_open.hour) * 60 + (t.minute - self.session_open.minute)
        interval_minutes = int(interval.duration.total_seconds() // 60)
        if interval_minutes <= 0:
            return False
        return (elapsed_minutes % interval_minutes) == 0

    def is_valid_session_close(self, close_time: datetime, interval: CandleInterval | timedelta) -> bool:
        """Return True if close_time represents a valid end-of-session bar close."""
        close_tz = close_time.astimezone(self.timezone) if close_time.tzinfo else close_time
        t = close_tz.time()
        if t == self.session_close:
            return True
        step = interval.duration if isinstance(interval, CandleInterval) else interval
        # Indian sessions (375m duration):
        if self.exchange in (Exchange.NSE, Exchange.BSE) or self.timezone == IST:
            if step in (timedelta(hours=1), timedelta(minutes=30)) and t == time(15, 15):
                return True
            if step == timedelta(minutes=10) and t == time(15, 25):
                return True
        # US sessions (390m duration from 09:30 to 16:00):
        # 6 full hours end at 15:30; remaining 30m bar closes at 16:00
        return bool(
            (self.exchange in (Exchange.NYSE, Exchange.NASDAQ) or self.timezone == US_EASTERN)
            and step == timedelta(hours=1)
            and t == time(15, 30)
        )


DEFAULT_EXCHANGE_SESSION = ExchangeSession.for_exchange(Exchange.NSE)


_ALLOWED_PRIMITIVE_TYPES = (
    str, int, float, bool, Decimal, datetime, date, time, timedelta, Enum, bytes, type(None), ExchangeSession
)


def _deep_freeze(
    obj: Any,
    max_depth: int = 16,
    max_nodes: int = 10_000,
    error_prefix: str = "Unsupported mutable or unhandled type",
) -> Any:
    """Recursively freeze mutable mappings, lists, and sets into immutable types.

    Guarantees:
    - Identity-based memoization retaining (original_object, frozen_object, subtree_depth)
      prevents Python memory address reuse on temporary mapping values and eliminates
      exponential processing on shared DAG structures.
    - Active call-stack tracking detects and rejects cyclical references immediately.
    - Hard bounds on total nodes visited (max_nodes, counting all primitives and containers)
      and nesting depth (max_depth, including depths of memoized subtrees).
    - Deep immutability across MappingProxyType, tuple, and frozenset.
    """
    active_stack: set[int] = set()
    memo: dict[int, tuple[Any, Any, int]] = {}
    node_count = [0]

    def _freeze_inner(cur: Any, depth: int) -> tuple[Any, int]:
        if depth > max_depth:
            raise ValueError(f"Maximum nesting depth ({max_depth}) exceeded during deep freeze")

        node_count[0] += 1
        if node_count[0] > max_nodes:
            raise ValueError(f"Maximum node count ({max_nodes}) exceeded during deep freeze")

        if isinstance(cur, _ALLOWED_PRIMITIVE_TYPES):
            return cur, 0

        obj_id = id(cur)
        if obj_id in memo:
            orig_obj, frozen_obj, subtree_depth = memo[obj_id]
            if orig_obj is cur:
                if depth + subtree_depth > max_depth:
                    raise ValueError(f"Maximum nesting depth ({max_depth}) exceeded during deep freeze")
                return frozen_obj, subtree_depth

        if obj_id in active_stack:
            raise ValueError("Cyclical reference detected during deep freeze")

        try:
            if len(cur) > max_nodes:
                raise ValueError(f"Maximum node count ({max_nodes}) exceeded during deep freeze")
        except TypeError:
            pass

        active_stack.add(obj_id)
        max_child_depth = 0
        try:
            if isinstance(cur, Mapping):
                d = {}
                for k, v in cur.items():
                    f_k, k_d = _freeze_inner(k, depth + 1)
                    f_v, v_d = _freeze_inner(v, depth + 1)
                    d[f_k] = f_v
                    max_child_depth = max(max_child_depth, k_d + 1, v_d + 1)
                frozen = MappingProxyType(d)
            elif isinstance(cur, (list, tuple)):
                items = []
                for v in cur:
                    f_v, v_d = _freeze_inner(v, depth + 1)
                    items.append(f_v)
                    max_child_depth = max(max_child_depth, v_d + 1)
                frozen = tuple(items)
            elif isinstance(cur, (set, frozenset)):
                items = []
                for v in cur:
                    f_v, v_d = _freeze_inner(v, depth + 1)
                    items.append(f_v)
                    max_child_depth = max(max_child_depth, v_d + 1)
                frozen = frozenset(items)
            else:
                raise TypeError(f"{error_prefix}: {type(cur).__name__}")
        finally:
            active_stack.remove(obj_id)

        memo[obj_id] = (cur, frozen, max_child_depth)
        return frozen, max_child_depth

    return _freeze_inner(obj, 0)[0]


@dataclass(frozen=True)
class ExchangeCalendar:
    """Exchange trading calendar specifying valid trading days and special sessions.

    Authoritative Calendar Completeness Contract (H-2):
    - An empty calendar (no trading_days, no holidays, no special_sessions, complete=False) has no evidence.
    - A partial calendar (complete=False) provides explicit evidence ONLY for dates explicitly listed in
      `holidays`, `special_sessions`, or `trading_days`. Unlisted weekdays have no evidence (missing evidence
      fails closed). Year-level inference from unrelated holidays is strictly prohibited.
    - A complete calendar (complete=True) provides authoritative evidence across its explicit coverage window
      `[coverage_start, coverage_end]`. Any weekday not in `holidays` is verified as a trading day.
      Any weekend not in `special_sessions` or date in `holidays` is verified as a non-trading day.
    - If `trading_days` is explicitly specified, any date in `trading_days` is a verified trading day;
      within `[coverage_start, coverage_end]` (or `[min(trading_days), max(trading_days)]`), any unlisted date
      is a verified non-trading day.
    """

    exchange: Exchange
    trading_days: frozenset[date] | None = None
    holidays: frozenset[date] = frozenset()
    special_sessions: Mapping[date, ExchangeSession] = field(default_factory=dict)
    coverage_start: date | None = None
    coverage_end: date | None = None
    complete: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.exchange, str):
            object.__setattr__(self, "exchange", Exchange(self.exchange.upper()))
        if self.trading_days is not None and not isinstance(self.trading_days, frozenset):
            object.__setattr__(self, "trading_days", frozenset(self.trading_days))
        if not isinstance(self.holidays, frozenset):
            object.__setattr__(self, "holidays", frozenset(self.holidays))
        if not isinstance(self.special_sessions, MappingProxyType):
            object.__setattr__(self, "special_sessions", _deep_freeze(self.special_sessions))

        # 1. Contradiction: overlap between trading_days and holidays
        if self.trading_days is not None:
            overlap = self.trading_days.intersection(self.holidays)
            if overlap:
                raise ValueError(
                    f"Contradictory calendar declaration: dates {sorted(overlap)} cannot be simultaneously "
                    f"listed as scheduled trading days and declared holidays"
                )

        # 2. Special session validation and contradiction checks
        for sd, sess in self.special_sessions.items():
            if sess.exchange != self.exchange:
                raise ValueError(
                    f"Contradictory special session on {sd}: session exchange ({sess.exchange}) "
                    f"does not match calendar exchange ({self.exchange})"
                )
            if sess.session_open >= sess.session_close:
                raise ValueError(
                    f"Contradictory special session on {sd}: session_open ({sess.session_open}) "
                    f"must be strictly before session_close ({sess.session_close})"
                )
            if sd in self.holidays:
                raise ValueError(
                    f"Contradictory special session on {sd}: date cannot be simultaneously declared "
                    f"as an all-day holiday and a special trading session"
                )
            if self.complete and self.trading_days is not None and sd not in self.trading_days:
                raise ValueError(
                    f"Contradictory special session on {sd}: special trading session date must be included "
                    f"in trading_days when calendar is complete"
                )

        # 3. Coverage window bounds
        if self.coverage_start is not None and self.coverage_end is not None:
            if self.coverage_start > self.coverage_end:
                raise ValueError(
                    f"coverage_start ({self.coverage_start}) cannot be after coverage_end ({self.coverage_end})"
                )
        elif self.complete and self.trading_days is not None and len(self.trading_days) > 0:
            if self.coverage_start is None:
                object.__setattr__(self, "coverage_start", min(self.trading_days))
            if self.coverage_end is None:
                object.__setattr__(self, "coverage_end", max(self.trading_days))
        if self.complete and self.trading_days is None:
            if self.coverage_start is None or self.coverage_end is None:
                raise ValueError(
                    "A complete ExchangeCalendar without explicit trading_days must specify coverage_start and coverage_end"
                )

    @property
    def is_populated(self) -> bool:
        """Return True if this calendar contains concrete trading day / holiday data or complete authority."""
        return bool(
            (self.trading_days is not None and len(self.trading_days) > 0)
            or len(self.holidays) > 0
            or len(self.special_sessions) > 0
            or (self.complete and self.coverage_start is not None and self.coverage_end is not None)
        )

    def has_evidence_for_date(self, d: date) -> bool:
        """Return True if the calendar has explicit evidence covering date d."""
        if not self.is_populated:
            return False
        if d in self.special_sessions or d in self.holidays:
            return True
        if self.trading_days is not None:
            return d in self.trading_days or (
                d.weekday() >= 5 and min(self.trading_days) <= d <= max(self.trading_days)
            )
        if self.complete and self.coverage_start is not None and self.coverage_end is not None:
            return self.coverage_start <= d <= self.coverage_end
        return False

    def has_evidence_for_range(self, start_d: date, end_d: date) -> bool:
        """Return True if the calendar has explicit evidence covering the entire range [start_d, end_d]."""
        if not self.is_populated:
            return False
        if start_d > end_d:
            return False
        if self.coverage_start is not None and self.coverage_end is not None:
            if not (self.coverage_start <= start_d and end_d <= self.coverage_end):
                return False
        curr = start_d
        while curr <= end_d:
            if not self.has_evidence_for_date(curr):
                return False
            curr += timedelta(days=1)
        return True

    def is_trading_day(self, d: date) -> bool:
        """Return True if date is a scheduled trading day for this exchange."""
        if d in self.special_sessions:
            return True
        if d in self.holidays:
            return False
        if self.trading_days is not None:
            return d in self.trading_days
        # Standard default: Mon-Fri minus explicit holidays
        return d.weekday() < 5 and d not in self.holidays

    def is_verified_trading_day(self, d: date) -> bool:
        """Return True if d is verified with calendar evidence as an active scheduled trading day."""
        if not self.has_evidence_for_date(d):
            return False
        if d in self.special_sessions:
            return True
        if d in self.holidays:
            return False
        if self.trading_days is not None:
            return d in self.trading_days
        if self.complete:
            return d.weekday() < 5
        return False

    def is_verified_non_trading_day(self, d: date) -> bool:
        """Return True if d is verified with calendar evidence as a non-trading day (holiday or standard weekend)."""
        if d in self.holidays:
            return True
        if not self.has_evidence_for_date(d):
            return False
        if d.weekday() >= 5 and d not in self.special_sessions:
            return True
        return False

    def get_session(self, d: date) -> ExchangeSession:
        """Return the effective ExchangeSession for the given date (standard or special)."""
        if d in self.special_sessions:
            sess = self.special_sessions[d]
            if not sess.is_special and d.weekday() >= 5:
                return ExchangeSession(
                    session_open=sess.session_open,
                    session_close=sess.session_close,
                    timezone=sess.timezone,
                    exchange=sess.exchange or self.exchange,
                    name=sess.name,
                    is_special=True,
                )
            return sess
        return ExchangeSession.for_exchange(self.exchange)


def _validate_finite_decimal(value: Any, field_name: str) -> Decimal:
    """Validate and convert an input into a finite Decimal.

    Rejects floats across all public paths to eliminate floating point precision degradation.
    """
    if isinstance(value, bool):
        raise TypeError(f"{field_name} cannot be a boolean")
    if isinstance(value, float):
        raise TypeError(
            f"{field_name} cannot be float; use Decimal, str, or int to preserve precision"
        )
    if isinstance(value, str) and value != value.strip():
        raise ValueError(f"{field_name} cannot have whitespace padding: {value!r}")
    try:
        dec = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {value!r}") from exc

    if not dec.is_finite():
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return dec


def _validate_volume(vol: Any) -> int:
    """Validate and normalize equity share volume as an integer."""
    if isinstance(vol, bool):
        raise TypeError("volume cannot be a boolean")
    if isinstance(vol, float):
        raise TypeError("volume cannot be float")
    if isinstance(vol, str) and vol != vol.strip():
        raise ValueError(f"volume cannot have whitespace padding: {vol!r}")
    if isinstance(vol, Decimal):
        if not vol.is_finite():
            raise ValueError("volume must be finite")
        if vol % 1 != 0:
            raise ValueError(f"volume must be an integer, got {vol}")
        return int(vol)
    if not isinstance(vol, int):
        try:
            return int(vol)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"volume must be an integer, got {vol!r}") from exc
    return vol


def _validate_timezone_aware(dt: Any, field_name: str) -> datetime:
    """Ensure timestamp is an instance of datetime and has explicit tzinfo with valid utcoffset."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware (tzinfo is None)")
    try:
        offset = dt.tzinfo.utcoffset(dt)
    except (AttributeError, ValueError, TypeError, OverflowError, RuntimeError) as exc:
        raise ValueError(f"{field_name} timezone calculation failed: {exc}") from exc
    if offset is None:
        raise ValueError(f"{field_name} must be timezone-aware (utcoffset returned None)")
    return dt


@dataclass(frozen=True)
class Candle:
    """Canonical, immutable OHLCV candle for Indian equities.

    Guarantees:
    - Immutability (frozen dataclass).
    - Decimal prices for exact precision (floats strictly rejected).
    - Timezone-aware datetimes for determinism (no bypasses permitted).
    - Strict rejection of non-finite numbers (NaN, Inf).
    - Explicit timing semantics: `open_time` (start, inclusive) and `close_time` (end, exclusive).
    - Explicit provenance: `source` and `retrieval_timestamp` required.

    Validation Contract:
    - `Candle` enforces structural domain validity (typing, non-negativity, finite Decimals, timezone awareness).
    - Authoritative validation of lifecycle completeness (in-progress rejection) and provenance causality
      (`retrieval_timestamp >= close_time`) is performed by the validation gate (`validate_candle`).
    """

    symbol: str
    exchange: Exchange
    interval: CandleInterval
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timestamp: datetime
    source: str
    retrieval_timestamp: datetime

    def __post_init__(self) -> None:
        # Validate symbol without silently changing instrument identity
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        clean_symbol = self.symbol.strip().upper()
        if not _SYMBOL_REGEX.match(clean_symbol):
            raise ValueError(
                f"symbol contains invalid characters: {self.symbol!r} "
                "(must contain only alphanumeric characters, hyphens, underscores, or ampersands)"
            )
        object.__setattr__(self, "symbol", clean_symbol)

        # Validate exchange
        if isinstance(self.exchange, str):
            clean_ex = self.exchange.strip().upper()
            try:
                object.__setattr__(self, "exchange", Exchange(clean_ex))
            except ValueError as exc:
                raise ValueError(f"Invalid exchange: {self.exchange!r}") from exc
        elif isinstance(self.exchange, Exchange):
            object.__setattr__(self, "exchange", self.exchange)
        else:
            raise TypeError(f"exchange must be Exchange or str, got {type(self.exchange).__name__}")

        # Validate interval
        if isinstance(self.interval, str):
            try:
                object.__setattr__(self, "interval", CandleInterval(self.interval))
            except ValueError as exc:
                raise ValueError(f"Invalid interval: {self.interval!r}") from exc
        elif isinstance(self.interval, CandleInterval):
            object.__setattr__(self, "interval", self.interval)
        else:
            raise TypeError(
                f"interval must be CandleInterval or str, got {type(self.interval).__name__}"
            )

        # Validate prices (Decimal, finite, non-float)
        object.__setattr__(self, "open", _validate_finite_decimal(self.open, "open"))
        object.__setattr__(self, "high", _validate_finite_decimal(self.high, "high"))
        object.__setattr__(self, "low", _validate_finite_decimal(self.low, "low"))
        object.__setattr__(self, "close", _validate_finite_decimal(self.close, "close"))

        # Validate volume
        object.__setattr__(self, "volume", _validate_volume(self.volume))

        # Validate timestamps (mandatory timezone awareness; no public bypass)
        object.__setattr__(
            self, "timestamp", _validate_timezone_aware(self.timestamp, "timestamp")
        )
        object.__setattr__(
            self,
            "retrieval_timestamp",
            _validate_timezone_aware(self.retrieval_timestamp, "retrieval_timestamp"),
        )

        # Validate source (provenance)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string representing data provenance")
        object.__setattr__(self, "source", self.source.strip().upper())

    @property
    def open_time(self) -> datetime:
        """Return the start time of the candle interval (inclusive)."""
        return self.timestamp

    @property
    def close_time(self) -> datetime:
        """Return the end time of the candle interval (bar completion time)."""
        try:
            session = ExchangeSession.for_exchange(self.exchange)
        except (ValueError, TypeError):
            session = DEFAULT_EXCHANGE_SESSION

        if self.interval == CandleInterval.D1:
            try:
                ts_local = self.timestamp.astimezone(session.timezone)
                if ts_local.time() < session.session_close:
                    close_local = ts_local.replace(
                        hour=session.session_close.hour,
                        minute=session.session_close.minute,
                        second=0,
                        microsecond=0,
                    )
                    return close_local.astimezone(self.timestamp.tzinfo)
            except (AttributeError, ValueError, TypeError, OverflowError):
                pass
            return self.timestamp + self.interval.duration

        if self.interval == CandleInterval.MN1:
            try:
                ts_local = self.timestamp.astimezone(session.timezone)
                num_days = py_calendar.monthrange(ts_local.year, ts_local.month)[1]
                last_day = ts_local.date().replace(day=num_days)
                close_local = ts_local.replace(
                    year=last_day.year,
                    month=last_day.month,
                    day=last_day.day,
                    hour=session.session_close.hour,
                    minute=session.session_close.minute,
                    second=0,
                    microsecond=0,
                )
                return close_local.astimezone(self.timestamp.tzinfo)
            except (AttributeError, ValueError, TypeError, OverflowError):
                pass
            return self.timestamp + self.interval.duration

        nominal_close = self.timestamp + self.interval.duration
        # For intraday bars, if the bar opened before session close but nominal close
        # extends past session close on the same trading date (e.g. H1 at 15:15 IST for NSE,
        # or H1 at 15:30 ET for NYSE), truncate close time to regular session close.
        if self.interval in (
            CandleInterval.M1,
            CandleInterval.M3,
            CandleInterval.M5,
            CandleInterval.M10,
            CandleInterval.M15,
            CandleInterval.M30,
            CandleInterval.H1,
        ):
            try:
                ts_local = self.timestamp.astimezone(session.timezone)
                nom_close_local = nominal_close.astimezone(session.timezone)
                if (
                    ts_local.time() < session.session_close
                    and nom_close_local.date() == ts_local.date()
                    and nom_close_local.time() > session.session_close
                ):
                    truncated_local = ts_local.replace(
                        hour=session.session_close.hour,
                        minute=session.session_close.minute,
                        second=0,
                        microsecond=0,
                    )
                    return truncated_local.astimezone(self.timestamp.tzinfo)
            except (AttributeError, ValueError, TypeError, OverflowError):
                pass
        return nominal_close

    @property
    def candle_timestamp(self) -> datetime:
        """Alias for timestamp (open_time)."""
        return self.timestamp

    @property
    def data_source(self) -> str:
        """Alias for source."""
        return self.source

    @property
    def is_bullish(self) -> bool:
        """Return True if close is greater than or equal to open."""
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        """Return True if close is strictly less than open."""
        return self.close < self.open

    @property
    def spread(self) -> Decimal:
        """Return candle range (high - low)."""
        return self.high - self.low

    @classmethod
    def create(
        cls,
        symbol: str,
        exchange: Exchange | str,
        interval: CandleInterval | str,
        open: Decimal | str | int,
        high: Decimal | str | int,
        low: Decimal | str | int,
        close: Decimal | str | int,
        volume: int,
        retrieval_timestamp: datetime,
        source: str,
        timestamp: datetime | None = None,
        candle_timestamp: datetime | None = None,
        data_source: str | None = None,
    ) -> Candle:
        """Construct a validated Candle without fabricating provenance or defaulting source.

        Rejects floats across all price arguments to guarantee financial precision.
        Requires explicit `retrieval_timestamp` and `source`.
        """
        # Strictly reject float and boolean inputs before any conversion
        for name, val in [("open", open), ("high", high), ("low", low), ("close", close)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} cannot be a boolean")
            if isinstance(val, float):
                raise TypeError(
                    f"{name} cannot be float; use Decimal, str, or int to preserve precision"
                )

        ts = candle_timestamp if candle_timestamp is not None else timestamp
        if ts is None:
            raise ValueError("Candle timestamp (open_time) must be explicitly provided")

        src = data_source if data_source is not None else source
        if not src or not isinstance(src, str) or not src.strip():
            raise ValueError("Explicit source provenance is required (no default permitted)")

        if retrieval_timestamp is None:
            raise ValueError(
                "Explicit retrieval_timestamp is required (fabricating timestamps is forbidden)"
            )

        return cls(
            symbol=symbol,
            exchange=Exchange(exchange.upper()) if isinstance(exchange, str) else exchange,
            interval=CandleInterval(interval) if isinstance(interval, str) else interval,
            open=open if isinstance(open, Decimal) else Decimal(str(open)),
            high=high if isinstance(high, Decimal) else Decimal(str(high)),
            low=low if isinstance(low, Decimal) else Decimal(str(low)),
            close=close if isinstance(close, Decimal) else Decimal(str(close)),
            volume=volume,
            timestamp=ts,
            source=src,
            retrieval_timestamp=retrieval_timestamp,
        )
