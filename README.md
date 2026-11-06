# Agentic Trading Lab

**An experimental, open-source project for multi-agent AI equity research and paper trading in Indian markets.**

Agentic Trading Lab explores how multiple AI agents and market-data tools can support structured equity research, risk analysis, and simulated portfolio decisions. The project is under active development and is not production-ready.

> **Safety first:** This repository is for research and paper-trading experimentation. It does not provide investment advice. The inspected Zerodha connector exposes read-only account methods; live order placement is not implemented. Do not use this project to make real-money trading decisions.

## Project status

- **Stage:** Early development / experimental
- **Primary market focus:** Indian equities (NSE/BSE)
- **Trading mode:** Paper trading / research
- **Broker integration:** Experimental, read-only Kite Connect connector in the v3 folder
- **Production readiness:** Not production-ready; interfaces, setup steps, and components may change

## Repository layout

```text
.
├── v1/
│   └── README.md
├── v2-india/
│   └── README.md
├── v3-zerodha/
│   ├── .env.example
│   ├── README.md
│   ├── pyproject.toml
│   └── src/
│       └── agentic_trading/
│           └── zerodha_connector.py
├── .gitignore
└── README.md
```

The version directories document the project's evolution. Some earlier versions currently contain documentation only; their complete runnable implementations are not present in this repository snapshot. The v3 directory contains an initial connector and project configuration, but its documented application entry points are not all present yet. Treat it as an incomplete development scaffold.

## Development direction

1. Establish a reproducible Python project structure and configuration.
2. Implement independent research agents behind clear interfaces.
3. Add reliable market-data adapters with explicit source and data-quality notes.
4. Build a deterministic paper broker and portfolio ledger.
5. Add portfolio-level risk checks and auditable decision records.
6. Integrate broker account data in read-only mode, with secure local credential handling.
7. Add automated tests, documentation, and repeatable development workflows.

See [ROADMAP.md](ROADMAP.md) for planned milestones.

## Getting started

There is not yet a complete end-to-end application entry point in this repository. The v3 folder includes a Python project configuration and an experimental read-only connector, but the full application described in its roadmap is not implemented. Do not assume that `pip install -e .` or the documented web callback can launch a complete trading application yet.

Python 3.11 or newer is the intended baseline for the v3 work.

## Configuration and secrets

- Copy `v3-zerodha/.env.example` to a local `.env` file when implementing the v3 configuration.
- Never commit `.env`, API keys, API secrets, access tokens, account identifiers, or personal account data.
- Use test credentials only where a provider offers an appropriate test environment.
- Keep local authentication callbacks bound to `127.0.0.1`; do not expose them publicly.
- Rotate any credential immediately if it is accidentally committed.

## Data, risk, and limitations

- Historical or third-party market data may be delayed, incomplete, adjusted, or unsuitable for execution.
- Yahoo Finance data is used in the earlier project descriptions and is not exchange-grade market data.
- A broker's read-only API connection is not a sandbox for order execution.
- Paper-trading results do not represent actual fills, slippage, liquidity, fees, taxes, or future performance.
- Risk controls are software safeguards, not guarantees against loss.

## Contributing

Contributions, bug reports, documentation improvements, and architecture feedback are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before submitting work.

## Disclaimer

This project is provided for educational and research purposes only, without warranties of any kind. It is not financial, investment, legal, or tax advice. You are responsible for evaluating the software, data sources, and applicable broker terms before use. Never connect experimental software to a live trading workflow.

## License

No open-source licence has been selected for this repository yet. Until a licence is added, the default copyright rules apply; do not assume that the code may be reused, modified, or redistributed.
