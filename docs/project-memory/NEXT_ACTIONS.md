# Next Actions

Current priority: Milestone 2b — Market Data Ingestion and Provider Integration Foundation.

## Immediate sequence
1. M2a finalized, verified (106 tests passed, ruff clean, compileall clean), committed, and pushed to `feature/reliable-foundation`.
2. Implement Milestone 2b:
   - Define provider-independent ingestion interface (`MarketDataProvider`, `HistoricalDataRequest`).
   - Implement deterministic synthetic provider for NSE equities.
   - Implement provider adapter, raw data validation, and normalization into internal `Candle` model.
   - Route normalized data through M2a quality gate (`validate_candle`, `validate_candle_sequence`).
   - Add comprehensive tests for synthetic ingestion, error handling, provider failures, and quality validation.
3. Validate complete test suite and static checks.
4. Update durable documentation and prepare M2b report.

## Non-negotiable boundaries
- Work exclusively on `feature/reliable-foundation`. Do not merge into `main`.
- Paper-only architecture; no live broker connectivity or order execution.
- No hardcoded secrets, API keys, or live credentials.
- No destructive Git operations.
- Do not commit or push M2b without human approval.
