# Current Project State

Last updated: 2026-11-01

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active branch: `feature/reliable-foundation`
- Latest confirmed remote commit: `0cba42239d13c323d499973a2f0200f1454a282a` — README project handoff update.
- Previous implementation baseline: `3bfe105ac8ba09860a3f24059547cc8e7e7e2253` — initial market-data quality foundation.
- Do not merge to `main` without explicit user approval.

## Local versus remote state
The user's Windows working copy has local, uncommitted M2a modifications in:
- `.github/workflows/ci.yml`
- `docs/DEVELOPMENT_PLAN.md`
- `src/agentic_trading/market_data/__init__.py`
- `src/agentic_trading/market_data/models.py`
- `src/agentic_trading/market_data/quality.py`
- `tests/test_market_data_models.py`
- `tests/test_market_data_quality.py`

The remote README-only commit `0cba422` was created after the user's last local status report. The local branch may therefore be behind remote and the working tree is dirty. **Do not pull, reset, rebase, stash, or overwrite local changes until current `git status`, branch, and log are inspected and a safe synchronization plan is agreed.**

A previous status showed an untracked path named `cls`. Its contents are unknown; inspect before deleting. A generated `src/agentic_trading_lab.egg-info/` directory was previously present and removal was attempted; verify current state.

## M2a validation evidence
User supplied local Windows terminal output:
- Ruff on market-data source and two market-data test modules: passed.
- Full pytest with bytecode/cache disabled: 63 passed.
- `python -m compileall -q src tests`: exit code 0.
- `git diff --check`: no whitespace errors; Git emitted LF-to-CRLF warnings.

These are local results, not GitHub Actions results. Python 3.11 CI compatibility is unverified.

## Current milestone
M2a is under review and remediation. It is not approved, committed, or pushed. See `ISSUES_AND_RISKS.md` and `NEXT_ACTIONS.md`.

## Environment
Windows 11, repository path:
`C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`

Use the venv executable explicitly:
` .\.venv\Scripts\python.exe `
because PATH may resolve `python` to MSYS2 rather than the project virtual environment.
