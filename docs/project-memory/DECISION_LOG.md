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
