# Current Project State

Last updated: 2026-11-01

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active branch: `feature/reliable-foundation`
- Current baseline commit: `a0ee7e018dbb3a70cd841753ebd718b56df27457` — `docs: link durable project memory from README`.
- Branch is synchronized with remote `origin/feature/reliable-foundation`.
- Do not merge to `main` without explicit user approval.

## Local working copy state
The user's Windows working copy has local, uncommitted M2a modifications in:
- `.github/workflows/ci.yml`
- `docs/DEVELOPMENT_PLAN.md`
- `pyproject.toml`
- `src/agentic_trading/market_data/__init__.py`
- `src/agentic_trading/market_data/models.py`
- `src/agentic_trading/market_data/quality.py`
- `tests/test_market_data_models.py`
- `tests/test_market_data_quality.py`
- `tests/integration/test_market_data_pipeline.py`

Documentation updates are maintained in:
- `docs/project-memory/CURRENT_STATE.md`
- `docs/project-memory/ISSUES_AND_RISKS.md`
- `docs/project-memory/NEXT_ACTIONS.md`
- `docs/project-memory/SESSION_LOG.md`

## M2a validation evidence
Verified local Windows virtual environment output:
- Ruff on `src/agentic_trading/risk_engine.py` and `tests/test_risk_engine.py`: passed (`All checks passed!`).
- Ruff on `src/agentic_trading/market_data`, `tests/test_market_data_models.py`, and `tests/test_market_data_quality.py`: passed (`All checks passed!`).
- Full pytest with bytecode/cache disabled: **106 passed in 0.19s** (84 base unit tests + 12 M2a regression tests + 10 pipeline integration tests).
- `python -m compileall -q -f src tests`: exit code 0.
- `git diff --check`: exit code 0 (no whitespace errors or EOF newline issues).

These checks apply to the local working copy. Python 3.14.4 tested locally; Python 3.11 compatibility is enforced via GitHub Actions CI workflow.

## Current milestone
Milestone 2a (Market Data Contracts & Quality Gate) finalized and committed to `feature/reliable-foundation`. Milestone 2b (Market Data Ingestion and Provider Integration Foundation) starting.

## Environment
Windows 11, repository path:
`C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`

Virtual environment executable:
`.\.venv\Scripts\python.exe` (Python 3.14.4, pytest 9.2.0, ruff 0.17.3).
