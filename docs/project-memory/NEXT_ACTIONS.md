# Next Actions

Current priority: finish M2b remediation and independent verification. The first major product milestone after the reliable cross-market data foundation is Time Machine.

## Immediate sequence
1. Baseline M2a committed (`1b7e582`) and pushed to `origin/feature/reliable-foundation`.
2. M2b Ingestion Foundation and Claude Batch 6 audit remediations verified in working tree:
   - Priority 1 (F1-A, F1-B, F1-D: Zerodha Read-Only Boundary Redesign): Never mutate caller-supplied KiteConnect instances; slotted facade composition `__slots__ = ("_target", "__weakref__")`; `ReadOnlyTransportAdapter(HTTPAdapter)` intercepts and blocks any non-GET request at transport level; `ReadOnlyKiteConnect` mounts adapter and overrides `_request` and write methods; `_ReadOnlyKiteWrapper` returns bound methods pointing to wrapper; complete API audit blocking orders, autoslice, GTT, MF, MF SIP, convert_position, session mutation, and non-GET requests; safe keyring token helpers never break construction.
   - Priority 2 (F2-A, F2-B, F2-C: Calendar Contradiction Rejection & Completeness Contract): Contradiction rejection in `ExchangeCalendar.__post_init__` for trading_days/holidays overlap and special session conflicts; complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed; exact failure error code `MARKET_CALENDAR_REQUIRED` and coverage status `CoverageStatus.MARKET_CALENDAR_REQUIRED.value`; intermediate missing days fail closed with `TRUNCATED_COVERAGE`. Tested across all 4 exchanges: NSE, BSE, NYSE, NASDAQ.
   - Priority 3 (F3-A, F3-B: Secret Scanning Hardening): Anchored exclusion regex `^(?:\.git/|\.venv(?:311)?/|\.ruff_cache/|\.pytest_cache/|\.coverage$|htmlcov/|m2a-review\.patch$)` strictly avoids masking `.github/` or `.gitlab-ci.yml`. Pin `detect-secrets==1.5.0` in CI with `.secrets.baseline` containing version 1.5.0 and zero unbaselined secrets. Verified detection of dummy AWS secrets across `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files.
   - Priority 4 (T-1: Genuine Dependency Verification & Test Coverage): Genuine `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `pytest-cov`, and `ruff` verified in Python 3.11 (`.venv311`) and Python 3.14 (`.venv`). Verified genuine KiteConnect integration with intercepted transport in `tests/test_zerodha_kiteconnect_integration.py` and `tests/test_claude_batch6_regressions.py`. All 310 tests pass across the entire suite with 85.49% test coverage on both Python 3.11.9 and Python 3.14.4.
3. Package verified audit bundle ZIP `m2b-remediated-batch6-bundle.zip` in parent directory `C:\Users\Rhyth\Downloads\agentic-trading-lab-main\` and compute its SHA-256.
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
