# Open Issues and Engineering Risks

Last reviewed: 2026-11-01

## M2a — Must resolve before approval

### R-001 — Nested validation details are mutable
- Severity: High
- Finding: `QualityIssue.details` wraps only the outer mapping with `MappingProxyType(dict(...))`; nested dictionaries/lists remain mutable.
- Required: Recursive freezing of supported nested containers and tests proving nested mutation fails.

### R-002 — Intraday gap detection can accept suspicious gaps
- Severity: High
- Finding: Current one-day date transition logic treats any next-date transition as normal overnight closure, even if the next candle is far into the session.
- Required: Enforce regular-session boundaries where supported; distinguish normal overnight/weekend transitions from missing bars; emit `MARKET_CALENDAR_REQUIRED` when certainty requires a holiday/special-session calendar.

### R-003 — Declared session boundaries are not enforced
- Severity: Medium
- Finding: `NSE_SESSION_OPEN` and `NSE_SESSION_CLOSE` are defined but current gap detection does not use them adequately.
- Required: Implement meaningful boundary-aware logic and tests, or remove unsupported claims.

### R-004 — Duplicate identity is too broad
- Severity: High
- Finding: Duplicate detection currently keys on timestamp alone.
- Required: Identity must include exchange, symbol, interval, and UTC-normalized timestamp; compare OHLCV only for matching identity.

### R-005 — Malformed sequence elements can crash validation
- Severity: High
- Finding: Attribute and timestamp validation is incomplete for arbitrary iterable elements.
- Required: Define input contract; malformed elements, None, invalid timestamp types, missing attributes, and timezone objects with `utcoffset() is None` should be handled deterministically with structured issues.

### R-006 — Timing argument validation incomplete
- Severity: Medium
- Finding: Validate `now` type/timezone and `max_staleness` type/non-negativity explicitly.
- Required: Tests for invalid types, negative duration, zero staleness, and exact boundary behaviour.

### R-007 — Constructor versus quality-gate timing contract
- Severity: Medium
- Finding: Candle construction may permit retrieval before bar close; quality validation is expected to reject it.
- Required: Make this separation explicit and ensure invalid provenance can never pass the authoritative validation gate.

### R-008 — CI lint scope narrowed temporarily
- Severity: Medium
- Finding: CI now lints market-data source/tests only to avoid known pre-existing Ruff violations in risk-engine source/tests.
- Required: Track and later resolve repository-wide lint baseline; do not permanently lose risk-engine lint coverage.

## Repository / workflow
- An untracked path `cls` was reported by `git status`; inspect before deleting.
- Local branch synchronization with remote README commit `0cba422` is pending; protect local uncommitted M2a changes.
- Windows LF-to-CRLF warnings were observed. They are not currently diff-check failures; consider a deliberate `.gitattributes` policy separately.

## Deferred to M2b
- Full NSE/BSE trading calendar, holidays, special sessions.
- Provider adapters and normalized ingestion boundaries.
- Corporate actions and symbol changes.
- Deterministic replayable data snapshots.
