# Agentic Trading Lab

A reliability-first, multi-agent research and **paper-trading-only** platform for Indian equities (NSE/BSE). The project is being rebuilt incrementally with deterministic risk controls, auditable decisions and testable data pipelines.

> **Operating rule:** this README is the durable project handoff. Update it whenever architecture, decisions, milestone status, validation results, risks, or next actions materially change. A new ChatGPT session should be able to resume from this file without requiring the user to copy an old conversation.

## 1. Project mission and non-negotiable boundaries

- Build a reliable multi-agent platform for Indian equities (NSE/BSE).
- Paper trading only during the current development phase.
- No live order placement; no agent receives direct broker order-placement capability.
- AI agents may research and propose. A deterministic risk engine is authoritative for paper-order approval.
- Missing, stale, malformed, or contradictory market data must fail closed.
- Zerodha is the intended eventual broker integration, initially read-only.
- Never commit credentials, API keys, access tokens, account statements, or personal data.
- Never merge to `main` without the user's explicit approval.

## 2. Collaboration and change-control workflow

| Role | Responsibility |
|---|---|
| User | Product owner; approves scope, financial assumptions, credentials, merges, and any future live-trading decision |
| ChatGPT | Architecture, requirements, risk policy, review, milestone tracking, and durable project handoff |
| Antigravity | Primary implementation environment; edits code and runs local checks |
| Claude Free | Optional independent reviewer; reviews GitHub commits and reports findings |

Working rules:
- Active engineering branch: `feature/reliable-foundation`.
- Do not work directly on `main`.
- Do not commit or push until the requested review/validation gate is complete and the user approves.
- Do not let multiple agents edit the same files concurrently.
- Keep changes focused by milestone; avoid unrelated refactors.
- Do not upload private reference videos or other unrelated personal material to GitHub.
- After each meaningful milestone, update this README with implementation status, test evidence, unresolved findings, and the next exact actions.
- Treat tool/agent reports as claims until verified from actual diffs, tests, and CI.

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

## 3. Repository and branch state

- Repository: [Evilfromblood/agentic-trading-lab](https://github.com/Evilfromblood/agentic-trading-lab)
- Active branch: `feature/reliable-foundation`
- Last previously confirmed implementation baseline: `3bfe105ac8ba09860a3f24059547cc8e7e7e2253` — `feat: add deterministic market data quality foundation`.
- `main` must remain untouched unless the user explicitly approves a merge.

### Important working-tree handoff (2026-11-01)

The user's Windows working copy contains local, **uncommitted M2a changes** in:
- `.github/workflows/ci.yml`
- `docs/DEVELOPMENT_PLAN.md`
- `src/agentic_trading/market_data/__init__.py`
- `src/agentic_trading/market_data/models.py`
- `src/agentic_trading/market_data/quality.py`
- `tests/test_market_data_models.py`
- `tests/test_market_data_quality.py`

These local M2a changes were not part of the previously confirmed remote baseline when this handoff was prepared. Do not assume they are committed or pushed. Check `git status` and `git log` before continuing.

The user also saw an untracked path named `cls`. Its contents and purpose have not yet been inspected. Do not delete it blindly. A generated `src/agentic_trading_lab.egg-info/` directory was also seen earlier; its removal was attempted, but verify current status.

## 4. Milestone status

### Milestone 1 — Reliability-first foundation

The initial feature foundation includes:
- Contribution and architecture documentation.
- Paper-only execution architecture decision.
- Deterministic risk engine and core approval/rejection tests.
- Python project metadata and GitHub Actions workflow.

The risk-engine local test suite previously passed 9 tests.

### Milestone 2 — Market data

M2 is deliberately split into two parts.

#### M2a — Market-data contracts and quality gate

**Status: implementation in local working copy; review/remediation pending; NOT approved or committed.**

The local implementation attempts to provide:
- Immutable candle model with Decimal price handling.
- Explicit open-time and close-time semantics; candle interval represented as half-open `[open_time, close_time)`.
- Explicit source provenance and retrieval timestamp; no fabricated retrieval time or default simulated source.
- Rejection of in-progress candles and retrieval before bar close.
- Staleness measured from bar close.
- OHLC geometry, positive price, volume, and timezone validation.
- Sequence validation for generators, duplicate observations, chronological ordering, and data gaps.
- CI lint coverage for market-data source and tests.

**Latest local validation evidence (user-provided terminal output):**
- Ruff on `src/agentic_trading/market_data`, `tests/test_market_data_models.py`, and `tests/test_market_data_quality.py`: passed.
- Full pytest with bytecode/cache disabled: **63 passed**.
- `python -m compileall -q src tests`: exit code 0.
- `git diff --check`: no whitespace errors; Git emitted LF-to-CRLF conversion warnings on Windows (warnings, not diff-check failures).

These checks apply to the user's local working copy at the time reported. They are not GitHub Actions results and do not establish Python 3.11 compatibility.

**Independent review findings from inspection of the local diffs; remediation required before M2a approval:**
1. `QualityIssue.details` uses a top-level `MappingProxyType`, but nested mappings/lists remain mutable. Implement recursive freezing and tests.
2. Intraday gap detection treats any one-day date transition as a normal overnight closure. A large gap into the next date can be missed. Distinguish legitimate session transitions from suspicious gaps; if calendar certainty is unavailable, emit `MARKET_CALENDAR_REQUIRED` rather than silently accepting.
3. `NSE_SESSION_OPEN` and `NSE_SESSION_CLOSE` are declared but not actually enforced by the current gap-detection logic.
4. Duplicate identity currently keys on timestamp only. Include exchange, symbol, interval, and UTC-normalized timestamp before comparing OHLCV.
5. Sequence validation needs stronger validation of malformed elements, missing attributes, invalid timestamp types, and timezone objects whose `utcoffset()` is `None`; malformed input should produce structured issues rather than unexpected crashes.
6. Validate `now` type/timezone and `max_staleness` type/non-negativity explicitly.
7. Make the contract explicit for retrieval timestamp versus candle close time. No incomplete/provenance-invalid candle may pass the authoritative quality gate.
8. Review test count and actual test diffs; do not rely only on agent summaries.

**M2a next actions:**
1. Remediate the findings above in the local working copy; do not commit/push yet.
2. Inspect the complete diffs for `models.py`, `quality.py`, tests, CI, and development plan.
3. Run Ruff, full pytest with cache disabled, forced compileall, and `git diff --check`.
4. Review `git status`; inspect the untracked `cls` file before deciding whether it is disposable.
5. Obtain explicit user approval before committing/pushing.
6. Push only to `feature/reliable-foundation`; verify GitHub Actions, especially Python 3.11.
7. Request an independent Claude audit of the resulting commit and resolve findings.

CI Ruff scope was changed locally to:
```yaml
- run: python -m ruff check src/agentic_trading/market_data tests/test_market_data_models.py tests/test_market_data_quality.py
```
This avoids making the new milestone fail on known pre-existing Ruff violations in `risk_engine.py` and `tests/test_risk_engine.py`. This is a temporary scoped check, not a permanent decision to abandon risk-engine lint coverage; establish and fix the repository-wide lint baseline separately.

#### M2b — Exchange calendar, corporate actions and adapters

**Status: not started.**

Planned scope:
- Provider adapters separated from normalized domain objects.
- Full NSE/BSE trading calendar, holidays, and special sessions.
- Corporate actions (splits, bonuses, dividends) and symbol changes.
- Deterministic fixtures and replayable market-data snapshots.

Do not claim full exchange-calendar correctness in M2a. Until M2b exists, ambiguous multi-day gaps must be surfaced as requiring calendar knowledge.

### Milestone 3 — Paper broker and ledger

Not started. Keep broker integration read-only until the architecture and safety gates explicitly authorize further scope.

## 5. Windows development environment

User's local repository path:
```text
C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab
```

Use the repository virtual environment explicitly because `python` may resolve to MSYS2 Python on PATH:
```powershell
.\.venv\Scripts\python.exe
```

Useful validation commands:
```powershell
.\.venv\Scripts\python.exe -m ruff check src/agentic_trading/market_data tests/test_market_data_models.py tests/test_market_data_quality.py
.\.venv\Scripts\python.exe -B -m pytest -v -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q -f src tests
git diff --check
git status --short
```

Local environment observed during M2a checks: Windows 11, Python 3.14.4. GitHub CI targets Python 3.11; verify compatibility through actual CI rather than assuming local success proves it.

## 6. Resume protocol for a new ChatGPT session

At the start of a resumed session:
1. Read this README first, then [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [CONTRIBUTING.md](CONTRIBUTING.md) as needed.
2. Ask the user for current `git status --short`, current branch, and latest commit if these are not already available. Do not assume the local working copy matches GitHub.
3. Continue from the earliest incomplete approval gate above; do not repeat completed work unnecessarily.
4. Preserve paper-only safety boundaries and never merge to `main` without explicit approval.
5. Update this README at the end of each meaningful work session so the next session has a reliable handoff.

## Safety boundary

**Live order placement is not implemented or authorized.** AI agents can generate research proposals only. A deterministic risk engine must approve every paper order. Zerodha integration remains read-only. Do not commit API keys, access tokens, account statements or personal data.

## Historical prototypes

- `agentic_trading_lab.zip`: initial US-market prototype.
- `agentic_trading_lab_v2_india.zip`: India-market hybrid-agent prototype.
- `agentic_trading_lab_v3_zerodha_readonly.zip`: read-only Zerodha connector prototype.

These are historical snapshots, not production-ready trading software. They are being preserved separately from the reliability-first rebuild.

## Local development

Python 3.11+:
```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

Provider and broker integrations are optional extras. Unit tests should not require network access or broker credentials.


## 7. Durable project memory

The `docs/project-memory/` directory is the detailed continuity record. Keep it current so a new ChatGPT conversation or another collaborator can resume without copying chat history.

- [Current state](docs/project-memory/CURRENT_STATE.md) — branch, commits, local/remote status, validation evidence.
- [Decision log](docs/project-memory/DECISION_LOG.md) — accepted architectural and workflow decisions.
- [Issues and risks](docs/project-memory/ISSUES_AND_RISKS.md) — open findings, severity, remediation requirements.
- [Next actions](docs/project-memory/NEXT_ACTIONS.md) — exact ordered continuation steps and commands.
- [Session log](docs/project-memory/SESSION_LOG.md) — chronological record of verified work.
- [Agent handoff](docs/project-memory/AGENT_HANDOFF.md) — operating instructions for ChatGPT, Antigravity, Claude, and human approval gates.

**Update discipline:** after every meaningful work session, update the relevant memory files and then refresh this README's concise status and links. Record facts and verified outcomes; distinguish local uncommitted work from remote commits and CI evidence. Never store credentials, tokens, personal account data, or secrets in project memory.
