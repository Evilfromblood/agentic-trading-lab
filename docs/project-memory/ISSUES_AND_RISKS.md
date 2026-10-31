# Open Issues and Engineering Risks

Last reviewed: 2026-11-01

## M2a Remediated Audit Findings (Resolved in Working Tree)

### R-001 — Nested validation details mutable
- Status: Resolved.
- Fix: Implemented recursive freezing in `_deep_freeze()` converting nested dicts to `MappingProxyType`, lists to tuples, and sets to `frozenset`. Rejects unsupported mutable types with `TypeError` to guarantee immutability. Removed global `copy._deepcopy_dispatch` monkeypatch in favor of safe local design: added local `to_dict()` and `__reduce__()` methods to `QualityIssue` and `ValidationResult` for serialization without global side effects. Added regression tests for nested mutation attempts, unsupported types, serialization, and copy.deepcopy.

### R-002 — Intraday and daily gap detection exchange holiday safety
- Status: Resolved.
- Fix: Enforced exact regular-session boundaries (closing bar must close exactly at 15:30 IST, opening bar must open exactly at 09:15 IST). Without reliable exchange calendar evidence (deferred to M2b), all multi-day transitions (including Friday-to-Monday weekend gaps and multi-day holiday gaps) emit `MARKET_CALENDAR_REQUIRED` for both intraday and daily candle sequences, rather than assuming no holiday or special session occurred. Only strictly consecutive calendar weekdays (e.g. Mon->Tue) are accepted without a calendar.

### R-003 — Declared session boundaries enforced
- Status: Resolved.
- Fix: Used `NSE_SESSION_OPEN` (09:15) and `NSE_SESSION_CLOSE` (15:30) in `check_missing_intervals` for exact boundary verification. Tests added for premature close (15:20/15:25) and delayed open (10:30).

### R-004 — Duplicate identity too broad
- Status: Resolved.
- Fix: Candle duplicate identity in `check_duplicate_timestamps` now includes exchange, symbol, interval, and UTC-normalized timestamp (`c.timestamp.astimezone(UTC)`). OHLCV comparison distinguishes identical duplicates (`DUPLICATE_CANDLE`) from conflicting duplicates (`CONFLICTING_DUPLICATE_DATA`).

### R-005 — Malformed sequence elements and no-bridging guarantee
- Status: Resolved.
- Fix: Implemented `check_candle_structure()` for complete structural pre-validation across all public entry points. Added `_is_tz_valid` and audited all datetime comparisons, subtraction, and astimezone conversions to catch corrupt or unstable `tzinfo` exceptions without leaking. Sequence validation functions (`check_duplicate_timestamps`, `check_sequence_monotonicity`, `check_missing_intervals`, `check_sequence_consistency`) break sequence continuity upon encountering malformed elements: they never silently skip malformed elements or bridge across them, and always preserve original sequence indices in `details["index"]`.

### R-006 — Timing argument validation incomplete
- Status: Resolved.
- Fix: `_validate_now_and_staleness()` strictly rejects non-datetime types (including bool), naive datetimes, and tzinfo implementations that raise exceptions with `TypeError`/`ValueError`. Rejects non-timedelta (including bool) and negative staleness. Tested boundary at exact bar close and zero staleness.

### R-007 — Constructor versus quality-gate timing contract
- Status: Resolved.
- Fix: `Candle.create()` strictly requires explicit provenance (`source`) and retrieval timestamp (`retrieval_timestamp`); no simulated defaults or timestamp fabrication permitted. Floats and booleans rejected with `TypeError`. Authoritative gate `validate_candle` enforces `open_time < close_time <= retrieval_timestamp <= now`.

### R-008 — CI lint scope
- Status: Resolved.
- Fix: `.github/workflows/ci.yml` retains the pre-existing risk-engine Ruff check AND adds the market-data Ruff check as separate, non-weakening steps. Ruff is pinned to `ruff==0.17.3` in `pyproject.toml`.

### R-009 — check_gaps=False did not disable gap detection
- Status: Resolved.
- Fix: `validate_candle_sequence(..., check_gaps=False)` now bypasses `check_missing_intervals` entirely while continuing to run structural validation, duplicate detection, and monotonicity validation.

### R-010 — Malformed interval inference crash
- Status: Resolved.
- Fix: Interval inference in `check_missing_intervals` and `validate_candle_sequence` only accepts validated `CandleInterval` enum instances, ignoring arbitrary string or numeric interval attributes. Invalid interval values produce structured `MALFORMED_CANDLE` issues.

## Deferred to M2b
- Full NSE/BSE trading calendar, trading holidays, and special sessions (e.g. Muhurat trading). Until M2b, unverified calendar gaps fail closed with `MARKET_CALENDAR_REQUIRED`.
- Provider adapters and normalized ingestion boundaries (e.g. Zerodha Kite read-only connector).
- Corporate actions (splits, bonuses, dividends) and symbol changes.
- Deterministic fixtures and replayable data snapshots.

## Active Engineering Risks
- Python 3.11 CI compatibility: Local checks run on Python 3.14.4 (Windows 11). While standard syntax and typing are 3.11-compliant, full confirmation depends on GitHub Actions CI.
