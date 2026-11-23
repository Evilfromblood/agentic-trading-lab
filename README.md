# Agentic Trading Lab

**A reliability-first, multi-agent equity research and paper-trading workstation for Indian and US equities.**

Agentic Trading Lab explores how autonomous AI agents and quantitative market-data engines collaborate to conduct multi-perspective equity research, generate auditable trade proposals, and simulate portfolio execution under strict deterministic risk controls.

> **Safety boundary:** This repository is strictly for research and simulated paper trading. All trading execution is hardcoded to paper trading (`paper_only: Literal[True] = True`). AI agents may analyze data and submit trade proposals, but the deterministic Proposal Risk Gate is strictly authoritative for approvals and sizing. Broker connectors (including Zerodha Kite Connect) are strictly read-only; no live order placement is supported or authorized. Do not use this software for live real-money execution.

---

## 1. Core Architecture & Capabilities

1. **7-Agent AI Research Desk (`src/agentic_trading/agents/`):**
   - **Data Analyst:** Analyzes financial ratios, balance sheets, and fundamental filings.
   - **News Analyst:** Scans real-time financial headlines and identifies catalysts and earnings blackout events.
   - **Market Analyst:** Evaluates technical structure, moving averages, momentum, and volume.
   - **Opportunity Scout:** Identifies market setups across Indian (`NSE`, `BSE`) and US (`NYSE`, `NASDAQ`) instruments.
   - **Strategist:** Formulates actionable trade plans with explicit entry prices, stop losses, and profit targets.
   - **Risk Guardian:** Red-teams proposals against portfolio exposure limits, sector caps, and volatility thresholds.
   - **Desk Orchestrator:** Synthesizes multi-agent consensus, logs rationale, and forwards proposals to the risk gate.

2. **Deterministic Proposal Risk Gate (`src/agentic_trading/risk_engine/`):**
   - Mathematically verifies all orders before paper execution.
   - Enforces currency isolation (`Currency.INR`, `Currency.USD`), lot size quantization, directional stop loss/take profit checks, drawdown circuit breakers, and event blackout rules.

3. **Multi-Currency Append-Only Ledger & Portfolio Engine (`src/agentic_trading/simulation/`):**
   - Preserves exact double-entry accounting conservation ($\text{Deposits} - \text{Withdrawals} + \text{Realized PnL} + \text{Dividends} - \text{Fees} = \text{Cash} + \text{Cost Basis}$).
   - Models statutory exchange fees, turnover taxes, and adverse slippage quantization.

4. **SSRF-Hardened Feed & Context Adapters (`src/agentic_trading/market_data/`):**
   - `ReadOnlyMarketFeedBridge` & `ReadOnlyContextBridge` enforce strict HTTPS schemes, host allowlists, no-redirect socket handlers, and XXE injection defenses.
   - Operates in 3 deterministic modes: `"synthetic"`, HMAC-SHA256 authenticated `"cache"`, and `"live"` external feeds.

5. **Local Ollama Loopback & LLM Client (`src/agentic_trading/agents/llm_client.py`):**
   - Provides private, zero-data-leakage local LLM execution via Ollama (`deepseek-r1`, `llama3.2`, `mistral`, etc.) with automatic failover to deterministic stubs.

6. **Quantitative Backtesting Engine (`src/agentic_trading/time_machine/`):**
   - Point-in-time universe selection, corporate action adjustment, Monte Carlo simulation, and equity curve generation.

7. **FastAPI Web Workstation & Dashboard (`src/agentic_trading/api/dashboard.py`):**
   - Local interactive single-page dashboard with cycle history inspection, real-time agent chat traces, `<canvas>` candlestick charts with AI buy/sell overlays, interactive trade plan execution, active position management, backtest equity curve visualization, and an SQLite-backed trading lessons manager.

---

## 2. Quick Start & Local Development

### Requirements
- **Python:** 3.11 or 3.14 (fully supported and tested)
- **OS:** Windows, macOS, or Linux

### Installation

```bash
# Clone the repository
git clone https://github.com/Evilfromblood/agentic-trading-lab.git
cd agentic-trading-lab

# Create and activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies with development and testing tools
pip install -e ".[dev]"
```

### Launching the Workstation

Start the local FastAPI server:

```powershell
python -m uvicorn agentic_trading.api.app:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser to:
- **Interactive Dashboard:** `http://127.0.0.1:8000/`
- **Swagger API Docs:** `http://127.0.0.1:8000/docs`

### Running the Test Suite

The repository maintains an adversarial test suite with over 515 tests and $\ge 88\%$ code coverage across Python 3.11 and Python 3.14:

```powershell
# Run full test suite with coverage
pytest --cov=src --cov=v3-zerodha/src --cov-fail-under=85

# Run code linters and static checks
ruff check src tests v3-zerodha/src
```

---

## 3. Configuration & Secrets

- Copy `v3-zerodha/.env.example` to `.env` if configuring the experimental read-only Kite Connect adapter.
- **Never commit `.env` files, API keys, access tokens, or account credentials.**
- Pre-commit scanning via `detect-secrets` protects the repository baseline.
- All local HTTP endpoints and callback servers are bound strictly to `127.0.0.1`.

---

## 4. Documentation & Project Memory

The `docs/` directory maintains comprehensive records of the platform's architectural evolution:
- [Roadmap](ROADMAP.md) — Multi-milestone platform progression.
- [Security Policy](SECURITY.md) — Vulnerability reporting, SSRF defense, and credential handling.
- [Contributing Guidelines](CONTRIBUTING.md) — Collaboration roles, change protocols, and definition of done.
- [Architecture Overview](docs/ARCHITECTURE.md) — System boundaries and module design.
- [Audit Brief](AUDIT_BRIEF.md) — Implementation verification, test matrices, and regression evidence.
- [Project Memory](docs/project-memory/) — Complete continuity records (`CURRENT_STATE.md`, `DECISION_LOG.md`, `NEXT_ACTIONS.md`, `SESSION_LOG.md`).

---

## 5. Disclaimer & License

This project is provided for educational and research purposes only, without warranties of any kind. It does not constitute investment, financial, legal, or tax advice. You are solely responsible for evaluating the software and data sources. Never connect experimental software to a live real-money broker workflow.

Licensed under default repository copyright. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
