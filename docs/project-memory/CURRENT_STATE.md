# Current Project State

Last updated: 2026-11-23

## Product direction
- Markets: India (NSE/BSE) and United States (NYSE/NASDAQ).
- Approach: extend the existing Agentic Trading Lab codebase using a shared core and market-specific adapters.
- First major product priority after the data foundation: Time Machine (historical backtesting and reproducible Monte Carlo simulation).
- Product remains strictly paper-only. No real-money execution or agent access to broker order-placement APIs.

## Repository
- Repository: Evilfromblood/agentic-trading-lab
- Active development branch: `feature/reliable-foundation`
- Baseline commit: `1b7e5829474239495163da1d2d3349eb35ca9744` — `feat: complete market data quality foundation`.
- Do not merge to `main` without explicit user approval.
- Treat the local working tree and GitHub branch as separate states; verify both before editing or synchronising.

## Local working copy state
The working tree has local M2b modifications for the market data ingestion foundation and Claude audit remediation Batches 1 through 7:
- `src/agentic_trading/market_data/__init__.py` (exports provider, adapter, pipeline interfaces, `ExchangeSession`, `CoverageStatus`, `ExchangeCalendar`, `US_EASTERN`, `get_exchange_timezone`)
- `src/agentic_trading/market_data/models.py` (authoritative `ExchangeCalendar` completeness contract: contradiction rejection for trading_days/holidays overlap and special session conflicts; complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed; `is_verified_trading_day` and `is_verified_non_trading_day` strictly distinguish verified vs unverified dates across NSE, BSE, NYSE, and NASDAQ; docstring aligned with completeness contract)
- `src/agentic_trading/market_data/quality.py` (session-aware cross-exchange mismatch checks `EXCHANGE_MISMATCH`; calendar holiday candle rejection `OUTSIDE_SESSION`; calendar-aware gap detection; D1/W1/MN1 grid anchor validation; sparse sequence handling via `allow_sparse`; specific exception handling eliminating BLE001)
- `src/agentic_trading/market_data/provider.py` (multi-exchange synthetic provider; dynamic synthetic close time calculation with calendar-month MN1 boundaries; specific exception handling)
- `src/agentic_trading/market_data/adapters.py` (normalization, direct Decimal handling, strict whitespace-padded string rejection, explicit bytes rejection, identity-less support)
- `src/agentic_trading/market_data/ingestion.py` (exact failure coverage and error codes: `MARKET_CALENDAR_REQUIRED` when calendar evidence is incomplete or required, `TRUNCATED_COVERAGE` when intermediate trading days are missing without calendar evidence; fail-closed coverage contracts)
- `v3-zerodha/src/agentic_trading/zerodha_connector.py` (Batch 7 & 7b redesign: `_target` completely removed from slots; `__slots__ = ("__weakref__",)` only; wrapped client held strictly in closure-encapsulated `WeakKeyDictionary` with `(client, injected)` tuple; `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession` blocked with `PermissionError` in `__getattribute__`; bound allowlisted read methods returned via `types.MethodType` ensuring `method.__self__ is wrapper`; caller-supplied `KiteConnect` client instances remain 100% unmutated across `_require_session()` and `logout()`; unauthenticated injected clients raise `KiteConfigurationError` without mutation; `order_margins`, `basket_order_margins`, `get_virtual_contract_note`, session mutation methods, and `complete_login` fail closed with `PermissionError` before transport; in-memory token bypasses keyring for locked keyrings; keyring backend errors caught cleanly as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`)
- `.github/workflows/ci.yml` (blocking secret scanning via pinned `detect-secrets==1.5.0` scanning `requirements.lock`; stable Python 3.14 matrix entry; blocking `pip-audit`; installation from `requirements.lock` and `[dev,zerodha-readonly]`; coverage command enforcing `--cov-fail-under=85`)
- `.secrets.baseline` (UTF-8 secret scanning baseline pinned to version 1.5.0 with 0 detected leaks; removed `is_lock_file` filter so `requirements.lock` is scanned; anchored exclusion regex excluding only exact generated/cache directories without masking `.github` or `.gitlab-ci.yml`)
- `pyproject.toml` (Ruff configuration selecting `F, E4, E7, E9, B, BLE, I`, dev dependencies `pytest-cov>=5.0`, optional dependency `requests>=2.32.0`, pythonpath including `src` and `v3-zerodha/src`)
- `src/agentic_trading/market_data/instruments.py` (M2c/M3: Currency enum for INR/USD, CurrencyMismatchError, immutable Money dataclass with strict arithmetic, AssetClass enum, Instrument model enforcing strict exchange-currency pairing and positive tick_size, point-in-time listed/delisted date survivorship guards, InstrumentRegistry with duplicate prevention, O(1) resolution, and get_as_of/list_active_on)
- `src/agentic_trading/market_data/corporate_actions.py` (M2c/M3: CorporateAction model with announcement_date look-ahead validation; resolve_symbol_lineage with iterative three-color cycle detection supporting >1500 hops; adjust_candles_for_corporate_actions with as_of_date look-ahead filtering, corporate action deduplication, tick_size quantization, and inverse volume scaling)
- `src/agentic_trading/market_data/replay_fixtures.py` (M2c/M3: FixtureManifest with SHA-256 payload digest; save_replay_fixture with canonical JSON serialization, recursive non-finite float/Decimal rejection across nested mappings and sequences, and path-traversal prevention; StoredReplayFixtureProvider with cryptographic verification via keyed HMAC-SHA256, fixture_id binding, parse_constant constant rejection, naive timestamp rejection, and deterministic window filtering)
- `src/agentic_trading/simulation/costs.py` (M3: statutory transaction fee models IndiaEquityFeeModel for NSE/BSE and USEquityFeeModel for NYSE/NASDAQ, ZeroFeeModel, and BasisPointsSlippageModel with true tick-grid quantization, always-adverse ceiling/floor slippage direction, strictly positive price validation, and below-tick-size sell rejection)
- `src/agentic_trading/simulation/portfolio.py` (M3: multi-currency PortfolioEngine, Position, and PortfolioSnapshot enforcing strict accounting conservation, unified position mutation via _apply_trade_to_position across apply_fill and _replay_ledger, per-position total cost basis tracking with exact zero residual drift across partial/full exits and flips, strictly positive fill price validation, realized PnL preservation across full exits, short-selling boundary with InsufficientPositionError, signed holdings value, SELL fee overdraft prevention, and apply_dividend API)
- `src/agentic_trading/strategy/contracts.py` (M3: SignalDirection, BarContext causal look-ahead guard rejecting future bar closes and non-overlapping bar validation, Signal, TradeProposal, and Strategy protocol)
- `src/agentic_trading/risk_engine/proposal_gate.py` (M3: authoritative evaluate_trade_proposal and PortfolioRiskPolicy enforcing currency isolation, lot-size alignment, position-aware SELL validation, long-exit stop loss / take profit directional bounds, odd-lot full exit allowance without lot size truncation, stop loss waiver on de-risking exits, kill-switch exit allowance during drawdown/daily loss, fail-closed validation for non-positive peak equity / entry price / stop loss / take profit / limit price, and exact max_allowed_quantity computation)
- `src/agentic_trading/market_data/provider.py` (M2b/M3: multi-exchange synthetic provider; strict query filtering on symbol/exchange/interval; close-time slicing on rec_close <= end_time and rec_close <= now; dynamic synthetic close time calculation with calendar-month MN1 boundaries; specific exception handling)
- `tests/test_m3_simulation_and_risk.py` (M3: 35 comprehensive adversarial tests covering point-in-time guards, append-only ledger sign invariants, statutory fee models, accounting conservation, exact zero-drift cost basis residuals, multi-lot fuzzing, ledger replay parity, true tick-grid slippage, short-selling boundaries, realized PnL preservation across exits, prepopulated ledger replay, dividend credit, kill-switch exit allowance, odd-lot full liquidations, long-exit stop loss direction, and proposal risk gate evaluation)
- `tests/test_m2c_cross_market_foundation.py` (M2c: 29 comprehensive adversarial regression tests covering currency isolation, instrument registry, corporate actions dedup and deep lineage, replay fixture identity binding, parse_constant rejection, naive timestamp rejection, recursive non-finite validation, and stored replay fixture tamper detection)
- `src/agentic_trading/time_machine/` (M4: `manifest.py` canonical-JSON SHA-256 experiment manifest with `hmac.compare_digest` verification; `metrics.py` Decimal metrics and buy-and-hold benchmark; `engine.py` zero-look-ahead `BacktestEngine` with next-open execution, risk-gate sizing, gap/intra-bar stops, delisting liquidation, point-in-time corporate actions and exact-zero conservation check; `validation.py` train/test split and walk-forward; `monte_carlo.py` seeded bootstrap)
- `tests/test_m4_time_machine.py` (M4: 25 adversarial tests covering next-open execution, future-bar invariance, gap and collision physics, liquidity cap, delisting, NSE/INR and NASDAQ/USD conservation, manifest reproducibility and per-field tamper detection, walk-forward isolation, seeded Monte Carlo, metric edge cases, corporate actions, input validation, no inline comments)
- `src/agentic_trading/paper_trading/` (M5: `kill_switch.py` independent dual-mechanism kill switch checking env var and sentinel file in O(1); `broker.py` simulated paper broker with idempotent deterministic order IDs, kill switch checks, market hours checks, realistic fills with adverse slippage and statutory fees, and daily reconciliation asserting exact zero conservation residual)
- `src/agentic_trading/agents/` (M5: 7-agent AI research desk with `AgentEnvelope` strict schemas and input hashing, `LLMClient` protocol with deterministic stubs and local Ollama client, 3-tier memory with append-only SQLite `DecisionLog` and read-only `HumanLessonsStore`, Market Analyst, Data Analyst with filing staleness checks, News Analyst with prompt injection containment and event blackout, Opportunity Scout, Strategist with deterministic math verification of trade proposals, Daily Reporter EOD summary, and 4-stage pipeline `TradingDeskOrchestrator`)
- `src/agentic_trading/risk_engine/proposal_gate.py` (M5: extended with sector position limits `SECTOR_LIMIT_EXCEEDED` and corporate event blackout `EVENT_BLACKOUT` fail-closed checks)
- `tests/test_m5_paper_and_agents.py` (M5: 16 comprehensive adversarial tests covering kill switch fail-closed checks, idempotent paper broker, limit price bounds, order cancellation state machine, thread-safe concurrent submissions, sector limits, blackout enforcement, envelope validation, LLM client, decision log SQLite persistence, market/data/news analysts, scout/strategist pipeline, deterministic multi-agent fan-out, end-to-end multi-market orchestrator, and zero inline comments)
- `src/agentic_trading/api/` (M6: local-first FastAPI HTTP REST API and visual monitoring dashboard: `schemas.py` enforcing `paper_only=True` and positive finite bounds, `state.py` thread-safe multi-currency portfolio manager, `routes.py` REST endpoints for health/kill-switch/orders/portfolios/backtest/desk, `dashboard.py` self-contained single-page UI with zero external CDN scripts, `app.py` FastAPI app factory with clean lifespan and localhost-only binding)
- `tests/test_m6_api_and_dashboard.py` (M6: 15 comprehensive tests covering dashboard rendering without external CDN links, INR/USD portfolio isolation, idempotent orders and limit pending/cancellation, kill switch blocking, backtest verified manifest, desk cycle run and SQLite decision log retrieval, DNS-rebinding & CSRF protection, CSP defensive headers, concurrency stress testing, restart continuity, and zero inline comments)
- `src/agentic_trading/market_data/feed_bridge.py` (M7: SSRF-hardened `ReadOnlyMarketFeedBridge`, `MarketDataQualityGate` structural and geometric validation, and HMAC-SHA256 authenticated `ReplayFixtureStore` supporting deterministic `"synthetic"`, `"cache"`, and `"delayed_feed"` modes)
- `src/agentic_trading/agents/llm_client.py` (M7: `LocalOllamaJSONClient` loopback isolation, model regex sanitation, 256KB cap, and `FailoverLLMClient` with transparent offline stub fallback)
- `tests/test_m7_feeds_and_ollama.py` (M7: 11 comprehensive adversarial tests covering SSRF blocks, payload caps, non-finite constant rejection, HMAC cache tamper detection, loopback Ollama validation, failover client resilience, feed endpoint execution, and zero inline comments)
- `docs/project-memory/AI_MASTER_CONTEXT.md` (reconciled master architectural context, product vision, 3 signature capabilities, 5-phase roadmap, and non-negotiable rules)
- `requirements.lock` (pinned dependency specification with exact verified pins: `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`)
- `tests/test_claude_batch7_regressions.py` (28 regression tests covering closure encapsulation, slot removal, uniform mutation blocking, keyring bypass, D1/M5 ingestion fail-closed `TRUNCATED_COVERAGE` across NSE/BSE/NYSE/NASDAQ, secret scanning of `requirements.lock`, injected client zero-mutation in session/logout, and POST endpoint blocking)

## Validation evidence
Verified local Windows virtual environment output:
- Ruff on `src/`, `tests/`, and `v3-zerodha/src`: passed (`All checks passed!`).
- Python compileall: `python -m compileall -q src tests v3-zerodha/src` passed with exit code 0 on both 3.11.9 and 3.14.4.
- `git diff --check`: exit code 0 (no whitespace errors or merge markers).
- Full pytest suite: **487 passed in 16.08s** on genuine Python 3.11.9 (.venv311) and **487 passed in 14.20s** on Python 3.14.4 (.venv).
- Genuine pytest-cov coverage: **88.33%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
- Secret scanning hook: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files, scanning `requirements.lock`.
- Zero inline `#` comments verified across all new and edited files in M6 and M7.

## Current milestone
- Milestone 2a: COMPLETE and committed (`1b7e582`).
- Milestone 2b: COMPLETE and committed (`edd383a`).
- Milestone 2c: COMPLETE and verified.
- Milestone 3: COMPLETE and verified.
- Milestone 4 (Time Machine): COMPLETE and hardened (ADR-026, ADR-027).
- Milestone 5 (Paper Trading Engine & 7-Agent AI Research Desk): COMPLETE and hardened (ADR-028, ADR-029).
- Milestone 6 (Local-First FastAPI Backend & Interactive Web Dashboard): COMPLETE and hardened (ADR-030, ADR-031). Local REST API and self-contained web dashboard with zero external CDN dependencies, DNS-rebinding & CSRF protection, CSP defensive headers, strict Pydantic bounds, thread-safe concurrency with exact 0 residual conservation, persistent SQLite audit trails, and dual-Python verification (472 passed, 88.17% coverage).
- Milestone 7 (Read-Only Market Feed Bridge, HMAC Replay Cache & Loopback Ollama Desk Integration): COMPLETE and hardened (ADR-032, ADR-033, ADR-034). Delayed market data feed bridge with no-redirect SSRF opener, path-traversal symbol defense, thread-safe HMAC cache, loopback Ollama client with markdown fence stripping and NaN rejection, transparent failover client, `/api/feed` endpoint, minimalist dashboard UI, human-readable desk reporting, and dual-Python verification (487 passed, 88.33% coverage).

## Development workflow
1. Claude independently verifies a frozen snapshot.
2. ChatGPT triages findings, separates confirmed defects from design decisions, and scopes remediation.
3. Antigravity implements approved fixes and regression tests.
4. Independent verification checks the new snapshot and remediation evidence.
5. Repeat only where material defects remain.

## Safety boundary
- Paper-only development.
- No real-money order execution.
- No agent access to broker order-placement APIs.
- Deterministic risk controls remain authoritative.
- Missing, stale, malformed or contradictory market data fails closed.
- Human approval required for financial assumptions, credentials, any change to the safety boundary, commits/pushes when requested, and merges.

## Environment and local state
- Windows working copy: `C:\Users\Rhyth\Downloads\agentic-trading-lab-main\agentic-trading-lab`
- Known project Python environments: `.venv` (Python 3.14) and `.venv311` (Python 3.11).
- Use explicit environment executables; do not rely on system Python.
- Preserve uncommitted work and `m2a-review.patch`. Never reset, clean, stash, overwrite or discard user changes.
