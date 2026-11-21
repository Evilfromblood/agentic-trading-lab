# Project Decision Log

Append decisions; do not silently rewrite historical decisions. Mark superseded decisions explicitly.

## D-001 — Paper-only development boundary
- Status: Accepted
- Decision: The platform remains paper-trading-only during the current development phase.
- Rationale: Establish deterministic controls and auditable behaviour before considering any live execution.
- Consequences: No live order placement; AI agents propose research/actions only; deterministic risk engine is authoritative for paper-order approval. Zerodha integration is initially read-only.
- Approval: User/product owner.

## D-002 — Hybrid development workflow
- Status: Accepted
- Decision: User owns product decisions and approvals; ChatGPT handles architecture/review; Antigravity is primary implementation environment; Claude Free may independently review GitHub changes.
- Consequences: Human approval required for commits/pushes when requested, merges, credentials, financial assumptions, and any future live-trading scope. Avoid concurrent edits to the same files.

## D-003 — Feature branch isolation
- Status: Accepted
- Decision: Active development occurs on `feature/reliable-foundation`; do not merge to `main` without explicit approval.
- Consequences: Verify branch and working tree before every Git operation that changes history or remote state.

## D-004 — M2 split
- Status: Accepted
- Decision: Split market-data work into M2a (normalized candle contracts and quality gate) and M2b (provider adapters, complete exchange calendars, corporate actions, symbol changes, replayable snapshots).
- Rationale: Do not imply calendar-aware correctness without a real exchange calendar.
- Consequences: Ambiguous gaps must be surfaced as requiring calendar knowledge, not silently accepted.

## D-005 — Provider abstraction and fail-closed ingestion architecture
- Status: Accepted
- Decision: Introduce a provider-independent ingestion architecture (`MarketDataProvider`, `ProviderAdapter`, `MarketDataIngestionPipeline`) that normalizes raw external payloads into canonical `Candle` models and routes them through the authoritative M2a quality gate before acceptance. Concrete provider starts with a deterministic synthetic provider with zero network or broker dependencies.
- Rationale: Decouples provider-specific formats (e.g. Zerodha Kite, synthetic feeds) from domain models; enforces strict fail-closed validation on raw payloads and ensures invalid or stale provider data cannot reach downstream trading strategies or risk evaluation.
- Consequences: Provider responses are never blindly trusted; floats, non-finite values, and invalid timestamps are rejected at the adapter boundary; pipeline fails closed on any validation or provider error.

## D-006 — Ingestion audit defensive hardening
- Status: Accepted
- Decision: Harden market data ingestion against payload identity mismatches (M-1), request timezone flaking/offset-None (L-1), synthetic provider range filtering (L-2), and latest-record cardinality ambiguity (L-3).
- Rationale: Defense-in-depth ensures provider payloads cannot silently stamp incorrect symbols/exchanges, invalid request timestamps fail closed cleanly with ValueError, synthetic test queries slice exact interval ranges, and latest-bar queries cannot return arbitrary records if multiple or conflicting entries are returned.
- Consequences: If an upstream provider payload contains conflicting symbol/exchange/interval, it fails with RawDataValidationError; if multiple candidate records share max timestamp in fetch_latest, pipeline fails closed with AMBIGUOUS_LATEST_RECORD.

## D-007 — Market data replay architecture levels
- Status: Accepted
- Decision: Explicitly delineate market data testing and replay into three tiers:
  1. Synthetic sample generation (implemented): In-memory deterministic bar series via `SyntheticMarketDataProvider.create_sample_series()` with zero filesystem/network dependencies.
  2. Stored replay fixtures (not yet implemented): Saving and reloading verified raw provider payloads to/from static fixture files on disk for deterministic snapshot testing.
  3. Historical replay infrastructure (not yet implemented): Full sequential market session clock simulation with tick-by-tick or bar-by-bar progression for strategy/backtest execution.
- Rationale: Avoid premature checkoffs claiming full snapshot/replay infrastructure when only in-memory synthetic sample generation currently exists.

## D-008 — Risk engine integration boundary separation
- Status: Accepted
- Decision: Document that `test_risk_engine_isolation_boundary_with_ingestion` is an architectural demonstration of component isolation and safe contract boundaries, NOT a verified end-to-end market-data-to-risk execution pipeline.
- Rationale: Prevents conflating unit-level interface boundary demonstration with full downstream pipeline verification. Real order generation and broker execution remain strictly out of scope on `feature/reliable-foundation`.

## D-009 — Cycle-safe, depth-bounded recursive freeze with DAG support
- Status: Accepted
- Decision: Enhance `_deep_freeze` across provider, adapter, and ingestion modules to track active traversal stack objects via `id(obj)` with stack removal on exit (`finally: _visited.remove(obj_id)`), and enforce a hard recursion depth limit (`max_depth=16`).
- Rationale: Guards against infinite recursion on cyclical graphs and stack overflow on deeply nested payloads, while cleanly supporting shared acyclic sub-graphs (DAGs) without false-positive cycle errors.
- Consequences: Cyclic payloads fail closed with structured `RAW_VALIDATION_ERROR` rather than escaping as unhandled `RecursionError`.

## D-010 — Session-aware intraday close truncation for H1, M30, M10
- Status: Accepted
- Decision: Continuous regular equity trading on NSE/BSE runs 09:15 to 15:30 IST (375 minutes). Intervals not dividing 375 minutes evenly (H1, M30, M10) either end naturally before session close (15:15 for H1/M30, 15:25 for M10) or emit an abbreviated final bar (15m for H1/M30, 5m for M10). In `Candle.close_time`, if an intraday candle opens before 15:30 IST but its nominal close exceeds 15:30 IST on the same calendar date, truncate `close_time` to 15:30:00 IST. In `quality._is_valid_session_close`, recognize 15:15 (for H1/M30) and 15:25 (for M10) as valid session transition close times.
- Rationale: Eliminates false `MISSING_INTERVAL` gap errors and `BOUNDARY_VIOLATION` errors on legitimate market data feeds.

## D-011 — Separation of live freshness evaluation from historical backfill integrity
- Status: Accepted
- Decision: When `ingest_historical` receives a query whose requested window is in the past (`request.end_time <= now`), disable live wall-clock staleness evaluation (`staleness_limit = None`, `eval_now = None`) unless the caller explicitly passes `max_staleness`. If the historical request covers up to current wall-clock time, enforce `FreshnessPolicy` against `now`.
- Rationale: Historical backfill data from past months or years is inherently older than the current wall-clock time; enforcing live staleness on historical backfills forced callers to use unbounded multi-year staleness overrides (`timedelta(days=3650)`), violating fail-closed safety.

## D-012 — Explicit truncated coverage reporting
- Status: Accepted
- Decision: In `SequenceIngestionResult`, evaluate whether the returned candles span the entire requested start and end window. If any part of the window is missing (`candles[0].timestamp > request.start_time` or `candles[-1].close_time < request.end_time`), explicitly report `coverage_status = "TRUNCATED_COVERAGE"`. Add `require_full_coverage: bool = False` to `ingest_historical`; when set to `True`, truncated coverage fails closed with `error_code = "TRUNCATED_COVERAGE"`.
- Rationale: Ensures partial data returns cannot be mistaken for complete historical window coverage.

## D-013 — Direct Decimal parsing and explicit bytes rejection
- Status: Accepted
- Decision: In `StandardDictAdapter._parse_decimal`, accept valid `Decimal` objects directly (including scientific notation representations such as `Decimal("1E+2")`) without passing them through ASCII string regex filters. Explicitly reject `bytes` across all price, volume, and symbol/exchange/interval arguments.
- Rationale: Eliminates improper rejection of valid `Decimal` instances while guaranteeing strict type safety.

## D-014 — Historical coverage correctness: distinction between outer boundary coverage and interior sequence completeness
- Status: Accepted
- Decision: Delineate historical sequence coverage into two distinct dimensions:
  1. Outer boundary coverage: Verifying `candles[0].timestamp <= request.start_time` and `candles[-1].close_time >= request.end_time`.
  2. Interior sequence completeness: Reusing M2a's session-aware `check_sequence_integrity` to detect missing intermediate candles, multiple consecutive missing bars, or entire missing trading days (`MISSING_INTERVAL` or `MARKET_CALENDAR_REQUIRED`), independent of the caller's `check_gaps` flag.
  When `require_full_coverage=True`, any boundary truncation or interior gap immediately fails closed with `error_code="TRUNCATED_COVERAGE"` and `coverage_status="TRUNCATED_COVERAGE"`.
  When `resp.records` is empty, report `coverage_status="EMPTY_COVERAGE"` with `EMPTY_PROVIDER_RESPONSE`.
  When quality gate rejects a sequence due to missing intervals or ambiguous calendar gaps, ensure `coverage_status` accurately reflects `TRUNCATED_COVERAGE`.
  Preserve `COVERAGE_UNVERIFIED` only when available checks find no boundary or interior truncation, reflecting that authoritative calendar completeness requires official exchange holiday data.
- Rationale: Resolves confirmed defect where missing middle candles or entire missing intermediate trading days were accepted when `check_gaps=False` even if `require_full_coverage=True` was specified.

## D-015 — Claude A Audit Batch 1 remediations: Candle integrity, DAG memoization, and historical freshness boundaries
- Status: Accepted
- Decision:
  1. Priority 1 (Candle integrity): Introduced `ExchangeSession` abstraction and configured `DEFAULT_EXCHANGE_SESSION` (09:15-15:30 IST). Added `check_session_and_grid` to detect candles outside session hours (`OUTSIDE_SESSION`), off-interval timestamps (`OFF_GRID_TIMESTAMP`), and overlapping candles (`OVERLAPPING_CANDLE`). Preserved session-truncated bar close timestamps for H1, M30, M10.
  2. Priority 2 (Historical freshness): In `ingest_historical`, decoupled historical backfills (`request.end_time < now`) from live queries (`request.end_time >= now`). Live queries strictly enforce `FreshnessPolicy`. Historical backfills disable live staleness checks but enforce `retrieval_timestamp <= now` and future-timestamp validation on all candles.
  3. Priority 3 (Recursive immutability): Unified `_deep_freeze` in `models.py` using object identity memoization (`_memo[id(obj)]`) to prevent exponential traversal in shared DAG structures, active stack cycle detection (`_active_stack`), a node budget of 10,000, and a depth limit of 16. Unified implementation imported by `quality.py`, `provider.py`, and `ingestion.py`.
  4. Priority 4 (Coverage & result consistency): Disentangled `TRUNCATED_COVERAGE` (missing intraday bars or boundary truncation) from `MARKET_CALENDAR_REQUIRED` (unaccounted multi-day jumps). Preserved strict invariant consistency in `IngestionResult` and `SequenceIngestionResult`.
  5. Priority 5 (Additional confirmed defects): Fixed D1 `close_time` calculation to ensure positive duration for post-open bars. Strictly rejected whitespace-padded numeric strings in `StandardDictAdapter` and models. Implemented explicit `__hash__` and `__eq__` on `FreshnessPolicy` for hashability and dataclass compatibility.
- Rationale: Fully resolves all five priority areas identified in Claude A's independent adversarial audit without changing branch, altering commit history, or weakening safety boundaries.

## D-016 — Claude B Audit Batch 2 remediations: Multi-exchange sessions, fail-closed coverage contract, deep freeze memoization, and calendar abstraction
- Status: Accepted
- Decision:
  1. Priority 1 (Exchange & Session Architecture - H-1, COV-05, COV-07, COV-09): Extended `Exchange` enum to support `NSE`, `BSE`, `NYSE`, and `NASDAQ` with case-insensitive normalization. Implemented US Eastern timezone with Energy Policy Act of 2005 DST transitions (`_USEasternFallback`). Extended `ExchangeSession` with `for_exchange(exchange)` factory, special-session flags, and `is_valid_grid_anchor` for D1, W1, and MN1 (rejecting off-grid timestamps like 03:00 IST). Updated `Candle.close_time` to dynamically resolve exchange sessions. Added `EXCHANGE_MISMATCH` check rejecting cross-exchange session mixing.
  2. Priority 2 (Fail-Closed Historical Coverage - H-2, COV-01): `ingest_historical` now defaults to `require_full_coverage=True` and `allow_partial=False`. If sequence boundaries are truncated or interior gaps are found, ingestion fails closed with `success=False` and empty `candles=()`. When `allow_partial=True` is explicitly passed, `success=False` is strictly maintained while populating `partial_candles` with the validated sequence, preventing downstream execution engines from accidentally processing partial backfills as successful. Defined distinct `CoverageStatus` enum values (`FULL_COVERAGE`, `COVERAGE_UNVERIFIED`, `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, `EMPTY_COVERAGE`).
  3. Priority 3 (Correct & Bounded Deep Freezing - H-3, M-1): Addressed CPython temporary object memory address reuse in `_deep_freeze` by storing `(orig_obj, frozen_obj, subtree_depth)` in memo tuples and validating `orig_obj is cur`. Bounded total traversal work across all nodes (primitives + containers) against a hard budget of `max_nodes=10000`. Prevented depth limit bypass on memoized DAG subtrees by checking `depth + subtree_depth > max_depth`.
  4. Priority 4 (Calendar Evidence & Historical Windows - M-2, COV-03, COV-08): Introduced `ExchangeCalendar` abstraction supporting trading days, declared holidays, and special sessions. Historical sequences spanning weekends or holidays without calendar evidence emit `MARKET_CALENDAR_REQUIRED`. Intervening calendar-verified non-trading days pass cleanly. Added `allow_sparse=True` contract for illiquid/sparse feeds.
  5. Priority 5 (Result-Object Invariant Hardening - M-4, ARCH-03): Enforced `__post_init__` checks on `IngestionResult` (requires valid `validation_result` on success) and `SequenceIngestionResult` (rejects `"BOGUS"` coverage statuses, rejects `raw_record_count < len(candles)`, and forbids `success=True` with `TRUNCATED_COVERAGE`, `EMPTY_COVERAGE`, or populated `partial_candles`).
  6. Priority 6 (Paper-Only Broker Boundaries & CI Hardening - SEC-01, SEC-03): Wrapped `KiteConnect` in `_ReadOnlyKiteWrapper` and implemented explicit order placement/modification/cancellation methods raising `PermissionError("Order placement is forbidden in paper-only mode")`. Pinned CI actions with commit SHAs and version comments, configured multi-version matrix (Python 3.11 and 3.12), and added `.venv311/`, `.ruff_cache/`, `*.egg-info/` to `.gitignore`. Eliminated all broad `BLE001` (`except Exception:`) suppressions in market data core.
- Rationale: Fully resolves all high-, medium-, and low-severity findings from Claude B's independent audit report without weakening paper-trading boundaries or altering commit history.

## D-017 — Claude C Audit Batch 3 remediations: Fail-closed calendar evidence, Zerodha allowlist isolation, trustworthy coverage contracts, result invariants, and CI reproducibility
- Status: Accepted
- Decision:
  1. Priority 1 (Calendar evidence must never fail open):
     - Differentiated unpopulated calendars (`is_populated is False`) from populated calendars. Empty calendars never claim evidence or provide verified coverage (`has_evidence_for_range` returns False).
     - Candles on declared calendar holidays/non-trading days are strictly rejected with `DataQualityErrorCode.OUTSIDE_SESSION`.
     - Ingestion pipeline requires sufficient calendar evidence covering the full query window before claiming `CoverageStatus.FULL_COVERAGE`.
     - Clearly distinguished verified non-trading days (valid multi-day transition), missing calendar evidence (`MARKET_CALENDAR_REQUIRED`), and actual missing trading days (`MISSING_INTERVAL`).
  2. Priority 2 (Zerodha paper-only boundary enforcement):
     - Replaced denylist-based forwarding with strict `_READ_ONLY_ALLOWLIST` on `_ReadOnlyKiteWrapper`.
     - Blocked private attribute access to underlying KiteConnect client (`_client`, `__client`, `_raw_client`) via `__getattribute__`.
     - Explicitly blocked order placement, modification, cancellation, exit, GTT, position conversion, mutual funds, and raw HTTP methods (`_post`, `_request`, `_put`, `_delete`), raising `PermissionError`.
     - Documented that Python in-process wrappers enforce application software policy, not an OS sandbox.
  3. Priority 3 (Trustworthy coverage success & explicit sparse mode):
     - Implemented `CoverageStatus.SPARSE_COVERAGE` and defined explicit policy for illiquid feeds.
     - Relaxed outer window boundary edge requirements when `allow_sparse=True` is explicitly requested, supporting illiquid instruments without treating interior unexplained gaps as valid.
     - Implemented `require_full_coverage` contract: when `require_full_coverage=True`, any unverified (`COVERAGE_UNVERIFIED`) or sparse (`SPARSE_COVERAGE`) data fails closed with `success=False` and explicit error code, preventing unverified data from being accidentally accepted downstream as complete data.
  4. Priority 4 (CI and reproducibility):
     - Added multi-version CI matrix for Python 3.11, 3.12, 3.13, and 3.14-dev in `.github/workflows/ci.yml`.
     - Configured Ruff with explicit rule selection (`F, E4, E7, E9, B, BLE, I`) in `pyproject.toml`.
     - Added test coverage threshold (`--cov-fail-under=85`) and dependency audit step (`pip-audit`) to CI.
     - Created architectural import boundary tests (`tests/test_import_boundaries.py`) verifying zero dependencies from market_data/risk_engine to broker execution.
     - Created reproducible dependency lockfile `requirements.lock`.
  5. Priority 5 (Result-object constructor invariants):
     - Added strict validation in `SequenceIngestionResult.__post_init__`: enforces `Candle` instance types, enforces uniform symbol and exchange across all candles, validates strictly monotonic timestamps, forbids `success=True` with `MARKET_CALENDAR_REQUIRED`, `TRUNCATED_COVERAGE`, or `EMPTY_COVERAGE`, forbids single intraday candle claiming `FULL_COVERAGE`, and forbids `success=False` with `FULL_COVERAGE`.
  6. Additional Correctness Fixes:
     - MN1 close-time: Implemented exact calendar month boundary calculation using `calendar.monthrange` for leap/non-leap February (28/29) and variable month lengths (30/31).
     - US Eastern fallback: Raised explicit `ValueError` for historical dates prior to 2007 in `_USEasternFallback`, requiring reliable IANA timezone data.
     - D1 midnight boundaries: Handled midnight-ending requests (`00:00:00`) consistently against previous day session close.
     - Caller-supplied `now`: Constrained injected `now` parameter against arbitrary distant future timestamps (> 365 days relative to system wall clock).
     - Exception safety (SEC-03): Eliminated all remaining broad `except Exception:` blocks across domain and adapter layers, catching explicit exception tuples including `RuntimeError`.
- Rationale: Fully resolves all findings from Claude C's independent audit report without modifying main, changing branches, or altering commit history.

## ADR-015: M2b Remediation Batch 4 — Final Blocker Resolution (H-1, N-1, H-2, M-2, M-3)

- **Date:** 2026-11-07
- **Status:** Accepted / Implemented
- **Context:** Claude D's independent Batch 3 audit identified 5 remaining actionable issues: H-1 (Zerodha raw-client escape paths via bound methods and attribute reflection), N-1 (unhandled ValueError in ingestion pipeline on holiday candle rejection), H-2 (authoritative calendar completeness contract and removal of year-level holiday inference), M-2 (enforceable CI matrix, blocking pip-audit, secret scanning, and honest dependency strategy in requirements.lock), and M-3 (genuine 85% pytest-cov verification).
- **Decisions:**
  1. **H-1 (Zerodha Raw Client Escape Path Elimination):** Removed `_get_raw_client` and `_get_underlying`. Replaced direct attribute storage with `__slots__ = ("__weakref__",)` and private module-level `weakref.WeakKeyDictionary` mappings. Implemented explicit forwarder methods on `_ReadOnlyKiteWrapper` so all allowlisted methods return `method.__self__ is wrapper` rather than leaking the underlying client. Blocked reflection access (`vars()`, `__dict__`, `object.__getattribute__`, class-level unbound methods). Documented in-process wrapper boundaries and requirement for restricted broker API credentials.
  2. **N-1 (Holiday Rejection Pipeline Crash Resolution):** Updated `ingest_historical` quality gate failure branch so sequences rejected due to holiday candles (`OUTSIDE_SESSION`) return a typed `SequenceIngestionResult(success=False, error_code="QUALITY_GATE_REJECTED", coverage_status=CoverageStatus.COVERAGE_UNVERIFIED.value)`. Guaranteed that no failed result can ever carry contradictory `FULL_COVERAGE`. Synchronized `_require_valid_now` docstring to 365 days.
  3. **H-2 (Authoritative Calendar Completeness Contract):** Added `complete: bool = False` to `ExchangeCalendar`. Removed year-level inference from unrelated holidays. Required explicit `coverage_start` and `coverage_end` bounds for complete calendars. Added `is_verified_trading_day` and `is_verified_non_trading_day` to cleanly distinguish verified trading days, non-trading days, and unverified dates. Preserved support across NSE, BSE, NYSE, and NASDAQ.
  4. **M-2 (Enforceable CI & Honest Dependency Specification):** Updated `.github/workflows/ci.yml` to test stable Python 3.14 without `continue-on-error`, made `pip-audit` blocking, added automated secret scanning, included `v3-zerodha/src` in Ruff and compileall, and enforced `--cov-fail-under=85`. Documented the core runtime zero-dependency architecture in `requirements.lock`.
  5. **M-3 (Genuine 85% Test Coverage):** Installed `pytest-cov` in both virtual environments (.venv311 and .venv). Added 21 targeted adversarial and regression tests in `tests/test_claude_batch4_regressions.py`. Achieved 87.12% genuine coverage across 269 tests on both Python 3.11.9 and 3.14.4.

## ADR-016: M2b Remediation Batch 5 — Closure-Held Zerodha Dispatch and Incomplete Calendar Fail-Closed Contract (F-1, F-2, F-3)

- **Date:** 2026-11-07
- **Status:** Accepted / Implemented
- **Context:** Claude's Batch 4 targeted verification confirmed three specific defects:
  1. F-1 (Critical): Module-level objects in `zerodha_connector.py` (`_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, `_get_client_for_connector`) exposed raw `KiteConnect` clients to callers who could invoke mutating operations (`place_order`, `place_gtt`, `_post`).
  2. F-2 (High): `ExchangeCalendar` with `complete=False` auto-populated `coverage_start` and `coverage_end` from `trading_days`, causing unlisted weekdays between min and max to be marked as verified non-trading days (`is_verified_non_trading_day == True`), allowing missing trading day gaps to be accepted as complete.
  3. F-3 (Medium): Secret scanning in CI was advisory (`detect-secrets scan` without failure gating) rather than blocking via baseline and hook.
- **Decisions:**
  1. **F-1 (Closure-Held Zerodha Dispatch & Module Registry Elimination):**
     - Completely removed `_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, and `_get_client_for_connector`.
     - Adopted instance-isolated closure dispatch: `_dispatch` is stored in `__slots__ = ("_dispatch", "__weakref__")`.
     - Overrode `__getattribute__` on both `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` to raise `PermissionError` on any access to `_dispatch`, `__dispatch`, `_client`, `_kite`, or other internal attributes.
     - On client initialization, preemptively neutralized mutation methods on the underlying client instance (`place_order`, `modify_order`, `cancel_order`, `exit_order`, `place_gtt`, `modify_gtt`, `delete_gtt`, `convert_position`, `place_mf_order`, `cancel_mf_order`, `_post`, `_request`, `_put`, `_delete`) to raise `PermissionError`, enforcing concentric rings of defense.
     - Confirmed all 20 allowlisted read-only methods remain accessible and return `method.__self__ is wrapper`.
  2. **F-2 (Incomplete Calendar Fail-Closed Evidence Contract):**
     - Updated `ExchangeCalendar.__post_init__` so `coverage_start` and `coverage_end` are auto-populated from `trading_days` ONLY when `complete=True`.
     - In `has_evidence_for_date`: when `complete=False`, returns `True` ONLY if date is explicitly in `trading_days`, `holidays`, or `special_sessions`. Unlisted weekdays have no evidence.
     - In `has_evidence_for_range`: when `complete=False`, every date in the range must have explicit evidence; any missing date causes the range to fail closed (`False`).
     - In `is_verified_non_trading_day`: when `complete=False`, unlisted weekdays are NEVER verified non-trading days (only explicit holidays and standard non-special weekends are non-trading days).
     - Verified across all four exchanges (NSE, BSE, NYSE, NASDAQ) that incomplete calendars cause D1 and M5 sequences with skipped weekdays to fail closed and reject `require_full_coverage=True`.
  3. **F-3 (Blocking Secret Scanning):**
     - Generated root-level `.secrets.baseline` in UTF-8 binary encoding with zero leaks.
     - Updated `.github/workflows/ci.yml` secret scanning step to execute `git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline`, failing the build immediately on any unmanaged secret.
  4. **Test Suite & Isolation Hardening:**
     - Fixed `sys.modules["keyring"]` and `sys.modules["kiteconnect"]` pollution in regression test suites using scoped `patch.dict`.
     - Added 14 targeted adversarial tests in `tests/test_claude_batch5_regressions.py`.
     - Validated 283/283 tests passing with 87.12% coverage on both Python 3.11.9 and Python 3.14.4.


## ADR-017: M2b Remediation Batch 6 — Zerodha In-Process Read-Only Boundary Redesign, Calendar Completeness Contract, Secret Scanning Rigor, and Test Coverage Enforcement

- **Date:** 2026-11-07
- **Status:** Accepted / Implemented
- **Context:** Claude A's Batch 5 audit returned REJECT on `m2b-remediated-batch5-bundle.zip` (SHA-256 `e708153be0bbbef6cbe7962f1d3e497e1bceb40704cfcd241be1057eac83013c`), finding:
  1. F1-A & F1-B (Critical): The closure-held dispatch mechanism used `object.__getattribute__` to recover `_dispatch`, and its closure exposed the raw client. Furthermore, mutating caller-supplied KiteConnect instances violated library contracts and broke legitimate reads.
  2. F1-D (High): Keyring handling broke connector construction in environments without keyring backends.
  3. F2-A, F2-B, F2-C (High): Calendar regression tests in Batch 5 lacked `exchange` identity; `complete=True` calendars silently inferred unexplained missing weekdays as holidays; contradictory calendar declarations (dates listed as both trading days and holidays, or special sessions with open >= close) were not rejected.
  4. F3-A & F3-B (Medium): Secret scanning baseline was not version-pinned; exclusion regex was unanchored and masked `.github` and `.gitlab-ci.yml`.
  5. T-1 (Medium): Integration tests substituted stubs instead of testing against genuine `kiteconnect==5.2.2`.
- **Decisions:**
  1. **Priority 1 (F1-A, F1-B, F1-D: Zerodha Read-Only Boundary Redesign):**
     - Never mutate caller-supplied KiteConnect instances: callers' objects remain 100% unmutated.
     - Slotted facade composition: `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` use `__slots__ = ("_target", "__weakref__")`. No `__dict__` exists; `vars()` and reflection fail closed.
     - Transport-layer rejection: Implemented `ReadOnlyTransportAdapter(HTTPAdapter)` intercepting requests at the transport level to reject any non-GET request with `PermissionError`.
     - Subclass protection: `ReadOnlyKiteConnect` mounts `ReadOnlyTransportAdapter` on `reqsession` and overrides `_request` to reject non-GET requests before transport.
     - Bound method isolation: `_ReadOnlyKiteWrapper.__getattr__` returns methods bound via `types.MethodType` so that `wrapper.method.__self__ is wrapper`.
     - Complete API surface audit: orders, autoslice orders, GTT, MF, MF SIP, convert_position, session mutation (`generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`), and raw HTTP methods (`_post`, `_put`, `_delete`, `_request`) are rejected with `PermissionError` before transport.
     - Keyring safety: safe token storage helpers catch backend errors gracefully; connector construction never crashes when keyring is unavailable or unconfigured.
     - Honest boundaries: documented that in-process Python wrappers provide defense-in-depth and application safety, but true security requires restricted broker credentials and egress controls.
  2. **Priority 2 (F2-A, F2-B, F2-C: Calendar Contradiction Rejection & Completeness Contract):**
     - Contradiction rejection in `ExchangeCalendar.__post_init__`: detects and raises `ValueError` on overlap between `trading_days` and `holidays`, special sessions on holidays, special sessions with `open >= close`, and special sessions with mismatched exchanges.
     - Completeness contract: when `complete=True`, explicit holiday evidence is required for every omitted weekday. An unexplained missing weekday has no evidence (`has_evidence_for_date == False`) and is never verified as a non-trading day.
     - Incomplete calendar fail-closed: sequences across unverified multi-day gaps fail closed with exact error code `MARKET_CALENDAR_REQUIRED` and coverage status `CoverageStatus.MARKET_CALENDAR_REQUIRED.value`.
     - Tested across all four exchanges: NSE, BSE, NYSE, NASDAQ for both D1 and M5 sequences.
  3. **Priority 3 (F3-A, F3-B: Secret Scanning Hardening):**
     - Anchored exclusion regex `^(?:\.git/|\.venv(?:311)?/|\.ruff_cache/|\.pytest_cache/|\.coverage$|htmlcov/|m2a-review\.patch$)` excludes only exact generated directories without matching `.github/` or `.gitlab-ci.yml`.
     - Pin `detect-secrets==1.5.0` in CI with `.secrets.baseline` containing version 1.5.0 and zero unbaselined secrets.
     - Verified detection of dummy AWS secrets across `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files.
  4. **Priority 4 & Integration Hardening (T-1):**
     - Genuine `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `pytest-cov`, and `ruff` verified in Python 3.11 (`.venv311`) and Python 3.14 (`.venv`).
     - Added 20 comprehensive regression tests in `tests/test_claude_batch6_regressions.py`.
     - Verified genuine KiteConnect integration with intercepted transport in `tests/test_zerodha_kiteconnect_integration.py`.
     - All 310 tests pass across the entire suite with 85.49% test coverage on both Python 3.11.9 and Python 3.14.4.
