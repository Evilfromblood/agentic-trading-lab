# Next Actions

Current priority: Milestone 3 (Strategy & deterministic simulation contracts, portfolio/cash accounting, sizing, transaction costs, slippage, and risk controls). M2a, M2b, and M2c are verified.

## Immediate sequence
1. Baseline M2a committed (`1b7e582`) and pushed to `origin/feature/reliable-foundation`.
2. M2b Ingestion Foundation and Claude Batch 7 / 7b audit remediations committed (`f780f80`):
   - Zero-mutation guarantee for injected KiteConnect clients; in-memory token bypass for locked keyring backends; fail-closed `PermissionError` on all POST and session-mutation methods.
   - Pinned dependencies in `requirements.lock`, verified `requirements.lock` actively scanned by `detect-secrets==1.5.0`, and full test coverage at 85.02%.
   - Packaged and frozen audit bundle `m2b-remediated-batch7b-bundle.zip`.
3. M2c Cross-Market Foundation & Stored Replay Fixtures implemented and verified in working tree:
   - Currency isolation (`Currency.INR`, `Currency.USD`) and immutable `Money` dataclass with strict currency safety.
   - Cross-market `Instrument` and O(1) `InstrumentRegistry` with strict exchange-currency pairing (`NSE`/`BSE` -> INR, `NYSE`/`NASDAQ` -> USD).
   - `CorporateAction` handling and `adjust_candles_for_corporate_actions` with tick_size quantization (`ROUND_HALF_EVEN`) and cycle-safe `resolve_symbol_lineage`.
   - Tier-2 `StoredReplayFixtureProvider` and `save_replay_fixture` with SHA-256 payload integrity check via `hmac.compare_digest` and path-traversal prevention.
   - 24 adversarial tests in `tests/test_m2c_cross_market_foundation.py`. All 362 tests passing on Python 3.11 and Python 3.14 with 86.56% coverage.
4. M3: define strategy and deterministic simulation contracts, portfolio/cash accounting, sizing, transaction costs, slippage and risk controls.
5. M4: build Time Machine backtesting and reproducible Monte Carlo simulation.
6. Later: paper trading engine, market/news intelligence agents and analytics dashboard.

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
