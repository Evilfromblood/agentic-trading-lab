# Engineering Session Log

Append concise entries in reverse chronological order. Record verified outcomes, not intentions.

## 2026-11-03 — M2b Remediation Batch 1: Claude A Independent Audit
- Remediated all confirmed technical findings across 5 priorities from Claude A's independent adversarial audit:
  - **Priority 1 (Candle Integrity & Session Grid)**:
    - Introduced `ExchangeSession` and `DEFAULT_EXCHANGE_SESSION` (09:15-15:30 IST) abstraction.
    - Implemented `check_session_and_grid` validating intraday candles belong to trading days, sit within session hours, and align to interval grids (`OUTSIDE_SESSION`, `OFF_GRID_TIMESTAMP`).
    - Added overlapping candle detection (`OVERLAPPING_CANDLE` in `check_sequence_monotonicity`).
    - Preserved session-truncated bar closes (H1/M30 closing at 15:15 or 15:30, M10 at 15:25 or 15:30).
    - Enforced missing final session candle detection across date boundaries and historical queries ending at session close.
  - **Priority 2 (Historical Freshness & Future Boundaries)**:
    - Enforced `retrieval_timestamp <= now` in `ingest_latest` and `ingest_historical`.
    - In `ingest_historical`, decoupled historical backfills (`end_time < now`) from live queries (`end_time >= now`). Live queries strictly enforce `FreshnessPolicy`. Historical backfills disable live staleness limits but strictly enforce future-timestamp validation.
  - **Priority 3 (Recursive Immutability & DAG Memoization)**:
    - Replaced active-frame traversal with identity memoization (`_memo[id(obj)]`) to prevent $O(2^D)$ exponential blowup in shared DAG structures.
    - Added cycle detection using active stack (`_active_stack`), a node budget of 10,000, and a depth limit of 16.
    - Unified `_deep_freeze` in `models.py` and replaced duplicate implementations across `quality.py`, `provider.py`, and `ingestion.py`.
  - **Priority 4 (Coverage & Result Consistency)**:
    - Decoupled `TRUNCATED_COVERAGE` (boundary truncation, interior intraday missing bars) from `MARKET_CALENDAR_REQUIRED` (unaccounted multi-day jumps).
    - Enforced internal consistency of result invariants across all failure and success paths.
  - **Priority 5 (Additional Confirmed Defects)**:
    - Fixed D1 `close_time` calculation to ensure positive duration when timestamp is on or after session open.
    - Enforced strict whitespace rejection for numeric strings in `StandardDictAdapter` and `models.py`.
    - Added explicit `__hash__` and `__eq__` to `FreshnessPolicy` for hashability and dataclass compatibility.
  - **Regression Test Suite**: Added 18 comprehensive regression tests in `tests/test_claude_batch1_regressions.py`.
- Validation results:
  - Pytest full suite: **206 passed in 0.19s** on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 206 passed across all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-02 — M2b Historical Coverage Correctness & Sequence Continuity
- Authorized remediation of confirmed defect in historical sequence coverage handling (`ingest_historical`):
  - **Outer Boundary vs Interior Completeness**: Disentangled boundary coverage (`candles[0].timestamp <= start` and `candles[-1].close_time >= end`) from interior sequence completeness. Reused M2a's session-aware `check_sequence_integrity` to detect missing intermediate candles, consecutive missing candles, or entire missing intermediate trading days (`MISSING_INTERVAL` or `MARKET_CALENDAR_REQUIRED`).
  - **Fail-Closed on `require_full_coverage=True`**: When `require_full_coverage=True`, any boundary truncation or interior sequence gap immediately fails closed with `error_code="TRUNCATED_COVERAGE"` and `coverage_status="TRUNCATED_COVERAGE"`, even if `check_gaps=False` was passed by the caller.
  - **Empty Provider Response**: Provider returning 0 records explicitly reports `coverage_status="EMPTY_COVERAGE"` (was previously `COVERAGE_UNVERIFIED`) alongside `EMPTY_PROVIDER_RESPONSE`.
  - **Quality Gate Gap Detection Alignment**: When M2a quality gate rejects a sequence due to missing intervals or ambiguous calendar gaps, `coverage_status` accurately reflects `TRUNCATED_COVERAGE`.
  - **Preservation of `COVERAGE_UNVERIFIED`**: Kept only when boundary matches and interior continuity passes available checks without gaps, correctly reflecting that exchange calendar evidence is required to prove absence of holiday/special trading sessions.
  - **11 Regression Tests Added**:
    1. Complete 4-candle M5 sequence passing with `COVERAGE_UNVERIFIED`.
    2. Missing first candle failing closed with `TRUNCATED_COVERAGE`.
    3. Missing last candle failing closed with `TRUNCATED_COVERAGE`.
    4. Missing middle candle with `check_gaps=True` rejected with `TRUNCATED_COVERAGE`.
    5. Missing middle candle with `check_gaps=False` and `require_full_coverage=True` failing closed with `TRUNCATED_COVERAGE`.
    6. Multiple consecutive missing middle candles detected as interior gaps.
    7. Entire intermediate trading day missing (both intraday and D1) failing closed with `TRUNCATED_COVERAGE`.
    8. Empty provider response reporting `EMPTY_COVERAGE`.
    9. `require_full_coverage=False` with `check_gaps=False` returning partial sequence with `TRUNCATED_COVERAGE`.
    10. `require_full_coverage=True` failing closed on incomplete sequence.
    11. Session boundary truncation with H1, M30, and M10 intervals.
- Validation results:
  - Pytest full suite: **188 passed in 0.15s** on both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 188 passed across all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-01 — M2b Python 3.11 & D1 Freshness Audit Remediation
- Remediated the two newly discovered defects from Claude's independent review of the M2b review bundle:
  - **Python 3.11 Dataclass Compatibility**: In `FreshnessPolicy`, changed mutable class attribute default `custom_limits: Mapping[CandleInterval, timedelta] = MappingProxyType({})` to standard `field(default_factory=lambda: MappingProxyType({}))`. In Python 3.11, `MappingProxyType` is unhashable (`__hash__ = None`), triggering `ValueError: mutable default ... use default_factory` during dataclass inspection at module import time. Verified that `field.default is MISSING` and `field.default_factory` evaluates cleanly without import crash on Python 3.11 and 3.14.
  - **Daily Candle Session Completion Semantics**: In `Candle.close_time` (`src/agentic_trading/market_data/models.py`), updated `D1` property logic to reflect Indian equity exchange session boundaries (NSE/BSE). For daily bars starting at session open (`09:15:00 IST`) or date start (`00:00:00 IST`), bar completion occurs at regular market close (`15:30:00 IST`) on that session date. Allows Monday EOD analysis at 18:30 IST to recognize the bar as completed rather than erroneously rejecting as `IN_PROGRESS_CANDLE` or `RETRIEVAL_BEFORE_CLOSE`.
  - **Session-Aware D1 Freshness & Calendar Ambiguity**: In `FreshnessPolicy.get_max_staleness`, removed hardcoded 72h weekend guess that previously accepted Friday data on Sunday (ignoring possible weekend trading like Diwali Muhurat sessions) and falsely rejected Friday data on Tuesday during a Monday-holiday scenario. Established that:
    1. Same calendar day (EOD post-close from 15:30 IST to midnight): fresh within 24h.
    2. Next consecutive calendar weekday (Mon->Tue, Tue->Wed, Wed->Thu, Thu->Fri overnight / pre-market): fresh within 24h.
    3. Multi-day gaps, weekends, and holidays: Fails closed with `MarketCalendarRequiredError` (`MARKET_CALENDAR_REQUIRED`) rather than guessing without exchange calendar evidence, unless the caller provides explicit `max_staleness` / `custom_limits`.
  - **Regression Tests**: Added and updated unit tests in `tests/test_market_data_ingestion.py` covering Monday EOD ingestion (09:15 and 00:00 opens), Tuesday pre-market ingestion, Sunday weekend fail-closed behavior, Tuesday holiday scenario with calendar reporting, and Python 3.11 dataclass introspection.
- Validation results:
  - Pytest full suite: **165 passed in 0.14s** on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - `compileall -q -f src tests`: passed (exit code 0).
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 165 passed on all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-01 — M2b Comprehensive Audit Remediation & Defense-in-Depth Hardening
- Completed comprehensive remediation of all high-, medium-, and low-severity audit findings on `feature/reliable-foundation`:
  - **H1 (Fail-open staleness and timing)**: Required timezone-aware `now` datetime in `ingest_latest`, `ingest_historical`, and `ingest_record` via private `_require_valid_now`. Rejects None, naive datetimes, or crashing tzinfo with `ValueError`. Applied consistent default 30-minute staleness (`DEFAULT_MAX_STALENESS`).
  - **H2 (Historical request-window enforcement)**: Pipeline independently enforces `[request.start_time, request.end_time)` window in `ingest_historical`, failing closed with `BOUNDARY_VIOLATION`. Introduced `coverage_status='COVERAGE_UNVERIFIED'` on `SequenceIngestionResult`.
  - **M1 (Identity-less raw payloads)**: Added `require_payload_identity: bool = False` to `StandardDictAdapter`. `MarketDataIngestionPipeline` defaults to `True`, rejecting anonymous payloads missing symbol/exchange/interval with `RawDataValidationError`.
  - **M2 (Provider exceptions & malformed responses)**: Caught `ProviderTimeoutError`, `ProviderConnectionError`, `ProviderPayloadError`, `ProviderError`, and unexpected exceptions (`PROVIDER_EXCEPTION`). Validated `ProviderResponse` envelope type and response retrieval timestamp timezone safety.
  - **M3 (Timezone safety consolidation)**: Consolidated timezone validation into `_require_valid_tz_dt` catching non-datetime types, naive instances, and crashing/None utcoffset calculations across models, requests, responses, and ingestion.
  - **M4 (Provenance correctness)**: `StandardDictAdapter` checks in-payload `source`, validating match with configured adapter source and rejecting contradictions with `RawDataValidationError`.
  - **M5 (Result consistency & immutability)**: Enforced `__post_init__` consistency in `IngestionResult` and `SequenceIngestionResult` (success forbids error fields; failure forbids valid candles). Raw payload dictionaries are deep-frozen via `MappingProxyType`.
  - **Low-Severity Remediation**: Synthetic provider `fetch_latest` raises `ValueError` if `now` omitted when empty; `fetch_historical` excludes unparseable/naive records during range filtering; filters by `exchange` and `interval`; adapter rejects conflicting timestamp aliases; eliminated private `_SYMBOL_REGEX` import; documented testing determinism.
  - **Documentation & Invariant Precision**: Unchecked premature snapshot fixture checkbox in `DEVELOPMENT_PLAN.md`; delineated synthetic sample generation vs stored replay fixtures vs historical session replay; documented risk-engine isolation demonstration vs pipeline integration.
- Validation results:
  - Pytest: **148 passed in 0.31s** (96 base + 10 pipeline integration + 42 M2b ingestion & audit regression tests).
  - Ruff `risk_engine`: passed (0 errors).
  - Ruff `market_data` & `tests`: passed (0 errors).
  - `compileall -q -f src tests`: passed (0 errors).
  - `git diff --check`: passed (0 whitespace/EOF errors).
- No commits or pushes made; stopped for review.

## 2026-11-03 — M2b Claude B Audit Remediation Batch 2 Engineering
- Addressed all confirmed defects from Claude B's independent audit report (`m2b-remediated-batch1-bundle.zip`, SHA-256 `005eb1c8b13df1b64f88cc076caba8539a8fc921fde6aac26a07c2eba3dd7043`):
  - **Priority 1 (Exchange & Session Architecture - H-1, COV-05, COV-07, COV-09)**:
    - Added `NYSE` and `NASDAQ` to `Exchange` enum with case-insensitive normalization.
    - Implemented US Eastern timezone with DST transition fallback (`_USEasternFallback`, `US_EASTERN`).
    - Added `for_exchange(exchange)` factory on `ExchangeSession`.
    - Made `Candle.close_time` dynamically resolve session hours per exchange, removing hardcoded IST/15:30.
    - Added `EXCHANGE_MISMATCH` check preventing cross-exchange candle/session mixing.
    - Supported D1/W1/MN1 grid anchor validation (`is_valid_grid_anchor`), rejecting off-grid intraday timestamps like 03:00 IST for daily candles.
    - Added `is_special` flag to `ExchangeSession` for non-standard trading sessions (e.g. Diwali Muhurat 18:15-19:15).
  - **Priority 2 (Fail-Closed Historical Coverage Contract - H-2, COV-01)**:
    - Configured `require_full_coverage: bool = True` and `allow_partial: bool = False` as default in `ingest_historical`.
    - Truncated or incomplete backfills fail closed with `success=False` and empty `candles=()`.
    - Explicit `allow_partial=True` populates `partial_candles` while strictly preserving `success=False` and `candles=()`, ensuring downstream trading engines cannot mistake partial data for successful backfills.
    - Introduced structured `CoverageStatus` enum (`FULL_COVERAGE`, `COVERAGE_UNVERIFIED`, `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, `EMPTY_COVERAGE`).
  - **Priority 3 (Correct & Bounded Deep Freezing - H-3, M-1)**:
    - Solved CPython memory address reuse on transient mapping keys in `_deep_freeze` by storing `(orig_obj, frozen_obj, subtree_depth)` in `_memo` and checking `orig_obj is cur`.
    - Counted every node (primitives + containers) against a hard budget `max_nodes=10000`, bounding traversal to `<2ms`.
    - Enforced `depth + subtree_depth > max_depth` when retrieving memoized DAG subtrees to prevent depth-limit circumvention.
  - **Priority 4 (Calendar Evidence & Historical Windows - M-2, COV-03, COV-08)**:
    - Introduced `ExchangeCalendar` abstraction.
    - Multi-day historical intervals spanning weekends or holidays without calendar evidence emit `MARKET_CALENDAR_REQUIRED`.
    - Intervening non-trading days verified by calendar pass cleanly.
    - Added `allow_sparse=True` contract for illiquid instruments.
  - **Priority 5 (Result-Object Invariant Hardening - M-4, ARCH-03)**:
    - Enforced `__post_init__` checks in `IngestionResult` (success strictly requires valid `validation_result`).
    - Enforced `__post_init__` checks in `SequenceIngestionResult` (rejects `"BOGUS"` coverage status, rejects `raw_record_count < len(candles)`, rejects `success=True` with `TRUNCATED_COVERAGE`, `EMPTY_COVERAGE`, or populated `partial_candles`).
  - **Priority 6 (Paper-Only Broker Controls & CI Hardening - SEC-01, SEC-03)**:
    - Wrapped Kite client in `_ReadOnlyKiteWrapper` and added explicit `place_order`, `modify_order`, `cancel_order` methods raising `PermissionError("Order placement is forbidden in paper-only mode")`.
    - SHA-pinned all GitHub actions in `.github/workflows/ci.yml` and added Python 3.11/3.12 testing matrix.
    - Ignored `.venv311/`, `.ruff_cache/`, `*.egg-info/` in `.gitignore`.
    - Replaced all broad `BLE001` (`except Exception:`) suppressions with explicit exception tuples.
- Validation results:
  - Genuine Python 3.11.9 (`.venv311`): **226 passed in 0.29s**.
  - Genuine Python 3.14.4 (`.venv`): **226 passed in 0.27s**.
  - Hash seed determinism (0, 42, 1337, 2026): all passed.
  - Ruff check (`src` and `tests`): 0 errors (`All checks passed!`).
  - Python compileall (`src` and `tests`): 0 errors on both 3.11 and 3.14.
  - Git working copy preserved; no commits or pushes made.

## Session 2026-11-03 (Session 9) — Claude C Audit Batch 3 Remediations
- Remediation scope:
  - **Priority 1 (Calendar evidence must never fail open)**:
    - Added `is_populated`, `has_evidence_for_date`, and `has_evidence_for_range` to `ExchangeCalendar`.
    - Unpopulated calendars return `is_populated is False` and never claim evidence or provide `FULL_COVERAGE`.
    - Reject candles occurring on declared exchange holidays with `DataQualityErrorCode.OUTSIDE_SESSION`.
    - Required calendar evidence covering the entire query window before reporting `FULL_COVERAGE`.
    - Differentiated verified holidays, missing calendar evidence (`MARKET_CALENDAR_REQUIRED`), and actual missing trading days (`MISSING_INTERVAL`).
  - **Priority 2 (Enforce Zerodha paper-only boundary)**:
    - Replaced denylist forwarding with strict `_READ_ONLY_ALLOWLIST` on `_ReadOnlyKiteWrapper`.
    - Blocked private attribute access (`_client`, `__client`, `_raw_client`) to underlying KiteConnect client.
    - Explicitly blocked `place_order`, `modify_order`, `cancel_order`, `exit_order`, `place_gtt`, `modify_gtt`, `delete_gtt`, `convert_position`, `place_mf_order`, `cancel_mf_order`, `_post`, `_request`, `_put`, `_delete` raising `PermissionError`.
    - Documented that Python in-process wrappers are software policy, not an OS sandbox.
  - **Priority 3 (Make coverage success trustworthy & explicit sparse mode)**:
    - Implemented `CoverageStatus.SPARSE_COVERAGE`.
    - Relaxed boundary edge-bar requirements when `allow_sparse=True`, supporting illiquid feeds without treating interior gaps as valid.
    - Implemented `require_full_coverage` contract: fails closed (`success=False`) on unverified (`COVERAGE_UNVERIFIED`) or sparse (`SPARSE_COVERAGE`) data.
  - **Priority 4 (CI and reproducibility)**:
    - Added multi-version CI matrix for Python 3.11, 3.12, 3.13, 3.14-dev in `.github/workflows/ci.yml`.
    - Configured Ruff with explicit rule selection (`F, E4, E7, E9, B, BLE, I`) in `pyproject.toml`.
    - Added coverage threshold (`--cov-fail-under=85`) and `pip-audit` security step.
    - Added architectural import boundary tests in `tests/test_import_boundaries.py`.
    - Created reproducible dependency lockfile `requirements.lock`.
  - **Priority 5 (Result-object constructor invariants)**:
    - Enforced `Candle` instance types in `SequenceIngestionResult.__post_init__`.
    - Enforced consistent symbol and exchange across all candles in sequence.
    - Validated strictly monotonic timestamps.
    - Forbade `success=True` with `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, or `EMPTY_COVERAGE`.
    - Forbade single intraday candle claiming `FULL_COVERAGE`.
    - Forbade `success=False` with `FULL_COVERAGE`.
  - **Additional Correctness Fixes**:
    - MN1 monthly close: Exact calendar month boundaries using `calendar.monthrange` (handling Feb 28/29, 30/31 days).
    - US Eastern fallback: Raised explicit `ValueError` for historical dates prior to 2007.
    - D1 midnight boundaries: Handled midnight-ending requests consistently.
    - Caller-supplied `now`: Constrained injected `now` parameter against distant future timestamps > 365 days.
    - Exception safety: Replaced all broad `except Exception:` blocks with explicit exception tuples including `RuntimeError`.
- Validation results:
  - Genuine Python 3.11.9 (`.venv311`): **248 passed in 0.33s**.
  - Genuine Python 3.14.4 (`.venv`): **248 passed in 0.35s**.
  - Hash seed determinism (0, 42, 1337, 2026): all passed (248/248 passed on each seed).
  - Ruff check (`src` and `tests`): 0 errors (`All checks passed!`).
  - Python compileall (`src` and `tests`): 0 errors on both 3.11 and 3.14.
  - `git diff --check`: 0 errors.
  - Git working copy preserved; no commits or pushes made.

## Session 2026-11-07 — M2b Remediation Batch 4 (Final Blocker Resolution)
- **Goal:** Resolve remaining actionable findings from Claude D's Batch 3 independent audit (H-1, N-1, H-2, M-2, M-3).
- **Actions Completed:**
  - Hardened `zerodha_connector.py` via `__slots__ = ("__weakref__",)` and `WeakKeyDictionary` dispatch, eliminating all 9 demonstrated raw-client escape paths.
  - Corrected `ingestion.py` failure handling to prevent contradictory `FULL_COVERAGE` on rejected holiday candles, resolving unhandled `ValueError`.
  - Upgraded `models.py` `ExchangeCalendar` with explicit `complete: bool = False` contract and removed single-holiday year-level inference.
  - Made `.github/workflows/ci.yml` strictly enforceable (stable 3.14, blocking pip-audit, secret scanning, `--cov-fail-under=85`).
  - Rewrote `requirements.lock` with transparent zero-runtime-dependency specification.
  - Added 21 focused regression tests in `tests/test_claude_batch4_regressions.py`.
  - Achieved **87.12% genuine coverage** and **269 passed tests** on both Python 3.11.9 and 3.14.4.

## Session 2026-11-07 — M2b Remediation Batch 5 (Final Targeted Fixes)
- **Goal:** Resolve confirmed defects from Claude's Batch 4 targeted verification (F-1, F-2, F-3).
- **Actions Completed:**
  - **F-1 (Critical): Zerodha Raw-Client Exposure Removed:**
    - Removed module-level `_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, and `_get_client_for_connector`.
    - Implemented closure-held dispatch in `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` using `__slots__ = ("_dispatch", "__weakref__")`.
    - Blocked all reflection bypasses (`vars()`, `__dict__`, `object.__getattribute__`) via `__getattribute__` raising `PermissionError`.
    - Neutralized all order mutation methods on the underlying client instance upon initialization.
    - Verified all 20 allowlisted read-only methods remain accessible with `__self__ is wrapper`.
  - **F-2 (High): Incomplete Calendar Evidence Fails Closed:**
    - Bounded `ExchangeCalendar` auto-population of `coverage_start` and `coverage_end` from `trading_days` to occur ONLY when `complete=True`.
    - Enforced that when `complete=False`, `has_evidence_for_date(d)` returns `True` ONLY for explicitly declared dates.
    - Guaranteed that unlisted weekdays are NEVER verified as non-trading days when `complete=False`.
    - Ensured `has_evidence_for_range` fails closed unless every intermediate date has explicit evidence.
    - Verified that D1 and M5 sequence ingestion fail closed and reject `require_full_coverage=True` across NSE, BSE, NYSE, and NASDAQ.
  - **F-3 (Medium): Blocking Secret Scanning in CI:**
    - Generated `.secrets.baseline` in UTF-8 binary encoding at repository root with 0 leaked secrets.
    - Updated `.github/workflows/ci.yml` secret scanning step to run `detect-secrets-hook --baseline .secrets.baseline`, blocking CI on unmanaged secrets.
  - **Test Suite Isolation:**
    - Fixed test isolation in `tests/test_claude_batch4_regressions.py` and `tests/test_claude_batch2_regressions.py` where `sys.modules["keyring"]` was mocked without restoration.
    - Added 14 targeted adversarial tests in `tests/test_claude_batch5_regressions.py`.
- **Validation Results:**
  - Genuine Python 3.11.9 (`.venv311`): **283 passed in 0.93s** with **87.12% coverage** (`--cov-fail-under=85`).
  - Genuine Python 3.14.4 (`.venv`): **283 passed in 0.74s** with **87.12% coverage** (`--cov-fail-under=85`).
  - Ruff check (`src`, `tests`, `v3-zerodha/src`): **All checks passed!**
  - Python compileall (`src`, `tests`, `v3-zerodha/src`): **0 errors** on both Python versions.
  - `git diff --check`: **0 errors**.
  - All original bundles and working tree preserved; no Git commits or branch changes made.


## 2026-11-07 — Session: M2b Remediation Batch 6 Implementation & Verification

- **Task:** Remediate all confirmed technical defects from Claude A's Batch 5 audit report (REJECT on `m2b-remediated-batch5-bundle.zip`, SHA-256 `e708153be0bbbef6cbe7962f1d3e497e1bceb40704cfcd241be1057eac83013c`).
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `src/agentic_trading/market_data/models.py`
  - `src/agentic_trading/market_data/ingestion.py`
  - `.github/workflows/ci.yml`
  - `.secrets.baseline`
  - `tests/test_claude_batch2_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `tests/test_claude_batch5_regressions.py`
  - `tests/test_claude_batch6_regressions.py` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-017)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md`
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `docs/project-memory/AGENT_HANDOFF.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. Priority 1 (F1-A, F1-B, F1-D):
     - Redesigned Zerodha read-only boundary using slotted facade composition (`__slots__ = ("_target", "__weakref__")`).
     - Stopped mutating caller-supplied KiteConnect instances; caller methods and attributes remain 100% unmutated.
     - Added `ReadOnlyTransportAdapter(HTTPAdapter)` intercepting requests at transport level to block any non-GET request with `PermissionError`.
     - Implemented `ReadOnlyKiteConnect` which mounts `ReadOnlyTransportAdapter` and overrides `_request` and write methods.
     - Implemented bound method dispatch via `types.MethodType` ensuring `wrapper.method.__self__ is wrapper`.
     - Full API audit blocking all order methods, autoslice orders, GTT, MF, MF SIP, convert_position, session mutation (`generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`), and raw HTTP methods (`_post`, `_put`, `_delete`, `_request`).
     - Safe keyring helpers catch backend errors; missing or unconfigured keyrings never break connector construction.
  2. Priority 2 (F2-A, F2-B, F2-C):
     - Implemented contradiction rejection in `ExchangeCalendar.__post_init__` for trading_days/holidays overlap and special session conflicts.
     - Completeness contract: complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed.
     - Incomplete calendar fail-closed: sequences across unverified multi-day gaps fail closed with exact error code `MARKET_CALENDAR_REQUIRED` and coverage status `CoverageStatus.MARKET_CALENDAR_REQUIRED.value`.
     - Ingestion across missing intermediate trading days without calendar evidence fails closed with exact error code `TRUNCATED_COVERAGE` and coverage status `TRUNCATED_COVERAGE`.
     - Tested across all four exchanges: NSE, BSE, NYSE, NASDAQ for D1 and M5 sequences.
  3. Priority 3 (F3-A, F3-B):
     - Anchored exclusion regex strictly avoids masking `.github/` or `.gitlab-ci.yml`.
     - Pinned `detect-secrets==1.5.0` in CI with `.secrets.baseline` containing version 1.5.0 and zero unbaselined secrets.
     - Verified detection of dummy AWS secrets across `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files.
  4. Priority 4 & Verification:
     - Verified genuine `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `pytest-cov`, and `ruff` in Python 3.11 (`.venv311`) and Python 3.14 (`.venv`).
     - Full test suite: **310 passed in 1.59s** on Python 3.11.9 and **310 passed in 0.84s** on Python 3.14.4.
     - Test coverage: **85.49%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
     - Generated separate test reports: `python311_verification_report.txt`, `python314_verification_report.txt`.
     - Ruff check passed with zero errors (`All checks passed!`).
     - Python compileall passed with zero errors on both interpreters.
     - `detect-secrets-hook` passed with zero errors across all tracked files.
     - `pip-audit` passed with zero known vulnerabilities.


## 2026-11-22 — Session: M2b Remediation Batch 7 Implementation & Verification

- **Task:** Remediate all 7 confirmed technical defects (D1–D7) from Claude's Batch 6 independent audit.
- **Specialist Sequence:** `agency-security-architect` -> `agency-backend-architect` -> `agency-reality-checker` -> `agency-code-reviewer`.
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `src/agentic_trading/market_data/ingestion.py`
  - `src/agentic_trading/market_data/models.py`
  - `pyproject.toml`
  - `requirements.lock`
  - `.github/workflows/ci.yml`
  - `.secrets.baseline`
  - `tests/test_claude_batch1_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `tests/test_claude_batch6_regressions.py`
  - `tests/test_market_data_ingestion.py`
  - `tests/test_claude_batch7_regressions.py` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-018)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md`
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. **D1 (Hide raw client completely):**
     - Removed `_target` from `__slots__` on `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (`__slots__ = ("__weakref__",)` only).
     - Stored underlying clients strictly in closure-encapsulated `WeakKeyDictionary` registries with zero instance attributes, zero slots, and zero module-level dictionaries.
     - Enforced `PermissionError` in `__getattribute__` for `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession`.
     - Bound allowlisted read methods via `types.MethodType(bound_call, self)` ensuring `method.__self__ is wrapper`.
     - Preserved caller-supplied `KiteConnect` instances 100% unmutated.
  2. **D2 & D3 (Uniform session-mutation blocking):**
     - Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`.
     - Made `ZerodhaReadOnlyConnector.complete_login` consistently fail closed with `PermissionError`.
     - Updated previous tests to assert fail-closed behavior.
  3. **D4 (In-memory token bypass for locked keyrings):**
     - Updated `_require_session()` to verify in-memory `access_token` on the client first; read methods execute cleanly without querying keyring.
     - Keyring is queried only when no in-memory token exists, catching backend errors as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`.
  4. **D5 (Ingestion error code alignment):**
     - When `ingest_historical` encounters missing intermediate trading days (`MISSING_INTERVAL`), set both `coverage_status = "TRUNCATED_COVERAGE"` and `error_code = "TRUNCATED_COVERAGE"`.
     - Updated `ExchangeCalendar` docstring in `models.py` to clarify that unlisted weekdays do NOT count as non-trading days without explicit holiday evidence.
  5. **D6 & D7 (Secret scanning & dependency pinning):**
     - Removed `is_lock_file` filter from `.secrets.baseline` so lockfiles are actively scanned.
     - Removed stray `# pragma: allowlist secret` comment from `.github/workflows/ci.yml`.
     - Added `requests>=2.32.0` in `pyproject.toml`.
     - Populated `requirements.lock` with exact verified pins (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`).
     - Updated CI to install from `requirements.lock`.
  6. **Verification Evidence:**
     - Full test suite: **327 passed in 1.98s** on Python 3.11.9 (`.venv311`) and **327 passed in 0.89s** on Python 3.14.4 (`.venv`).
     - Test coverage: **85.55%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
     - Generated separate test reports: `python311_verification_report.txt`, `python314_verification_report.txt`.
     - Ruff check passed with zero errors (`All checks passed!`).
     - Python compileall passed with zero errors on both interpreters.
     - `detect-secrets-hook` passed with zero errors across all tracked files, actively scanning `requirements.lock`.
     - `pip-audit` passed with zero known vulnerabilities.


## 2026-11-22 — Session: M2b Remediation Batch 7b Polish & Packaging

- **Task:** Remediate two targeted findings (F1, F3) from Claude's verification review of the Zerodha read-only boundary.
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `tests/test_claude_batch7_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `docs/project-memory/BATCH7B_VERIFICATION.md` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-019)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md` (R-034, R-035)
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. **F1 (Zero mutation of caller-injected clients):**
     - Stored `(client, injected: bool)` tuple in closure-encapsulated `_connector_registry`.
     - In `_require_session()`: if `injected` is True, verified `raw_client.access_token` is already a non-empty string; if missing/empty, raises `KiteConfigurationError("Injected client must be pre-authenticated with an active access_token")` without calling `set_access_token()` or querying keyring.
     - In `logout()`: if `injected` is True, deleted only local keyring token and left caller client completely untouched.
     - Injected genuine `KiteConnect.__dict__` and `reqsession.headers` verified identical before and after wrapping, reading, and `logout()`.
  2. **F3 (Block POST margin/contract-note endpoints):**
     - Removed `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`.
     - Added explicit method overrides on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` before transport.
     - Added messages in `_OPERATION_MESSAGES`.
  3. **Regression Tests:**
     - Added 11 new tests in `tests/test_claude_batch7_regressions.py` covering F1, F3, and wrapper edge cases.
     - Total tests in suite: **338 passed** across both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
     - Test coverage: **85.02%** (exceeds `--cov-fail-under=85`).
  4. **Quality Gates:**
     - Ruff check: 0 errors (`All checks passed!`).
     - Compileall: 0 errors on both 3.11 and 3.14.
     - detect-secrets hook: 0 unbaselined leaks across all tracked files, scanning `requirements.lock`.
     - pip-audit: 0 known vulnerabilities.
  5. **Packaging:**
     - Packaged `m2b-remediated-batch7b-bundle.zip` in parent directory and computed SHA-256 hash.


## 2026-11-22 — Session: Milestone 2c (Cross-Market Foundation, Instrument Registry, Corporate Actions, and Stored Replay Fixtures)

- **Task:** Implement Milestone 2c on `feature/reliable-foundation` across 4 specialist roles (`agency-backend-architect` -> `agency-security-architect` -> `agency-reality-checker` -> `agency-code-reviewer`) adhering strictly to paper-only constraints and zero inline `#` comments.
- **Files Created/Modified:**
  - `src/agentic_trading/market_data/instruments.py` (new)
  - `src/agentic_trading/market_data/corporate_actions.py` (new)
  - `src/agentic_trading/market_data/replay_fixtures.py` (new)
  - `src/agentic_trading/market_data/__init__.py` (modified: clean exports)
  - `tests/test_m2c_cross_market_foundation.py` (new: 24 adversarial tests)
  - `docs/project-memory/DECISION_LOG.md` (ADR-020)
  - `docs/project-memory/CURRENT_STATE.md` (updated)
  - `docs/project-memory/NEXT_ACTIONS.md` (updated)
  - `docs/project-memory/SESSION_LOG.md` (updated)
- **Actions Taken:**
  1. **Cross-Market Instruments & Currency Isolation (`instruments.py`):**
     - Defined `Currency` enum (`INR`, `USD`) and `CurrencyMismatchError`.
     - Implemented immutable `Money` dataclass with strict currency safety: validates non-negative finite `Decimal`, rejects `float`, `bool`, and `bytes`. Addition and subtraction require matching currency; scalar multiplication supports `Decimal` and `int` (rejecting `float`/`bool`).
     - Defined `AssetClass` (`EQUITY`, `COMMODITY`, `INDEX`, `FOREX`, `CRYPTO`).
     - Implemented `Instrument` with strict exchange-currency pairing validation (`NSE`/`BSE` requires `INR`; `NYSE`/`NASDAQ` requires `USD`), positive finite `tick_size`, positive integer `lot_size`, and immutable `provider_tokens` dictionary (`MappingProxyType`).
     - Implemented `InstrumentRegistry` with duplicate detection, thread-safe lookup, and O(1) resolution by `(exchange, symbol)` or `(provider, token)` failing closed with `UnknownInstrumentError`.
  2. **Corporate Actions & Symbol Lineage (`corporate_actions.py`):**
     - Modeled `CorporateAction` and `CorporateActionType` (`SPLIT`, `BONUS`, `DIVIDEND`, `SYMBOL_CHANGE`).
     - Implemented `resolve_symbol_lineage` to trace rename histories bidirectionally with topological graph cycle detection (`ValueError`).
     - Implemented `adjust_candles_for_corporate_actions` applying cumulative adjustment factors to historical OHLC, preserving OHLC invariants, quantizing prices to `tick_size` using `ROUND_HALF_EVEN`, and inverse-scaling volumes.
  3. **Tier-2 Stored Replay Fixtures (`replay_fixtures.py`):**
     - Defined `FixtureManifest` with SHA-256 payload digest.
     - Implemented `save_replay_fixture` with canonical JSON serialization, path-traversal prevention, and atomic manifest generation.
     - Implemented `StoredReplayFixtureProvider` extending `MarketDataProvider`: cryptographically verifies raw payload integrity on load via `hmac.compare_digest` against manifest SHA-256 (raising `FixtureIntegrityError` on tampering or mismatch), and provides deterministic `[start_time, end_time)` window filtering.
  4. **Adversarial Regression Tests (`test_m2c_cross_market_foundation.py`):**
     - 24 comprehensive tests covering currency arithmetic, instrument validation, duplicate prevention, corporate action price/volume adjustment, cyclic rename graph rejection, and replay fixture tampering/mismatch detection.
     - 0 inline `#` comments in all code and test files.
- **Verification Evidence:**
  - Full pytest suite: **362 passed in 4.67s** on Python 3.11.9 (`.venv311`) and **362 passed in 2.06s** on Python 3.14.4 (`.venv`).
  - Total test coverage: **86.56%** (exceeds mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff check: clean (0 errors) on `src`, `tests`, and `v3-zerodha/src`.
  - Python compileall: 0 errors on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` clean (0 leaks).
  - Comment check: verified 0 `#` comment characters across all 5 new/edited files.
