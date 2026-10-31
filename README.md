# Agentic Trading Lab

A reliability-first, multi-agent research and **paper-trading-only** platform for Indian equities (NSE/BSE). The project is being rebuilt incrementally with deterministic risk controls, auditable decisions and testable data pipelines.

## Current engineering branch

See [CONTRIBUTING.md](CONTRIBUTING.md) for the ChatGPT / Antigravity / Claude workflow, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system boundaries and [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) for milestones.

The `feature/reliable-foundation` branch currently introduces:
- A documented AI-assisted contribution protocol.
- A paper-only execution architecture decision.
- A deterministic, standard-library risk engine.
- Unit tests for core approval/rejection conditions.
- Python project metadata and a GitHub Actions CI workflow.

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
