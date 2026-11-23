# ADR 0001: Paper-only execution

- Status: Accepted
- Date: 2026-11-01

## Context
This project is an educational and experimental AI-assisted trading platform. Early prototypes contain model-generated trade ideas and a read-only Zerodha connector, but they have not been validated for real capital.

## Decision
All executable trading remains paper-only. Broker integration must be read-only until a separate explicit owner-approved design decision. The deterministic risk engine must approve every proposed paper order.

## Consequences
- No live order-placement methods or API routes are included in the current architecture.
- Backtests and paper results must be reported with fees, slippage and limitations.
- AI outputs cannot directly trigger execution.
- Any future live capability requires a new ADR, security review, operational safeguards and explicit approval.
