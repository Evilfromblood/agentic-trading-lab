# Platform architecture

## Design objective
Build an auditable, India-market research and paper-trading platform. Reliability, reproducibility and capital preservation take precedence over trading frequency or model complexity.

## Logical components

1. **Market data adapters** — normalize instrument identifiers, timestamps, OHLCV, corporate actions and source metadata. Every observation carries source and observation time.
2. **Data quality gate** — reject missing, stale, duplicate, non-monotonic or impossible observations before analysis.
3. **Feature engine** — deterministic indicators and fundamentals with explicit lookback windows and warm-up handling.
4. **Analyst agents** — independent bull, bear and quantitative analyses. Agents return schema-validated proposals with evidence, assumptions, confidence and expiry.
5. **Decision aggregator** — records agreement/disagreement and produces a proposed action; it cannot submit orders.
6. **Risk engine** — deterministic, versioned policy. It is the sole authority that can approve or reject a proposed paper order.
7. **Execution adapter** — paper broker only. Broker interface is segregated from analysis and cannot be called directly by an LLM.
8. **Portfolio and ledger** — immutable order/fill/event history, positions, cash and mark-to-market snapshots.
9. **Observability** — structured logs, decision traces, model/version metadata and reproducible backtest runs.

## Trust boundaries
- LLM output is untrusted input. Parse against strict schemas and treat invalid output as rejection.
- Market data is untrusted input. Validate timestamps, prices, units and source quality.
- Broker credentials stay outside source control and are not needed for offline tests.
- Network access is disabled in unit tests; fixtures provide deterministic inputs.

## Execution invariant
The current release supports paper execution only. There must be no path from an analyst agent to a live broker order endpoint. A future live-trading proposal requires a separate threat model, explicit approval, kill switch, limits, monitoring and compliance review.

## First implementation milestones
- M0: development workflow, architecture and deterministic risk policy.
- M1: typed domain models, risk engine and unit tests.
- M2: market data normalization and data quality checks.
- M3: paper broker, ledger and reconciliation.
- M4: agent adapters and consensus; no execution permissions.
- M5: historical backtesting with realistic costs.
- M6: read-only broker visibility and paper-trading operations.
