# Next Actions

Current priority: finish M2b remediation and independent verification. The first major product milestone after the reliable cross-market data foundation is Time Machine.

## Immediate sequence
1. Baseline M2a committed (`1b7e582`) and pushed to `origin/feature/reliable-foundation`.
2. M2b Ingestion Foundation and Claude Batch 7 / 7b audit remediations verified in working tree:
   - Priority 1 (D1, D2, D3, D4, F1, F3: Zerodha Read-Only Boundary Hardening): Removed `_target` from slots (`__slots__ = ("__weakref__",)`). Underlying clients stored in closure-encapsulated `WeakKeyDictionary` registries inside `_init_facades()` with `(client, injected)` tuple. Injected and default clients cannot be inspected or retrieved via slots, descriptors, or dicts. Bound methods return wrapper (`method.__self__ is wrapper`). Caller-injected instances never mutated across `_require_session()` and `logout()`. Unauthenticated injected clients fail closed with `KiteConfigurationError`. `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, `set_access_token`, `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` blocked before transport with `PermissionError`. `complete_login` consistently fails closed with `PermissionError`. In-memory non-empty `access_token` permits read-only operations without keyring queries. Keyring failures degrade gracefully with `KiteConfigurationError` without swallowing system exits or breaking unauthenticated initializations.
   - Priority 2 (D5: Ingestion Error Code & Docstring Alignment): In `ingest_historical`, intermediate missing interval/day failures return both `coverage_status = TRUNCATED_COVERAGE` and `error_code = "TRUNCATED_COVERAGE"`. Updated `ExchangeCalendar` docstring to document the closed-world holiday evidence requirement for complete calendars and fail-closed behavior for incomplete calendars.
   - Priority 3 (D6, D7: Secret Scanning Baseline & Dependency Pinning): Removed `is_lock_file` filter from `.secrets.baseline` so `requirements.lock` is actively scanned. Cleaned comment in `.github/workflows/ci.yml`. Pinned exact dependencies in `requirements.lock` (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`). Added `requests>=2.32.0` to `pyproject.toml`. Added lockfile installation step in CI.
   - Regression test suite: 28 regression tests in `tests/test_claude_batch7_regressions.py`. All 338 tests pass across the entire suite with 85.02% test coverage on both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`). Ruff check clean (0 errors), compileall clean (0 errors), detect-secrets clean (0 leaks), pip-audit clean.
3. Package verified audit bundle ZIP `m2b-remediated-batch7b-bundle.zip` in parent directory `C:\Users\Rhyth\Downloads\agentic-trading-lab-main\` and compute its SHA-256.
4. Close M2b only when independent audit review findings are satisfied.
5. M2c: establish cross-market instrument identity, exchange-specific sessions/calendars, historical data adapters, INR/USD representation and data provenance for NSE/BSE and NYSE/NASDAQ.
6. M3: define strategy and deterministic simulation contracts, portfolio/cash accounting, sizing, transaction costs, slippage and risk controls.
7. M4: build Time Machine backtesting and reproducible Monte Carlo simulation.
8. Later: paper trading engine, market/news intelligence agents and analytics dashboard.

## Review/remediation loop
Claude independent verification -> ChatGPT triage and scoped technical direction -> Antigravity implementation and regression tests -> independent verification of the new snapshot. Avoid overlapping audits of unchanged code when a focused remediation cycle is more efficient.

## Product and safety constraints
- Shared core with market-specific adapters; do not fork the platform into separate India and US implementations.
- Strictly paper-only: no real-money execution, no agent broker order-placement access, no autonomous live trading.
- AI agents research and propose; deterministic risk controls remain authoritative.
- Fail closed on missing, stale, malformed or contradictory data.
- Preserve provenance, assumptions and simulation reproducibility.
- No live broker execution milestone is authorised.

## Git and change-control constraints
- Work on `feature/reliable-foundation`; never merge to `main` without explicit approval.
- Preserve all uncommitted work and `m2a-review.patch`.
- No destructive Git operations.
- Do not commit or push implementation changes without explicit user approval.
