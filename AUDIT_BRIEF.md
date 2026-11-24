# End-to-End Platform Audit & Release Candidate Verification (Milestones 1–7)

**Status:** M1 through M7 complete, verified, hardened, and RC2-remediated (ADR-001 through ADR-038).
**Baseline Commit:** `1b7e5829474239495163da1d2d3349eb35ca9744`  
**Active Branch:** `feature/reliable-foundation`  
**Audit Bundle:** `full-project-rc2-bundle.zip`

---

## 1. Executive Summary

Milestones 1 through 7 (Market Data Foundation, Ingestion, Cross-Market Instruments, Simulation & Risk Gate, Time Machine, Paper Trading & 7-Agent Desk, Local-First FastAPI Dashboard, Read-Only Feed Bridge, and Loopback Ollama Integration) have been completely implemented, hardened against adversarial vectors, and verified end-to-end (ADR-001 through ADR-036).

All 495 tests pass across the entire test suite on both genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`). Measured test coverage is **88.33%** (strictly enforcing `--cov-fail-under=85`). Ruff linting, compileall byte-compilation on both Python versions, and blocking secret scanning (`detect-secrets-hook --baseline .secrets.baseline` version 1.5.0 scanning `requirements.lock`) pass with zero errors and zero unbaselined secrets. Audited modules across Milestones 4 through 7 (`time_machine/`, `paper_trading/`, `agents/`, `api/`, `feed_bridge.py`) and all new tests enforce zero inline `#` comments via automated tokenizer tests. Release Candidate 2 (`full-project-rc2-bundle.zip`) is fully sealed and verified.


---

## 2. Mapping from Every Finding to Resolution and Test

| Finding ID | Severity | Audit Finding Description | Implementation Fix in Source | Regression Test Verification |
|---|---|---|---|---|
| **D1** | Critical | Injected client slot descriptor access (`_target`) allowed callers to bypass read-only facade and execute live orders. | Removed `_target` from `__slots__` on `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (`__slots__ = ("__weakref__",)` only). Underlying clients are stored strictly inside closure-encapsulated `WeakKeyDictionary` registries with zero instance attributes, zero slots, and zero module-level dictionaries. `__getattribute__` blocks `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession` with `PermissionError`. Bound methods returned via `types.MethodType(bound_call, self)` ensure `method.__self__ is wrapper`. Caller-injected `KiteConnect` client instances remain 100% unmutated. | `tests/test_claude_batch7_regressions.py::test_d1_raw_client_hidden_completely`<br>`tests/test_claude_batch7_regressions.py::test_d1_injected_genuine_kiteconnect_remains_unmutated` |
| **D2 & D3** | High | Inconsistent session-mutation blocking; `generate_session`, `set_access_token`, and `complete_login` permitted write-like credential mutations. | Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and placed them into `_BLOCKED_METHODS`. Both default and injected clients raise `PermissionError` before transport. `complete_login` consistently fails closed with `PermissionError` in read-only mode, directing users to pre-authenticated injection or `store_access_token`. Updated Batch 4 regression tests to assert fail-closed behavior. | `tests/test_claude_batch7_regressions.py::test_d2_d3_session_mutation_and_complete_login_blocked`<br>`tests/test_claude_batch7_regressions.py::test_d2_default_readonly_kiteconnect_blocks_mutations`<br>`tests/test_claude_batch4_regressions.py::test_h1_connector_read_methods_with_session` |
| **D4** | High | Keyring backend failures or locked states crashed read operations even when an authenticated client was already in memory. | Updated `_require_session()` to check if the underlying client in memory holds a valid `access_token`; if present, read operations (`profile`, `margins`, `holdings`, `positions`, `orders`, `trades`, `quote`, `ltp`, `ohlc`, `historical_data`, `instruments`) proceed cleanly without touching keyring. Keyring is queried only when no in-memory token exists, catching backend failures cleanly as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`. | `tests/test_claude_batch7_regressions.py::test_d4_in_memory_token_bypasses_locked_keyring`<br>`tests/test_claude_batch7_regressions.py::test_d4_missing_token_with_locked_keyring_raises_kite_configuration_error`<br>`tests/test_claude_batch7_regressions.py::test_d4_keyboard_interrupt_in_keyring_not_swallowed` |
| **D5** | High | Ingestion error code returned `QUALITY_GATE_REJECTED` instead of `TRUNCATED_COVERAGE` when intermediate trading days were missing; `ExchangeCalendar` docstring was out of alignment with completeness contract. | In `src/agentic_trading/market_data/ingestion.py`, when intermediate trading days or intervals are missing (`MISSING_INTERVAL`), set both `coverage_status = CoverageStatus.TRUNCATED_COVERAGE.value` and `error_code = "TRUNCATED_COVERAGE"`. Updated `ExchangeCalendar` docstring in `models.py` to state that unlisted weekdays do NOT count as verified non-trading days without explicit holiday evidence. | `tests/test_claude_batch7_regressions.py::test_d5_missing_intermediate_trading_day_d1_returns_truncated_coverage`<br>`tests/test_claude_batch7_regressions.py::test_d5_missing_intermediate_candle_m5_returns_truncated_coverage`<br>`tests/test_market_data_ingestion.py::test_coverage_intermediate_missing_middle_candle_typed_error` |
| **D6** | Medium | Secret scanner ignored `requirements.lock` due to heuristic filter; CI workflow contained a stray allowlist pragma. | Removed `{"path": "detect_secrets.filters.heuristic.is_lock_file"}` from `filters_used` in `.secrets.baseline` so lockfiles are actively scanned. Removed stray `# pragma: allowlist secret` comment from `.github/workflows/ci.yml`. | `tests/test_claude_batch7_regressions.py::test_d6_detect_secrets_scans_requirements_lock` |
| **D7** | Medium | Optional dependencies missed `requests`; `requirements.lock` lacked concrete pins. | Added `"requests>=2.32.0"` to `zerodha-readonly` optional dependencies in `pyproject.toml`. Populated `requirements.lock` with exact verified pins (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`) and updated CI to install from the lockfile. | `tests/test_claude_batch7_regressions.py::test_d7_pinned_dependencies_in_requirements_lock` |
| **F1** | High | Injected `KiteConnect` client mutation during `_require_session()` and `logout()`. | Stored `(client, injected)` tuple in closure registry. `_require_session()` verifies pre-authenticated token without mutating client or querying keyring. `logout()` leaves injected client's `access_token` and `reqsession.headers` completely untouched. | `tests/test_claude_batch7_regressions.py::test_f1_injected_client_not_mutated_by_require_session`<br>`tests/test_claude_batch7_regressions.py::test_f1_injected_client_not_mutated_by_logout`<br>`tests/test_claude_batch7_regressions.py::test_f1_unauthenticated_injected_client_raises_kite_configuration_error`<br>`tests/test_claude_batch7_regressions.py::test_f1_genuine_injected_kiteconnect_not_mutated_across_session_and_logout` |
| **F3** | High | `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` executed HTTP POST in `kiteconnect==5.2.2`. | Removed all three from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS` with explicit overrides on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` before transport. | `tests/test_claude_batch7_regressions.py::test_f3_order_margins_blocked_on_mock_wrapper`<br>`tests/test_claude_batch7_regressions.py::test_f3_order_margins_blocked_on_connector`<br>`tests/test_claude_batch7_regressions.py::test_f3_order_margins_blocked_on_genuine_kiteconnect_wrapper`<br>`tests/test_claude_batch7_regressions.py::test_f3_order_margins_blocked_on_readonly_kiteconnect_instance` |

---

## 3. Verification Commands & Evidence

### 3.1. Full Pytest Suite & Coverage
- **Python 3.11.9 (`.venv311`):**
  ```powershell
  .\.venv311\Scripts\python.exe -m pytest --cov=agentic_trading --cov-report=term-missing --cov-fail-under=85
  ```
  **Result:** 338 passed in 2.24s. Coverage: **85.02%** (exceeds mandatory 85% gate). Full test-by-test log saved in `python311_verification_report.txt`.
- **Python 3.14.4 (`.venv`):**
  ```powershell
  .\.venv\Scripts\python.exe -m pytest --cov=agentic_trading --cov-report=term-missing --cov-fail-under=85
  ```
  **Result:** 338 passed in 1.42s. Coverage: **85.02%**. Full test-by-test log saved in `python314_verification_report.txt`.

### 3.2. Ruff Linting
- Command:
  ```powershell
  .\.venv311\Scripts\python.exe -m ruff check src tests v3-zerodha/src
  ```
  **Result:** `All checks passed!`

### 3.3. Python Byte-Compilation
- Commands:
  ```powershell
  .\.venv311\Scripts\python.exe -m compileall -q src tests v3-zerodha/src
  .\.venv\Scripts\python.exe -m compileall -q src tests v3-zerodha/src
  ```
  **Result:** Exit code 0 on both Python 3.11 and Python 3.14.

### 3.4. Secret Scanning
- Command:
  ```powershell
  .\.venv311\Scripts\detect-secrets-hook.exe --baseline .secrets.baseline
  ```
  **Result:** Exit code 0 on all tracked repository files, scanning `requirements.lock`.

### 3.5. Dependency Vulnerability Audit
- Command:
  ```powershell
  .\.venv311\Scripts\python.exe -m pip_audit
  ```
  **Result:** `No known vulnerabilities found`.

---

## 4. Required Follow-Up Before Independent Acceptance

1. Have Claude perform an independent adversarial review of `m2b-remediated-batch7b-bundle.zip`.
2. Do not begin M2c until that review closes all critical and high-severity findings.

---

## 5. Milestone 3 Final Polish Pass (R1–R8) & Audit Hardening (D1–D3) Summary

Milestone 3 establishes the append-only ledger, multi-currency portfolio solvency, statutory cost models, point-in-time universe guards, strategy contracts, deterministic risk gate, and cross-market foundation. The Final Polish Pass and Hardening resolve all audit findings:

| Item | Area | Description & Resolution | Verification Test |
|---|---|---|---|
| **D1 & D2** | Portfolio Accounting | Position mutation unified in `_apply_trade_to_position` across live `apply_fill` and `_replay_ledger`. Exact zero-drift math (`_total_cost_basis`) with `ROUND_HALF_EVEN` 1E-12 basis removal guarantees exact `Decimal("0")` conservation residual across arbitrary multi-lot fills under 28-digit precision and 120-digit localcontext, and 100% parity on replay. | `tests/test_m3_simulation_and_risk.py::test_d1_claude_multi_lot_sequence_and_fuzz_residual`<br>`tests/test_m3_simulation_and_risk.py::test_d2_partial_sell_ledger_replay_parity` |
| **D3** | Replay Fixtures | `save_replay_fixture` recursively traverses nested mappings (keys and values) and sequences via `_check_finite_values`, raising `FixtureIntegrityError` if any nested float or Decimal is `NaN`, `Infinity`, or `-Infinity`. | `tests/test_m2c_cross_market_foundation.py::test_d3_save_replay_fixture_nested_non_finite_rejection` |
| **R1 & R3** | Costs & Pricing | `calculate_slippage` and `apply_fill` reject `price <= 0` with `ValueError`. When adverse `ROUND_FLOOR` on sell reduces effective price below `tick_size` (or `<= 0`), raises `ValueError` rather than clamping upward. | `tests/test_m3_simulation_and_risk.py::test_r1_slippage_and_fill_price_positive_rejection`<br>`tests/test_m3_simulation_and_risk.py::test_r3_slippage_sell_below_tick_size_rejection` |
| **R2** | Portfolio Accounting | Exact per-position cost basis tracking (`_total_cost_basis`) eliminates fractional cent drift on partial and full liquidations, guaranteeing exact zero residual drift (`Decimal("0")`). | `tests/test_m3_simulation_and_risk.py::test_r2_exact_zero_drift_conservation_residual` |
| **R4 & R8** | Proposal Risk Gate | Directional checks on long exits: `stop_loss < entry_price` and `take_profit > entry_price`. Detects exact full exits (`proposal.quantity == held_qty`), permitting odd-lot full liquidations without `LOT_SIZE_MISMATCH` or truncation. | `tests/test_m3_simulation_and_risk.py::test_r4_proposal_gate_long_exit_stop_loss_take_profit_direction`<br>`tests/test_m3_simulation_and_risk.py::test_r8_proposal_gate_odd_lot_full_exit_allowed` |
| **R5** | Replay Fixtures | Validates `manifest.fixture_id == self._fixture_id` on load, raising `FixtureIntegrityError("Fixture identity mismatch")`. Rejects timezone-naive `recorded_at` in manifest. | `tests/test_m2c_cross_market_foundation.py::test_r5_replay_fixture_id_mismatch_and_naive_dt` |
| **R6** | Synthetic Provider | Enforces strict matching on `symbol`, `exchange`, and `interval` (failing closed on mismatch), and slices on `rec_close <= end_time` and `rec_close <= now` to eliminate in-progress bar leakage. | `tests/test_m2c_cross_market_foundation.py::test_r6_synthetic_provider_filtering_and_slicing` |
| **R7** | Strategy & Actions | `BarContext` enforces non-overlapping bars (`timestamp < prev_close`). Replay fixtures reject non-finite float/Decimal and parse constants. Corporate actions deduplicate identical actions and resolve lineage iteratively (>1500 hops). | `tests/test_m3_simulation_and_risk.py::test_r7_bar_context_overlapping_bars_rejection`<br>`tests/test_m2c_cross_market_foundation.py::test_r7_corporate_actions_dedup_and_deep_lineage`<br>`tests/test_m2c_cross_market_foundation.py::test_r7_replay_fixture_rejects_non_finite_values_and_constants` |

### Suite Verification:
- **Pytest:** 413 passed in 11.21s on Python 3.11 (`.venv311`), 413 passed in 7.42s on Python 3.14 (`.venv`).
- **Coverage:** **87.27%** (exceeds `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 in git diff.

---

## 6. Milestone 4 — Time Machine Hardened (ADR-026 & ADR-027), Verified 2026-11-23

**Files:** `src/agentic_trading/time_machine/{__init__,manifest,metrics,engine,validation,monte_carlo}.py`, `tests/test_m4_time_machine.py`.

| Area | Behaviour | Test |
|---|---|---|
| Zero look-ahead | Signal at bar `t` close fills at bar `t+1` open; strategy context is `bars[: t+1]` | `test_signal_executes_at_next_open_not_signal_close`, `test_changing_future_bars_never_changes_earlier_decisions` |
| Final-bar signal cancellation | Signal emitted on final bar has no subsequent open; cleanly cancelled with `END_OF_DATA_PENDING_CANCELLED` | `test_final_bar_pending_signal_cancelled_at_end_of_data` |
| Gap and collision | Gap-through fills at open (with adverse slippage applied); `STOP_FIRST` / `TARGET_FIRST` | `test_gap_through_stop_fills_at_gap_open`, `test_protective_gap_through_stop_fills_at_open_with_adverse_slippage`, `test_intrabar_collision_policies_and_single_trigger_exits` |
| Liquidity | Quantity capped at `volume * max_volume_participation`; sub-lot cap rejected | `test_liquidity_participation_cap_and_sub_lot_rejection` |
| Delisting | `DELISTED` liquidation at open, trading halted | `test_delisting_forces_liquidation_at_open_and_halts_trading` |
| Conservation | Exact `Decimal("0")` residual, NSE/INR and NASDAQ/USD with statutory fees and slippage | `test_cross_market_conservation_nse_inr_and_nasdaq_usd` |
| Keyed HMAC Manifest | Cryptographic HMAC-SHA256 authentication with `hmac_key` (bytes or str); tamper-evident unkeyed SHA-256 fallback | `test_manifest_keyed_hmac_and_backtest_config_validation`, `test_manifest_reproducibility_and_tamper_detection` |
| Validation | Train strictly precedes test; fresh strategy per run; no overlapping OOS windows | `test_train_test_split_temporal_separation`, `test_walk_forward_windows_are_ordered_non_overlapping_and_isolated` |
| Monte Carlo | Bit-for-bit reproducible per seed, seed-sensitive, input validation, graceful zero-trade handling | `test_seeded_monte_carlo_is_reproducible_and_seed_sensitive`, `test_monte_carlo_degenerate_cases_and_validation` |
| Zero Comments & Imports | Automated AST and tokenizer test enforcing 0 inline comments and 0 forbidden imports | `test_time_machine_sources_have_no_inline_comments_or_forbidden_imports` |

### Suite Verification:
- **Pytest:** 441 passed in 14.13s on Python 3.11 (`.venv311`), 441 passed in 6.73s on Python 3.14 (`.venv`).
- **Coverage:** **88.54%** (exceeds `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline` (scanning `requirements.lock`).
- **Inline `#` Comments:** 0 comments in git diff.---

## 7. Milestone 5 — Paper Trading Engine & 7-Agent AI Research Desk (ADR-028 & ADR-029 Hardened), Verified 2026-11-23

**Files:**
- `src/agentic_trading/paper_trading/{__init__,kill_switch,broker}.py`
- `src/agentic_trading/risk_engine/proposal_gate.py` (extended)
- `src/agentic_trading/agents/{__init__,envelope,llm_client,memory,market_analyst,data_analyst,news_analyst,opportunity_scout,strategist,reporter,orchestrator}.py`
- `tests/test_m5_paper_and_agents.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Paper Trading | `KillSwitch` | Dual-mechanism hardware-like kill switch (`TRADING_DESK_STOP` env var and `STOP` sentinel file) evaluated in O(1) time without network I/O; fail-closed on `OSError`/permission errors raising `KillSwitchError`. | `test_kill_switch_env_var_and_stop_file_guards`, `test_news_analyst_nan_sentiment_and_mid_cycle_kill_switch` |
| Paper Trading | `PaperBroker` | Idempotent deterministic order IDs (`order_{sha256(...)[:16]}`), duplicate submission protection, pre-order kill switch & market hours checks, limit order bounds (`OrderStatus.PENDING` when unmarketable), order cancellation state machine (`cancel_order`), thread-safe concurrency (`threading.RLock`), adverse slippage, statutory fee models, and daily reconciliation asserting exact `Decimal("0")` residual. | `test_paper_broker_order_idempotence_and_reconciliation`, `test_paper_broker_limit_order_semantics_and_cancel_state_machine`, `test_paper_broker_concurrent_submissions_thread_safety_and_conservation` |
| Risk Engine | `proposal_gate` | Extended with sector concentration caps (`SECTOR_LIMIT_EXCEEDED`) and corporate event blackout (`EVENT_BLACKOUT`). Rejections fail closed setting `max_allowed_quantity = 0`. M3/M4 backward compatibility 100% preserved. | `test_risk_gate_event_blackout_and_sector_cap_extension` |
| Agents | `AgentEnvelope` & LLM Client | Standardized input/output schemas, deterministic input hashing (`compute_inputs_hash`), non-finite `NaN`/`Infinity` input rejection with fail-closed fallback (`data_quality="missing"`), retry on schema mismatch. Zero third-party LLM framework dependencies (`LLMClient` protocol, offline rule stub, native standard library Ollama client). | `test_envelope_hashing_and_schema_guard_fail_closed`, `test_news_analyst_nan_sentiment_and_mid_cycle_kill_switch` |
| Agents | 3-Tier Memory | `WorkingState` ephemeral cycle state, append-only SQLite `DecisionLog` with parameterized queries (`?`) and deterministic `ORDER BY id ASC` retrieval, and read-only `HumanLessonsStore` preventing autonomous self-modification. | `test_orchestrator_end_to_end_desk_cycle_nse_and_nasdaq` |
| Agents | Market Analyst (1) | Deterministic math indicator calculations (SMA 20/50/200, RSI 14, ATR 14, volume ratio, distance from high %, support/resistance), evidence number hallucination verification, and invalidation prices on the wrong side of close failing closed. | `test_market_analyst_indicator_computation_and_invalidation_guards` |
| Agents | Data Analyst (2) | `FundamentalSnapshot` balance sheet/income evaluation with strict filing staleness checks (`max_filing_age_days = 180`). | `test_data_analyst_staleness_and_score_clamping` |
| Agents | News Analyst (3) | Control character stripping on untrusted titles/summaries, headline deduplication, untrusted article container prompt injection defense, strict `net_sentiment` clamping (rejecting `NaN`/`Infinity` to `0.0`), and code-enforced event blackout window. | `test_news_analyst_prompt_injection_defense_and_event_blackout`, `test_news_analyst_nan_sentiment_and_mid_cycle_kill_switch` |
| Agents | Scout & Strategist (4 & 5) | `OpportunityScout` liquidity/price filtering, analyst alignment scoring, shortlist ranking capped at 3 with auditable drop reasons. `Strategist` synthesis, deterministic math verification of pricing and reward-to-risk, and canonical `TradeProposal` generation. | `test_opportunity_scout_filtering_and_shortlist_capping`, `test_strategist_mandate_verification_and_proposal_creation` |
| Agents | Desk Orchestrator | `TradingDeskOrchestrator` 4-stage sequential pipeline executing kill switch check, parallel fan-out analysis preserving deterministic watchlist ordering, exception isolation across tickers, opportunity scouting & proposal, mid-cycle kill switch re-check, and authoritative risk/execution/reconciliation/reporting across NSE (INR) and NASDAQ (USD). | `test_orchestrator_end_to_end_desk_cycle_nse_and_nasdaq`, `test_orchestrator_deterministic_stage1_fan_out_ordering_under_threadpool` |
| Architecture | Zero Comments & Isolation | Automated AST and tokenizer test enforcing zero inline `#` comments and zero forbidden imports (`zerodha`/`kiteconnect`) across all paper trading and agent modules. | `test_m5_sources_have_no_inline_comments_or_forbidden_imports` |

### Suite Verification:
- **Pytest:** 457 passed in 6.09s on Python 3.11 (`.venv311`), 457 passed in 4.08s on Python 3.14 (`.venv`).
- **Coverage:** **87.91%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline` (scanning `requirements.lock`).
- **Inline `#` Comments:** 0 comments in git diff.---

## 8. Milestone 6 — Local-First FastAPI Backend & Interactive Web Dashboard (ADR-030 & ADR-031 Hardened), Verified 2026-11-23

**Files:**
- `src/agentic_trading/api/{__init__,app,schemas,state,routes,dashboard}.py`
- `tests/test_m6_api_and_dashboard.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Security | `app.py` Middleware | DNS-rebinding protection rejecting unauthorized `Host` headers outside localhost/127.0.0.1; cross-origin state mutation guard blocking non-local `Origin` and `Referer` headers on POST/PUT/DELETE. | `test_dns_rebinding_and_cross_origin_state_mutation_blocked` |
| Security | Defensive CSP | Content-Security-Policy (`default-src 'none'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` on all responses. | `test_security_headers_present` |
| Validation | Pydantic Schemas | `extra="forbid"`, string length caps (`<= 64`), bounded watchlist (`<= 20`), bounded bars and Monte Carlo runs, non-positive price/qty rejection. | `test_schema_extra_forbid_and_bounds_rejection` |
| Concurrency | State & Portfolios | Thread-safe `RLock` synchronization across virtual INR/USD portfolios, order submission, backtest, and desk runs; exact `0` conservation residual preserved under 16-thread contention. | `test_concurrent_state_and_portfolio_conservation` |
| Dashboard | Local Web UI | Self-contained single-page UI with zero external CDN scripts or stylesheet links; Emergency Stop kill switch button. | `test_dashboard_renders_and_has_no_external_cdn_links` |

### Suite Verification:
- **Pytest:** 472 passed in 7.58s on Python 3.11 (`.venv311`), 472 passed in 3.92s on Python 3.14 (`.venv`).
- **Coverage:** **88.17%** (exceeds `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.---

## 9. Milestone 7 — Read-Only Market Feed Bridge, HMAC Replay Cache & Loopback Ollama Desk Integration (ADR-032 & ADR-033 Hardened), Verified 2026-11-23

**Files:**
- `src/agentic_trading/market_data/feed_bridge.py`
- `src/agentic_trading/market_data/__init__.py`
- `src/agentic_trading/agents/llm_client.py`
- `src/agentic_trading/agents/__init__.py`
- `src/agentic_trading/api/{schemas,state,routes,dashboard}.py`
- `tests/test_m7_feeds_and_ollama.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Feed Bridge | `ReadOnlyMarketFeedBridge` | SSRF-hardened fetcher strictly enforcing HTTPS, allowlisted hosts (`query1.finance.yahoo.com`, `query2.finance.yahoo.com`), no-redirect urllib opener (`_NoRedirectHandler`), 1 MB payload limits, and non-finite constant rejection (`parse_constant=_reject_constant`). | `test_feed_bridge_ssrf_and_payload_caps`, `test_feed_bridge_rejects_non_finite_constants`, `test_feed_bridge_and_ollama_client_reject_http_redirects` |
| Security | Symbol Sanitization | Strict symbol regex `^[A-Za-z0-9._-]{1,32}$` blocking `..`, `/`, `\`, null bytes, and whitespace; path-traversal rejection in feed bridge and HTTP 400 in `/api/feed/{exchange}/{symbol}`. | `test_path_traversal_symbol_rejection_in_feed_bridge_and_route` |
| Concurrency | Cache Thread Safety | `threading.RLock()` synchronization in `ReplayFixtureStore` and `ReadOnlyMarketFeedBridge` preventing race conditions during concurrent cache writes/reads. | `test_concurrent_feed_bridge_cache_access_thread_safety` |
| Quality Gate | `MarketDataQualityGate` | Batch validation checking monotonic timestamps, interval uniformity, positive OHLC, high/low envelopes, non-negative volume, and 50% max bar jump thresholds. | `test_quality_gate_detects_geometry_and_jump_violations` |
| Replay Cache | `ReplayFixtureStore` | Tier-2 HMAC-SHA256 authenticated cache with deterministic `"synthetic"`, `"cache"`, and `"delayed_feed"` modes and automatic fallback. Directory traversal prevention. | `test_replay_fixture_store_cache_and_tamper_detection`, `test_feed_bridge_fallback_to_cache_and_synthetic` |
| LLM Client | `LocalOllamaJSONClient` | Restricted strictly to loopback addresses (`127.0.0.1`, `localhost`, `::1`, `[::1]`) and HTTP/HTTPS schemes; no-redirect opener; model name regex sanitization; 256 KB payload cap; clean markdown fence extraction (`_extract_json_text`); strict `NaN`/`Infinity` rejection. | `test_ollama_client_loopback_isolation_and_model_validation`, `test_ollama_client_payload_cap_and_json_parsing`, `test_ollama_markdown_fences_and_non_finite_rejection_with_failover` |
| LLM Failover | `FailoverLLMClient` | Transparent failover delegating to deterministic offline stub on network errors, timeouts, connection issues, non-finite constants, or malformed JSON responses. | `test_failover_client_delegates_to_fallback`, `test_ollama_markdown_fences_and_non_finite_rejection_with_failover` |
| API & UI | Feed & Desk Integration | `GET /api/feed/{exchange}/{symbol}` endpoint with bounds validation; `llm_backend` and `feed_source` parameters in backtest and desk run APIs; UI selectors with zero external scripts. | `test_feed_endpoint_and_state_integration` |
| Architecture | Zero Comments & Isolation | Automated tokenizer and AST verification enforcing 0 inline `#` comments and 0 forbidden imports. | `test_no_inline_comments_in_m7_code`, `test_import_boundaries_maintained` |

### Suite Verification:
- **Pytest:** 487 passed in 22.56s on Python 3.11 (`.venv311`), 487 passed in 16.70s on Python 3.14 (`.venv`).
- **Coverage:** **88.36%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.---

## 10. Dashboard UI Simplification & Human-Readable Desk Summary Formatting (ADR-034), Verified 2026-11-23

**Files:**
- `src/agentic_trading/agents/reporter.py`
- `src/agentic_trading/api/dashboard.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Reporter | Human-Readable Money | `_format_value` formats `Money` as `f"{money.amount:,.2f} {money.currency.value}"` (e.g., `1,000,000.00 INR`), eliminating raw Python reprs. Added `format_report = generate_eod_report` alias. | `tests/test_m5_paper_and_agents.py::test_reporter_eod_summary_generation_and_formatting`, `tests/test_m6_api_and_dashboard.py::test_desk_run_and_reporting_lifecycle` |
| Reporter | Clean Headings | Replaced heavy `===` ASCII divider walls with clean section headings (`Portfolio Summary`, `Executed Orders`, `Skipped / Rejected`, `Position Reconciliation`) while preserving exact `DAILY DESK SUMMARY` header. | `tests/test_m5_paper_and_agents.py::test_reporter_eod_summary_generation_and_formatting` |
| Dashboard | Minimalist Layout | Dark-slate theme (`max-width: 1020px`) with system sans-serif typography, compact header, and muted borders. | `tests/test_m6_api_and_dashboard.py::test_dashboard_renders_and_has_no_external_cdn_links` |
| Dashboard | Header & Safety | Amber `PAPER TRADING ONLY` badge, live active/stopped status indicator, and emergency stop kill switch button in a unified compact header. | `tests/test_m6_api_and_dashboard.py::test_dashboard_renders_and_has_no_external_cdn_links` |
| Dashboard | Portfolio Cards | Primary large Total Equity display on INR and USD cards, compact key-value metrics, automated portfolio refresh after desk runs/backtests, and fail-closed discrepancy warnings. | `tests/test_m6_api_and_dashboard.py::test_dashboard_renders_and_has_no_external_cdn_links` |
| Dashboard | Settings & Output | Collapsible `Settings ▾` toggle for feed source and LLM backend selectors, safe DOM manipulation via `textContent`/`createElement`, zero external CDN scripts or stylesheet links. | `tests/test_m6_api_and_dashboard.py::test_dashboard_renders_and_has_no_external_cdn_links`, `tests/test_m7_feeds_and_ollama.py::test_no_inline_comments_in_m7_code` |

### Suite Verification:
- **Pytest:** 487 passed in 13.12s on Python 3.11 (`.venv311`), 487 passed in 14.20s on Python 3.14 (`.venv`).
- **Coverage:** **88.33%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.---

## 11. End-to-End Platform Audit & Release Sign-Off (ADR-035), Verified 2026-11-23

**Files:**
- `tests/test_e2e_platform_audit.py`
- `tests/test_import_boundaries.py`
- `src/agentic_trading/api/app.py`
- `src/agentic_trading/api/state.py`
- `src/agentic_trading/paper_trading/broker.py`
- `src/agentic_trading/time_machine/engine.py`
- `src/agentic_trading/agents/orchestrator.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Security | Paper-Only Boundary | `paper_only: Literal[True] = True` across all API schemas and state responses. Zero live broker imports (`zerodha`, `kiteconnect`) across `src/agentic_trading/`. | `tests/test_e2e_platform_audit.py::test_import_boundaries_maintained`, `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit` |
| Security | Host & Network Controls | Loopback `Host` validation, DNS-rebinding guards, cross-origin state mutation blocking (HTTP 403 on invalid Origin/Referer), and defensive CSP/security headers in `app.py`. | `tests/test_m6_api_and_dashboard.py::test_dns_rebinding_and_cross_origin_state_mutation_blocked`, `tests/test_m6_api_and_dashboard.py::test_security_headers_present` |
| Security | SSRF & Traversal Defenses | No-redirect HTTP openers (`_NoRedirectHandler`), allowlisted Yahoo chart hosts, 1 MB payload limits, and regex symbol validation (`^[A-Za-z0-9._-]{1,32}$`) in `feed_bridge.py`. Loopback isolation in `LocalOllamaJSONClient`. | `tests/test_m7_feeds_and_ollama.py::test_feed_bridge_and_ollama_client_reject_http_redirects`, `tests/test_m7_feeds_and_ollama.py::test_path_traversal_symbol_rejection_in_feed_bridge_and_route` |
| Accounting | Mathematical Conservation | Exact `Decimal("0")` residual: `(deposits - withdrawals + realized_pnl + dividends - fees) - (cash + open_total_cost_basis) == Decimal("0")` across ledger, portfolio, time machine, paper broker, and API state. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit`, `tests/test_m3_simulation_and_risk.py::test_r2_exact_zero_drift_conservation_residual` |
| Accounting | Currency Isolation | Strict isolation between INR (`NSE`/`BSE`) and USD (`NYSE`/`NASDAQ`) virtual portfolios with zero cross-currency fills or shared cash pools. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit`, `tests/test_m6_api_and_dashboard.py::test_inr_and_usd_portfolio_isolation` |
| Concurrency | Thread Safety & Persistence | Parameterized SQLite queries with `with conn:` transactions in `memory.py`. Shared state mutations in `state.py`, `broker.py`, and `feed_bridge.py` protected by `threading.RLock`. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit`, `tests/test_m6_api_and_dashboard.py::test_concurrent_state_and_portfolio_conservation` |
| Causality | Time Machine Backtest | Next-open execution, causal bar-close signal evaluation, cancellation of final-bar pending orders (`END_OF_DATA_PENDING_CANCELLED`), and keyed HMAC-SHA256 manifest authentication. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit`, `tests/test_m4_time_machine.py::test_signal_executes_at_next_open_not_signal_close` |
| Multi-Agent | Deterministic Orchestration | Deterministic fan-out ordering under `ThreadPoolExecutor`, pre-Stage 4 kill switch re-checks, read-only `HumanLessonsStore`, and fail-closed error fallback to `data_quality="missing"`. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit`, `tests/test_m5_paper_and_agents.py::test_orchestrator_deterministic_stage1_fan_out_ordering_under_threadpool` |
| End-to-End | Lifecycle Integration | Unified lifecycle: portfolio initialization, synthetic feed fetch, backtest with verified manifest and zero residual, 7-agent research desk cycle with SQLite audit logging, kill switch order blocking (HTTP 409), resume, and final reconciliation. | `tests/test_e2e_platform_audit.py::test_end_to_end_platform_lifecycle_audit` |
| Cleanliness | Zero Inline Comments | Repository-wide tokenizer assertion verifying zero inline `#` comments across all modules under `src/agentic_trading/`. | `tests/test_e2e_platform_audit.py::test_repository_wide_zero_inline_comments` |

### Suite Verification:
- **Pytest:** 490 passed in 16.58s on Python 3.11 (`.venv311`), 490 passed in 14.72s on Python 3.14 (`.venv`).
- **Coverage:** **88.33%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.---

## 12. RC2 Remediation: Manual Order Risk Gating, Lock-Free Kill Switch, Sequential Snapshots & Cache HMAC Isolation (ADR-036), Verified 2026-11-24

**Files:**
- `src/agentic_trading/api/schemas.py`
- `src/agentic_trading/api/state.py`
- `src/agentic_trading/api/routes.py`
- `src/agentic_trading/api/dashboard.py`
- `src/agentic_trading/agents/orchestrator.py`
- `src/agentic_trading/market_data/feed_bridge.py`
- `tests/test_e2e_platform_audit.py`
- `tests/test_m6_api_and_dashboard.py`
- `tests/test_m7_feeds_and_ollama.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Risk Gate | Manual Order Defense | `quote_price` is optional on `SubmitOrderRequest`. Server resolves entry price from market feed and validates 5% deviation if client supplied. Evaluates `evaluate_trade_proposal` against portfolio risk policy, raising `ProposalRiskRejectionError` (HTTP 422) on missing stop loss or policy breach. | `test_manual_order_risk_gate_and_price_deviation` |
| Safety | Lock-Free Kill Switch | Removed coarse lock from `set_kill_switch`, allowing immediate $O(1)$ writes/unlinks (<0.5s) even while backtests or desk runs are in flight. Removed coarse lock wrapping `run_backtest` and `run_desk`. | `test_lock_free_kill_switch_responsiveness` |
| Multi-Agent | Sequential Snapshots | Orchestrator refreshes portfolio snapshot after every fill in Stage 4, evaluating sequential proposals against cumulative exposure and position caps. | `test_multi_ticker_sequential_snapshot_updates_prevent_exposure_breach` |
| Multi-Agent | Authentic Agent Inputs | Removed fabricated mock `FundamentalSnapshot` and fake `NewsArticle` in `run_desk`, passing genuine `None` and `()` so analysts evaluate true empty/unsupported states. | `test_desk_run_and_decision_log_retrieval` |
| Accounting | Mark-to-Market & Zero Residual | Added `_mark_prices` tracking in `TradingLabState`. `get_portfolio_summary` reports real mark-to-market `holdings_value` and `unrealized_pnl` while calculating `conservation_residual` strictly on `cost_basis`, guaranteeing exact `0` residual. Numeric reconciliation check in dashboard JS. | `test_mark_to_market_holdings_and_conservation_residual`, `test_dashboard_renders_and_has_no_external_cdn_links` |
| Feed Bridge | Replay Cache HMAC Key Isolation | `ReadOnlyMarketFeedBridge` accepts optional `hmac_key`, falling back to `TRADING_LAB_REPLAY_HMAC_KEY` env var and per-instance `secrets.token_bytes(32)`. Passes key consistently to `ReplayFixtureStore` and `StoredReplayFixtureProvider`. | `test_feed_bridge_per_instance_hmac_isolation`, `test_feed_bridge_fails_over_to_cache_on_network_error` |
| Cleanliness | Zero Inline Comments | Tokenizer verification enforcing zero inline comments across all M4-M7 modules. | `test_repository_wide_zero_inline_comments` |

### Suite Verification:
- **Pytest:** 495 passed in 10.39s on Python 3.11 (`.venv311`), 495 passed in 11.20s on Python 3.14 (`.venv`).
- **Coverage:** **88.33%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.---

## 13. Milestone 8 Workstation Upgrade: Strategy Library, Positions Close, Backtest Equity Curve, Lessons Manager & Sandbox Reset (ADR-038, ADR-039), Verified 2026-11-24

**Files:**
- `src/agentic_trading/strategy/library.py`
- `src/agentic_trading/strategy/__init__.py`
- `src/agentic_trading/agents/memory.py`
- `src/agentic_trading/api/{schemas,state,routes,dashboard}.py`
- `tests/test_m8_workstation_features.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Strategy Library | `STRATEGY_REGISTRY` | Concrete deterministic quantitative strategies: `EMAPullbackStrategy` (9/21 EMA + ATR brackets), `RSIMeanReversionStrategy` (RSI 32/70 + ATR), `ATRBreakoutStrategy` (Donchian 20 channel), and `SmaCrossStrategy` (5/15 SMA). Exported through `strategy/__init__.py`. | `test_strategy_library_direct_evaluation_and_registry`, `test_backtest_with_different_strategies_and_equity_curve` |
| Positions | Open Holdings & Close | `GET /api/positions` returns open positions with average cost, mark price, market value, and unrealized P&L. `POST /api/positions/close` submits market SELL order at current feed mark price, validates open quantity, records realized P&L, sets quantity to 0, and preserves `Decimal("0")` conservation residual. Blocked by Kill Switch (HTTP 409). | `test_positions_list_and_close_position` |
| Backtesting | Visual Equity Curve | `BacktestRequest` accepts `strategy_name: str = "ema_pullback"`. `BacktestResponse` returns `strategy_name` and `equity_curve: list[dict[str, str]]` with timestamp, cash, holdings, total equity, and drawdown %. Dashboard renders interactive `<canvas id="equityCurveCanvas">` with green stroke, area fill, and mousemove hover crosshair. | `test_backtest_with_different_strategies_and_equity_curve`, `test_dashboard_ui_m8_elements_and_hygiene` |
| Lessons | SQLite Persistence | `HumanLessonsStore` extended with SQLite `lessons` table (`id`, `lesson`, `created_at`). `GET /api/lessons` and `POST /api/lessons` manage persistent rules injected directly into Strategist and Risk Guardian agent reasoning. | `test_lessons_store_sqlite_persistence_and_orchestrator` |
| Sandbox | Safeguarded Reset | `POST /api/sandbox/reset` restores INR portfolio to 1,000,000 and USD portfolio to 25,000, clears open positions and mark price cache under lock. Blocked by Kill Switch (HTTP 409). | `test_sandbox_reset` |
| Dashboard | Operator UI | Added subtle Reset Sandbox header button, Strategy selector beside Run Backtest, and 3 new tabs (`Positions`, `Backtest`, `Lessons`). All dynamic DOM constructed strictly via `document.createElement` and `textContent`. Zero external CDN scripts or stylesheet links. | `test_dashboard_ui_m8_elements_and_hygiene` |
| Hygiene | Zero Inline Comments | Automated tokenizer verification enforcing 0 inline `#` comments in all new and edited Python/JS code. | `test_no_inline_comments_in_workstation_test_file` |

### Suite Verification:
- **Pytest:** 507 passed in 15.68s on Python 3.11 (`.venv311`), 507 passed in 12.69s on Python 3.14 (`.venv`).
- **Coverage:** **88.35%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.

---

## 14. Milestone 10 — SSRF-Hardened Live Fundamentals & Financial News Ingestion Adapters (ADR-041), Verified 2026-11-24

**Files:**
- `src/agentic_trading/market_data/context_bridge.py`
- `src/agentic_trading/agents/{llm_client.py,memory.py}`
- `src/agentic_trading/api/{schemas,state,routes,dashboard}.py`
- `tests/test_m10_fundamentals_and_news.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Context Bridge | `ReadOnlyContextBridge` | SSRF-hardened fetcher enforcing HTTPS only, host allowlist (`query1/query2/feeds.finance.yahoo.com`), no-redirect urllib opener (`_NoRedirectHandler`), 512 KB payload limit, 10s socket timeout, and symbol regex `^[A-Za-z0-9._-]{1,32}$`. | `test_context_bridge_ssrf_and_symbol_validation`, `test_context_bridge_redirects_and_payload_caps` |
| XXE & HTML | Content Sanitization | Rejecting `<!DOCTYPE` and `<!ENTITY` prior to `ET.fromstring`, pre-filtering control characters, and stripping HTML tags with `html.unescape`. | `test_context_bridge_xxe_and_html_cleaning` |
| Context Modes | 3 Deterministic Modes | `"synthetic"` (hash-derived fundamental snapshot and sector news without I/O), `"cache"` (HMAC-SHA256 authenticated disk cache with tamper rejection), and `"live"` (HTTPS RSS and quoteSummary with fail-closed fallback to cache/synthetic). | `test_context_bridge_deterministic_synthetic_and_cache` |
| Desk Integration | State & Orchestrator | `DeskRunRequest` accepts `context_source: Literal["synthetic", "cache", "live"] = "synthetic"`. `TradingLabState.run_desk` resolves real `FundamentalSnapshot`, `NewsArticle`s, and `ScheduledEvent`s outside locks, enabling `DataAnalyst` and `NewsAnalyst` to output `data_quality="ok"` instead of missing. | `test_desk_run_with_synthetic_context_and_analyst_evaluation` |
| Risk Engine | `EVENT_BLACKOUT` | Automatic blackout enforcement when scheduled earnings date falls within window (`<= 2 days`), rejecting trade proposal with `EVENT_BLACKOUT` and `max_allowed_quantity = 0`. | `test_desk_run_earnings_blackout_enforcement` |
| REST API | `/api/context` Endpoint | `GET /api/context/{exchange}/{symbol}` endpoint returning sanitized fundamentals, articles, scheduled events, and blackout status with `paper_only: True`. | `test_get_context_endpoint_and_dashboard_elements` |
| Dashboard UI | Settings & Badges | Added Context Source selector inside `Settings ▾`, `Fundamental Health & Catalyst Summary` badges in Overview, and Fundamental/Catalyst status pills in Agent Chat. Zero external CDNs and safe DOM creation. | `test_get_context_endpoint_and_dashboard_elements` |
| Hygiene | Zero Inline Comments | Automated AST and tokenizer test verifying 0 inline `#` comments across all modified/new files. | `test_m10_sources_and_tests_have_zero_inline_comments` |

### Suite Verification:
- **Pytest:** 515 passed in 14.82s on Python 3.11 (`.venv311`), 515 passed in 11.95s on Python 3.14 (`.venv`).
- **Coverage:** **88.37%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.

---

## 15. Milestone 11 — Multi-Symbol Basket Portfolio Backtester, Walk-Forward Parameter Optimizer & Trade Journal Export (ADR-042), Verified 2026-11-24

**Files:**
- `src/agentic_trading/time_machine/basket.py`
- `src/agentic_trading/time_machine/__init__.py`
- `src/agentic_trading/api/{schemas,state,routes,dashboard}.py`
- `tests/test_m11_basket_backtest_and_journal.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Basket Backtester | `run_basket_backtest` | Causal multi-symbol basket portfolio simulation sharing a single currency capital pool (`INR` or `USD`). Proposals sorted descending by signal confidence, evaluated against dynamic portfolio snapshot, executing at bar $t+1$ open, checking intrabar stops/targets on bar $t$ high/low, and verifying exact double-entry accounting conservation residual `== Decimal("0")`. | `test_basket_backtest_direct_execution_and_conservation`, `test_basket_backtest_endpoint_and_state` |
| Concentration | Risk Policy Caps | Single-position concentration cap (`max_position_fraction`) and volume participation caps enforced under concurrent symbol allocation. | `test_basket_backtest_concentration_cap_enforcement` |
| Walk-Forward | Parameter Optimizer | Chronological 70% in-sample / 30% out-of-sample split with zero look-ahead leakage. Parameter grid search across `ema_pullback`, `rsi_mean_reversion`, `atr_breakout`, `sma_cross` strategies measuring out-of-sample robustness. | `test_walk_forward_optimization_standalone` |
| Trade Journal | JSON & CSV Export | `GET /api/journal/export` exporting closed trades, open positions, order history, and ledger entries for INR and USD portfolios. | `test_journal_export_json_and_csv_endpoints` |
| CSV Injection | Formula Sanitization | Spreadsheet formula injection defense neutralizing text fields starting with `=`, `+`, `-`, `@`, `\t`, or `\r` by prepending a single quote (`'`). | `test_csv_formula_injection_defense` |
| Dashboard UI | Operator Controls | Added `Run Basket & Walk-Forward` button, `Export CSV` / `Export JSON` buttons, Walk-Forward summary cards (`#walkForwardGrid`), and Per-Symbol Attribution table (`#basketAttributionCard`) constructed safely via `document.createElement`. Zero external CDN links. | `test_dashboard_ui_m11_elements_and_hygiene` |
| Hygiene | Zero Inline Comments | Automated AST and tokenizer test verifying 0 inline `#` comments across all modified/new files. | `test_no_inline_comments_in_m11_files` |

### Suite Verification:
- **Pytest:** 523 passed in 18.75s on Python 3.11 (`.venv311`), 523 passed in 13.78s on Python 3.14 (`.venv`).
- **Coverage:** **87.73%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.

---

## 16. Milestone 12 — Unique Per-Symbol Pricing, Dynamic Gain/Loss Scorecard, Closed Trades History & Beginner-Guided UX (ADR-043), Verified 2026-11-24

**Files:**
- `src/agentic_trading/market_data/feed_bridge.py`
- `src/agentic_trading/paper_trading/broker.py`
- `src/agentic_trading/api/{schemas,state,routes,dashboard}.py`
- `tests/test_m12_pnl_and_beginner_ux.py`
- `tests/{test_m6_api_and_dashboard.py,test_m8_workstation_features.py,test_e2e_platform_audit.py}`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Per-Symbol Pricing | `ReadOnlyMarketFeedBridge` | Realistic `_KNOWN_BASE_PRICES` dictionary (RELIANCE: 2940, TCS: 3860, INFY: 1840, HDFCBANK: 1720, ICICIBANK: 1290, SBIN: 830, AAPL: 228, MSFT: 425, NVDA: 138, GOOGL: 176, AMZN: 205; fallback SHA-256 derived 150..2500). Sinusoidal wave time index anchored to offset days (`t = 120 - offset_days + sim_step`), ensuring single-bar queries ($offset\_days=0$) evaluate to the exact same wave point as the latest bar of multi-candle queries. | `test_unique_per_symbol_pricing_and_deterministic_variation`, `test_feed_bridge_single_bar_matches_last_bar_of_series` |
| Scenario Simulation | Practice Scenarios | `POST /api/sandbox/scenario` endpoint accepting `ScenarioRequest` (`bull_rally`, `sudden_crash`, `sideways_chop`). Advances simulation steps, updates mark prices, and triggers `sweep_positions` to automatically execute stop loss and take profit orders. | `test_scenario_endpoint_and_stop_loss_trigger` |
| Gain/Loss Scorecard | Scorecard & Audit | `GET /api/pnl` endpoint returning `PnlSummaryResponse` with exact starting capital, total equity, net P&L, realized gains/losses, unrealized gains/losses, total fees paid, win rate, best/worst trade return, and closed trade audit trail. | `test_pnl_summary_endpoint_realized_and_unrealized` |
| Closed Trades | Audit Trail | Position liquidations append `ClosedTradeRecord` with explicit exit reasons (`MANUAL_SELL`, `STOP_LOSS_TRIGGERED`, `TAKE_PROFIT_TRIGGERED`) and preserved cost-basis conservation ($residual == Decimal("0")$). | `test_closed_trades_history_recorded_on_manual_sell` |
| Broker Monotonicity | Non-Decreasing Timestamps | Clamped `submitted_at = max(submitted_at, self.portfolio.ledger.entries[-1].timestamp)` in `broker.submit_order` to prevent out-of-order ledger rejections under mixed execution. | `tests/test_m8_workstation_features.py` |
| Dashboard UI | Beginner Guided UX | Added collapsible Quick-Start Guide banner (`#beginnerGuideBanner`), dual-currency Gain/Loss scorecard cards (`#inrPnlCard`, `#usdPnlCard`), Watchlist Presets (`Nifty Safe`, `IT Movers`, `US Leaders`), Practice Scenario buttons, Closed Trades History table (`#closedTradesContainer`), and solid dark-bordered badge pills on Candlestick overlays. Maintained zero external CDN links and safe DOM creation via `document.createElement`. | `test_dashboard_ui_m12_elements_and_hygiene` |
| Hygiene | Zero Inline Comments | Automated AST and tokenizer test verifying 0 inline `#` comments across all modified/new files. | `test_no_inline_comments_in_m12_files` |

### Suite Verification:
- **Pytest:** 531 passed on Python 3.11 (`.venv311`) and Python 3.14 (`.venv`).
- **Coverage:** **>87%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.

---

## 17. Milestone 12 Polish — Mark-Price Consistency, Exact Close Execution & Chart Axis Collision Avoidance (ADR-044), Verified 2026-11-24

**Files:**
- `src/agentic_trading/api/{schemas,state,dashboard}.py`
- `tests/test_m12_pnl_and_beginner_ux.py`

| Area | Component | Behaviour & Hardening | Verification Test |
|---|---|---|---|
| Mark Price Cache | `TradingLabState` | `_get_or_fetch_mark_price(exchange, symbol, currency)` caches mark prices without incrementing simulation steps. Synchronized `get_portfolio_summary`, `get_positions`, and `get_pnl_summary` so `market_value` and `unrealized_pnl` match to the exact cent across every card and table without drifting between polls. | `test_mark_price_consistency_across_repeated_passive_polls` |
| Close Execution | `close_position` | Executes at the exact displayed mark price from `_mark_prices` (falling back to `_get_or_fetch_mark_price` if unpopulated), locking in displayed P&L (minus statutory slippage and fees). Clears liquidated positions from `_mark_prices`. | `test_close_position_executes_at_exact_displayed_mark_price` |
| Backtest UI | Expectancy Binding | Safely binds `backtestExpectancy` to `Number(data.expectancy ?? data.expectancy_per_trade ?? data.metrics?.expectancy_per_trade ?? data.metrics?.expectancy ?? 0).toFixed(2) + " " + currency`, eliminating `undefined INR`. | `test_dashboard_expectancy_risk_mapping_and_chart_collision_avoidance` |
| Candlestick Chart | Axis Collision Avoidance | Widened right axis margin to `padRight = 96`. Pre-collected active AI pills (`BUY`, `TARGET`, `STOP`), sorted vertically, and enforced minimum `18px` vertical spacing (`badgeY`). Suppressed gray horizontal grid tick price text within `18px` of active AI pills. | `test_dashboard_expectancy_risk_mapping_and_chart_collision_avoidance` |
| Risk Explanations | Plain-English Guidance | `formatRiskReason` and `formatRiskReasons` mapping risk rejection codes (`POSITION_CONCENTRATION_EXCEEDED`, `MAX_OPEN_POSITIONS_EXCEEDED`, `INSUFFICIENT_CASH`, `EVENT_BLACKOUT`, etc.) into actionable plain-English text in Overview and AI Trade Plans views. | `test_dashboard_expectancy_risk_mapping_and_chart_collision_avoidance` |
| Position Table | Active Brackets | Added `stop_loss` and `take_profit` fields to `PositionItem` and displayed active Stop Loss and Sell Target prices in the Open Portfolio Positions table. | `test_mark_price_consistency_across_repeated_passive_polls`, `test_dashboard_expectancy_risk_mapping_and_chart_collision_avoidance` |
| Hygiene | Zero Inline Comments | Automated AST and tokenizer test verifying 0 inline `#` comments across all modified/new files. | `test_no_inline_comments_in_m12_code` |

### Suite Verification:
- **Pytest:** 534 passed on Python 3.11 (`.venv311`) and Python 3.14 (`.venv`).
- **Coverage:** **>88%** (exceeds mandatory `--cov-fail-under=85`).
- **Ruff & Compileall:** All clean, exit code 0 on both 3.11 and 3.14.
- **Secrets:** 0 leaks detected against `.secrets.baseline`.
- **Inline `#` Comments:** 0 comments in git diff.
