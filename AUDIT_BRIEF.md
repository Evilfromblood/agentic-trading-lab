# Milestone 2b — Batch 6 Remediation Audit Brief

**Status:** Remediation Complete — M2b awaits independent review; M2c has not begun.  
**Baseline Commit:** `1b7e5829474239495163da1d2d3349eb35ca9744`  
**Active Branch:** `feature/reliable-foundation`  
**Audit Bundle:** `m2b-remediated-batch6-bundle.zip`

---

## 1. Executive Summary

Milestone 2b Remediation Batch 6 resolves all confirmed technical defects from Claude A's Batch 5 audit report (REJECT on `m2b-remediated-batch5-bundle.zip`, SHA-256 `e708153be0bbbef6cbe7962f1d3e497e1bceb40704cfcd241be1057eac83013c`).

All 310 tests pass across the test suite on both genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`). Measured test coverage is **85.49%** (enforcing `--cov-fail-under=85`). Ruff linting, compileall byte-compilation, and blocking secret scanning (`detect-secrets-hook --baseline .secrets.baseline` version 1.5.0) pass with zero errors and zero unbaselined secrets.

---

## 2. Mapping from Every Finding to Resolution and Test

| Finding ID | Severity | Audit Finding Description | Implementation Fix in Source | Regression Test Verification |
|---|---|---|---|---|
| **F1-A** | Critical | In-process Zerodha boundary relied on closure-held dispatch that was recoverable via `object.__getattribute__`; denylist-only or closure-based protection is defenseless against hostile Python. | Redesigned boundary using clean slotted facade composition `__slots__ = ("_target", "__weakref__")`. Implemented `ReadOnlyTransportAdapter(HTTPAdapter)` blocking any non-GET request at the transport/socket level. Overrode `_request` on `ReadOnlyKiteConnect` to reject non-GET requests before transport. Removed closure-dispatch hacks and module registries. Documented explicit threat model: in-process wrappers provide defense-in-depth and application ergonomics, but true security requires restricted broker credentials and network egress policies. | `tests/test_claude_batch6_regressions.py::test_p1_all_mutations_blocked_before_transport_and_zero_calls_reach_adapter`<br>`tests/test_claude_batch6_regressions.py::test_p1_reflection_and_dict_probing_fail_closed` |
| **F1-B** | Critical | Mutating caller-supplied `KiteConnect` instances broke legitimate reads and violated the principle that library wrappers must never mutate injected caller objects. | Caller-supplied `KiteConnect` client instances are NEVER mutated or monkeypatched. Caller methods and attributes remain 100% untouched. For injected clients, `_ReadOnlyKiteWrapper` wraps the caller client and dispatches only allowlisted read methods via `types.MethodType` ensuring `wrapper.method.__self__ is wrapper`. | `tests/test_claude_batch6_regressions.py::test_p1_injected_genuine_kiteconnect_client_remains_unmutated`<br>`tests/test_zerodha_kiteconnect_integration.py::test_genuine_kite_read_reaches_get_transport_without_mutating_injected_client` |
| **F1-D** | High | Keyring handling broke connector construction in environments without keyring backends. | Implemented safe keyring helpers (`_safe_get_stored_token`, `_safe_set_stored_token`, `_safe_delete_stored_token`) with fail-safe error handling. Missing or unconfigured OS keyrings never raise exceptions or prevent connector construction. | `tests/test_claude_batch6_regressions.py::test_p1_keyring_failures_and_missing_backends_fail_safe` |
| **F2-A** | High | Ingestion regression tests in Batch 5 omitted the required `exchange` identity field, masking ingestion issues. | All synthetic ingestion test records across `test_claude_batch5_regressions.py` and `test_claude_batch6_regressions.py` specify explicit `exchange` identity fields (`exchange="NSE"` or parameterized exchange). Pipeline validates payload identity and executes full ingestion through to calendar validation. | `tests/test_claude_batch5_regressions.py::test_f2_incomplete_calendar_daily_ingestion_fails_closed`<br>`tests/test_claude_batch6_regressions.py::test_p2_incomplete_calendar_daily_d1_fails_closed_across_all_exchanges` |
| **F2-B** | High | Incomplete calendar daily/intraday ingestion tests did not assert exact error codes and coverage statuses. | Updated ingestion pipeline and tests to assert exact typed status and error code: `res.coverage_status == CoverageStatus.MARKET_CALENDAR_REQUIRED.value` and `res.error_code == "MARKET_CALENDAR_REQUIRED"` when calendar evidence is incomplete or required, and `TRUNCATED_COVERAGE` when intermediate trading days are missing without calendar evidence. | `tests/test_claude_batch5_regressions.py::test_f2_incomplete_calendar_daily_ingestion_fails_closed`<br>`tests/test_claude_batch5_regressions.py::test_f2_incomplete_calendar_intraday_m5_ingestion_fails_closed`<br>`tests/test_market_data_ingestion.py::test_coverage_entire_intermediate_trading_day_missing` |
| **F2-C** | High | Complete calendars silently inferred unexplained missing weekdays as holidays; contradictory calendar declarations were not rejected. | Implemented contradiction checks in `ExchangeCalendar.__post_init__`: raises `ValueError` on overlap between `trading_days` and `holidays`, special session on declared holiday, special session with `open >= close`, and special session exchange mismatch. Complete calendar requires explicit holiday evidence for omitted weekdays. Unexplained weekdays have no evidence and fail closed. | `tests/test_claude_batch6_regressions.py::test_p2_calendar_contradiction_trading_day_holiday_overlap`<br>`tests/test_claude_batch6_regressions.py::test_p2_calendar_contradiction_special_session_on_holiday`<br>`tests/test_claude_batch6_regressions.py::test_p2_calendar_contradiction_special_session_open_gte_close`<br>`tests/test_claude_batch6_regressions.py::test_p2_calendar_contradiction_special_session_exchange_mismatch`<br>`tests/test_claude_batch5_regressions.py::test_f2_complete_calendar_authoritative_evidence` |
| **F3-A** | Medium | False positives in test suite and broad unanchored exclusion regex masked `.github` and `.gitlab-ci.yml`. | False positives in tests suppressed with narrow, justified inline `# pragma: allowlist secret` comments. Replaced broad exclusion regex with anchored pattern `^(?:\.git/|\.venv(?:311)?/|\.ruff_cache/|\.pytest_cache/|\.coverage$|htmlcov/|m2a-review\.patch$)` that excludes only exact generated/cache directories without masking `.github` or `.gitlab-ci.yml`. | `tests/test_claude_batch6_regressions.py::test_p3_exclusion_pattern_does_not_mask_github_or_ci` |
| **F3-B** | Medium | Secret scanning was not version-pinned and lacked verification of dummy AWS secret detection across critical repo paths. | Pinned `detect-secrets==1.5.0` in CI and `.secrets.baseline`. Added comprehensive leak detection test verifying dummy AWS secrets are caught in `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files. Hook runs blocking in CI. | `tests/test_claude_batch6_regressions.py::test_p3_secrets_baseline_is_clean_and_pinned_to_v150`<br>`tests/test_claude_batch6_regressions.py::test_p3_detect_secrets_detects_leaks_in_all_required_locations` |
| **T-1** | Medium | Test suite substituted stubs instead of verifying genuine `kiteconnect==5.2.2` dependency integration. | Genuine `kiteconnect==5.2.2` installed and tested in `.venv311` with intercepted transport. Verified legitimate reads (`profile`, `margins`, `holdings`, `quote`, `historical_data`) reach transport as GET requests while zero blocked mutation requests reach transport. | `tests/test_claude_batch6_regressions.py::test_p1_genuine_kiteconnect_read_operations_reach_transport`<br>`tests/test_zerodha_kiteconnect_integration.py` (all 8 tests passing) |

---

## 3. Verification Commands & Evidence

### 3.1. Full Pytest Suite & Coverage
- **Python 3.11.9 (`.venv311`):**
  ```powershell
  .\.venv311\Scripts\python.exe -m pytest --cov=agentic_trading --cov-report=term-missing --cov-fail-under=85
  ```
  **Result:** 310 passed in 1.59s. Coverage: **85.49%** (exceeds mandatory 85% gate). Full test-by-test log saved in `python311_verification_report.txt`.
- **Python 3.14.4 (`.venv`):**
  ```powershell
  .\.venv\Scripts\python.exe -m pytest --cov=agentic_trading --cov-report=term-missing --cov-fail-under=85
  ```
  **Result:** 310 passed in 0.84s. Coverage: **85.49%**. Full test-by-test log saved in `python314_verification_report.txt`.

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
  **Result:** Exit code 0, zero errors or warnings on both interpreters.

### 3.4. Git Diff Check
- Command:
  ```powershell
  git diff --check
  ```
  **Result:** Exit code 0, zero trailing whitespace or whitespace errors.

### 3.5. Secret Scanning
- Command:
  ```powershell
  git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline
  ```
  **Result:** Exit code 0, zero unbaselined secrets detected across all tracked files.

### 3.6. Dependency Security Audit
- Command:
  ```powershell
  python -m pip_audit
  ```
  **Result:** Exit code 0, zero known vulnerabilities found.
