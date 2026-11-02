# Development Plan

## Product direction (accepted 2026-11-03)

Build one Agentic Trading Lab platform supporting:
- India: NSE and BSE.
- United States: NYSE and NASDAQ.

Extend the existing codebase. Use a shared domain, strategy, simulation and risk core with market-specific adapters for instruments, sessions, calendars, currencies, data and transaction costs.

**First major product priority:** Time Machine — historical backtesting and reproducible Monte Carlo simulation — after M2b and the cross-market data/strategy foundations are reliable.

**Safety boundary:** Strictly paper-only. No real-money execution, no autonomous live trading and no agent access to broker order-placement APIs. AI agents may research and propose; deterministic risk controls remain authoritative. Missing, stale, malformed or contradictory data fails closed.

## Current execution order

### M2b — Market data ingestion and provider reliability (in progress; audit remediation)
- [ ] Complete independent review remediation.
- [ ] Validate provider provenance, strict raw-data normalization and immutable result contracts.
- [ ] Validate interval grid, session membership, overlaps and session-truncated bars.
- [ ] Validate historical retrieval timestamps and live freshness boundaries.
- [ ] Validate historical coverage semantics and calendar limitations.
- [ ] Verify Python 3.11/3.14, full tests, Ruff, compile checks and adversarial regressions.
- [ ] Produce a new frozen audit bundle and pass independent remediation verification.

### M2c — Cross-market data and instrument foundation
- [ ] Shared market/exchange/instrument abstractions.
- [ ] NSE/BSE and NYSE/NASDAQ instrument identity and symbol mapping.
- [ ] Exchange-specific sessions, holidays and special-session modelling.
- [ ] Historical data adapters and source provenance.
- [ ] INR/USD-aware representation and currency conversion boundaries.
- [ ] Corporate-action and adjusted/unadjusted data semantics where supported.
- [ ] Provider-specific incomplete-bar and no-trade interval contracts.

### M3 — Strategy and deterministic simulation foundation
- [ ] Strategy configuration and versioned entry/exit rules.
- [ ] Deterministic candle-by-candle simulation contracts.
- [ ] Portfolio, cash, position sizing and exposure accounting.
- [ ] Transaction costs, taxes/fees by market and instrument, slippage and gap assumptions.
- [ ] Deterministic portfolio-level risk controls.
- [ ] Validated market-data-to-simulation pipeline; no look-ahead or survivorship leakage.

### M4 — Time Machine (first major product milestone)
- [ ] Select market, exchange, instrument and historical period.
- [ ] Configure and run strategies over historical data.
- [ ] Reproducible Monte Carlo runs with recorded seeds and assumptions.
- [ ] Conservative handling when stop and target are both touched within one candle.
- [ ] Model transaction costs, slippage, position sizing and incomplete sessions.
- [ ] Report expectancy, average R, win rate, drawdown, exposure and return distributions.
- [ ] Preserve data, strategy, configuration and seed provenance for reproducibility.
- [ ] Present uncertainty and limitations; simulations are not predictions or guarantees.

### M5 — Paper trading engine
- [ ] Simulated order lifecycle, fills and portfolio ledger.
- [ ] Deterministic risk approval before simulated execution.
- [ ] Restart/recovery, reconciliation and audit trail.
- [ ] No real broker order-placement connectivity.

### M6 — Market intelligence and multi-agent research
- [ ] Market scanner and instrument research.
- [ ] News, earnings and event analysis with source provenance.
- [ ] Strategy, entry/exit and portfolio-risk research agents.
- [ ] Agents can produce analysis and proposals only; no execution authority.

### M7 — Analytics and decision dashboard
- [ ] Cross-market portfolio and strategy analytics.
- [ ] Backtest and Monte Carlo visualisations.
- [ ] Paper-trading performance and data-quality views.
- [ ] Audit exports and research history.

## Deferred / excluded
- Real-money trading and live broker order placement.
- Autonomous agent execution.
- Unrestricted broker permissions.
- Separate duplicated India and US platforms.
- News-driven live execution before the Time Machine and risk foundations are validated.

## Historical plan note
Earlier milestone labels and sequencing below this point were superseded by the accepted product direction above. Historical completed work and decisions should not be silently rewritten.
