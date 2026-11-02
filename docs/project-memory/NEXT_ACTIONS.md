# Next Actions

Current priority: finish M2b remediation and independent verification. The first major product milestone after the reliable cross-market data foundation is Time Machine.

## Immediate sequence
1. Triage Claude A's corrected M2b audit (snapshot SHA-256: `15b9657b7b636a5a196b3c99842aac2322b0668b2b9dd1ac59d28abbf53972e1`).
2. Authorise a narrowly scoped Antigravity remediation batch for confirmed defects; record unresolved market-data policy decisions rather than inventing them.
3. Run full tests on Python 3.11 and 3.14, Ruff on source and tests, compile checks, and targeted adversarial regression probes.
4. Produce a new immutable audit bundle and SHA-256; ask an independent reviewer to verify the remediation.
5. Close M2b only when acceptance criteria and review findings are satisfied.
6. M2c: establish cross-market instrument identity, exchange-specific sessions/calendars, historical data adapters, INR/USD representation and data provenance for NSE/BSE and NYSE/NASDAQ.
7. M3: define strategy and deterministic simulation contracts, portfolio/cash accounting, sizing, transaction costs, slippage and risk controls.
8. M4: build Time Machine backtesting and reproducible Monte Carlo simulation.
9. Later: paper trading engine, market/news intelligence agents and analytics dashboard.

## Review/remediation loop
Claude independent verification -> ChatGPT triage and scoped technical direction -> Antigravity implementation and regression tests -> independent verification of the new snapshot. Avoid overlapping audits of unchanged code when a focused remediation cycle is more efficient.

## Product and safety constraints
- Shared core with market-specific adapters; do not fork the platform into separate India and US implementations.
- Strictly paper-only: no real-money execution, no agent broker order-placement access, no autonomous live trading.
- AI agents research and propose; deterministic risk controls remain authoritative.
- Fail closed on missing, stale, malformed or contradictory data.
- Preserve provenance, assumptions and simulation reproducibility.
- No live broker execution milestone is authorised.

## Git and change-control constraints
- Work on `feature/reliable-foundation`; never merge to `main` without explicit approval.
- Preserve all uncommitted work and `m2a-review.patch`.
- No destructive Git operations.
- Do not commit or push implementation changes without explicit user approval.
