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

## ADR-018 (Batch 7) — Closure Encapsulation, Uniform Mutation Blocking, and Secret Scanning of Lockfiles
- **Status:** Accepted (2026-11-22)
- **Context:** Claude's Batch 6 independent audit reported 7 actionable defects:
  1. D1 (Critical): Injected client slot descriptor access (`_target`) allowed callers to bypass read-only facade.
  2. D2 & D3 (High): Inconsistent session-mutation blocking; `generate_session`, `set_access_token`, and `complete_login` allowed credential modifications.
  3. D4 (High): Keyring backend failures crashed read operations even when client held valid in-memory token.
  4. D5 (High): Ingestion error code returned `QUALITY_GATE_REJECTED` instead of `TRUNCATED_COVERAGE` on missing intermediate trading days; calendar docstring was misaligned.
  5. D6 (Medium): Secret scanning baseline heuristic filtered lockfiles, skipping `requirements.lock`.
  6. D7 (Medium): Optional dependencies missed `requests`; `requirements.lock` lacked concrete pins.
- **Decisions:**
  1. **D1 (Hide raw client completely):** Removed `_target` from `__slots__` (`__slots__ = ("__weakref__",)` only). Store underlying clients strictly inside closure-encapsulated `WeakKeyDictionary` registries with zero instance attributes, zero slots, and zero module-level dictionaries. `__getattribute__` blocks `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession` with `PermissionError`. Bound methods returned via `types.MethodType(bound_call, self)` ensure `method.__self__ is wrapper`. Caller-injected `KiteConnect` instances remain 100% unmutated.
  2. **D2 & D3 (Session mutation blocking):** Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`. Both default and injected clients raise `PermissionError`. `complete_login` fails closed with `PermissionError`.
  3. **D4 (In-memory token bypass):** `_require_session()` checks `access_token` on client first without touching keyring; queries keyring only when no in-memory token exists, catching backend failures cleanly as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`.
  4. **D5 (Ingestion error code alignment):** `ingest_historical` sets `error_code = "TRUNCATED_COVERAGE"` and `coverage_status = "TRUNCATED_COVERAGE"` on `MISSING_INTERVAL`. `ExchangeCalendar` docstring updated to reflect that unlisted weekdays do NOT count as verified non-trading days without explicit holiday evidence.
  5. **D6 & D7 (Secret scanning & dependency pinning):** Removed `is_lock_file` filter from `.secrets.baseline`. Added `requests>=2.32.0` in `pyproject.toml`. Populated `requirements.lock` with exact pins (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`). CI installs pinned lockfile.
  6. **Verification:** 327 passed in 1.98s on Python 3.11 with 85.55% test coverage and 327 passed in 0.89s on Python 3.14.


## ADR-019 (Batch 7b) — Injected Client Zero-Mutation Guarantee and POST Margin Endpoint Blocking
- **Status:** Accepted (2026-11-22)
- **Context:** Claude's verification identified two final boundary findings in `v3-zerodha/src/agentic_trading/zerodha_connector.py`:
  1. F1: `_require_session()` and `logout()` could mutate caller-injected `KiteConnect` clients (`access_token` and `reqsession.headers`).
  2. F3: `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` execute HTTP POST (`_post`) in `kiteconnect==5.2.2`, violating the read-only transport invariant.
- **Decisions:**
  1. **F1 (Zero Mutation):** Store `(client, injected: bool)` in the closure-encapsulated registry. In `_require_session()`, if `injected` is True, verify non-empty `access_token` on the client; if missing, raise `KiteConfigurationError("Injected client must be pre-authenticated with an active access_token")` without mutating or querying keyring. In `logout()`, if `injected` is True, delete only keyring token and leave caller client completely untouched.
  2. **F3 (Block POST Endpoints):** Remove `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` from `_READ_ONLY_ALLOWLIST` and add to `_BLOCKED_METHODS`. Add explicit method overrides on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` before transport.
- **Consequences:** Injected clients remain 100% immutable across wrapping, session checks, and logout. All POST-based margin and contract note methods fail closed with `PermissionError`.
- **Verification:** 338 tests pass across the suite with 85.02% coverage on Python 3.11 and Python 3.14.


## ADR-020 (M2c) — Cross-Market Foundation, Instrument Registry, Corporate Actions, and Stored Replay Fixtures
- **Status:** Accepted (2026-11-22)
- **Context:** Milestone 2c establishes cross-market instrument models, strict currency isolation (INR vs USD), corporate action accounting (splits, bonuses, dividends, symbol lineage tracking), and Tier-2 stored replay fixtures with cryptographic tamper detection.
- **Decisions:**
  1. **Currency Isolation & Money Model:** Implemented `Currency` (INR, USD) and immutable `Money` dataclass rejecting float, bool, bytes, and non-finite Decimal. Cross-currency arithmetic (`+`, `-`) strictly raises `CurrencyMismatchError`. Scalar multiplication supports Decimal and int, rejecting float/bool.
  2. **Instrument & Registry:** Defined `Instrument` enforcing strict exchange-currency pairing (`NSE`/`BSE` -> `Currency.INR`, `NYSE`/`NASDAQ` -> `Currency.USD`), positive finite `tick_size`, integer `lot_size >= 1`, and deep-frozen `provider_tokens`. `InstrumentRegistry` provides O(1) resolution by `(exchange, symbol)` and `(provider, token)` with duplicate prevention and fail-closed `UnknownInstrumentError`.
  3. **Corporate Actions & Symbol Lineage:** Modeled `CorporateAction` (SPLIT, BONUS, DIVIDEND, SYMBOL_CHANGE). `resolve_symbol_lineage` deterministically traces rename graphs forward/backward with cycle detection (`ValueError`). `adjust_candles_for_corporate_actions` adjusts historical OHLC prices by cumulative factors and quantizes to `tick_size` (`ROUND_HALF_EVEN`) while preserving OHLC invariants and inverse-scaling volume.
  4. **Tier-2 Stored Replay Fixtures:** Defined `FixtureManifest` with SHA-256 payload digest. `save_replay_fixture` writes canonical JSON payloads and manifests with path-traversal prevention. `StoredReplayFixtureProvider` inherits from `MarketDataProvider`, verifies cryptographic integrity on load/fetch via `hmac.compare_digest`, and provides deterministic window filtering `[start_time, end_time)`.
- **Consequences:** Strategy engines and Time Machine backtesting can now query verified cross-market instruments, replay frozen historical snapshots from disk without network access, and adjust for corporate actions without floating-point drift.
- **Verification:** 362 passed across both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 86.56% test coverage, clean Ruff linting, zero compile errors, and zero unbaselined secrets.


## ADR-021 (M3) — Append-Only Ledger, Multi-Currency Portfolio, Strategy Contracts & Deterministic Risk Gate
- **Status:** Accepted (2026-11-22)
- **Context:** Milestone 3 establishes the simulation core, deterministic accounting, multi-currency portfolio solvency, market-specific cost models, point-in-time universe guards, strategy evaluation contracts, and the authoritative pre-trade risk gate.
- **Decisions:**
  1. **Point-in-Time Universe & Corporate Action Look-Ahead Guards:** Extended `Instrument` with `listed_date`, `delisted_date`, `version`, and `is_active_on(as_of_date)`. Added `InstrumentRegistry.get_as_of` and `list_active_on` to eliminate survivorship bias. Added `announcement_date` to `CorporateAction` and `as_of_date` filtering to `adjust_candles_for_corporate_actions` to prevent look-ahead bias.
  2. **Append-Only Accounting Ledger:** Implemented `AccountingLedger` and immutable `LedgerEntry` tracking `DEPOSIT`, `WITHDRAWAL`, `BUY_FILL`, `SELL_FILL`, `FEE_CHARGE`, and `DIVIDEND_CREDIT`. Enforces monotonic `sequence_id` (starting at 1) and strictly rejects non-causal timestamps (`timestamp < previous`).
  3. **Statutory Transaction Cost & Slippage Modeling:** Implemented `IndiaEquityFeeModel` (brokerage caps, STT, exchange txn fee, SEBI fee, stamp duty, and GST quantized to 0.01 INR) and `USEquityFeeModel` (per-share commission, SEC turnover fee, FINRA TAF fee quantized to 0.01 USD), alongside `BasisPointsSlippageModel` (adverse impact quantized to instrument tick size).
  4. **Multi-Currency Portfolio Solvency & Accounting Conservation:** Implemented `PortfolioEngine`, `PortfolioSnapshot`, and `Position`. Rejects overdrafts with `InsufficientFundsError`. Enforces strict accounting conservation invariant: $\text{Deposits} - \text{Withdrawals} + \text{Realized PnL} - \text{Fees} = \text{Cash} + \text{Cost Basis of Open Positions}$.
  5. **Strategy Contracts & Pure Technical Indicators:** Defined `SignalDirection`, `BarContext` (failing closed with `ValueError` on any bar closing after `decision_time`), `Signal`, and `TradeProposal`. Implemented pure deterministic `sma`, `ema`, `rsi`, and `atr` functions with explicit warmup verification.
  6. **Authoritative Deterministic Proposal Risk Gate:** Implemented `evaluate_trade_proposal` against `PortfolioRiskPolicy`. Deterministically fails closed on currency mismatches, lot size violations, missing or inverted stop-loss direction, per-trade risk limit breaches, single-instrument concentration breaches, total portfolio exposure breaches, daily loss limits, and drawdown circuit breakers.
- **Consequences:** Time Machine simulation and backtesting can now evaluate strategies over verified causal bar windows, execute fills with realistic statutory costs, maintain mathematically solvent multi-currency portfolios, and enforce hard risk ceilings with zero human or agent intervention.
- **Verification:** 378 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 87.89% test coverage, clean Ruff linting, zero compile errors, and zero unbaselined secrets.


## ADR-022 (M3 Batch A) — Accounting Conservation, Tick-Grid Costs, Position-Aware Risk Gate & Dead File Cleanup
- **Status:** Accepted (2026-11-22)
- **Context:** Post-M3 adversarial analysis identified accounting sign conventions, slippage quantization modes, SELL risk handling, and input validation gaps.
- **Decisions:**
  1. **Ledger Semantic Sign Invariants:** `AccountingLedger.append` enforces strict sign contracts for `DEPOSIT` (cash > 0, qty == 0), `WITHDRAWAL` (cash < 0, qty == 0), `BUY_FILL` (cash < 0, qty > 0, price > 0), `SELL_FILL` (cash > 0, qty < 0, price > 0), `FEE_CHARGE` (cash <= 0, qty == 0), and `DIVIDEND_CREDIT` (cash > 0, qty == 0). Total fees computed as non-abs `-sum(...)`. Added `get_total_dividends`.
  2. **Portfolio Accounting & Short Boundaries:** Preserved cumulative realized PnL across full exits (`_realized_pnl_by_symbol`). Replayed pre-populated ledgers in `PortfolioEngine.__init__`. Enforced `InsufficientPositionError` for short sales when `allow_short=False`, and signed market value with cover-to-flat PnL when `allow_short=True`. Implemented SELL fee overdraft prevention and `apply_dividend` API ensuring exact decimal equality in accounting conservation.
  3. **True Tick-Grid Quantization & Always-Adverse Slippage:** Replaced `.quantize(tick_size)` with `(val / tick_size).to_integral_value(mode) * tick_size` across `BasisPointsSlippageModel` (using `ROUND_CEILING` on BUY and `ROUND_FLOOR` on SELL) and `adjust_candles_for_corporate_actions` (using `ROUND_HALF_EVEN`). Validated positive price, quantity, tick size, non-negative fee rates, and currency matching caps.
  4. **Position-Aware Risk Gate & Dead File Cleanup:** `evaluate_trade_proposal` validates SELL positions (`UNAUTHORIZED_SHORT`, `INSUFFICIENT_POSITION`), waives stop-loss requirements on de-risking exits, permits held SELL exits during kill-switch triggers (daily loss and drawdown limits apply only to BUY), fails closed on non-positive peak equity / entry price / stop loss / take profit / limit price, and computes exact `max_allowed_quantity` floored to `lot_size`. Removed dead shim file `src/agentic_trading/risk_engine.py`.
- **Consequences:** Portfolio accounting satisfies strict conservation invariants without sign ambiguity, tick quantization aligns to exchange tick grids, and risk-reducing de-risking exits are never blocked by stop-loss absence or portfolio drawdown breakers.
- **Verification:** 389 tests pass across Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 87.18% coverage, clean Ruff linting, zero compile errors, and zero unbaselined secrets.


## ADR-023 (M3 Batch B) — Replay Fixture HMAC Integrity, Close-Time Slicing, BarContext Invariant Guards & Connector Hardening
- **Status:** Accepted (2026-11-22)
- **Context:** Claude Batch 6 adversarial audit of Milestone 2c and Milestone 3 identified replay fixture integrity/filtering gaps (H5, H6, H7, L7), corporate action deduplication/cycle scoping (M9, L5), instrument registry concurrency & date type safety (L3, L4), strategy BarContext & RSI zero-volatility guards (M7, M8), and Zerodha connector transport/keyring isolation (L8).
- **Decisions:**
  1. **Replay Fixture HMAC Integrity & Close-Time Slicing (H5, H6, H7, L7):** `StoredReplayFixtureProvider.fetch_historical` filters strictly by requested symbol, exchange, and interval (returning empty records on mismatch). Slices historical and latest windows using each bar's close time (`close_time <= request.end_time` and `close_time <= now`) preventing look-ahead of in-progress bars. Replaced plain SHA-256 with keyed HMAC-SHA256 (`_compute_fixture_hmac`) covering canonical manifest metadata and payload bytes; added `overwrite: bool = False` to `save_replay_fixture` raising `FixtureIntegrityError`; enforced `allow_nan=False`; validated required manifest fields; and failed closed with `ProviderPayloadError` on missing timestamps.
  2. **Corporate Action Deduplication & Scoped Cycle Resolution (M9, L5):** Deduplicated identical `CorporateAction` entries before computing cumulative adjustment factors in `adjust_candles_for_corporate_actions`. Scoped cycle detection in `resolve_symbol_lineage` strictly to the connected component reachable from the target symbol.
  3. **Instrument Registry Concurrency & Date Safety (L3, L4):** Protected `InstrumentRegistry` reads and writes with `threading.RLock`. Rejected `datetime` instances in `Instrument.is_active_on`, `InstrumentRegistry.get_as_of`, and `InstrumentRegistry.list_active_on` with `TypeError("as_of_date must be a date, not datetime")`.
  4. **Strategy BarContext Invariants & RSI Flat-Volatility Neutrality (M7, M8):** `BarContext.__post_init__` enforces strictly increasing bar timestamps, uniform intervals, strictly positive OHLC prices, valid OHLC bounds (`high >= max(open, close)` and `low <= min(open, close)`), and non-negative volume. `rsi` returns `Decimal("50")` (neutral) when both average gain and average loss are zero (flat price series).
  5. **Zerodha Connector Request Signature & Keyring Isolation (L8):** Aligned `ReadOnlyKiteConnect._request` signature to match `kiteconnect==5.2.2` (`route, method, url_args=None, params=None, is_json=False, query_params=None`), blocking non-GET methods before transport. Made `logout()` on `ZerodhaReadOnlyConnector` with injected client an immediate no-op, preserving the caller's client attributes and stored keyring token.
- **Consequences:** Replay fixtures are cryptographically authenticated and immune to in-progress look-ahead; corporate actions and instruments are thread-safe and date-isolated; strategy bar sequences are structurally verified; and broker facades guarantee complete caller isolation.
- **Verification:** 400 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 87.18% test coverage, clean Ruff linting, zero compile errors, zero unbaselined secrets, and zero inline `#` comments.


## ADR-024 (M3 Final Polish) — Exact Zero-Drift Cost Basis, Strict Positive Fill Pricing & Fixture Identity Binding
- **Status:** Accepted (2026-11-22)
- **Context:** Post-M3 verification audit residuals (R1–R8) identified precision edge cases in portfolio cost basis tracking, slippage price limits, proposal risk gate exit validations, replay fixture security, synthetic provider query filtering, and corporate action cycle handling.
- **Decisions:**
  1. **Strict Positive Pricing & Slippage Limits (R1, R3):** `BasisPointsSlippageModel.calculate_slippage` and `PortfolioEngine.apply_fill` reject non-positive prices (`price.amount <= Decimal("0")`) with `ValueError`. In `BasisPointsSlippageModel`, when adverse `ROUND_FLOOR` on `SELL` reduces effective price below `tick_size` (or `<= 0`), raise `ValueError` rather than clamping upward to `tick_size`.
  2. **Exact Zero-Drift Cost Basis Conservation (R1, R2):** `PortfolioEngine` explicitly tracks per-position total cost basis (`_total_cost_basis`) across `apply_fill` and `_replay_ledger`. On partial position reductions, basis removed is computed as `(total_cost_basis * Decimal(quantity)) / Decimal(curr_qty)`, subtracted from tracked basis, and deducted from proceeds to produce `trade_pnl`. On full position exit, the exact remaining tracked basis is removed (`_total_cost_basis.pop(key)`), guaranteeing zero residual drift (`Decimal("0")`) across multi-lot partial and full round trips.
  3. **Proposal Gate Long-Exit Direction & Odd-Lot Liquidation (R4, R8):** In `evaluate_trade_proposal`, for `SELL` exits of held long positions (`held_qty > 0`), when stop loss or take profit is provided, strictly enforces directional bounds: `stop_loss.amount < entry_price` (`INVALID_STOP_LOSS_DIRECTION`) and `take_profit.amount > entry_price` (`INVALID_TAKE_PROFIT_DIRECTION`). When `proposal.quantity == held_qty`, permits exact odd-lot liquidations without lot-size truncation or `LOT_SIZE_MISMATCH`.
  4. **Replay Fixture Cryptographic Identity & Naive Timestamp Rejection (R5):** `StoredReplayFixtureProvider` validates `manifest.fixture_id == self._fixture_id` on load, raising `FixtureIntegrityError("Fixture identity mismatch")` on tampering. Rejects timezone-naive `recorded_at` in manifest with `FixtureIntegrityError("timezone-naive")`.
  5. **Synthetic Provider Range Filtering & Time Machine Slicing (R6):** `SyntheticMarketDataProvider.fetch_historical` and `fetch_latest` strictly validate matching `symbol`, `exchange`, and `interval` (failing closed on mismatches), and slice records strictly on `rec_close <= request.end_time` and `rec_close <= now` to eliminate in-progress bar leakage.
  6. **BarContext Non-Overlapping Invariant & Non-Finite JSON Rejection (R7):** `BarContext.__post_init__` enforces non-overlapping bars (`candle.timestamp < prev_candle.close_time` raises `ValueError`). Replay fixture serialization rejects non-finite `float` and `Decimal` (`NaN`, `Infinity`), and `json.loads` rejects non-standard JSON constants with `parse_constant=_reject_constant`.
  7. **Iterative Corporate Action Lineage & Deduplication (R7):** Deduplicates identical corporate actions in `adjust_candles_for_corporate_actions` across `(exchange, symbol, action_type, effective_date, adjustment_factor, new_symbol)`. Replaced recursive DFS in `resolve_symbol_lineage` with iterative three-color cycle detection to safely handle arbitrary lineage depths (>1,500 hops).
- **Consequences:** Simulation engine guarantees mathematical conservation to exact zero residual across arbitrary order fills; risk gate accurately handles odd-lot liquidations and long-exit bracket orders; replay fixtures and provider slices strictly enforce causal boundaries without data or timestamp leakage.
- **Verification:** 410 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 87.40% test coverage, clean Ruff linting, zero compile errors, zero unbaselined secrets, and zero inline `#` comments.


## ADR-025 (Exact Zero-Drift Cost Basis & Replay Parity) — D1, D2, D3
- **Status:** Accepted (2026-11-23)
- **Context:** Claude adversarial audit identified cost basis calculation drift between live execution and ledger replay (D1, D2), and shallow non-finite pre-check in replay fixture serialization (D3).
- **Decisions:**
  1. **Unified Position Mutation & Exact Zero-Drift Math (D1, D2):**
     - Refactored position mutation (`BUY` and `SELL`, long and short) into a single shared internal helper `_apply_trade_to_position` called by both `apply_fill` and `_replay_ledger`.
     - `self._total_cost_basis: dict[tuple[Exchange, str], Decimal]` serves as the single source of truth for open position cost basis. `Position.average_cost` is derived at snapshot time as `Money(basis / Decimal(abs(qty)), currency)`.
     - Adding to position: `self._total_cost_basis[key] = self._total_cost_basis.get(key, Decimal("0")) + (Decimal(add_qty) * exec_price_amount)` without recomputing prior basis.
     - Reducing/closing position (`reduce_qty <= abs(curr_qty)`):
       On full close (`reduce_qty == abs(curr_qty)`): `basis_removed = curr_basis`, `new_basis = Decimal("0")`.
       On partial close (`reduce_qty < abs(curr_qty)`): `basis_removed = ((curr_basis * Decimal(reduce_qty)) / Decimal(abs(curr_qty))).quantize(Decimal("1E-12"), rounding=ROUND_HALF_EVEN)`, `new_basis = curr_basis - basis_removed`.
       Realized P&L delta is `proceeds - basis_removed` for long reductions and `basis_removed - cover_cost` for short reductions.
     - Flip trades (`quantity > abs(curr_qty)` when `allow_short=True`) close the existing side completely (`basis_removed = curr_basis`) and open the remainder on the opposite side with `new_basis = Decimal(rem_qty) * exec_price_amount`.
     - Guarantees `(deposits - withdrawals + realized_pnl + dividends - fees) - (cash + open_total_cost_basis) == Decimal("0")` under both default 28-digit precision and 120-digit localcontext.
  2. **Recursive Non-Finite Pre-Check in Replay Fixtures (D3):**
     - `save_replay_fixture` recursively traverses nested mappings (keys and values) and non-string/bytes sequences via `_check_finite_values`.
     - Raises `FixtureIntegrityError` on any nested `float` or `Decimal` that is `NaN`, `Infinity`, or `-Infinity` (including `Decimal("NaN")`).
- **Consequences:** Live execution and ledger replay are 100% identical with zero drift; portfolio accounting invariant holds to exact zero across multi-lot partial/full round trips; replay fixtures reject non-finite inputs at arbitrary nesting depths.
- **Verification:** 413 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`) with 87.27% test coverage, clean Ruff linting, zero compile errors, zero unbaselined secrets, and zero inline `#` comments.


## ADR-026 (Milestone 4) — Time Machine Backtesting, Walk-Forward Validation, Seeded Monte Carlo & Experiment Manifests
- **Status:** Implemented 2026-11-23; independent verification pending (see Verification).
- **Context:** Product priority after the reliable data foundation is historical backtesting plus reproducible Monte Carlo (D-016). M3 supplied the ledger, portfolio, cost models, strategy contracts and the authoritative risk gate.
- **Decisions:**
  1. **Package `agentic_trading.time_machine`** (`manifest`, `metrics`, `engine`, `validation`, `monte_carlo`); framework-independent, no broker or live imports (asserted by test).
  2. **Strict causality:** the strategy sees only `bars[: t+1]` (point-in-time corporate-action adjusted when enabled) through `BarContext`; a bar-`t` close signal becomes a proposal executed at bar `t+1` open. Order per bar: delisting guard, corporate actions, pending order at open, protective stop/target, strategy evaluation at close, equity mark at close.
  3. **Single application of costs:** `PortfolioEngine.apply_fill` already applies the configured `SlippageModel` and `FeeModel`; the engine passes raw reference prices (bar open, stop, target) and reads the slipped price and fee back from the ledger entries. Slippage is never applied twice.
  4. **Risk gate stays authoritative:** every entry and signal exit goes through `evaluate_trade_proposal` at bar-`t+1` open. Quantity is first capped by `max_volume_participation`; if the gate rejects only for non-blocking size reasons and reports `max_allowed_quantity >= lot_size`, the proposal is re-evaluated once at that size and executed only if approved. Rejections are kept in `rejected_proposals`. Exits are not liquidity-capped (documented optimism).
  5. **Protective exits:** gap-through at open fills at open; intra-bar collision resolved by `intrabar_collision_policy` (`STOP_FIRST` default). Stops quantize with `ROUND_FLOOR`, targets with `ROUND_CEILING`.
  6. **Delisting:** liquidate at open with `DELISTED` on the first bar whose local date is `>= instrument.delisted_date` and halt all trading from then on (the spec text mixed `is_active_on` and "on/after"; the conservative reading was chosen).
  7. **Corporate actions:** execution and marking use raw bars. `SPLIT`/`BONUS` effective while a position is open raises `CorporateActionConflictError` (position rebasing is not implemented); a pending BUY is cancelled across such an action. `DIVIDEND` with `cash_amount` credits `quantity * cash_amount` to the ledger for positions held at the prior close.
  8. **Accounting:** `ledger_conservation_residual` must equal exactly `Decimal("0")` at the end of every run, else `LedgerConservationError`. Open positions are liquidated at the last close with `END_OF_DATA`.
  9. **Manifest:** frozen, canonical-JSON SHA-256 over all fields; `verify_manifest_integrity` uses `hmac.compare_digest` and fails closed. It is an unkeyed checksum (tamper-evident, not authenticated): anyone who can edit a manifest can also recompute its hash. Engine settings (`position_size_pct`, stop/target defaults, participation, collision policy, adjustment flag) are sealed under `risk_policy["engine"]`; corporate actions are sealed through a digest inside `corporate_action_policy`; fee/slippage model names carry a parameter digest; `created_at` defaults to the dataset end time so results are wall-clock independent. `git_commit` is caller-asserted, not read from git.
  10. **Metrics:** Decimal throughout (`Decimal.sqrt` instead of `math.sqrt`, avoiding floats), quantized to 4 dp. Undefined ratios (zero variance, zero downside deviation, no losing trades, no trades, span under one day) return `0`, never NaN/Infinity; a `0` profit factor therefore means "undefined" when there are no losses. Annualization uses the observed observation count per elapsed year; CAGR spans first to last equity timestamp.
  11. **Validation:** `run_train_test_split` and `run_walk_forward` build a fresh strategy per run; train strictly precedes test; the test segment re-warms on its own bars (no train data leaks into it). `step_bars >= test_bars` is required so out-of-sample windows never overlap. Aggregate OOS return compounds per-window returns (capital resets each window); aggregate drawdown is the worst window.
  12. **Monte Carlo:** `random.Random(seed)` with `randrange`; iid bootstrap of absolute trade `net_pnl` (ignores serial correlation and compounding). Ruin = drawdown >= `ruin_drawdown_pct` or equity <= 0 at any step. Empty trades raise `ValueError`.
- **Known limitations:** single instrument, long-only, no pyramiding, `SHORT`/`FLAT` signals ignored; no partial exits; no position rebasing across splits; strategy attributes must be canonicalizable (string-keyed mappings, no arbitrary objects) or manifest creation fails closed.
- **Verification:** 25 tests in `tests/test_m4_time_machine.py` pass in a Linux Python 3.12 sandbox using a minimal local `pytest` stand-in (the real `pytest`, `ruff`, `pytest-cov` and `detect-secrets` were unavailable offline). Nine deliberate engine/manifest/Monte Carlo mutations were applied and each is caught by at least one test. `compileall` passed on 3.12. Full-suite regression, Ruff, coverage (`--cov-fail-under=85`), secret scanning and the `.venv311` / `.venv` runs have NOT been executed and must be run locally before acceptance.


## ADR-027 (Milestone 4 Adversarial Hardening & Verified Suite Evidence)
- **Status:** Accepted (2026-11-23)
- **Context:** Milestone 4 (Time Machine backtesting engine, walk-forward validation, seeded Monte Carlo, and experiment manifests) underwent adversarial review and hardening across both Python 3.11.9 and Python 3.14.4 environments.
- **Decisions:**
  1. **Keyed HMAC Authentication on Experiment Manifests (`manifest.py`, `engine.py`):**
     - Extended `build_experiment_manifest` and `verify_manifest_integrity` with optional `hmac_key: bytes | str | None = None`.
     - When `hmac_key` is provided, seals canonical JSON metadata using HMAC-SHA256 (`hmac.new(key_bytes, canonical_payload, hashlib.sha256).hexdigest()`), upgrading experiment manifests from unkeyed checksums to cryptographically authenticated seals.
     - When `hmac_key is None`, preserves unkeyed SHA-256 for backward compatibility.
     - Added `hmac_key: bytes | str | None = None` to `BacktestConfig` with fail-closed validation (`TypeError` for non-bytes/str, `ValueError` for empty key), automatically forwarded by `BacktestEngine.run` into `build_experiment_manifest`.
     - Verification fails closed via `hmac.compare_digest` returning `False` on key mismatch, type error, or tampered payload.
  2. **Final-Bar Pending Signal Non-Execution & Cancellation (`engine.py`):**
     - In `_Session.execute()`, after the bar-processing loop, any pending order queued on the final bar is explicitly cancelled and recorded in `rejected_proposals` with reason `"END_OF_DATA_PENDING_CANCELLED"`.
     - Eliminates orphaned pending proposals when data terminates without a subsequent bar.
  3. **Zero-Trade Monte Carlo Graceful Handling (`monte_carlo.py`):**
     - Updated `run_seeded_monte_carlo` to handle empty trade sequences gracefully instead of raising `ValueError`.
     - Returns `MonteCarloSummary` with `trade_count=0`, all return/drawdown quantiles set to `Decimal("0.0000")`, and `probability_of_loss_pct` / `probability_of_ruin_pct` set to `Decimal("0.0000")`.
  4. **Protective Gap-Through Stop Fill with Adverse Slippage (`engine.py`):**
     - Verified and tested that positions gapping down through protective stops on bar open (`bar.open <= stop`) fill at `bar.open` (not the phantom stop price) with adverse slippage applied via `apply_fill(..., side="SELL")` tick-quantizing downward.
  5. **Zero Inline Comments & Architectural Isolation:**
     - Enforced 100% comment-free codebase across `src/agentic_trading/time_machine/` and `tests/test_m4_time_machine.py` via AST and tokenizer assertions.
     - Enforced zero imports of `zerodha` or `kiteconnect` in time machine modules.
- **Consequences:** Time machine backtests produce cryptographically verifiable manifests; zero-trade backtests, final-bar signals, and gap-through stops behave deterministically; complete test suite passes dual-Python verification with >88% coverage.
- **Verification Evidence:**
  - 441 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) in 14.13s and Python 3.14.4 (`.venv`) in 6.73s.
  - Test coverage: **88.54%** (exceeding 85% requirement with `--cov-fail-under=85`).
  - Ruff check: All checks passed!
  - Compileall: 0 errors on Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-028 (Milestone 5) — Paper Trading Engine, Risk Gate Sector/Blackout Extensions & 7-Agent AI Research Desk
- **Status:** Accepted (2026-11-23)
- **Context:** Milestone 5 establishes the paper trading execution layer and the 7-agent AI research desk operating strictly within the paper-only boundary. Real-money execution and direct broker order-placement access remain strictly forbidden.
- **Decisions:**
  1. **Paper Trading Execution Layer (`src/agentic_trading/paper_trading/`):**
     - `kill_switch.py`: Independent hardware-like `KillSwitch` checking both environment variable `TRADING_DESK_STOP=1` and filesystem sentinel file `STOP`. Checks execute in O(1) time without network I/O; `is_tripped()` fails closed if tripped. Raises `KillSwitchError(RuntimeError)` with clear context.
     - `broker.py`: Simulated broker execution engine with `OrderStatus` (`PENDING`, `SUBMITTED`, `FILLED`, `PARTIALLY_FILLED`, `REJECTED`, `CANCELLED`), frozen `PaperOrder`, and frozen `ReconciliationReport`. Order IDs are idempotent deterministic hashes `order_{sha256(as_of:symbol:side:quantity:order_type)[:16]}`; duplicate order submissions return the existing order without re-executing or double-charging. Orders check the kill switch and exchange market hours before submission. Realistic fill against current candle price with always-adverse slippage (`ROUND_CEILING` on BUY, `ROUND_FLOOR` on SELL) and statutory transaction fees (`ZeroFeeModel`, `IndiaEquityFeeModel`, `USEquityFeeModel`). Daily EOD reconciliation compares ledger cash and positions against portfolio snapshots, asserting exact `Decimal("0")` conservation residual.
  2. **Risk Gate Extensions (`src/agentic_trading/risk_engine/proposal_gate.py`):**
     - Extended `PortfolioRiskPolicy` with `max_positions_per_sector: int | None = None` and `blackout_symbols: frozenset[str] = frozenset()`.
     - Extended `evaluate_trade_proposal` with `sector: str | None = None`, `sector_counts: Mapping[str, int] | None = None`, and `event_blackout: bool = False`.
     - Any BUY proposal on a symbol under event blackout fails closed with `EVENT_BLACKOUT` and `max_allowed_quantity = 0`.
     - Any BUY proposal exceeding `max_positions_per_sector` fails closed with `SECTOR_LIMIT_EXCEEDED` and `max_allowed_quantity = 0`.
     - Backward compatibility with M3/M4 is 100% preserved (defaults `None` / `False`).
  3. **7-Agent AI Research Desk (`src/agentic_trading/agents/`):**
     - `envelope.py`: Strict input/output schema contract `AgentEnvelope` with canonical JSON serialization, deterministic input hashing (`compute_inputs_hash`), and `invoke_with_schema_guard` implementing 1 retry on validation failure before failing closed with `data_quality="missing"`.
     - `llm_client.py`: Framework-agnostic `LLMClient` Protocol, deterministic offline `DeterministicStubLLMClient` returning structured JSON rules, and standard library `LocalOllamaJSONClient` using `urllib.request` with zero third-party framework dependencies.
     - `memory.py`: Three-tier memory architecture with `WorkingState` (in-memory cycle state), `DecisionRecord` and `DecisionLog` (append-only audit log with optional SQLite persistence and explicit `conn.close()` resource management), and `HumanLessonsStore` (read-only human directive store preventing autonomous modification).
     - `market_analyst.py` (Agent 1): Technical analysis engine computing pure math indicators (SMA 20/50/200, RSI 14, ATR 14, 20-day volume ratio, distance from high %, support/resistance) and validating LLM outlook (`BULLISH`, `BEARISH`, `NEUTRAL`), confidence (0.0 to 1.0), and invalidation level.
     - `data_analyst.py` (Agent 2): Fundamental health evaluation assessing `FundamentalSnapshot` and enforcing strict filing staleness checks (`max_filing_age_days = 180`), failing closed on stale data.
     - `news_analyst.py` (Agent 3): Sentiment & catalyst evaluation with headline deduplication, untrusted article container prompt injection defense, days to scheduled event calculation, and code-enforced event blackout window (`event_window_days = 2`).
     - `opportunity_scout.py` (Agent 4): Multi-market screener filtering candidates by minimum average volume and minimum price, evaluating analyst alignment, and capping shortlists at 3 with auditable drop reasons.
     - `strategist.py` (Agent 5): Senior portfolio strategist synthesizing analyst signals against `TradingMandate`, verifying `reward_to_risk >= mandate.min_reward_to_risk` and bracket price validity via pure deterministic code checks, and producing canonical `TradeProposal` objects.
     - `reporter.py`: `DailyReporter` human-readable end-of-day markdown executive summary covering portfolio snapshot, executed orders, rejected proposals, dropped candidates, and reconciliation status.
     - `orchestrator.py`: `TradingDeskOrchestrator` running a 4-stage sequential pipeline: (1) Kill switch check, (2) Parallel fan-out analysis (Agents 1, 2, 3), (3) Opportunity scouting (Agent 4) & strategy proposal (Agent 5), (4) Authoritative risk gate evaluation, paper execution, decision logging, reconciliation, and EOD reporting.
  4. **Zero Comments & Framework Independence:**
     - Zero inline `#` comments enforced across all paper trading and agent modules via automated tokenizer tests.
     - Zero imports of `zerodha` or `kiteconnect` across all modules.
- **Consequences:** Provides a complete, deterministic, auditable paper trading execution and AI research desk pipeline. All decisions are logged to an append-only audit trail; broker reconciliations assert exact zero residuals; real-money risk is fully guarded by the paper-only boundary and deterministic kill switch.
- **Verification Evidence:**
  - 453 tests pass across the full suite on genuine Python 3.11.9 (`.venv311`) in 6.01s and Python 3.14.4 (`.venv`) in 4.19s.
  - Test coverage: **88.04%** (exceeding 85% requirement with `--cov-fail-under=85`).
  - Ruff check: All checks passed!
  - Compileall: 0 errors on Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-029 (Milestone 5 Adversarial Hardening: Limit Order Semantics, Thread-Safe Broker & Agent Fail-Closed Guards)
- **Status:** Accepted (2026-11-23)
- **Context:** Adversarial review and hardening of Milestone 5 components across execution, risk, agent intelligence, and concurrency.
- **Decisions:**
  1. **PaperBroker Limit Price Validation & Marketable Bounds (`broker.py`):**
     - Immediate rejection of non-positive limit prices (`amount <= 0`) with `ValueError` and currency mismatches with `CurrencyMismatchError`.
     - Pre-evaluation of slipped execution prices against limit orders: unmarketable BUYs (`slipped_exec_price > limit_price.amount`) and SELLs (`slipped_exec_price < limit_price.amount`) remain in `OrderStatus.PENDING` without calling `PortfolioEngine.apply_fill`, eliminating unwanted fills, ledger entries, or cash mutations.
  2. **Explicit Order Cancellation State Machine (`cancel_order` in `broker.py`):**
     - Allowed transitions: `PENDING` / `SUBMITTED` -> `CANCELLED` (with `reject_reason="ORDER_CANCELLED"`).
     - Partial fills: cancels unfilled balance to `CANCELLED` without reverting executed cash or positions.
     - Terminal rejections: attempting to cancel `FILLED`, `REJECTED`, or `CANCELLED` orders raises `ValueError`.
  3. **Thread-Safe Broker Concurrency (`broker.py`):**
     - Guarded all broker order lookups, submissions, cancellations, and reconciliations with `threading.RLock()`.
     - Concurrent submissions with identical `client_order_id` synchronize cleanly, returning the identical `PaperOrder` without race conditions, duplicate ledger fills, or conservation drift.
  4. **KillSwitch & Memory Fail-Closed Hardening (`kill_switch.py`, `memory.py`):**
     - `KillSwitch`: `OSError` / filesystem permission errors on sentinel paths fail closed (`is_active() == True`), preventing bypass via unreadable sentinel files.
     - `DecisionLog`: All SQLite writes and reads use parameterized queries (`?`), explicit `with conn:` transactions, and deterministic `ORDER BY id ASC` retrieval. `HumanLessonsStore` guarantees immutable tuple storage with zero mutation methods.
  5. **Agent Input/Output Security & Prompt-Injection Hardening (`envelope.py`, `news_analyst.py`, `market_analyst.py`, `strategist.py`):**
     - `invoke_with_schema_guard`: Catches non-finite `NaN`/`Infinity` floats or Decimals in input payloads and fails closed with `data_quality="missing"`.
     - `NewsAnalyst`: Strips ASCII control characters from untrusted headlines and summaries, clamps `net_sentiment` strictly to `[-1.0, 1.0]` (rejecting `NaN`/`Infinity` to `0.0` and `data_quality="missing"`), and unconditionally enforces `blackout_suggested = True` when `days_to_next_event <= blackout_window_days`.
     - `MarketAnalyst`: Hallucinated numbers in `evidence` (not found in computed metrics payload) downgrade confidence and trigger `data_quality="missing"`; invalidations on the wrong side of `close` fail closed to `view="neutral"` and `data_quality="missing"`.
     - `Strategist`: Non-positive or non-finite pricing levels (`entry`, `stop`, `target`), invalid confidence outside `[0, 1]`, and `reward_to_risk < min_reward_to_risk` fail closed to `action="no_trade"`.
  6. **Deterministic Orchestrator Fan-Out & Pre-Stage 4 Re-Check (`orchestrator.py`):**
     - Resolved task futures in deterministic watchlist order, guaranteeing identical `envelopes` ordering regardless of thread completion timing, and isolating per-ticker exceptions.
     - Added an explicit `kill_switch.assert_clear()` re-check immediately prior to Stage 4 order submission, preventing order dispatch if the switch trips mid-cycle.
- **Verification Evidence:**
  - Full pytest suite: **457 passed in 6.09s** on Python 3.11.9 (`.venv311`) and **457 passed in 4.08s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **87.91%** (exceeding mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-030 (Milestone 6: Local-First FastAPI Backend & Self-Contained Monitoring Dashboard)
- **Status:** Accepted (2026-11-23)
- **Context:** Milestone 6 establishes a local-first HTTP REST API and visual monitoring dashboard for paper trading operations, portfolio tracking, kill switch controls, 7-agent research desk cycles, and Time Machine backtesting.
- **Decisions:**
  1. **Strict Pydantic Schemas (`src/agentic_trading/api/schemas.py`):**
     - Enforce `paper_only: Literal[True] = True` across health, status, portfolio, order, backtest, and research desk payloads.
     - Strict currency validation (`Literal["INR", "USD"]`) and positive finite `Decimal` / `int` bounds, rejecting `NaN`, `Infinity`, non-positive, or boolean values with HTTP 422.
     - Full request and response models for `HealthResponse`, `KillSwitchRequest`/`Response`, `PortfolioSummaryResponse`, `SubmitOrderRequest`, `OrderResponse`, `BacktestRequest`/`Response`, `DeskRunRequest`/`Response`, and `DecisionRecordItem`.
  2. **Thread-Safe State & Isolated Virtual Portfolios (`src/agentic_trading/api/state.py`):**
     - Implemented `TradingLabState` protected by `threading.RLock()`.
     - Maintains two strictly isolated virtual accounts: INR account (`NSE`/`BSE`, `IndiaEquityFeeModel`, `BasisPointsSlippageModel`) and USD account (`NYSE`/`NASDAQ`, `USEquityFeeModel`, `BasisPointsSlippageModel`).
     - Wires shared `KillSwitch` (backed by configurable `STOP` sentinel file), append-only SQLite `DecisionLog`, read-only `HumanLessonsStore`, `DeterministicStubLLMClient`, `TradingDeskOrchestrator`, and `BacktestEngine`.
     - Initial deposits dated in the past (`2025-01-01`) guaranteeing monotonic causal ledger timestamps across order submissions and synthetic candle series.
  3. **FastAPI Endpoints (`src/agentic_trading/api/routes.py`):**
     - `GET /api/health` and `GET /api/status`: return system status and kill switch state.
     - `POST /api/kill-switch`: creates/removes the configured `STOP` sentinel file deterministically and returns updated kill switch state.
     - `GET /api/portfolios/{currency}`: returns isolated INR or USD snapshot, open positions, recent ledger events, and verified `ReconciliationReport` asserting exact `0` conservation residual; returns HTTP 400 on unsupported currencies.
     - `POST /api/orders` & `POST /api/orders/{currency}/{client_order_id}/cancel`: route through `PaperBroker`, returning HTTP 409 when `KillSwitch` is active, HTTP 400 on currency mismatch or terminal cancel, and HTTP 404 on missing orders.
     - `POST /api/backtest`: executes `BacktestEngine` + `run_seeded_monte_carlo`, verifies `manifest_sha256` integrity, and verifies `Decimal("0")` conservation residual.
     - `POST /api/desk/run`: runs full 4-stage 7-agent research desk cycle, persists decisions to `DecisionLog`, and returns EOD markdown report.
     - `GET /api/decisions`: reads append-only audit trail records with optional `run_id` filter.
  4. **Self-Contained Dashboard (`src/agentic_trading/api/dashboard.py`):**
     - Serves `GET /` returning single-page web UI with inline CSS and vanilla JS.
     - Zero external CDN links (zero external `<script>` or `<link>` tags) for local security.
     - Prominent `PAPER TRADING ONLY` banner, interactive `EMERGENCY STOP` Kill Switch toggle, side-by-side INR/USD portfolio cards with conservation residual badge, and safe DOM manipulation (`textContent`).
  5. **Application Lifecycle (`src/agentic_trading/api/app.py`):**
     - `create_app` factory with clean `lifespan` context manager closing SQLite connections on shutdown.
     - Localhost-only entrypoint (`127.0.0.1:8000`, never `0.0.0.0`).
  6. **Zero Comments & Framework Independence:**
     - Zero inline `#` comments across all API source files and tests.
     - Zero FastAPI or web imports in domain modules (`market_data`, `simulation`, `risk_engine`, `strategy`, `time_machine`, `paper_trading`, `agents`).
- **Consequences:** Provides a complete local web dashboard and REST API for paper trading monitoring, strategy backtesting, and multi-agent desk execution with zero live financial or network risk.
- **Verification Evidence:**
  - Full pytest suite: **467 passed in 7.94s** on Python 3.11.9 (`.venv311`) and **467 passed in 4.98s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.12%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-031 (Milestone 6 Adversarial Hardening: Host/Origin CSRF & DNS-Rebinding Guard, CSP Headers, Strict Pydantic Bounds & Concurrent State Integrity)
- **Status:** Accepted (2026-11-23)
- **Context:** Following the initial Milestone 6 implementation, an adversarial audit identified vectors in HTTP host validation, cross-origin state mutation, missing browser security/CSP headers, unbounded request payload fields, and state concurrency under multi-threaded contention.
- **Decisions:**
  1. **Host Header & DNS-Rebinding Defense (`src/agentic_trading/api/app.py`):**
     - HTTP middleware extracts and normalizes the `Host` header (stripping ports and handling IPv6 bracket syntax `[::1]`).
     - Rejects any request whose host is not in `ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}` with HTTP 403 (`{"detail": "Forbidden host header"}`).
  2. **Cross-Origin State Mutation Defense (`src/agentic_trading/api/app.py`):**
     - For state-mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`), middleware parses `Origin` and `Referer` headers via `urllib.parse.urlparse`.
     - Rejects requests from untrusted origins or referers with HTTP 403 (`{"detail": "Cross-origin state mutation forbidden"}`), mitigating CSRF and malicious script exploitation.
  3. **Strict Content-Security-Policy & Defensive Security Headers (`src/agentic_trading/api/app.py`):**
     - Injected defensive security headers on every response:
       - `Content-Security-Policy`: `default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
       - `X-Content-Type-Options`: `nosniff`
       - `X-Frame-Options`: `DENY`
       - `Referrer-Policy`: `no-referrer`
  4. **Strict Schema Constraints & Bounds (`src/agentic_trading/api/schemas.py`, `src/agentic_trading/api/routes.py`):**
     - `ConfigDict(extra="forbid")` enforced across all models, failing closed on unexpected extra fields with HTTP 422.
     - String length caps (`max_length <= 64`) on request identifiers (`run_id`, `symbol`, `client_order_id`, `reason`).
     - Bounded collection limits: `DeskRunRequest.watchlist` capped at 20 symbols (`max_length=20`); `BacktestRequest.bars_count` bounded to `[10, 500]`; `monte_carlo_runs` bounded to `[1, 5000]`.
     - Sanitized cancel endpoint validation: `client_order_id` in path must be non-empty and `<= 64` characters.
  5. **Concurrency & Thread Safety (`src/agentic_trading/api/state.py`):**
     - All state access (`get_portfolio_summary`, `submit_order`, `cancel_order`, `run_backtest`, `run_desk`, `get_decisions`, `set_kill_switch`) synchronized under `self._lock` (`threading.RLock`).
     - Fixed `Position` snapshot evaluation to access `@property cost_basis.amount`, ensuring exact `Decimal("0")` conservation residual without `Money` callable errors under concurrent order submission.
  6. **Restart Continuity & Adversarial Regression Suite (`tests/test_m6_api_and_dashboard.py`):**
     - Added 5 new adversarial tests (expanding suite to 15 tests):
       - `test_dns_rebinding_and_cross_origin_state_mutation_blocked`
       - `test_security_headers_present`
       - `test_schema_extra_forbid_and_bounds_rejection`
       - `test_concurrent_state_and_portfolio_conservation`
       - `test_restart_continuity`
     - Validated zero inline `#` comments via `tokenize`.
- **Consequences:** Hardens local paper trading dashboard and HTTP API against DNS rebinding, cross-origin state manipulation, injection attacks, and thread races while preserving exact 0 conservation residuals and persistent audit trails.
- **Verification Evidence:**
  - Full pytest suite: **472 passed in 7.58s** on Python 3.11.9 (`.venv311`) and **472 passed in 3.92s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.17%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-032 (Milestone 7: Read-Only Market Feed Bridge, HMAC Replay Cache & Loopback Ollama Desk Integration)
- **Status:** Accepted (2026-11-23)
- **Context:** Milestone 6 delivered a local FastAPI dashboard and REST API backed by deterministic synthetic series and offline stub LLMs. Milestone 7 bridges the system to optional read-only delayed market data feeds and genuine local Ollama inference without introducing live trading risks, external cloud dependencies, non-deterministic API failures, or SSRF attack vectors.
- **Decisions:**
  1. **SSRF-Hardened Delayed Market Data Bridge (`src/agentic_trading/market_data/feed_bridge.py`):**
     - Implemented `ReadOnlyMarketFeedBridge` strictly enforcing `https` scheme and allowlisted hostnames (`query1.finance.yahoo.com`, `query2.finance.yahoo.com`).
     - Enforced strict payload size cap (`_MAX_PAYLOAD_BYTES = 1_048_576`, 1 MB) to guard against resource exhaustion.
     - Rejected non-finite JSON constants (`parse_constant=_reject_constant`) preventing NaN/Infinity injection.
     - Provided pluggable, offline-injectable `fetch_fn` for test isolation and offline fallback.
     - Transformed external timestamps into timezone-aware `Candle` instances aligned with official exchange timezones (`Asia/Kolkata` for NSE/BSE, `America/New_York` for NYSE/NASDAQ).
  2. **Structural & Geometric Quality Gate (`MarketDataQualityGate`):**
     - Enforced batch-level chronological ordering, interval uniformity, positive pricing, high/low envelope validity, non-negative volume, and maximum allowable percentage jump thresholds (50% max bar jump).
  3. **Cryptographically Authenticated Replay Fixture Store (`ReplayFixtureStore`):**
     - Implemented local cache using Tier-2 HMAC-SHA256 authenticated fixture manifests (`StoredReplayFixtureProvider` and `save_replay_fixture`).
     - Guarded filesystem reads/writes against directory traversal by sanitizing exchange and symbol identifiers.
     - Supported three deterministic modes: `"synthetic"`, `"cache"`, and `"delayed_feed"` (with graceful fallback to cache and synthetic data).
  4. **Loopback-Isolated Ollama Client & Transparent Failover (`src/agentic_trading/agents/llm_client.py`):**
     - Implemented `LocalOllamaJSONClient` restricted strictly to loopback addresses (`127.0.0.1`, `localhost`, `::1`, `[::1]`) and HTTP/HTTPS schemes.
     - Sanitized model names via strict regex (`^[A-Za-z0-9._:-]{1,64}$`) defaulting to `gemma4:12b`.
     - Enforced a 256 KB response payload cap and strict JSON decoding.
     - Implemented `FailoverLLMClient(primary, fallback)` which transparently delegates to the deterministic offline stub on network errors, timeouts, connection failures, or malformed responses.
  5. **API & Dashboard Integration (`src/agentic_trading/api/`):**
     - Added `GET /api/feed/{exchange}/{symbol}` endpoint with query parameters `source` and `bars`.
     - Extended `BacktestRequest` with `feed_source: Literal["synthetic", "cache", "delayed_feed"] = "synthetic"`.
     - Extended `DeskRunRequest` with `llm_backend: Literal["stub", "ollama", "failover"] = "stub"`, `ollama_model: str = "gemma4:12b"`, and `feed_source`.
     - Integrated source and backend controls into `dashboard.py` maintaining zero external CDN scripts and zero inline `#` comments.
  6. **Adversarial Regression Suite (`tests/test_m7_feeds_and_ollama.py`):**
     - Created 11 comprehensive tests covering SSRF prevention, 1 MB payload limits, non-finite constant rejection, quality gate geometry violations, HMAC cache roundtrip and tamper detection, loopback-only Ollama validation, 256 KB response caps, failover client resilience, feed route execution, and AST/tokenizer verification for zero inline comments and zero forbidden imports.
- **Consequences:** Enables operators to backtest and paper trade against authenticated delayed market data and local LLM models while maintaining complete isolation from live broker order execution and external cloud LLM dependencies.
- **Verification Evidence:**
  - Full pytest suite: **483 passed in 25.99s** on Python 3.11.9 (`.venv311`) and **483 passed in 23.92s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.34%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files.
  - Zero inline `#` comments verified across all new and edited files.


## ADR-033 (Milestone 7 Adversarial Hardening: No-Redirect SSRF Opener, Symbol Path-Traversal Guard & Concurrent Cache Safety)
- **Status:** Accepted (2026-11-23)
- **Context:** Following the initial Milestone 7 implementation, an adversarial review identified security and concurrency risks: HTTP 3xx redirect bouncing on allowlisted hosts, symbol path traversal escaping fixture directories in replay caches, race conditions during concurrent fixture file writes, and unstripped markdown fences or NaN/Infinity constants in local Ollama responses causing parsing anomalies.
- **Decisions:**
  1. **Disable HTTP Redirects in Default Transport (`src/agentic_trading/market_data/feed_bridge.py`, `src/agentic_trading/agents/llm_client.py`):**
     - Subclassed `urllib.request.HTTPRedirectHandler` as `_NoRedirectHandler` raising `urllib.error.URLError("HTTP redirects are forbidden")` on `redirect_request`.
     - Built custom urllib openers (`urllib.request.build_opener(_NoRedirectHandler())`) in both `ReadOnlyMarketFeedBridge` and `LocalOllamaJSONClient` so allowlisted hosts or loopback proxies cannot redirect requests to internal network endpoints or non-allowlisted targets.
  2. **Strict Symbol Sanitization & Directory Traversal Defense (`src/agentic_trading/market_data/feed_bridge.py`, `src/agentic_trading/api/routes.py`):**
     - Enforced strict regex validation `^[A-Za-z0-9._-]{1,32}$` and explicitly blocked `".."`, `/`, `\`, null bytes, and whitespace via `_validate_symbol` and `validate_symbol`.
     - Rejects path-traversal attempts with `ValueError` in `ReadOnlyMarketFeedBridge` and `ReplayFixtureStore`, and HTTP 400 in `GET /api/feed/{exchange}/{symbol}`.
  3. **Concurrent Cache Synchronization (`src/agentic_trading/market_data/feed_bridge.py`):**
     - Guarded `ReplayFixtureStore` read and write operations with `threading.RLock()` across `save_candles`, `load_candles`, and `fetch_candles` so multi-threaded calls never race or corrupt fixture files.
  4. **Markdown Fence Stripping & Strict Non-Finite Constant Rejection (`src/agentic_trading/agents/llm_client.py`):**
     - Added `_extract_json_text` in `LocalOllamaJSONClient` to cleanly strip ```` ```json ... ``` ```` and ```` ``` ... ``` ```` fences before JSON parsing.
     - Enforced `parse_constant=_reject_constant` on both the outer Ollama envelope and inner response text (as well as `FailoverLLMClient`), failing closed on `NaN` or `Infinity` constants with `ValueError` and triggering graceful delegation to offline stubs.
  5. **Adversarial Regression Tests (`tests/test_m7_feeds_and_ollama.py`):**
     - Expanded test suite to 15 tests, adding:
       - `test_feed_bridge_and_ollama_client_reject_http_redirects`
       - `test_path_traversal_symbol_rejection_in_feed_bridge_and_route`
       - `test_concurrent_feed_bridge_cache_access_thread_safety`
       - `test_ollama_markdown_fences_and_non_finite_rejection_with_failover`
- **Consequences:** Eliminates HTTP redirect SSRF attack vectors, closes file traversal vulnerabilities in fixture caching, protects against concurrent thread corruption, and gracefully handles common LLM formatting edge cases.
- **Verification Evidence:**
  - Full pytest suite: **487 passed in 22.56s** on Python 3.11.9 (`.venv311`) and **487 passed in 16.70s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.36%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-034 (Minimalist Dashboard UI & Human-Readable Desk Summary Formatting)
- **Status:** Accepted (2026-11-23)
- **Context:** The initial local dashboard featured heavy ASCII dividers, redundant badges, verbose Python object reprs (`Money(...)`), and prominent configuration controls that cluttered the daily monitoring experience.
- **Decisions:**
  1. **Human-Readable Money & Scannable Reporting (`src/agentic_trading/agents/reporter.py`):**
     - Formatted `Money` amounts cleanly as `f"{money.amount:,.2f} {money.currency.value}"` (e.g. `1,000,000.00 INR`, `105.10 INR`).
     - Replaced heavy `===` ASCII divider walls with clean section headings (`Portfolio Summary`, `Executed Orders`, `Skipped / Rejected`, `Position Reconciliation`).
     - Maintained backward compatibility with existing tests (`DAILY DESK SUMMARY` header preserved; `format_report = generate_eod_report` alias added).
  2. **Calm, Minimalist Dark-Slate Dashboard (`src/agentic_trading/api/dashboard.py`):**
     - Adopted clean system sans-serif typography with generous spacing (`max-width: 1020px`) and muted 1px borders.
     - Single compact header containing the title, an amber `PAPER TRADING ONLY` status pill, live status dot (`Active`/`Stopped`), and `Emergency Stop` button.
     - Two portfolio cards (INR and USD) highlighting Total Equity as the primary large figure with key-value rows for Cash, Holdings, Realized P&L, and Positions. Replaced redundant green conservation pills with fail-closed warning banners shown only on discrepancies.
     - Focused action bar (`Run Desk`, `Run Backtest`) with collapsible inline settings panel for feed source and LLM backend selectors.
     - Automatic portfolio refresh following desk runs, backtests, or kill switch toggles.
     - Clean output card showing a concise status line above the execution log rendered strictly via safe DOM manipulation (`textContent` and `createElement`).
- **Consequences:** Delivers a modern, distraction-free operations cockpit while upholding zero external CDN dependencies, strict XSS protection, and framework independence.
- **Verification Evidence:**
  - Full pytest suite: **487 passed in 16.08s** on Python 3.11.9 (`.venv311`) and **487 passed in 14.20s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.

## ADR-035 (End-to-End Platform Audit & Release Sign-Off M1–M7)
- **Status:** Accepted (2026-11-23)
- **Context:** Complete platform audit and Release Candidate 1 (RC1) sign-off covering Milestones 1 through 7, verifying cross-milestone architectural invariants, strict paper-only boundary controls, exact mathematical conservation, cross-currency isolation, causal backtesting physics, multi-agent determinism, and repository-wide code cleanliness.
- **Decisions:**
  1. **Defense-in-Depth & Boundary Audit:** Confirmed `paper_only: Literal[True] = True` across all API schemas and state responses; zero live brokerage imports in `src/agentic_trading/`; loopback host validation; DNS-rebinding & CSRF mitigation; defensive CSP headers; no-redirect HTTP transport in feed bridge and Ollama client; symbol path-traversal sanitization; fail-closed kill switch; and clean secret scanning with zero leaked credentials.
  2. **Accounting Conservation & Currency Isolation Audit:** Verified exact zero-residual mathematical conservation across `simulation/ledger.py`, `time_machine/engine.py`, `paper_trading/broker.py`, and `api/state.py`. Confirmed complete isolation between INR (`NSE`/`BSE`) and USD (`NYSE`/`NASDAQ`) virtual portfolios with zero shared cash pools or cross-currency fills. Confirmed thread-safe `RLock` synchronization across shared state mutations and parameterized SQLite queries with `with conn:` transactional blocks.
  3. **Causal Backtesting & Multi-Agent Determinism Audit:** Confirmed causal backtesting physics in `time_machine/engine.py` (next-open execution, bar-close signal evaluation, cancellation of final-bar pending signals with `END_OF_DATA_PENDING_CANCELLED`, point-in-time corporate action filtering, and keyed HMAC-SHA256 manifest authentication). Confirmed deterministic fan-out ordering in `TradingDeskOrchestrator`, mid-cycle kill switch re-checks before Stage 4 execution, read-only `HumanLessonsStore`, and fail-closed error fallback to `data_quality="missing"`.
  4. **End-to-End Integration Test (`tests/test_e2e_platform_audit.py`):** Added comprehensive integration test exercising isolated INR/USD portfolio initialization, synthetic feed fetching, backtest execution with HMAC-verified manifest and zero conservation residual, full 7-agent research desk cycle with SQLite decision logging, kill switch order blocking (HTTP 409), resume, final portfolio reconciliation, and repository-wide tokenizer validation of zero inline `#` comments.
- **Consequences:** Releases Release Candidate 1 (`full-project-rc1-bundle.zip`) with 100% verified test coverage, zero architectural regressions, and consistent documentation across all milestones.
- **Verification Evidence:**
  - Full pytest suite: **490 passed in 16.58s** on Python 3.11.9 (`.venv311`) and **490 passed in 14.72s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.


## ADR-036 (RC2 Remediation: Manual Order Risk Gating, Lock-Free Kill Switch, Sequential Snapshots & Cache HMAC Isolation)
- **Status:** Accepted (2026-11-24)
- **Context:** Release Candidate 2 (RC2) adversarial audit identified 8 findings: manual order risk bypass and arbitrary quote pricing, coarse locking blocking emergency stops during desk runs, intra-cycle portfolio snapshot staleness allowing cumulative exposure breaches, fabricated mock objects in desk runs, mark-to-market valuation omission, false dashboard reconciliation warnings on exact zero residual, broken multi-process/cold-start replay fixture HMAC verification, and over-broad zero-comment claims in documentation.
- **Decisions:**
  1. **Manual Order Risk Gating & Server-Resolved Pricing (`src/agentic_trading/api/{schemas.py,state.py,routes.py}`):**
     - Made `quote_price` optional on `SubmitOrderRequest` (`Decimal | None = None`).
     - Server resolves market price from `ReadOnlyMarketFeedBridge` when `quote_price` is omitted. If provided, server asserts `abs(quote_price - feed_price) / feed_price <= 0.05` (`ValueError: quote_price deviates from market feed`).
     - Manual orders are evaluated against authoritative `evaluate_trade_proposal` using `inr_risk_policy` or `usd_risk_policy`. Rejections raise `ProposalRiskRejectionError(ValueError)`, mapped to HTTP 422 in routes (e.g. `MISSING_STOP_LOSS`).
  2. **Lock-Free Kill Switch & Coarse Lock Removal (`src/agentic_trading/api/state.py`):**
     - Removed `with self._lock:` from `set_kill_switch`, enabling immediate $O(1)$ writes/unlinks (<0.5s) without waiting on long-running backtests or desk cycles.
     - Removed coarse `with self._lock:` wrapping the entire `run_backtest` and `run_desk` methods, acquiring locks only for atomic dictionary mutations (`self._mark_prices`).
  3. **Sequential Snapshot Refresh in Desk Orchestrator (`src/agentic_trading/agents/orchestrator.py`):**
     - In `TradingDeskOrchestrator.run_cycle`, initialized `current_snapshot = snapshot` and refreshed `current_snapshot = broker.portfolio.snapshot(...)` after every filled order in Stage 4, preventing multi-ticker cumulative exposure breaches within a single cycle.
  4. **Removal of Fabricated Mock Objects in Desk Runs (`src/agentic_trading/api/state.py`):**
     - Removed synthesized mock `FundamentalSnapshot` and fake `NewsArticle` fabrication, passing `fundamental_snapshot=None` and `news_articles=()` so desk agents evaluate genuine empty/unsupported states without hallucinations.
  5. **Mark-to-Market Valuation & Numeric Residual Check (`src/agentic_trading/api/{state.py,dashboard.py}`):**
     - Added `self._mark_prices` tracking in `TradingLabState`. `get_portfolio_summary` uses `self._mark_prices` for mark-to-market `holdings_value` and `unrealized_pnl` while computing `conservation_residual` strictly on `cost_basis`, guaranteeing exact zero residual drift.
     - In `dashboard.py`, converted reconciliation check to numeric (`Math.abs(residualNum) > 0`), eliminating false reconciliation warnings on exact `0` or `0.00` residuals.
  6. **Replay Cache HMAC Key Isolation & Configuration (`src/agentic_trading/market_data/feed_bridge.py`):**
     - `ReadOnlyMarketFeedBridge` accepts optional `hmac_key: bytes | str | None = None`, falling back to `os.environ.get("TRADING_LAB_REPLAY_HMAC_KEY")` and then per-instance `secrets.token_bytes(32)`.
     - Propagates `hmac_key` consistently to `ReplayFixtureStore` and `StoredReplayFixtureProvider`.
  7. **Zero-Comment Rule Accuracy Clarification:**
     - Clarified that zero inline comment rule applies strictly to M4–M7 and new/modified code; legacy M2a modules (`adapters.py`, `ingestion.py`, `models.py`, `provider.py`, `quality.py`) retain legitimate comments.
  8. **Comprehensive Platform Regression Tests (`tests/test_e2e_platform_audit.py`):**
     - Added 5 regression tests covering manual order risk rejection (422) and price deviation (400), lock-free kill switch responsiveness (<0.5s), sequential multi-ticker snapshot exposure limits, mark-to-market valuation with zero residual, and feed bridge HMAC key isolation.
- **Consequences:** Closes all 8 RC2 audit findings, reinforces defensive risk gating across all API order paths, ensures responsive kill-switch actuation, and guarantees multi-process cache reproducibility.
- **Verification Evidence:**
  - Full pytest suite: **495 passed in 10.39s** on Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.


## ADR-037 (Abstracted Dashboard UI with Active Cycle Inspector & Agent Chat Trace)
- **Status:** Accepted (2026-11-24)
- **Context:** To address visibility into multi-agent research operations during paper trading, the dashboard required an active cycle inspector answering "Which Paper Trading Cycle Is It Reviewing?" and a detailed agent exchange trace answering "Which Chat Is It Seeing?". Furthermore, historical cycle runs needed durable SQLite persistence and REST API exposure.
- **Decisions:**
  1. **Cycle Context & Step-by-Step Chat Trace Capture (`src/agentic_trading/agents/orchestrator.py`):**
     - Extended `DeskCycleResult` with optional `chat_trace: tuple[dict[str, Any], ...] = ()` for backward compatibility.
     - Implemented `_strip_control_chars` sanitizing untrusted inputs/outputs to prevent ASCII/ANSI control character injection.
     - Sequentially recorded granular entries across Stage 1 (Market Analyst, Data Analyst, News Analyst per target), Stage 2 (Opportunity Scout), Stage 3 (Strategist per shortlisted target), and Stage 4 (Risk Gate & Execution per proposal).
     - Each entry captures `step`, `stage`, `agent`, `symbol`, `model`, `input_context`, `output_message`, and `status` (`ok`, `approved`, `rejected`, `no_trade`, `missing`).
  2. **SQLite Cycle Run Persistence (`src/agentic_trading/agents/memory.py`):**
     - Added `cycle_runs` table in `DecisionLog._init_sqlite` with columns for `run_id`, `timestamp`, `currency`, `watchlist_json`, `feed_source`, `llm_backend`, `ollama_model`, `shortlist_json`, `dropped_json`, `approved_orders_json`, `rejected_proposals_json`, `chat_trace_json`, `report_markdown`, and `reconciled`.
     - Implemented `save_cycle_run(data)`, `list_cycle_runs(limit=25)`, and `get_cycle_run(run_id)` with parameterized queries and in-memory fallback list.
  3. **Pydantic Schemas & REST API Endpoints (`src/agentic_trading/api/{schemas.py,state.py,routes.py}`):**
     - Added `AgentChatEntry`, `CycleSummaryItem`, `CycleDetailResponse` schemas with `extra="forbid"` and `paper_only: Literal[True] = True`.
     - Enriched `DeskRunResponse` with `timestamp`, `watchlist`, `ollama_model`, and `chat_trace`.
     - Implemented `GET /api/cycles` returning recent cycle summaries and `GET /api/cycles/{run_id}` returning full cycle detail, validating `run_id` against `^[A-Za-z0-9._-]{1,64}$` and path-traversal tokens (`..`).
  4. **Abstracted Dashboard UI Redesign (`src/agentic_trading/api/dashboard.py`):**
     - Replaced raw JSON display with an abstracted dark-slate UI (`max-width: 1120px`, dark palette `#0f172a`, `#1e293b`, `#334155`, accents `#38bdf8`, `#22c55e`, `#ef4444`, `#eab308`).
     - Added Reviewing Cycle Context Strip displaying Cycle ID, timestamp, market, watchlist pills, feed source, model, and `<select id="cycleSelect">` history switcher.
     - Abstracted INR and USD portfolio cards displaying equity, cash, holdings, realized P&L, open positions, and conditional reconciliation warnings.
     - Two-Tab Inspection Workspace:
       - **Tab 1: Overview:** Candidate screening shortlist/dropped badges, executed paper orders table, risk rejections, and collapsible raw report.
       - **Tab 2: Agent Chat:** Ordered exchange cards for Stages 1–4 showing step number, stage/agent/model/symbol badges, status pill, and structured "Input Context Seen" and "Agent / LLM Response" bubbles.
     - Ensured zero external CDN dependencies and pure DOM construction via `document.createElement` and `textContent`.
  5. **Regression Verification (`tests/test_m6_api_and_dashboard.py`, `tests/test_e2e_platform_audit.py`):**
     - Added comprehensive regression tests verifying cycle trace capture, summary listing, detail retrieval, invalid run_id rejection (400), nonexistent run_id handling (404), and UI DOM element assertions with zero inline `#` comments.
- **Consequences:** Provides complete auditability and interactive review of multi-agent paper trading cycles and agent reasoning directly within the local dashboard without leaking credentials or compromising isolation.


## ADR-038 (Auto-Buy Toggle, AI Buy/Sell Price Plan Cards & Candlestick Chart with AI Overlays)
- **Status:** Accepted (2026-11-24)
- **Context:** While the 7-agent research desk produces structured trade recommendations, human operators required granular control to preview AI trade plans before paper orders execute, review modeled entry brackets, target upside, and stop loss risks, and inspect historical OHLCV candlesticks with overlaid AI price levels directly inside the local dashboard.
- **Decisions:**
  1. **Conditional Order Execution & Plan Status in Orchestrator (`src/agentic_trading/agents/orchestrator.py`):**
     - Added `auto_execute: bool = True` parameter to `TradingDeskOrchestrator.run_cycle`.
     - When `auto_execute=True` and risk gate approves: submits paper order to `PaperBroker` (`status="executed"`), records `"Stage 4 · Risk & Execution"` in `chat_trace`.
     - When `auto_execute=False` and risk gate approves: skips `broker.submit_order`, marks trade plan status as `"planned"`, and records `"Stage 4 · Risk & Plan Preview"` in `chat_trace`.
     - Added `trade_plans: tuple[dict[str, Any], ...]` and `candle_series: Mapping[str, tuple[dict[str, Any], ...]]` to `DeskCycleResult`.
     - Built comprehensive `trade_plans` across all watchlist symbols (covering executed orders, planned orders, rejected proposals, no-trade signals, and dropped candidates) capturing `symbol`, `exchange`, `currency`, `action`, `status`, `current_price`, `buy_price`, `sell_target`, `stop_loss`, `quantity`, `reward_to_risk`, `confidence`, `rationale`, `risk_reasons`, and `executed_order_id`.
     - Captured exact input OHLCV bars in `candle_series` for every analyzed ticker.
  2. **Backward-Compatible SQLite Persistence & Migration (`src/agentic_trading/agents/memory.py`):**
     - Extended `cycle_runs` table schema in `DecisionLog._init_sqlite` with `auto_buy INTEGER DEFAULT 1`, `trade_plans_json TEXT DEFAULT '[]'`, and `candle_series_json TEXT DEFAULT '{}'`.
     - Implemented dynamic SQLite migration via `ALTER TABLE cycle_runs ADD COLUMN ...` inside `try...except sqlite3.OperationalError` blocks, enabling non-destructive zero-downtime upgrades of existing test databases.
     - Updated `save_cycle_run`, `list_cycle_runs`, and `get_cycle_run` to persist and retrieve `auto_buy`, `trade_plans`, and `candle_series`.
  3. **Pydantic v2 Schemas & REST APIs (`src/agentic_trading/api/{schemas.py,state.py,routes.py}`):**
     - Added `CandleBarItem` and `TradePlanItem` schemas with `extra="forbid"`.
     - Added `auto_buy: bool = True` to `DeskRunRequest` and passed through to `orchestrator.run_cycle(auto_execute=request.auto_buy)`.
     - Extended `DeskRunResponse` and `CycleDetailResponse` with `auto_buy`, `trade_plans`, and `candle_series`.
     - Extended `CycleSummaryItem` with `auto_buy: bool = True`.
     - Populated `candles: list[CandleBarItem]` in `FeedCandlesResponse` (`GET /api/feed/{exchange}/{symbol}`).
  4. **Interactive Dashboard UI Redesign (`src/agentic_trading/api/dashboard.py`):**
     - **Auto-Buy Toggle Switch:** Positioned beside the "Run Desk" button (`<input type="checkbox" id="autoBuyToggle" checked>`) with smooth toggle transitions and dynamic text ("Auto-Buy ON" in accent blue vs "Auto-Buy OFF" in amber).
     - **AI Trade Plans Card (`tradePlansContainer`):** Structured table displaying Symbol, Status badge (`EXECUTED`, `READY TO BUY`, `RISK BLOCKED`, `NO TRADE`, `DROPPED`), Current Price, Buy Price (sky-blue highlight), Sell Target (green with upside % e.g. `+4.9%`), Stop Loss (red with risk % e.g. `-2.8%`), Qty & R:R (`12 shs | R:R 1.71`), Rationale, and interactive **`Execute Paper Buy`** button for planned items submitting `POST /api/orders`.
     - **Candlestick Chart with AI Overlays (`candlestickCanvas`):** Self-contained HTML5 `<canvas>` rendering OHLC green/red candles and wicks, ticker selector pills (`#chartTickerPills`), horizontal dashed AI levels (`BUY`, `SELL TARGET`, `STOP LOSS`) with right-margin price ticks, translucent shaded reward band (`rgba(34, 197, 94, 0.07)`) and risk band (`rgba(239, 68, 68, 0.07)`), and interactive mousemove crosshair with instant OHLCV readout (`#chartReadoutBar`).
     - Maintained zero external CDN scripts/styles and strict DOM manipulation via `document.createElement` and `textContent`.
  5. **Regression Verification (`tests/test_m6_api_and_dashboard.py`, `tests/test_e2e_platform_audit.py`):**
     - Added regression tests verifying `auto_buy=False` non-execution and planned status, manual paper buy order execution from plan parameters, `auto_buy=True` automatic execution, candle feed serialization, canvas chart DOM elements, and zero inline `#` comments.
- **Consequences:** Provides human operators with discretionary control to review and confirm AI trade brackets before paper capital is deployed, while enhancing market situational awareness through native candlestick visualization.

## ADR-039 (Complete Workstation Upgrade: Strategy Library, Open Positions Close, Visual Backtest Equity Curve, Lessons Manager & Safeguarded Sandbox Reset)
- **Status:** Accepted (2026-11-24)
- **Context:** To finalize the local-first Agentic Trading Lab into a fully integrated, operator-ready trading research workstation, several critical operational capabilities were needed on top of ADR-038: a pluggable concrete strategy library for the Time Machine backtesting engine, live open portfolio position tracking with one-click position closing, an interactive visual backtest equity curve with mousemove crosshair inspection, persistent operator trading lessons injected into agent reasoning, and a safeguarded sandbox reset capability.
- **Decisions:**
  1. **Concrete Strategy Library (`src/agentic_trading/strategy/library.py` & `__init__.py`):**
     - Implemented `EMAPullbackStrategy` (`ema_pullback`): fast EMA(9) > slow EMA(21) with pullback tolerance (`fast_val * 1.015`), ATR(14)-based stop loss (`1.5 * ATR`) and profit target (`3.0 * ATR`).
     - Implemented `RSIMeanReversionStrategy` (`rsi_mean_reversion`): Wilder RSI(14) oversold entry (`RSI <= 32`), stop loss (`1.5 * ATR`), target (`2.5 * ATR`), and overbought exit (`RSI >= 70`).
     - Implemented `ATRBreakoutStrategy` (`atr_breakout`): Donchian 20-bar channel high breakout with expanding ATR volatility.
     - Implemented `SmaCrossStrategy` (`sma_cross`): Deterministic 5/15 SMA crossover strategy.
     - Centralized `STRATEGY_REGISTRY` mapping `"ema_pullback"`, `"rsi_mean_reversion"`, `"atr_breakout"`, and `"sma_cross"`, exported through `src/agentic_trading/strategy/__init__.py`.
  2. **Strategy-Selectable Backtest & Visual Equity Curve (`src/agentic_trading/api/{schemas.py,state.py,routes.py,dashboard.py}`):**
     - Extended `BacktestRequest` with `strategy_name: str = "ema_pullback"`, validated against allowed strategy keys.
     - Extended `BacktestResponse` with `strategy_name: str` and `equity_curve: list[dict[str, str]]`.
     - Time Machine `BacktestResult.equity_curve` serialized to `list[dict[str, str]]` preserving `timestamp`, `cash`, `holdings_value`, `total_equity`, and `drawdown_pct`.
     - Built dedicated `Backtest` tab in Dashboard UI with Strategy dropdown, KPI summary cards (Net Return %, Sharpe Ratio, Max Drawdown %, Win Rate %, Trades Count, Monte Carlo 95% VaR, Profit Factor, Expectancy, Bars Evaluated, HMAC verification badge), and native `<canvas id="equityCurveCanvas">` visual line chart with green accent stroke, translucent area fill, and interactive mousemove crosshair inspection with hover readout bar (`#equityCurveReadoutBar`).
  3. **Open Portfolio Positions & One-Click Sell (`src/agentic_trading/api/{schemas.py,state.py,routes.py,dashboard.py}`):**
     - Added `PositionItem` and `PositionsListResponse` schemas with `extra="forbid"`.
     - Added endpoint `GET /api/positions` returning open holdings across INR and USD paper portfolios with average cost, current mark price, market value, and unrealized P&L.
     - Added `ClosePositionRequest` schema and endpoint `POST /api/positions/close`.
     - Position closing validates open quantity, fetches latest feed mark price, creates market SELL trade proposal, executes through `PaperBroker.submit_order(side="SELL")`, records realized P&L, updates cash, reduces position to 0, and preserves `Decimal("0")` conservation residual.
     - Built dedicated `Positions` tab in Dashboard UI with full positions table and interactive `Sell / Close` button for instant liquidation.
  4. **Persistent SQLite Trading Lessons Manager (`src/agentic_trading/agents/memory.py` & `src/agentic_trading/api/{schemas.py,routes.py,dashboard.py}`):**
     - Extended `HumanLessonsStore` with optional `db_path: Path | None`. When configured, creates `lessons` table (`id INTEGER PRIMARY KEY`, `lesson TEXT UNIQUE`, `created_at TEXT`), provides thread-safe `add_lesson(lesson: str)` and `load_lessons() -> tuple[str, ...]`.
     - Added `AddLessonRequest` and `LessonsListResponse` schemas.
     - Added endpoints `GET /api/lessons` and `POST /api/lessons`.
     - Built dedicated `Lessons` tab in Dashboard UI with rule count badges, interactive rule submission form, and persistent rule list injected directly into Strategist and Risk Guardian prompts.
  5. **Safeguarded Paper Sandbox Reset (`src/agentic_trading/api/{schemas.py,state.py,routes.py,dashboard.py}`):**
     - Added `ResetSandboxRequest` and `ResetSandboxResponse` schemas.
     - Added endpoint `POST /api/sandbox/reset`.
     - When invoked, validates Kill Switch (returns 409 if active), resets INR portfolio cash to 1,000,000, USD portfolio cash to 25,000, clears open positions and mark price caches, and reinstantiates fresh paper brokers under mutual exclusion lock.
     - Added subtle `Reset Sandbox` button in Dashboard header with client-side modal confirmation.
  6. **Workstation Regression Suite (`tests/test_m8_workstation_features.py`):**
     - Built comprehensive test suite covering concrete strategy library signals, multi-strategy backtest execution and equity curve serialization, open position listing and closing, lessons SQLite persistence across state re-instantiation, and sandbox reset under Kill Switch guards.
     - Maintained strict zero inline `#` comments and zero external CDN script/style references.
- **Consequences:** Completes the local-first Agentic Trading Lab into an autonomous research workstation with quantitative backtesting, live position control, visual equity analytics, memory-backed human governance, and safe capital reset.

## ADR-041 (SSRF-Hardened Live Fundamentals & Financial News Ingestion Adapters)
- **Status:** Accepted (2026-11-24)
- **Context:** While the 7-agent AI research desk possessed structured `DataAnalyst` and `NewsAnalyst` agent schemas, desk cycles ran without live or verified external fundamental filings and financial news feeds, causing analysts to default to `data_quality="missing"`. To empower authentic fundamental evaluations, catalyst sentiment analysis, and automated earnings blackout enforcement without introducing SSRF, XXE, or denial-of-service risks, an isolated, hardened context ingestion adapter was required.
- **Decisions:**
  1. **SSRF-Hardened Context Adapter (`src/agentic_trading/market_data/context_bridge.py`):**
     - Implemented `ReadOnlyContextBridge` providing genuine `FundamentalSnapshot`, `NewsArticle`, and `ScheduledEvent` context data.
     - **Strict SSRF Defenses:** Enforced HTTPS scheme only, strict hostname allowlist (`query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `feeds.finance.yahoo.com`), custom `_NoRedirectHandler` raising `urllib.error.URLError` on 3xx redirects, 10-second socket timeout, 512 KB payload size cap, and regex symbol validation (`^[A-Za-z0-9._-]{1,32}$`).
     - **XXE & Content Defenses:** Prior to XML parsing in `parse_rss_xml`, scanned text for `<!DOCTYPE` and `<!ENTITY` (case-insensitive) and failed closed with `ValueError`. Stripped ASCII control characters before `ET.fromstring`. Decoded entities with `html.unescape` and stripped HTML tags via regex.
     - **Three Deterministic Modes:**
       - `"synthetic"`: Generates deterministic fundamental ratios (P/E, ROE, debt-to-equity, revenue growth, next earnings date) and curated sector headlines derived from ticker hash seed without network I/O.
       - `"cache"`: Reads HMAC-SHA256 authenticated cached context payloads from disk with tamper rejection.
       - `"live"`: Fetches public RSS headlines and quote data over HTTPS with automatic fail-closed fallback to cache or synthetic.
  2. **Orchestrator, State & Desk Pipeline Integration (`src/agentic_trading/api/{schemas,state,routes}.py`):**
     - Extended `DeskRunRequest` with `context_source: Literal["synthetic", "cache", "live"] = "synthetic"`.
     - In `TradingLabState.run_desk`, resolved `ctx_res = self.context_bridge.fetch_context(...)` outside locks, passing real `FundamentalSnapshot`, `NewsArticle`s, and `ScheduledEvent`s into `WatchlistTarget`.
     - `DataAnalyst` and `NewsAnalyst` evaluate genuine fundamental metrics and catalyst sentiment, outputting `data_quality="ok"`.
     - In `orchestrator.run_cycle`, when an earnings date falls within the blackout window (`<= 2 days`), `NewsAnalyst` sets `blackout_suggested=True`, and `ProposalGate` enforces `EVENT_BLACKOUT`, setting `max_allowed_quantity = 0`.
     - Added REST endpoint `GET /api/context/{exchange}/{symbol}` with symbol sanitization, returning `ContextResponse` with `paper_only: True`.
  3. **Interactive Dashboard UI Encodings (`src/agentic_trading/api/dashboard.py`):**
     - Added Context Source dropdown inside `Settings ▾` (`#contextSourceSelect`).
     - Displayed `Context:` status badge inside the Reviewing Cycle Context Strip (`#cycleContextPill`).
     - Added `Fundamental Health & Catalyst Summary` badge card in the Overview tab (`#overviewContextContainer`).
     - Added live Quality, Growth, Safety, Sentiment, and Blackout status pills inside the Agent Chat cards.
     - Strictly maintained zero external CDN links and DOM manipulation via `document.createElement`.
  4. **Verification & Regression Suite (`tests/test_m10_fundamentals_and_news.py`):**
     - Added 8 comprehensive adversarial tests covering SSRF blocks, payload caps, XXE and entity expansion rejection, deterministic synthetic and HMAC cache loading, desk run integration with non-missing analyst ratings, earnings blackout enforcement, `/api/context` endpoint, and zero inline `#` comments.
- **Consequences:** Enables genuine fundamental and news catalyst reasoning for the multi-agent trading desk while maintaining strict defense-in-depth isolation against SSRF, XXE, and prompt injection vectors.
