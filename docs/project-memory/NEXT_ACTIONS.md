# Next Actions

Current priority: Milestone 4 (Time Machine Engine: historical sequential event clock, bar-by-bar progression, strategy backtesting driver, and reproducible Monte Carlo simulation). Milestones 2a, 2b, 2c, and 3 are verified.

## Immediate sequence
1. Baseline M2a committed (`1b7e582`) and pushed to `origin/feature/reliable-foundation`.
2. M2b Ingestion Foundation and Claude Batch 7 / 7b audit remediations committed (`f780f80`):
   - Zero-mutation guarantee for injected KiteConnect clients; in-memory token bypass for locked keyring backends; fail-closed `PermissionError` on all POST and session-mutation methods.
   - Pinned dependencies in `requirements.lock`, verified `requirements.lock` actively scanned by `detect-secrets==1.5.0`, and full test coverage at 85.02%.
   - Packaged and frozen audit bundle `m2b-remediated-batch7b-bundle.zip`.
3. M2c Cross-Market Foundation & Stored Replay Fixtures implemented and verified:
   - Currency isolation (`Currency.INR`, `Currency.USD`) and immutable `Money` dataclass with strict currency safety.
   - Cross-market `Instrument` and O(1) `InstrumentRegistry` with strict exchange-currency pairing (`NSE`/`BSE` -> INR, `NYSE`/`NASDAQ` -> USD).
   - `CorporateAction` handling and `adjust_candles_for_corporate_actions` with tick_size quantization (`ROUND_HALF_EVEN`) and cycle-safe `resolve_symbol_lineage`.
   - Tier-2 `StoredReplayFixtureProvider` and `save_replay_fixture` with SHA-256 payload integrity check via `hmac.compare_digest` and path-traversal prevention.
   - 24 adversarial tests in `tests/test_m2c_cross_market_foundation.py`. All 362 tests passing on Python 3.11 and Python 3.14 with 86.56% coverage.
4. M3 Append-Only Ledger, Multi-Currency Portfolio, Cost Models, Strategy Contracts, Risk Gate, Hardening Batches A & B, and Final Polish Pass (R1–R8) implemented and verified:
   - Point-in-time universe guards (`Instrument.is_active_on`, `InstrumentRegistry.get_as_of`) and corporate action look-ahead guards (`CorporateAction.announcement_date`).
   - Append-only `AccountingLedger` and immutable `LedgerEntry` with monotonic sequence IDs, causal timestamps, semantic sign invariants, non-abs fee computation, and total dividend tracking.
   - Statutory fee models (`IndiaEquityFeeModel`, `USEquityFeeModel`), `ZeroFeeModel`, and `BasisPointsSlippageModel` with true tick-grid quantization, always-adverse slippage (`ROUND_CEILING` on BUY, `ROUND_FLOOR` on SELL), positive price validation, and below-tick-size sell rejection.
   - Multi-currency `PortfolioEngine` preserving strict accounting conservation ($\text{Deposits} - \text{Withdrawals} + \text{Realized PnL} + \text{Dividends} - \text{Fees} = \text{Cash} + \text{Cost Basis of Open Positions}$), pre-populated ledger replay, per-position total cost basis tracking with exact zero residual drift (`Decimal("0")`) across partial/full exits, strictly positive fill price validation, realized PnL preservation across full exits, short-selling boundary with `InsufficientPositionError`, signed market value, SELL fee overdraft prevention, and `apply_dividend` API.
   - Strategy contracts: `SignalDirection`, `BarContext` with strict invariant validation (increasing timestamps, uniform intervals, positive OHLC, high/low bounds, non-negative volume, non-overlapping bars, causal look-ahead guard), `Signal`, `TradeProposal`, and pure technical indicators (`sma`, `ema`, `rsi` with 50-neutral on flat price series, `atr`).
   - Replay fixtures: `StoredReplayFixtureProvider` filtering strictly by symbol/exchange/interval, close-time slicing excluding in-progress bars, keyed HMAC-SHA256 authentication covering manifest metadata and payload, fixture identity verification (`manifest.fixture_id == self._fixture_id`), naive timestamp rejection, and non-finite constant blocking.
   - Authoritative deterministic proposal risk gate (`evaluate_trade_proposal`) enforcing currency matching, lot size alignment, position-aware SELL checks (`UNAUTHORIZED_SHORT`, `INSUFFICIENT_POSITION`), long-exit stop loss / take profit directional bounds, odd-lot full exit allowance without lot-size truncation, stop loss waiver on de-risking exits, kill-switch exit allowance during drawdown/daily loss, fail-closed validation for non-positive peak equity / entry price / stop loss / take profit / limit price, and exact `max_allowed_quantity`.
   - Zerodha connector: `ReadOnlyKiteConnect._request` aligned to kiteconnect signature, non-GET blocked before transport, and injected client `logout()` as no-op preserving caller client and keyring token.
   - 410 tests passing across the full suite on Python 3.11 and Python 3.14 with 87.40% coverage. Zero inline `#` comments.
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
