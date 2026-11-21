# Current Project State

Last updated: 2026-11-22

## Product direction
- Markets: India (NSE/BSE) and United States (NYSE/NASDAQ).
- Approach: extend the existing Agentic Trading Lab codebase using a shared core and market-specific adapters.
- First major product priority after the data foundation: Time Machine (historical backtesting and reproducible Monte Carlo simulation).
- Product remains strictly paper-only. No real-money execution or agent access to broker order-placement APIs.

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active development branch: `feature/reliable-foundation`
- Baseline commit: `1b7e5829474239495163da1d2d3349eb35ca9744` — `feat: complete market data quality foundation`.
- Do not merge to `main` without explicit user approval.
- Treat the local working tree and GitHub branch as separate states; verify both before editing or synchronising.

## Local working copy state
The working tree has local M2b modifications for the market data ingestion foundation and Claude audit remediation Batches 1 through 7:
- `src/agentic_trading/market_data/__init__.py` (exports provider, adapter, pipeline interfaces, `ExchangeSession`, `CoverageStatus`, `ExchangeCalendar`, `US_EASTERN`, `get_exchange_timezone`)
- `src/agentic_trading/market_data/models.py` (authoritative `ExchangeCalendar` completeness contract: contradiction rejection for trading_days/holidays overlap and special session conflicts; complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed; `is_verified_trading_day` and `is_verified_non_trading_day` strictly distinguish verified vs unverified dates across NSE, BSE, NYSE, and NASDAQ; docstring aligned with completeness contract)
- `src/agentic_trading/market_data/quality.py` (session-aware cross-exchange mismatch checks `EXCHANGE_MISMATCH`; calendar holiday candle rejection `OUTSIDE_SESSION`; calendar-aware gap detection; D1/W1/MN1 grid anchor validation; sparse sequence handling via `allow_sparse`; specific exception handling eliminating BLE001)
- `src/agentic_trading/market_data/provider.py` (multi-exchange synthetic provider; dynamic synthetic close time calculation with calendar-month MN1 boundaries; specific exception handling)
- `src/agentic_trading/market_data/adapters.py` (normalization, direct Decimal handling, strict whitespace-padded string rejection, explicit bytes rejection, identity-less support)
- `src/agentic_trading/market_data/ingestion.py` (exact failure coverage and error codes: `MARKET_CALENDAR_REQUIRED` when calendar evidence is incomplete or required, `TRUNCATED_COVERAGE` when intermediate trading days are missing without calendar evidence; fail-closed coverage contracts)
- `v3-zerodha/src/agentic_trading/zerodha_connector.py` (Batch 7 & 7b redesign: `_target` completely removed from slots; `__slots__ = ("__weakref__",)` only; wrapped client held strictly in closure-encapsulated `WeakKeyDictionary` with `(client, injected)` tuple; `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession` blocked with `PermissionError` in `__getattribute__`; bound allowlisted read methods returned via `types.MethodType` ensuring `method.__self__ is wrapper`; caller-supplied `KiteConnect` client instances remain 100% unmutated across `_require_session()` and `logout()`; unauthenticated injected clients raise `KiteConfigurationError` without mutation; `order_margins`, `basket_order_margins`, `get_virtual_contract_note`, session mutation methods, and `complete_login` fail closed with `PermissionError` before transport; in-memory token bypasses keyring for locked keyrings; keyring backend errors caught cleanly as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`)
- `.github/workflows/ci.yml` (blocking secret scanning via pinned `detect-secrets==1.5.0` scanning `requirements.lock`; stable Python 3.14 matrix entry; blocking `pip-audit`; installation from `requirements.lock` and `[dev,zerodha-readonly]`; coverage command enforcing `--cov-fail-under=85`)
- `.secrets.baseline` (UTF-8 secret scanning baseline pinned to version 1.5.0 with 0 detected leaks; removed `is_lock_file` filter so `requirements.lock` is scanned; anchored exclusion regex excluding only exact generated/cache directories without masking `.github` or `.gitlab-ci.yml`)
- `pyproject.toml` (Ruff configuration selecting `F, E4, E7, E9, B, BLE, I`, dev dependencies `pytest-cov>=5.0`, optional dependency `requests>=2.32.0`, pythonpath including `src` and `v3-zerodha/src`)
- `requirements.lock` (pinned dependency specification with exact verified pins: `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`)
- `tests/test_claude_batch7_regressions.py` (28 regression tests covering closure encapsulation, slot removal, uniform mutation blocking, keyring bypass, D1/M5 ingestion fail-closed `TRUNCATED_COVERAGE` across NSE/BSE/NYSE/NASDAQ, secret scanning of `requirements.lock`, injected client zero-mutation in session/logout, and POST endpoint blocking)

## Validation evidence
Verified local Windows virtual environment output:
- Ruff on `src/`, `tests/`, and `v3-zerodha/src`: passed (`All checks passed!`).
- Python compileall: `python -m compileall -q src tests v3-zerodha/src` passed with exit code 0 on both 3.11.9 and 3.14.4.
- `git diff --check`: exit code 0 (no whitespace errors or merge markers).
- Full pytest suite: **338 passed in 2.24s** on genuine Python 3.11.9 (.venv311) and **338 passed in 1.42s** on Python 3.14.4 (.venv).
- Genuine pytest-cov coverage: **85.02%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
- Secret scanning hook: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files, scanning `requirements.lock`.
- Dependency audit: `pip-audit` exited with code 0 (0 known vulnerabilities).

## Current milestone
- Milestone 2a: COMPLETE and committed (`1b7e582`).
- Milestone 2b: Batch 7 & 7b remediations complete and verified locally; packaged into `m2b-remediated-batch7b-bundle.zip` ready for independent audit.

## Development workflow
1. Claude independently verifies a frozen snapshot.
2. ChatGPT triages findings, separates confirmed defects from design decisions, and scopes remediation.
3. Antigravity implements approved fixes and regression tests.
4. Independent verification checks the new snapshot and remediation evidence.
5. Repeat only where material defects remain.

## Safety boundary
- Paper-only development.
- No real-money order execution.
- No agent access to broker order-placement APIs.
- Deterministic risk controls remain authoritative.
- Missing, stale, malformed or contradictory market data fails closed.
- Human approval required for financial assumptions, credentials, any change to the safety boundary, commits/pushes when requested, and merges.

## Environment and local state
- Windows working copy: `C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`
- Known project Python environments: `.venv` (Python 3.14) and `.venv311` (Python 3.11).
- Use explicit environment executables; do not rely on system Python.
- Preserve uncommitted work and `m2a-review.patch`. Never reset, clean, stash, overwrite or discard user changes.
