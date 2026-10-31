# Development plan

## Milestone 0 — Engineering foundation
- [x] Define AI-assisted contribution and review workflow.
- [x] Record paper-only execution boundary.
- [x] Add deterministic risk-engine baseline and unit tests.
- [ ] Add CI and make the first branch green.
- [ ] Restore and version the three historical prototype snapshots.

## Milestone 1 — Domain and risk controls
- [ ] Define canonical instrument, candle, signal, proposal, order, fill and position models.
- [ ] Add market-data freshness and integrity validation.
- [ ] Add portfolio-wide exposure, concentration and open-order checks.
- [ ] Add currency-aware cash and equity accounting.
- [ ] Add property-based tests for risk invariants.

## Milestone 2 — Market data
- [ ] Separate provider adapters from normalized domain objects.
- [ ] Record source, exchange, timezone, retrieval time and bar close time.
- [ ] Handle NSE holidays, sessions, corporate actions and symbol changes.
- [ ] Add deterministic fixtures and replayable data snapshots.

## Milestone 3 — Paper broker and ledger
- [ ] Implement order lifecycle and partial fills.
- [ ] Model brokerage, STT, GST, exchange charges and stamp duty by instrument/segment.
- [ ] Make ledger events append-only and reconcile positions/cash.
- [ ] Add restart/recovery tests.

## Milestone 4 — Agent research
- [ ] Define strict JSON schemas and prompt/version tracking.
- [ ] Run bull, bear and quant agents independently.
- [ ] Add evidence citations, uncertainty and stale-data rejection.
- [ ] Add disagreement-aware aggregation; no agent has execution authority.

## Milestone 5 — Backtesting
- [ ] Prevent look-ahead and survivorship bias.
- [ ] Include costs, slippage, liquidity and realistic order timing.
- [ ] Use walk-forward and out-of-sample evaluation.
- [ ] Report drawdown, volatility, Sharpe, turnover and benchmark comparison.

## Milestone 6 — Operations
- [ ] Read-only broker reconciliation.
- [ ] Paper-trading dashboard, alerting and audit exports.
- [ ] Security review and operational runbooks.

A milestone is complete only when its acceptance criteria are testable, automated checks pass, and the changes have independent review.
