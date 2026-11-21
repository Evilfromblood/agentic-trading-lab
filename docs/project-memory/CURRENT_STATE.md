# Current Project State

Last updated: 2026-11-07

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active branch: `feature/reliable-foundation`
- Current baseline commit: `1b7e5829474239495163da1d2d3349eb35ca9744` — `feat: complete market data quality foundation`.
- Remote branch is pushed and synchronized with `origin/feature/reliable-foundation`.
- Do not merge to `main` without explicit user approval.

## Local working copy state
The working tree has local, uncommitted M2b modifications for the market data ingestion foundation and Claude audit remediation Batches 1 through 6:
- `src/agentic_trading/market_data/__init__.py` (exports provider, adapter, pipeline interfaces, `ExchangeSession`, `CoverageStatus`, `ExchangeCalendar`, `US_EASTERN`, `get_exchange_timezone`)
- `src/agentic_trading/market_data/models.py` (authoritative `ExchangeCalendar` completeness contract: contradiction rejection for trading_days/holidays overlap and special session conflicts; complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed; `is_verified_trading_day` and `is_verified_non_trading_day` strictly distinguish verified vs unverified dates across NSE, BSE, NYSE, and NASDAQ)
- `src/agentic_trading/market_data/quality.py` (session-aware cross-exchange mismatch checks `EXCHANGE_MISMATCH`; calendar holiday candle rejection `OUTSIDE_SESSION`; calendar-aware gap detection; D1/W1/MN1 grid anchor validation; sparse sequence handling via `allow_sparse`; specific exception handling eliminating BLE001)
- `src/agentic_trading/market_data/provider.py` (multi-exchange synthetic provider; dynamic synthetic close time calculation with calendar-month MN1 boundaries; specific exception handling)
- `src/agentic_trading/market_data/adapters.py` (normalization, direct Decimal handling, strict whitespace-padded string rejection, explicit bytes rejection, identity-less support)
- `src/agentic_trading/market_data/ingestion.py` (exact failure coverage and error codes: `MARKET_CALENDAR_REQUIRED` when calendar evidence is incomplete or required, `TRUNCATED_COVERAGE` when intermediate trading days are missing without calendar evidence; `_require_valid_now` docstring synchronized to 365 days; strict fail-closed coverage contracts)
- `v3-zerodha/src/agentic_trading/zerodha_connector.py` (Priority 1 redesign: caller-supplied `KiteConnect` instances are never mutated; slotted facade composition `__slots__ = ("_target", "__weakref__")`; `ReadOnlyTransportAdapter(HTTPAdapter)` intercepts and blocks any non-GET request at transport level; `ReadOnlyKiteConnect` mounts adapter and overrides `_request` and write methods; `_ReadOnlyKiteWrapper` returns bound methods pointing to wrapper; complete API audit blocking orders, autoslice, GTT, MF, MF SIP, convert_position, session mutation, and non-GET requests; safe keyring token helpers never break construction)
- `.github/workflows/ci.yml` (blocking secret scanning via pinned `detect-secrets==1.5.0` with `detect-secrets-hook --baseline .secrets.baseline`; stable Python 3.14 matrix entry; blocking `pip-audit`; package installation with `[dev,zerodha-readonly]`; coverage command enforcing `--cov-fail-under=85`)
- `.secrets.baseline` (UTF-8 secret scanning baseline pinned to version 1.5.0 with 0 detected leaks; anchored exclusion regex excluding only exact generated/cache directories without masking `.github` or `.gitlab-ci.yml`)
- `pyproject.toml` (Ruff configuration selecting `F, E4, E7, E9, B, BLE, I`, dev dependencies `pytest-cov>=5.0`, pythonpath including `src` and `v3-zerodha/src`)
- `requirements.lock` (honest dependency specification documenting 0 runtime third-party dependencies in core and pyproject.toml dev tooling)
- `.gitignore` (ignoring `.coverage`, `htmlcov/`, `.venv311/`, `.ruff_cache/`)
- `tests/test_claude_batch6_regressions.py` (20 comprehensive regression tests covering genuine KiteConnect 5.2.2 integration with intercepted transport, caller unmutated client integrity, all order/GTT/MF/session mutations blocked before transport, calendar contradiction rejection, D1/M5 ingestion fail-closed across NSE/BSE/NYSE/NASDAQ, and secret scanning leak detection)

## Validation evidence
Verified local Windows virtual environment output:
- Ruff on `src/`, `tests/`, and `v3-zerodha/src`: passed (`All checks passed!`).
- Python compileall: `python -m compileall -q src tests v3-zerodha/src` passed with exit code 0 on both 3.11.9 and 3.14.4.
- `git diff --check`: exit code 0 (no whitespace errors or merge markers).
- Full pytest suite: **310 passed in 1.59s** on genuine Python 3.11.9 (.venv311) and **310 passed in 0.84s** on Python 3.14.4 (.venv).
- Genuine pytest-cov coverage: **85.49%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
- Secret scanning hook: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files.
- Dependency audit: `pip-audit` exited with code 0 (0 known vulnerabilities).

## Current milestone
- Milestone 2a: COMPLETE and committed (`1b7e582`).
- Milestone 2b: Batch 6 remediations complete and verified locally; ready for independent audit bundle packaging.

## Environment
Windows 11, repository path:
`C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`

Interpreters:
- Python 3.11.9: `.\.venv311\Scripts\python.exe` (with genuine `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `pytest-cov`, `detect-secrets==1.5.0`, `pip-audit`)
- Python 3.14.4: `.\.venv\Scripts\python.exe` (with `pytest-cov`, `ruff`)
