# Milestone 2b — Batch 7 / 7b Remediation Audit Brief

**Status:** Remediation Complete — M2b awaits independent review; M2c has not begun.  
**Baseline Commit:** `1b7e5829474239495163da1d2d3349eb35ca9744`  
**Active Branch:** `feature/reliable-foundation`  
**Audit Bundle:** `m2b-remediated-batch7b-bundle.zip`

---

## 1. Executive Summary

Milestone 2b Remediation Batch 7 and Batch 7b resolve all 7 confirmed technical defects (D1 through D7) and final polish items (F1, F3) from Claude's independent audit.

All 338 tests pass across the test suite on both genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`). Measured test coverage is **85.02%** (enforcing `--cov-fail-under=85`). Ruff linting, compileall byte-compilation, pip-audit vulnerability checks, and blocking secret scanning (`detect-secrets-hook --baseline .secrets.baseline` version 1.5.0 scanning `requirements.lock`) pass with zero errors and zero unbaselined secrets.

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
