# AI Master Context — Agentic Trading Lab

Reconciled architectural reference, operating principles, product roadmap, and non-negotiable engineering constraints.

---

## 1. Product Vision & Operating Boundary
- **Core Vision:** Cross-market quantitative research and paper-trading simulation platform supporting Indian equities (NSE/BSE) and US equities (NYSE/NASDAQ) using a shared core and market-specific adapters.
- **Strictly Paper-Only:** Zero live order execution, zero real-money trading, and zero broker order-placement access. AI agents operate exclusively in research, proposal, and analysis roles; deterministic algorithms remain authoritative.
- **Dual Runtime Support:** Verified compatibility on both genuine Python 3.11 (production baseline) and Python 3.14 (forward-looking release).

---

## 2. Three Signature Capabilities

### 1. Fail-Closed Ingestion & Market Data Integrity
- Microsecond-precision, immutable domain models (`Candle`, `ExchangeCalendar`, `Instrument`, `CorporateAction`).
- Strict closed-world exchange calendars and intraday session grids for NSE, BSE, NYSE, and NASDAQ.
- Comprehensive quality gates rejecting gaps, future timestamps, stale records, malformed numeric inputs, and session violations.
- Backward/forward symbol lineage resolution with graph cycle detection and tick-quantized corporate action adjustment.
- Tier-2 stored replay fixtures verified via cryptographic SHA-256 digests (`hmac.compare_digest`) with path-traversal prevention.

### 2. Append-Only Multi-Currency Simulation & Time Machine
- Strictly append-only accounting ledger (`AccountingLedger`, `LedgerEntry`) enforcing monotonic sequence IDs and causal timestamps.
- Exact statutory transaction fee models:
  - India (`IndiaEquityFeeModel`): Brokerage caps, STT, exchange transaction fees, SEBI charges, stamp duty, and GST.
  - United States (`USEquityFeeModel`): Per-share commissions, SEC turnover fees, and FINRA TAF charges.
- Adverse slippage models (`BasisPointsSlippageModel`) quantized to instrument tick sizes.
- Multi-currency portfolio engine (`PortfolioEngine`, `PortfolioSnapshot`, `Position`) guaranteeing strict accounting conservation:
  $$\text{Deposits} - \text{Withdrawals} + \text{Realized PnL} - \text{Fees} = \text{Cash} + \text{Cost Basis of Open Positions}$$
- Point-in-time universe guards preventing survivorship bias (`Instrument.is_active_on`, `InstrumentRegistry.get_as_of`) and corporate action look-ahead bias (`CorporateAction.announcement_date`).

### 3. Authoritative Deterministic Risk Governance
- Clean contract separation between generative strategy intelligence and deterministic safety:
  - Strategies receive causal `BarContext` (failing closed with `ValueError` on any bar closing after `decision_time`).
  - Strategies emit non-binding directional `Signal` and structured `TradeProposal`.
- Deterministic proposal risk gate (`evaluate_trade_proposal`) evaluates proposals against `PortfolioRiskPolicy`:
  - Enforces currency isolation across instruments, entries, stops, and portfolio cash.
  - Validates positive lot-size multiples.
  - Enforces mandatory stop-loss presence and direction.
  - Enforces per-trade risk limits, single-instrument concentration caps, and total portfolio exposure ceilings.
  - Triggers daily loss limit stops and peak-to-trough drawdown circuit breakers.

---

## 3. Product Roadmap

1. **Milestone 2a — Normalized Candle Contracts & Authoritative Quality Gate:** (Completed, committed `1b7e582`)
2. **Milestone 2b — Fail-Closed Ingestion & Read-Only Broker Boundaries:** (Completed, committed `f780f80`)
3. **Milestone 2c — Cross-Market Foundation & Stored Replay Fixtures:** (Completed and verified)
4. **Milestone 3 — Append-Only Ledger, Multi-Currency Portfolio, Cost Models, Strategy Contracts & Risk Gate:** (Completed and verified)
5. **Milestone 4 — Time Machine Engine & Historical Simulation:** Sequential event clock, tick/bar event progression, backtesting driver, and reproducible Monte Carlo evaluation.
6. **Milestone 5 — Paper Trading Engine, Market Intelligence Agents & Analytics Dashboard.**

---

## 4. Non-Negotiable Engineering & Git Rules
- **Branch Discipline:** Active development stays on `feature/reliable-foundation`. Never commit, push, or merge to `main` without explicit human authorization.
- **Preserve Artifacts:** Preserve `m2a-review.patch`, test verification logs, and all prior audit bundle ZIP archives.
- **Code Cleanliness:** Domain models and test suites must have zero inline `#` comments and zero extraneous boilerplate.
- **Fail-Closed Principle:** Reject missing, stale, ambiguous, or out-of-order data immediately rather than guessing or interpolating.
- **Immutability & Decimal Precision:** Financial amounts and prices are represented using immutable `Money` and `Decimal`; floats are strictly rejected in financial calculations.
