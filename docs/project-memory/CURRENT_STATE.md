# Current Project State

Last updated: 2026-11-03

## Product direction
- Markets: India (NSE/BSE) and United States (NYSE/NASDAQ).
- Approach: extend the existing Agentic Trading Lab codebase using a shared core and market-specific adapters.
- First major product priority after the data foundation: Time Machine (historical backtesting and reproducible Monte Carlo simulation).
- Product remains strictly paper-only. No real-money execution or agent access to broker order-placement APIs.

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active development branch: `feature/reliable-foundation`
- Do not merge to `main` without explicit user approval.
- Treat the local working tree and GitHub branch as separate states; verify both before editing or synchronising.

## Current M2b review state
- M2b corrected audit snapshot SHA-256: `15b9657b7b636a5a196b3c99842aac2322b0668b2b9dd1ac59d28abbf53972e1`.
- Claude A independently verified this snapshot and returned REJECT.
- Claude A reported 188 tests passing on Python 3.11 and 188 on Python 3.14, Ruff clean, and identified remaining defects involving candle grid/session validation, final session bars, historical retrieval timestamps, freshness boundary handling, shared-DAG freeze performance, coverage semantics and related regression gaps.
- These are reviewer-reported results, not a claim that the current local working tree has been independently re-run by ChatGPT.
- Next action: triage Claude A findings and perform a narrowly scoped Antigravity remediation batch. Preserve the original audit ZIP; create a new snapshot and SHA-256 after remediation.
- Do not expand M2b into Time Machine implementation. Complete M2b reliability and release gates first.

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
