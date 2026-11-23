# Milestone 5 Hardened & Multi-Milestone Verification Audit Brief

**Status:** M2a, M2b, M2c, M3, M4, and M5 verified and hardened (ADR-028, ADR-029).  
**Baseline Commit:** `1b7e5829474239495163da1d2d3349eb35ca9744`  
**Active Branch:** `feature/reliable-foundation`  
**Audit Bundle:** `full-project-m5-final-bundle.zip`

---

## 1. Executive Summary

Milestone 4 (Time Machine: causal backtesting engine, walk-forward validation, seeded Monte Carlo, and experiment manifests) has been implemented and hardened against adversarial failure modes.

All 441 tests pass across the entire test suite on both genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`). Measured test coverage is **88.54%** (strictly enforcing `--cov-fail-under=85`). Ruff linting, compileall byte-compilation on both Python versions, and blocking secret scanning (`detect-secrets-hook --baseline .secrets.baseline` version 1.5.0 scanning `requirements.lock`) pass with zero errors and zero unbaselined secrets. All time machine source files and tests enforce zero inline `#` comments via automated tokenizer tests.

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
- **Inline `#` Comments:** 0 comments in git diff.

---

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
- **Inline `#` Comments:** 0 comments in git diff.
