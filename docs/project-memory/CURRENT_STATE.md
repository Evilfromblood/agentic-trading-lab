# Current Project State

Last updated: 2026-11-07

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active branch: `feature/reliable-foundation`
- Current baseline commit: `1b7e5829474239495163da1d2d3349eb35ca9744` — `feat: complete market data quality foundation`.
- Remote branch is pushed and synchronized with `origin/feature/reliable-foundation`.
- Do not merge to `main` without explicit user approval.

## Local working copy state
The working tree has local, uncommitted M2b modifications for the market data ingestion foundation and Claude audit remediation Batches 1 through 5:
- `src/agentic_trading/market_data/__init__.py` (exports provider, adapter, pipeline interfaces, `ExchangeSession`, `CoverageStatus`, `ExchangeCalendar`, `US_EASTERN`, `get_exchange_timezone`)
- `src/agentic_trading/market_data/models.py` (`ExchangeCalendar` completeness contract: when `complete=False`, unlisted weekdays never have evidence and are never marked as verified non-trading days; `has_evidence_for_range` verifies all dates fail-closed; auto-population of `coverage_start` and `coverage_end` from `trading_days` occurs only when `complete=True`; `is_verified_trading_day` and `is_verified_non_trading_day` cleanly distinguish verified trading days, non-trading days, and unverified dates across NSE, BSE, NYSE, and NASDAQ)
- `src/agentic_trading/market_data/quality.py` (session-aware cross-exchange mismatch checks `EXCHANGE_MISMATCH`; calendar holiday candle rejection `OUTSIDE_SESSION`; calendar-aware gap detection; D1/W1/MN1 grid anchor validation; sparse sequence handling via `allow_sparse`; specific exception handling eliminating BLE001)
- `src/agentic_trading/market_data/provider.py` (multi-exchange synthetic provider; dynamic synthetic close time calculation with calendar-month MN1 boundaries; specific exception handling)
- `src/agentic_trading/market_data/adapters.py` (normalization, direct Decimal handling, strict whitespace-padded string rejection, explicit bytes rejection, identity-less support)
- `src/agentic_trading/market_data/ingestion.py` (N-1 holiday rejection failure path hardened: failed results strictly prohibited from carrying contradictory `FULL_COVERAGE`; `_require_valid_now` docstring synchronized to 365 days; strict fail-closed coverage contracts)
- `v3-zerodha/src/agentic_trading/zerodha_connector.py` (F-1 critical remediation: removed `_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, `_get_client_for_connector`; implemented `__slots__ = ("_dispatch", "__weakref__")` and closure-held dispatch; blocked reflection access `vars()`, `__dict__`, `object.__getattribute__`; sanitized underlying client mutation methods on initialization; explicit order and mutation blocks raising `PermissionError`)
- `.github/workflows/ci.yml` (blocking secret scanning via `detect-secrets-hook --baseline .secrets.baseline`; stable Python 3.14 matrix entry; blocking `pip-audit`; coverage command enforcing `--cov-fail-under=85`)
- `.secrets.baseline` (UTF-8 secret scanning baseline with 0 detected leaks)
- `pyproject.toml` (Ruff configuration selecting `F, E4, E7, E9, B, BLE, I`, dev dependencies `pytest-cov>=5.0`, pythonpath including `src` and `v3-zerodha/src`)
- `requirements.lock` (honest dependency specification documenting 0 runtime third-party dependencies in core and pyproject.toml dev tooling)
- `.gitignore` (ignoring `.coverage`, `htmlcov/`, `.venv311/`, `.ruff_cache/`)
- `tests/test_claude_batch5_regressions.py` (14 targeted regression tests covering F-1 closure dispatch and raw client elimination, F-2 incomplete calendar fail-closed contract across all exchanges, F-3 blocking secret scanning baseline, and test isolation)

## Validation evidence
Verified local Windows virtual environment output:
- Ruff on `src/`, `tests/`, and `v3-zerodha/src`: passed (`All checks passed!`).
- Python compileall: `python -m compileall -q src tests v3-zerodha/src` passed with exit code 0 on both 3.11.9 and 3.14.4.
- `git diff --check`: exit code 0 (no whitespace errors or merge markers).
- Full pytest suite: **283 passed in 0.93s** on genuine Python 3.11.9 (.venv311) and **283 passed in 0.74s** on Python 3.14.4 (.venv).
- Genuine pytest-cov coverage: **87.12%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).

## Current milestone
- Milestone 2a: COMPLETE and committed (`1b7e582`).
- Milestone 2b: Batch 5 remediations complete and verified locally; awaiting independent audit.

## Environment
Windows 11, repository path:
`C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`

Interpreters:
- Python 3.11.9: `.\.venv311\Scripts\python.exe`
- Python 3.14.4: `.\.venv\Scripts\python.exe`
