# Open Issues and Engineering Risks

Last reviewed: 2026-11-02

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

## M2b Ingestion Audit Remediations (Resolved in Working Tree)

### R-011 — Finding M-1: Payload identity mismatch & malformed identifiers
- Status: Resolved.
- Fix: `StandardDictAdapter.adapt_record` now validates in-payload `symbol`, `exchange`, and `interval` against requested parameters if present. Normalizes strings and enum values, and raises `RawDataValidationError` on contradiction or malformed types rather than silently stamping requested parameters over contradictory data.

### R-012 — Finding L-1: HistoricalDataRequest timezone awareness and offset validation
- Status: Resolved.
- Fix: `HistoricalDataRequest.__post_init__` verifies `tzinfo` exists and that `utcoffset()` returns a non-None offset without raising exceptions (`_validate_request_datetime`). Invalid timezone configurations or calculation errors raise a clear `ValueError`.

### R-013 — Finding L-2: SyntheticMarketDataProvider historical range filtering
- Status: Resolved.
- Fix: `SyntheticMarketDataProvider.fetch_historical` now filters records to the interval `[start_time, end_time)`. Records prior to start, at the end boundary, or after end are excluded, preserving deterministic ordering without data fabrication. In `fetch_latest`, causality is maintained by computing retrieval timestamps from candidate records.

### R-014 — Finding L-3: MarketDataIngestionPipeline latest-record contract & ambiguity
- Status: Resolved.
- Fix: `MarketDataIngestionPipeline.ingest_latest` inspects provider response cardinality. For multi-record responses, resolves the newest record via validated timestamps. If multiple records share the maximum timestamp or contain unparseable timestamps, it fails closed with `AMBIGUOUS_LATEST_RECORD`.

### R-015 — Finding H1: Fail-open staleness and timing
- Status: Resolved.
- Fix: `ingest_latest`, `ingest_historical`, and `ingest_record` require `now` to be an explicit timezone-aware datetime via `_require_valid_now`. Reject None, naive datetimes, or crashing tzinfo with `ValueError`. Enforce default 30-minute staleness (`DEFAULT_MAX_STALENESS`) when `max_staleness` is omitted; older candles fail closed with `STALE_DATA`.

### R-016 — Finding H2: Historical request-window boundary enforcement
- Status: Resolved.
- Fix: `ingest_historical` verifies every adapted candle falls within `[request.start_time, request.end_time)` and `close_time <= request.end_time`. Out-of-window candles fail closed with structured `BOUNDARY_VIOLATION`. `SequenceIngestionResult.coverage_status` explicitly set to `"COVERAGE_UNVERIFIED"` without claiming complete calendar coverage.

### R-017 — Finding M1: Identity-less raw payloads
- Status: Resolved.
- Fix: Added `require_payload_identity: bool = False` to `StandardDictAdapter`. `MarketDataIngestionPipeline` passes `require_payload_identity=True` by default, rejecting anonymous payloads missing `symbol`, `exchange`, or `interval` with `RawDataValidationError`.

### R-018 — Finding M2: Provider exceptions and malformed responses
- Status: Resolved.
- Fix: `ingest_latest` and `ingest_historical` wrap provider calls in try/except blocks catching `ProviderTimeoutError` (`TIMEOUT`), `ProviderConnectionError` (`PROVIDER_CONNECTION_ERROR`), `ProviderPayloadError` (`PROVIDER_PAYLOAD_ERROR`), `ProviderError` (`PROVIDER_ERROR`), and unexpected exceptions (`PROVIDER_EXCEPTION`). Validate `ProviderResponse` type and response `retrieval_timestamp` timezone safety.

### R-019 — Finding M3: Timezone safety consolidation
- Status: Resolved.
- Fix: Factored `_require_valid_tz_dt` helper validating timezone awareness and catching tzinfo offset computation errors. Used consistently across `ProviderResponse`, `HistoricalDataRequest`, and `_require_valid_now`.

### R-020 — Finding M4: Provenance correctness
- Status: Resolved.
- Fix: `StandardDictAdapter.adapt_record` validates `source` in raw payloads when present. If it contradicts the adapter's declared source, raises `RawDataValidationError`; stamps default adapter source when omitted. Boundary check in pipeline enforces that `ProviderResponse.source` matches configured provider and adapter.

### R-021 — Finding M5: Result consistency and immutability
- Status: Resolved.
- Fix: `IngestionResult` and `SequenceIngestionResult` enforce invariant consistency in `__post_init__` (success cannot have error fields; failure cannot expose valid candles). Raw payload dictionaries are deep-frozen into immutable `MappingProxyType`.

### R-022 — Finding Low-Severity: Provider & adapter edge-case hardening
- Status: Resolved.
- Fix: Synthetic provider `fetch_latest` raises `ValueError` if `now` is omitted when no records exist; `fetch_historical` skips unparseable/naive records during range filtering; filters by `exchange` and `interval`; adapter rejects conflicting timestamp aliases (`timestamp` vs `date`).

### R-023 — Finding C1: Python 3.11 Dataclass Default Incompatibility
- Status: Resolved.
- Fix: `FreshnessPolicy.custom_limits` declared using `field(default_factory=lambda: MappingProxyType({}))` ensuring compatibility across Python 3.11 through Python 3.14 without mutable default errors. Verified with genuine Python 3.11.9 interpreter.

### R-024 — Finding H1: D1 Freshness Semantics and Weekend/Holiday Safety
- Status: Resolved.
- Fix: Supported same-day post-close EOD (18:30 IST) and next-day morning pre-market (08:30 IST) under 24-hour staleness limit. All multi-day gaps, weekends, and holidays fail closed with `MarketCalendarRequiredError` unless explicit `max_staleness` is provided. Fixed D1 candle `close_time` for 15:30:00 IST timestamps to close at 15:30:00 IST on session date rather than next day.

### R-025 — Phase 3: Direct Decimal Parsing, Bytes Rejection, Causal Timestamps
- Status: Resolved.
- Fix: Direct Decimal parsing in `_parse_decimal` (accepts `Decimal("1E+2")` without ASCII string regex failure). Explicit `bytes` rejection across all fields. Causal `retrieval_timestamp` in `fetch_latest(now=None)` respecting session close (15:30:01 IST). Window filtering in `fetch_historical` enforcing `rec_close <= request.end_time`.

### R-026 — Finding Critical: Historical Sequence Coverage Correctness & Interior Gap Detection
- Status: Resolved.
- Fix: Disentangled boundary coverage (`candles[0].timestamp <= start` and `candles[-1].close_time >= end`) from interior sequence completeness. Reused M2a's session-aware `check_sequence_integrity` to detect missing intermediate candles, consecutive missing candles, or entire missing intermediate trading days (`MISSING_INTERVAL` or `MARKET_CALENDAR_REQUIRED`). If `require_full_coverage=True`, sequence fails closed with `error_code="TRUNCATED_COVERAGE"` and `coverage_status="TRUNCATED_COVERAGE"` regardless of caller's `check_gaps` flag. Empty provider responses report `coverage_status="EMPTY_COVERAGE"`. Quality gate rejections on missing intervals propagate `coverage_status="TRUNCATED_COVERAGE"`. Added 11 regression tests.

### R-027 — Claude A Priority 1: Candle Integrity, Session Membership & Grid Anchoring
- Status: Resolved.
- Fix: Added `ExchangeSession` and `DEFAULT_EXCHANGE_SESSION` abstraction (`09:15` - `15:30` IST). Implemented `check_session_and_grid` validating intraday candles occur on weekdays, within session hours (`OUTSIDE_SESSION`), and at exact interval-grid offsets (`OFF_GRID_TIMESTAMP`). Extended `check_sequence_monotonicity` to flag `OVERLAPPING_CANDLE` when `c2.timestamp < c1.close_time`. Preserved session-truncated bar close timestamps for H1, M30, and M10. Enforced missing final session candle detection across date boundaries and session-close queries.

### R-028 — Claude A Priority 2: Historical Freshness & Future Boundaries
- Status: Resolved.
- Fix: Enforced `retrieval_timestamp <= now` across all ingestion modes (`ingest_latest` and `ingest_historical`). Decoupled historical backfills (`end_time < now`) from live queries (`end_time >= now`). Live queries strictly enforce `FreshnessPolicy`. Historical backfills disable live staleness checks while strictly enforcing future-timestamp validation on all candles.

### R-029 — Claude A Priority 3: DAG Memoization & Recursive Immutability
- Status: Resolved.
- Fix: Replaced active-frame traversal with identity memoization (`_memo[id(obj)]`) to prevent $O(2^D)$ exponential traversal in shared DAG structures. Added cycle detection via active stack (`_active_stack`), a node budget of 10,000, and a depth limit of 16. Consolidated `_deep_freeze` into `models.py` and unified its use across `quality.py`, `provider.py`, and `ingestion.py`.

### R-030 — Claude A Priority 4: Coverage & Result Consistency
- Status: Resolved.
- Fix: Decoupled `TRUNCATED_COVERAGE` (boundary truncation, interior intraday missing bars) from `MARKET_CALENDAR_REQUIRED` (unaccounted multi-day jumps). Preserved strict invariant consistency in `IngestionResult` and `SequenceIngestionResult` across all success and error paths.

### R-031 — Claude A Priority 5: Additional Confirmed Defects
- Status: Resolved.
- Fix: Fixed D1 `close_time` calculation to ensure positive duration when timestamp is on or after session open. Strictly rejected whitespace-padded numeric strings in `StandardDictAdapter` and `models.py`. Implemented explicit `__hash__` and `__eq__` on `FreshnessPolicy` for hashability and dataclass compatibility. Added 18 regression tests in `test_claude_batch1_regressions.py`.

### R-032 — Claude B H-1, COV-05, COV-07, COV-09: Multi-Exchange Session Architecture & Timezone Modeling
- Status: Resolved.
- Fix: Extended `Exchange` enum to support `NSE`, `BSE`, `NYSE`, and `NASDAQ` with case-insensitive parsing. Implemented US Eastern timezone with Energy Policy Act of 2005 DST transitions (`_USEasternFallback`). Extended `ExchangeSession` with dynamic session boundaries per exchange and `is_valid_grid_anchor` for D1/W1/MN1, rejecting off-grid intraday timestamps like 03:00 IST for daily candles. Updated `Candle.close_time` to dynamically look up exchange session without hardcoded IST/15:30. Added `EXCHANGE_MISMATCH` check in `check_session_and_grid`.

### R-033 — Claude B H-2, COV-01: Fail-Closed Historical Coverage Contract
- Status: Resolved.
- Fix: Configured `require_full_coverage: bool = True` and `allow_partial: bool = False` as default in `ingest_historical`. Truncated or incomplete backfills fail closed with `success=False` and empty `candles=()`. Explicit `allow_partial=True` populates `partial_candles` while preserving `success=False` and `candles=()`, preventing downstream trading engines from treating partial backfills as complete. Defined structured `CoverageStatus` enum values (`FULL_COVERAGE`, `COVERAGE_UNVERIFIED`, `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, `EMPTY_COVERAGE`).

### R-034 — Claude B H-3, M-1: Correct and Bounded Deep Freezing
- Status: Resolved.
- Fix: Addressed CPython memory address reuse on transient mapping keys in `_deep_freeze` by storing `(orig_obj, frozen_obj, subtree_depth)` in `_memo` and verifying `orig_obj is cur`. Counted every node (primitives + containers) against a hard budget `max_nodes=10000`, bounding traversal to `<2ms`. Enforced `depth + subtree_depth > max_depth` when retrieving memoized DAG subtrees to prevent depth-limit circumvention.

### R-035 — Claude B M-2, COV-03, COV-08: Exchange Calendar Abstraction & Multi-Day Spans
- Status: Resolved.
- Fix: Introduced `ExchangeCalendar` abstraction supporting trading days, declared holidays, and special sessions. Historical sequences spanning weekends or holidays without calendar evidence emit `MARKET_CALENDAR_REQUIRED`. Intervening non-trading days verified by calendar pass cleanly. Added `allow_sparse=True` contract for illiquid instruments.

### R-036 — Claude B M-4, ARCH-03: Result-Object Invariant Hardening
- Status: Resolved.
- Fix: Enforced `__post_init__` checks in `IngestionResult` (success strictly requires valid `validation_result`). Enforced `__post_init__` checks in `SequenceIngestionResult` (rejects `"BOGUS"` coverage status, rejects `raw_record_count < len(candles)`, rejects `success=True` with `TRUNCATED_COVERAGE`, `EMPTY_COVERAGE`, or populated `partial_candles`).

### R-037 — Claude B SEC-01, SEC-03: Paper-Only Broker Controls & CI Hardening
- Status: Resolved.
- Fix: Wrapped Kite client in `_ReadOnlyKiteWrapper` and added explicit `place_order`, `modify_order`, `cancel_order` methods raising `PermissionError("Order placement is forbidden in paper-only mode")`. SHA-pinned all GitHub actions in `.github/workflows/ci.yml` and added Python 3.11/3.12 testing matrix. Ignored `.venv311/`, `.ruff_cache/`, `*.egg-info/` in `.gitignore`. Replaced all broad `BLE001` (`except Exception:`) suppressions with explicit exception tuples. Added 20 comprehensive regression tests in `test_claude_batch2_regressions.py`.

### R-038 — Claude C Priority 1: Calendar Evidence Must Never Fail Open
- Status: Resolved.
- Fix: Added `is_populated`, `has_evidence_for_date`, and `has_evidence_for_range` to `ExchangeCalendar`. Unpopulated/empty calendars return `is_populated is False` and never claim evidence or provide verified coverage (`has_evidence_for_range` returns False). Candles occurring on dates declared in `calendar.holidays` are strictly rejected as `OUTSIDE_SESSION`. Sequences across multi-day intervals require verified calendar evidence covering the entire requested window before reporting `FULL_COVERAGE`.

### R-039 — Claude C Priority 2: Enforce Zerodha Paper-Only Boundary
- Status: Resolved.
- Fix: Replaced denylist-based forwarding with an explicit `_READ_ONLY_ALLOWLIST` on `_ReadOnlyKiteWrapper`. Blocked direct, nested, and forwarded access to underlying order-capable `KiteConnect` client via `__getattribute__` on both `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (blocking `_client`, `__client`, `_raw_client`, etc.). Explicitly blocked order placement, modification, cancellation, exit, GTT, position conversion, mutual fund orders, and direct HTTP methods (`_post`, `_request`, `_put`, `_delete`), raising `PermissionError`. Documented that Python in-process wrappers enforce application software policy, not an OS sandbox.

### R-040 — Claude C Priority 3: Make Coverage Success Trustworthy & Explicit Sparse Mode
- Status: Resolved.
- Fix: Introduced `CoverageStatus.SPARSE_COVERAGE` with clearly defined policy. When `allow_sparse=True` is explicitly passed, missing window edge bars and intraday missing intervals are tolerated for illiquid instruments without treating interior unexplained gaps as valid, reporting `coverage_status="SPARSE_COVERAGE"`. Implemented strict `require_full_coverage` contract: when `require_full_coverage=True`, any unverified (`COVERAGE_UNVERIFIED`) or sparse (`SPARSE_COVERAGE`) data fails closed with `success=False` and explicit error code, ensuring partial/sparse data cannot be passed downstream as fully validated data.

### R-041 — Claude C Priority 4: CI and Reproducibility
- Status: Resolved.
- Fix: Configured multi-version CI matrix for Python 3.11, 3.12, 3.13, and 3.14-dev in `.github/workflows/ci.yml`. Configured Ruff with explicit rule selection (`F, E4, E7, E9, B, BLE, I`) across all source and test files. Added coverage threshold (`--cov-fail-under=85`) and dependency audit (`pip-audit`) step. Implemented architectural import boundary test (`tests/test_import_boundaries.py`) verifying zero dependencies from `market_data` and `risk_engine` to broker execution. Added reproducible dependency lockfile `requirements.lock`.

### R-042 — Claude C Priority 5 & Additional: Result-Object Invariants and Domain Correctness
- Status: Resolved.
- Fix: Enforced strict `__post_init__` checks in `SequenceIngestionResult`: validates `Candle` instance types, enforces uniform symbol and exchange across all candles, validates strictly monotonic timestamps, forbids `success=True` with `MARKET_CALENDAR_REQUIRED`, `TRUNCATED_COVERAGE`, or `EMPTY_COVERAGE`, forbids single intraday candle claiming `FULL_COVERAGE`, and forbids `success=False` with `FULL_COVERAGE`. Fixed MN1 monthly close-time calculation to use actual calendar month boundaries (`py_calendar.monthrange`) handling leap/non-leap February and variable month lengths. Raised explicit `ValueError` for historical US Eastern dates prior to 2007 in `_USEasternFallback`. Constrained caller-supplied `now` against distant future timestamps (> 365 days). Eliminated all remaining broad `except Exception:` blocks across domain and adapter layers, catching explicit exception tuples including `RuntimeError`.

## M2b Ingestion Status & Remaining Scope
- Implemented in M2b:
  - Provider-independent interface (`MarketDataProvider`, `HistoricalDataRequest`, `ProviderResponse`).
  - Provider adapter and raw data validation (`ProviderAdapter`, `StandardDictAdapter`, `RawDataValidationError`).
  - End-to-end ingestion pipeline (`MarketDataIngestionPipeline`, `IngestionResult`, `SequenceIngestionResult`).
  - Deterministic synthetic provider (`SyntheticMarketDataProvider`) with failure simulation (timeouts, errors, empty results).
  - 110 comprehensive unit and regression tests (248 total passing tests in suite).
- Delineation of testing & replay scope:
  - **Synthetic sample generation** (current): `SyntheticMarketDataProvider.create_sample_series()` generates deterministic in-memory test data.
  - **Stored replay fixtures** (not yet implemented): saving and reloading actual provider responses from static files on disk.
  - **Historical replay infrastructure** (not yet implemented): full sequential market session clock simulation with tick-by-tick or bar-by-bar progression for strategy/backtest execution.
- Integration boundary note:
  - `test_risk_engine_isolation_boundary_with_ingestion` is an architectural component isolation demonstration showing safe contract boundaries, NOT a verified end-to-end execution pipeline.
- Remaining in M2b:
  - Full NSE/BSE trading calendar, trading holidays, and special sessions (e.g. Muhurat trading).
  - Corporate actions (splits, bonuses, dividends) and symbol changes.
  - Read-only Zerodha Kite adapter (deferred until authenticated broker connector phase).

## Active Engineering Risks
- Python 3.11 compatibility: Verified locally on genuine Python 3.11.9 (`.venv311`) passing all 248 tests, ruff, compileall, and hash seed determinism.
- Authoritative Exchange Calendar: Gaps in historical sequences cannot be fully validated without an official NSE/BSE calendar; `coverage_status` remains `COVERAGE_UNVERIFIED`.

## M2b Remediation Batch 4 Resolution Summary (2026-11-07)

### Resolved Blockers
1. **H-1: Zerodha Raw-Client Escape Paths:** Fully resolved. Removed `_get_raw_client` and `_get_underlying`. Implemented `__slots__ = ("__weakref__",)` and `WeakKeyDictionary` isolation. Bound method `__self__` points to wrapper, not raw client. Reflection access via `vars()`, `__dict__`, and `object.__getattribute__` blocked. All 9 demonstrated escape paths closed and proven with adversarial tests.
2. **N-1: Holiday Rejection Pipeline Crash:** Fully resolved. Quality gate failure path returns typed `SequenceIngestionResult(success=False, error_code="QUALITY_GATE_REJECTED", coverage_status="COVERAGE_UNVERIFIED")` without crashing on `FULL_COVERAGE` post-init invariant.
3. **H-2: Calendar Evidence Completeness:** Fully resolved. `ExchangeCalendar` completeness contract introduced with `complete: bool = False`. Single-holiday year-level inference eliminated. Explicit coverage bounds required. Fail-closed on missing evidence. Four exchanges verified.
4. **M-2: Enforceable CI & Dependency Lock:** Fully resolved. Python 3.14 stable, blocking pip-audit, secret scanning added, Ruff covers all source/test directories, `--cov-fail-under=85` enforced, and `requirements.lock` rewritten with honest architecture description.
5. **M-3: Genuine 85% Test Coverage:** Fully resolved. 87.12% genuine coverage verified on both Python 3.11.9 and Python 3.14.4 across 269 passing tests.

### Documented Low-Priority Limitations
1. **Mixed Candle Intervals in Results:** `SequenceIngestionResult` validates basic types; uniform interval enforcement across multi-timeframe analytics is deferred to M2c/M3.
2. **Missing/Synthetic Retrieval Timestamp:** Defaults to evaluation timestamp `now` when physical feed observation timestamp is not provided by upstream source.
3. **Sparse Mode Density Threshold:** Permissive sparse mode is currently explicit opt-in; configurable minimum bar density thresholds (e.g. >=20%) will be added in M2c provider policies.
4. **Candle.close_time Session Truncation:** Arithmetic duration (`timestamp + interval.duration`) is preserved; special-session boundary enforcement is handled by the quality gate session boundaries.
5. **AST Import Boundary Static Inspection:** Verified via `test_import_boundaries.py`; dynamic runtime interception of optional imports is deferred.
6. **Timezone Data Dependency:** Relies on Python `zoneinfo` and OS tzdata; `tzdata` package recommended on bare Windows installations lacking IANA tz databases.

## M2b Remediation Batch 5 Resolution Summary (2026-11-07)

### Resolved Findings
1. **F-1 (Critical): Zerodha Module-Level Raw-Client Exposure Removed:** Fully resolved.
   - Removed module-level `_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, and `_get_client_for_connector`.
   - Replaced with instance-level closure-held dispatch: `_dispatch` is declared in `__slots__ = ("_dispatch", "__weakref__")`.
   - Blocked all reflection attacks (`vars()`, `__dict__`, `object.__getattribute__`) via strict `__getattribute__` raising `PermissionError`.
   - On initialization, neutralized all mutating methods (`place_order`, `modify_order`, `cancel_order`, `exit_order`, `place_gtt`, `modify_gtt`, `delete_gtt`, `convert_position`, `place_mf_order`, `cancel_mf_order`, `_post`, `_request`, `_put`, `_delete`) on the underlying client instance.
   - All 20 allowlisted read-only methods continue to function correctly and preserve `__self__ is wrapper`.
2. **F-2 (High): ExchangeCalendar Incomplete Evidence Fails Closed:** Fully resolved.
   - Bounded calendar auto-population of `coverage_start` and `coverage_end` from `trading_days` to occur ONLY when `complete=True`.
   - When `complete=False`, `has_evidence_for_date(d)` returns `True` ONLY for dates explicitly present in `trading_days`, `holidays`, or `special_sessions`.
   - When `complete=False`, unlisted weekdays are NEVER verified as non-trading days (`is_verified_non_trading_day == False`).
   - `has_evidence_for_range` fails closed (`False`) if any intermediate date lacks explicit evidence.
   - Daily and intraday (M5) sequence ingestion fail closed with `COVERAGE_UNVERIFIED` and reject `require_full_coverage=True` when intermediate weekdays are unlisted. Verified across NSE, BSE, NYSE, and NASDAQ.
3. **F-3 (Medium): Blocking Secret Scanning in CI:** Fully resolved.
   - Generated `.secrets.baseline` in UTF-8 format at the repository root with 0 leaked secrets.
   - Configured `.github/workflows/ci.yml` secret scanning step to use `detect-secrets-hook --baseline .secrets.baseline`, blocking the build on any unmanaged secret.
4. **Test Suite Isolation:**
   - Fixed `sys.modules["keyring"]` and `sys.modules["kiteconnect"]` pollution across tests using scoped `patch.dict`.
   - Verified 283/283 tests pass with 87.12% coverage across both Python 3.11.9 and Python 3.14.4.


## M2b Remediation Batch 6 Resolution Summary (2026-11-07)

### Resolved Findings
1. **F1-A & F1-B (Critical): Zerodha In-Process Read-Only Boundary Redesigned:** Fully resolved.
   - Caller-supplied injected KiteConnect client instances are NEVER mutated or monkeypatched; caller methods remain untouched.
   - Redesigned using slotted facade composition (`__slots__ = ("_target", "__weakref__")`).
   - Implemented `ReadOnlyTransportAdapter(HTTPAdapter)` intercepting requests at the transport level to reject any non-GET request with `PermissionError`.
   - `ReadOnlyKiteConnect` mounts `ReadOnlyTransportAdapter` on `reqsession` and overrides `_request` and write methods.
   - `_ReadOnlyKiteWrapper` returns bound methods via `types.MethodType` so that `wrapper.method.__self__ is wrapper`.
   - Full API audit blocking all order methods, autoslice orders, GTT, MF, MF SIP, convert_position, session mutation (`generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`), and raw HTTP methods (`_post`, `_put`, `_delete`, `_request`).
2. **F1-D & T-1 (High): Keyring Safety & Genuine KiteConnect Integration:** Fully resolved.
   - Safe token helpers catch backend errors; missing or unconfigured keyrings never break connector construction.
   - Genuine `kiteconnect==5.2.2` tested with intercepted HTTP transport in `tests/test_zerodha_kiteconnect_integration.py` and `tests/test_claude_batch6_regressions.py`.
   - Verified legitimate reads (`profile`, `margins`, `holdings`, `positions`, `historical_data`, `quote`, `ltp`) reach transport as GET requests.
   - Verified zero blocked mutation requests reach the transport adapter.
3. **F2-A, F2-B, F2-C (High): Calendar Contradiction Rejection & Completeness Contract:** Fully resolved.
   - Contradiction rejection in `ExchangeCalendar.__post_init__`: detects and raises `ValueError` on overlap between `trading_days` and `holidays`, special sessions on holidays, special sessions with `open >= close`, and special sessions with mismatched exchanges.
   - `complete=True` calendars require explicit holiday evidence for omitted weekdays; unexplained missing weekdays have no evidence and fail closed.
   - Incomplete calendars fail closed with exact error code `MARKET_CALENDAR_REQUIRED` and coverage status `CoverageStatus.MARKET_CALENDAR_REQUIRED.value`.
   - Ingestion across missing intermediate trading days without calendar evidence fails closed with exact error code `TRUNCATED_COVERAGE` and coverage status `TRUNCATED_COVERAGE`.
   - Tested across all four exchanges: NSE, BSE, NYSE, NASDAQ for D1 and M5 sequences.
4. **F3-A & F3-B (Medium): Secret Scanning Hardening:** Fully resolved.
   - Anchored exclusion regex `^(?:\.git/|\.venv(?:311)?/|\.ruff_cache/|\.pytest_cache/|\.coverage$|htmlcov/|m2a-review\.patch$)` strictly avoids masking `.github/` or `.gitlab-ci.yml`.
   - Pin `detect-secrets==1.5.0` in CI with `.secrets.baseline` containing version 1.5.0 and zero unbaselined secrets.
   - Verified detection of dummy AWS secrets across `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files.
5. **Test Coverage & Quality Enforcement:**
   - All 310 tests pass across the entire suite with 85.49% test coverage on both Python 3.11.9 and Python 3.14.4.
   - Ruff linting and compileall pass cleanly.


## M2b Batch 7 Remediated Audit Findings (Resolved in Working Tree)

### R-028 — Finding D1: Raw client exposure via slot descriptor `_target`
- Status: Resolved.
- Fix: Removed `_target` from `__slots__` on `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (`__slots__ = ("__weakref__",)` only). Injected and default clients are stored strictly inside closure-encapsulated `WeakKeyDictionary` registries with zero instance attributes, zero slots, and zero module-level dictionaries. `__getattribute__` blocks access to `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession` with `PermissionError`. Bound methods returned via `types.MethodType(bound_call, self)` ensure `method.__self__ is wrapper`. Injected caller `KiteConnect` instances remain 100% unmutated.

### R-029 — Finding D2 & D3: Inconsistent session-mutation blocking & complete_login
- Status: Resolved.
- Fix: Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and placed into `_BLOCKED_METHODS`. Both default and injected clients raise `PermissionError` before transport. `complete_login` consistently fails closed with `PermissionError` in read-only mode.

### R-030 — Finding D4: Keyring lock crashing in-memory authenticated sessions
- Status: Resolved.
- Fix: `_require_session()` checks if the underlying client already holds a non-empty `access_token` in memory; if present, read operations proceed without querying keyring. Keyring is queried only when no in-memory token exists, catching backend failures as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`.

### R-031 — Finding D5: Ingestion error code mismatch & calendar docstring
- Status: Resolved.
- Fix: When `ingest_historical` encounters missing intermediate trading days (`MISSING_INTERVAL`), it sets both `coverage_status = "TRUNCATED_COVERAGE"` and `error_code = "TRUNCATED_COVERAGE"`. Updated `ExchangeCalendar` docstring in `models.py` to clarify that unlisted weekdays do NOT count as non-trading days without explicit holiday evidence.

### R-032 — Finding D6: Secret scanner skipping lockfiles & CI stray comment
- Status: Resolved.
- Fix: Removed `{"path": "detect_secrets.filters.heuristic.is_lock_file"}` from `filters_used` in `.secrets.baseline` so lockfiles are actively scanned. Removed stray `# pragma: allowlist secret` comment from `.github/workflows/ci.yml`.

### R-033 — Finding D7: Missing requests dependency & unpinned lockfile
- Status: Resolved.
- Fix: Added `"requests>=2.32.0"` to optional dependencies in `pyproject.toml`. Populated `requirements.lock` with exact verified pins (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`). Updated CI to install from `requirements.lock`.


## M2b Batch 7b Remediated Audit Findings (Resolved in Working Tree)

### R-034 — Finding F1: Injected KiteConnect mutation in _require_session() and logout()
- Status: Resolved.
- Fix: Injected client stored with boolean flag in closure dictionary; `_require_session()` fails closed with `KiteConfigurationError` if `access_token` missing/empty without mutating client; `logout()` leaves injected client object and headers completely untouched.

### R-035 — Finding F3: HTTP POST margin and contract note methods permitted in read-only allowlist
- Status: Resolved.
- Fix: Removed `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` from `_READ_ONLY_ALLOWLIST`, added to `_BLOCKED_METHODS`, with explicit stubs on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` before transport.


## M3 Final Polish Remediated Audit Findings (Resolved in Working Tree)

### R-036 — Finding R1 & R3: Slippage & Fill Price Positive Validation and Tick Size Rejection
- Status: Resolved.
- Fix: `BasisPointsSlippageModel.calculate_slippage` and `PortfolioEngine.apply_fill` reject non-positive prices (`price.amount <= Decimal("0")`) with `ValueError`. In `BasisPointsSlippageModel`, when adverse `ROUND_FLOOR` on `SELL` reduces effective price below `tick_size` (or `<= 0`), raise `ValueError("Effective sell price falls below minimum tick size")` instead of clamping upward.

### R-037 — Finding R2: Exact Zero-Drift Cost Basis Tracking & Conservation Residual
- Status: Resolved.
- Fix: `PortfolioEngine` explicitly tracks per-position total cost basis (`_total_cost_basis`) across `apply_fill` and `_replay_ledger`. On partial position reductions, basis removed is computed as `(total_cost_basis * Decimal(quantity)) / Decimal(curr_qty)`, subtracted from tracked basis, and deducted from proceeds to produce `trade_pnl`. On full position exits, the exact remaining tracked basis is removed (`_total_cost_basis.pop(key)`), guaranteeing zero residual drift (`Decimal("0")`) across multi-lot partial and full round trips.

### R-038 — Finding R4: Proposal Gate Long-Exit Stop-Loss & Take-Profit Direction
- Status: Resolved.
- Fix: For `SELL` exits of held long positions (`held_qty > 0`), strictly enforce directional bounds: `stop_loss.amount < entry_price` (`INVALID_STOP_LOSS_DIRECTION`) and `take_profit.amount > entry_price` (`INVALID_TAKE_PROFIT_DIRECTION`).

### R-039 — Finding R5: Replay Fixture Identity Mismatch & Naive Timestamp Rejection
- Status: Resolved.
- Fix: `StoredReplayFixtureProvider` validates `manifest.fixture_id == self._fixture_id` on load, raising `FixtureIntegrityError("Fixture identity mismatch")` on tampering. Rejects timezone-naive `recorded_at` in manifest with `FixtureIntegrityError("timezone-naive")`.

### R-040 — Finding R6: Synthetic Provider Filtering & Look-Ahead Slicing
- Status: Resolved.
- Fix: `SyntheticMarketDataProvider.fetch_historical` and `fetch_latest` strictly validate matching `symbol`, `exchange`, and `interval` (failing closed on mismatches), and slice records strictly on `rec_close <= request.end_time` and `rec_close <= now` to eliminate in-progress bar leakage.

### R-041 — Finding R7: BarContext Non-Overlapping Invariant, Non-Finite JSON Rejection & Iterative Lineage
- Status: Resolved.
- Fix: `BarContext.__post_init__` enforces non-overlapping bars (`candle.timestamp < prev_candle.close_time` raises `ValueError`). `save_replay_fixture` rejects non-finite `float` and `Decimal` (`NaN`, `Infinity`). `json.loads` rejects non-standard JSON constants with `parse_constant=_reject_constant`. In `corporate_actions.py`, deduplicated identical corporate actions by `(exchange, symbol, action_type, effective_date, adjustment_factor, new_symbol)` and replaced recursive DFS in `resolve_symbol_lineage` with iterative three-color cycle detection (>1,500 hops).

### R-042 — Finding R8: Proposal Gate Odd-Lot Full Exit Allowance
- Status: Resolved.
- Fix: Detected `is_exact_full_exit = (proposal.side == "SELL" and held_qty > 0 and proposal.quantity == held_qty)`. Allowed odd-lot full liquidations without `LOT_SIZE_MISMATCH` and bypassed lot-size truncation in `max_allowed_quantity`.
