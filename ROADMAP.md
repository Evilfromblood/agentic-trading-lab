# Roadmap

This roadmap describes intended work, not completed functionality. Priorities may change as the project is implemented.

## Milestone 0 — Public foundation
- [x] Publish an honest project overview and current limitations.
- [ ] Select and add an open-source licence.
- [ ] Add CI, formatting, linting, and a minimal test suite.
- [ ] Document supported Python versions and reproducible setup.

## Milestone 1 — Core research interfaces
- [ ] Define typed interfaces for market data, agents, portfolio state, and broker adapters.
- [ ] Add configuration validation and structured logging.
- [ ] Define a common research-result schema with source attribution and timestamps.
- [ ] Add unit tests with deterministic fixtures.

## Milestone 2 — Research agents
- [ ] Implement independent analyst agents with bounded responsibilities.
- [ ] Record prompts, model identifiers, input data references, and outputs for auditability.
- [ ] Add failure handling, timeouts, and model-provider abstraction.
- [ ] Make agent outputs explicitly non-executable research signals.

## Milestone 3 — Paper portfolio and risk
- [ ] Implement a deterministic paper broker and portfolio ledger.
- [ ] Model fees, slippage assumptions, and order lifecycle states.
- [ ] Add configurable position, exposure, and drawdown limits.
- [ ] Test edge cases and prevent accidental live-order pathways.

## Milestone 4 — Data and broker integrations
- [ ] Document data-source licensing, limitations, and freshness.
- [ ] Add market-data adapter contracts and validation.
- [ ] Keep broker account integrations read-only by default.
- [ ] Add secure local credential storage and token lifecycle tests.

## Milestone 5 — Release quality
- [ ] Add integration tests using mocked external services.
- [ ] Publish architecture and threat-model documentation.
- [ ] Add release notes and versioned installation instructions.
- [ ] Review dependencies, security posture, and operational safeguards.

## Non-goals for the current stage
- Live order placement.
- Financial advice or investment recommendations.
- Claims of profitability, predictive accuracy, or production readiness.
