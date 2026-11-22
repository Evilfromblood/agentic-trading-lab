# Next Actions

Current priority: Milestone 5 (Paper Trading Engine & 7-Agent AI Research Desk) is complete and verified. Next step is independent verification / packaging, followed by Milestone 6 (Live Web Dashboard & Visual Monitoring). Milestones 2a, 2b, 2c, 3, 4, and 5 are verified.

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
4. M3 Append-Only Ledger, Multi-Currency Portfolio, Cost Models, Strategy Contracts, Risk Gate, Hardening Batches A & B, Final Polish Pass (R1–R8), and D1–D3 Hardening implemented and verified:
   - Point-in-time universe guards (`Instrument.is_active_on`, `InstrumentRegistry.get_as_of`) and corporate action look-ahead guards (`CorporateAction.announcement_date`).
   - Append-only `AccountingLedger` and immutable `LedgerEntry` with monotonic sequence IDs, causal timestamps, semantic sign invariants, non-abs fee computation, and total dividend tracking.
   - Statutory fee models (`IndiaEquityFeeModel`, `USEquityFeeModel`), `ZeroFeeModel`, and `BasisPointsSlippageModel` with true tick-grid quantization, always-adverse slippage (`ROUND_CEILING` on BUY, `ROUND_FLOOR` on SELL), positive price validation, and below-tick-size sell rejection.
   - Multi-currency `PortfolioEngine` preserving strict accounting conservation ($\text{Deposits} - \text{Withdrawals} + \text{Realized PnL} + \text{Dividends} - \text{Fees} = \text{Cash} + \text{Cost Basis of Open Positions}$), unified position mutation via `_apply_trade_to_position` across live fills and ledger replay, per-position total cost basis tracking with exact zero residual drift (`Decimal("0")`) across multi-lot partial/full exits and flips, strictly positive fill price validation, realized PnL preservation across full exits, short-selling boundary with `InsufficientPositionError`, signed market value, SELL fee overdraft prevention, and `apply_dividend` API.
   - Strategy contracts: `SignalDirection`, `BarContext` with strict invariant validation (increasing timestamps, uniform intervals, positive OHLC, high/low bounds, non-negative volume, non-overlapping bars, causal look-ahead guard), `Signal`, `TradeProposal`, and pure technical indicators (`sma`, `ema`, `rsi` with 50-neutral on flat price series, `atr`).
   - Replay fixtures: `StoredReplayFixtureProvider` filtering strictly by symbol/exchange/interval, close-time slicing excluding in-progress bars, keyed HMAC-SHA256 authentication covering manifest metadata and payload, fixture identity verification (`manifest.fixture_id == self._fixture_id`), naive timestamp rejection, non-finite constant blocking, and recursive non-finite validation across nested structures.
   - Authoritative deterministic proposal risk gate (`evaluate_trade_proposal`) enforcing currency matching, lot size alignment, position-aware SELL checks (`UNAUTHORIZED_SHORT`, `INSUFFICIENT_POSITION`), long-exit stop loss / take profit directional bounds, odd-lot full exit allowance without lot-size truncation, stop loss waiver on de-risking exits, kill-switch exit allowance during drawdown/daily loss, fail-closed validation for non-positive peak equity / entry price / stop loss / take profit / limit price, and exact `max_allowed_quantity`.
   - Zerodha connector: `ReadOnlyKiteConnect._request` aligned to kiteconnect signature, non-GET blocked before transport, and injected client `logout()` as no-op preserving caller client and keyring token.
   - 413 tests passing across the full suite on Python 3.11 and Python 3.14 with 87.27% coverage. Zero inline `#` comments.
5. M4 Time Machine implemented and hardened (ADR-026, ADR-027):
   - Cryptographically verifiable experiment manifests with keyed HMAC-SHA256 and fail-closed integrity checks.
   - Strictly causal backtest execution with next-open entry, risk gate sizing, protective stops with gap-open adverse slippage, delisting liquidation, point-in-time corporate action handling, and exact-zero accounting conservation residual check.
   - Walk-forward validation with isolated train/test splits and non-overlapping OOS windows.
   - Seeded Monte Carlo bootstrap with graceful zero-trade handling and deterministic ruin/drawdown quantiles.
   - 441 tests passing across the full suite on Python 3.11 and Python 3.14 with 88.54% coverage. Zero inline `#` comments.
6. M5 Paper Trading Engine & 7-Agent AI Research Desk implemented and verified (ADR-028):
   - Independent hardware-like `KillSwitch` checking env var and filesystem sentinel file in O(1).
   - `PaperBroker` with idempotent deterministic order IDs, kill switch checks, market hours checks, adverse slippage and statutory fee execution, and daily reconciliation asserting exact zero conservation residual.
   - Authoritative risk gate extended with sector concentration limits (`SECTOR_LIMIT_EXCEEDED`) and corporate event blackout (`EVENT_BLACKOUT`).
   - 7-Agent AI Research Desk: strict JSON schema `AgentEnvelope` with input hashing and retries, framework-agnostic `LLMClient` with deterministic stubs, 3-tier memory (`WorkingState`, append-only SQLite `DecisionLog`, read-only `HumanLessonsStore`), Market Analyst, Data Analyst with filing staleness checks, News Analyst with prompt injection containment and blackout enforcement, Opportunity Scout with shortlist capping, Strategist with deterministic math verification of trade proposals, Daily Reporter EOD executive summary, and 4-stage pipeline `TradingDeskOrchestrator`.
   - 453 tests passing across the full suite on Python 3.11 and Python 3.14 with 88.04% coverage. Zero inline `#` comments.
7. Next: Milestone 6 (Live Web Dashboard & Visual Monitoring), strategy optimization, and live feed paper testing.

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
