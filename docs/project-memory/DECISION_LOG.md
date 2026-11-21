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

## D-016 — Cross-market product direction and Time Machine priority
- Status: Accepted (2026-11-03)
- Decision: Build Agentic Trading Lab for both Indian markets (NSE/BSE) and US markets (NYSE/NASDAQ), extending the existing codebase. The first major product priority after the reliable data foundation is the Time Machine: historical backtesting and reproducible Monte Carlo simulation.
- Architecture: Shared domain and simulation core with market-specific adapters, calendars, sessions, instrument metadata, currencies and transaction-cost models. Do not create separate India and US platforms.
- Consequences: Complete and verify M2b first; then establish cross-market instrument/session/data foundations, strategy and deterministic simulation contracts, and build the Time Machine. Scanner, news intelligence, multi-agent research and dashboard capabilities follow rather than displacing this priority.
- Safety: Remains strictly paper-only. No real-money order execution, no agent access to broker order-placement APIs, and no autonomous live trading. AI agents may research and propose; deterministic risk controls remain authoritative. Missing, stale, malformed or contradictory data fails closed.
- Approval: User/product owner.

## D-017 — Iterative verification/remediation workflow
- Status: Accepted (2026-11-03)
- Decision: Use a resource-efficient cycle: Claude independent verification -> ChatGPT finding triage and technical direction -> Antigravity scoped remediation -> focused independent verification of the changed snapshot.
- Consequences: Do not require multiple overlapping audits before fixing a verified defect. Use Claude reviews at meaningful quality gates, preserve each audited snapshot and its SHA-256, and ensure reviewers inspect the exact same snapshot. Antigravity must add regression tests and report actual commands/results. ChatGPT distinguishes confirmed defects, design decisions and false positives before authorising scope.
- Safety: No concurrent edits to a frozen audit snapshot. No destructive Git operations. No commit, push or merge without explicit user approval; never modify `main`.

## ADR-017 (Batch 6) — Remediation Architecture for Zerodha Facade, Calendar Contradictions, and Secret Baseline Pinning
- **Status:** Accepted (2026-11-07)
- **Context:** Claude A's independent audit of Batch 5 returned REJECT based on:
  1. F1-A (Critical): In-process isolation was subverted by `object.__getattribute__` retrieving closure-dispatch internals.
  2. F1-B (High): Overwriting caller KiteConnect methods broke caller read operations.
  3. F1-D (Medium): Unconfigured keyrings crashed connector construction.
  4. F2-A (Critical): `ExchangeCalendar` accepted contradictory date definitions.
  5. F2-B (Critical): Incomplete calendar missing evidence returned false success.
  6. F3-A & F3-B (Medium): Secret scanning baseline was not version-pinned; exclusion regex was unanchored and masked `.github` and `.gitlab-ci.yml`.
  7. T-1 (Medium): Integration tests substituted stubs instead of testing against genuine `kiteconnect==5.2.2`.
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
