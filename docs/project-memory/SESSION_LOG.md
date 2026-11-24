# Engineering Session Log

Append concise entries in reverse chronological order. Record verified outcomes, not intentions.

## 2026-11-24 — Unique Per-Symbol Pricing, Gain/Loss Scorecard, Closed Trades History & Beginner UX (ADR-043 / v1.4.0)
- Implemented ADR-043 bringing realistic per-symbol market pricing, dynamic Gain/Loss scorecard, closed trades history, practice scenarios simulator, and beginner-guided workstation UX:
  - **Deterministic Per-Symbol Market Pricing (`feed_bridge.py`)**:
    - Created `_KNOWN_BASE_PRICES` dictionary (`RELIANCE`: 2940, `TCS`: 3860, `INFY`: 1840, `HDFCBANK`: 1720, `ICICIBANK`: 1290, `SBIN`: 830, `AAPL`: 228, `MSFT`: 425, `NVDA`: 138, `GOOGL`: 176, `AMZN`: 205, with SHA-256 fallback between 150 and 2500).
    - Anchored sinusoidal wave time index to offset days (`t = 120 - offset_days + sim_step`), guaranteeing identical latest price evaluation regardless of requested bar count (1 vs. 120 bars).
    - Added deterministic scenario biases (`normal`, `bull_rally`, `sudden_crash`, `sideways_chop`).
  - **Practice Scenarios & Automated Position Sweep (`schemas.py`, `state.py`, `routes.py`)**:
    - Added `POST /api/sandbox/scenario` endpoint accepting `ScenarioRequest`.
    - Implemented `apply_scenario` advancing simulation steps and running `sweep_positions` to check mark prices against stop-loss and take-profit brackets.
    - Automated market SELL execution when brackets trigger (`STOP_LOSS_TRIGGERED`, `TAKE_PROFIT_TRIGGERED`).
  - **Dynamic Gain/Loss Scorecard & Closed Trades Audit (`schemas.py`, `state.py`, `routes.py`)**:
    - Added `GET /api/pnl` endpoint returning `PnlSummaryResponse` with starting capital, total equity, net PnL, realized/unrealized gains, fees paid, win rate, and reversed closed trade records.
    - Logged all manual and bracket-triggered position exits into `_closed_trades` with exact cost basis conservation ($residual == Decimal("0")$).
  - **Broker Ledger Monotonicity (`broker.py`)**:
    - Clamped `submitted_at = max(submitted_at, self.portfolio.ledger.entries[-1].timestamp)` in `broker.submit_order` to prevent out-of-order ledger rejections when mixed manual and auto-buy orders execute.
  - **Beginner Workstation UX (`dashboard.py`)**:
    - Added collapsible Quick-Start Guide banner (`#beginnerGuideBanner`) with 3-step walk-through.
    - Added dual-currency Gain/Loss scorecard (`#inrPnlCard`, `#usdPnlCard`).
    - Added Watchlist Presets (`Nifty Safe`, `IT Movers`, `US Leaders`) and Practice Scenario buttons.
    - Added Closed Trades History table container (`#closedTradesContainer`).
    - Upgraded Candlestick Chart AI overlays to solid dark-bordered badge pills (`drawBadgePill`).
    - Maintained zero external CDN links and safe DOM manipulation via `document.createElement`.
  - **Adversarial Test Suite (`tests/test_m12_pnl_and_beginner_ux.py`)**:
    - Added 8 comprehensive tests covering per-symbol pricing, price consistency across bar queries, scenario simulation and bracket sweeps, PnL scorecard accuracy, closed trades audit recording, dashboard UI components, and zero inline `#` comments.
    - All 531 tests passing across the entire test suite on Python 3.11 and Python 3.14 with >87% coverage.

## 2026-11-24 — Multi-Symbol Basket Backtester, Walk-Forward Parameter Optimizer & Trade Journal Export (ADR-042)
- Implemented ADR-042 adding multi-symbol basket portfolio backtesting, walk-forward parameter optimization, and audit-ready trade journal export:
  - **Causal Multi-Symbol Basket Engine (`src/agentic_trading/time_machine/basket.py`)**:
    - Created `run_basket_backtest` simulating a basket of symbols (e.g. `["RELIANCE", "TCS", "INFY"]` or `["AAPL", "MSFT", "NVDA"]`) sharing a single currency capital pool (`INR` or `USD`).
    - Aligned timestamps causally across all symbols, sorting pending buy proposals by signal confidence, enforcing `PortfolioRiskPolicy` concentration caps and volume participation, executing entries strictly at bar $t+1$ open, and processing intrabar stop-loss / take-profit exits on bar $t$ high/low.
    - Verified exact double-entry accounting conservation: verified $\text{residual} == \text{Decimal}("0")$.
    - Calculated per-symbol attribution metrics (`trades`, `win_rate_pct`, `realized_pnl`, `total_return_pct`).
    - Keyed HMAC-SHA256 experiment manifest verification (`manifest_verified: True`).
  - **Chronological Walk-Forward Parameter Optimizer (`src/agentic_trading/time_machine/basket.py`)**:
    - Created `run_walk_forward_optimization` splitting historical candles into an in-sample training window (70%) and an untouched out-of-sample validation window (30%) with zero look-ahead leakage.
    - Evaluated deterministic parameter grids across strategies (`ema_pullback`, `rsi_mean_reversion`, `atr_breakout`, `sma_cross`), selecting the optimal parameter set maximizing Sharpe ratio and return, and evaluating the out-of-sample window to report parameter robustness.
  - **API Schemas, State & REST Endpoints (`schemas.py`, `state.py`, `routes.py`)**:
    - Added `BasketBacktestRequest`, `PerSymbolAttributionItem`, `WalkForwardSummary`, `BasketBacktestResponse`, and `JournalExportResponse` with `extra="forbid"`.
    - Implemented `TradingLabState.run_basket_backtest` and `TradingLabState.export_journal`.
    - Neutralized CSV formula injection by prepending single quotes (`'`) to any text field starting with `=`, `+`, `-`, `@`, `\t`, or `\r`.
    - Added REST endpoints `POST /api/backtest/basket` and `GET /api/journal/export`.
  - **Dashboard Operator UI (`src/agentic_trading/api/dashboard.py`)**:
    - Added `Run Basket & Walk-Forward` button in the header toolbar (`#runBasketBacktestBtn`).
    - Added `Export CSV` and `Export JSON` download buttons (`#exportJournalCsvBtn`, `#exportJournalJsonBtn`).
    - Added In-Sample vs. Out-of-Sample Walk-Forward summary cards (`#walkForwardGrid`).
    - Added Per-Symbol Basket Attribution table (`#basketAttributionCard`) rendered dynamically via `document.createElement`.
    - Maintained zero external CDN links and zero inline `#` comments.
  - **Adversarial Test Suite (`tests/test_m11_basket_backtest_and_journal.py`)**:
    - Added 8 tests covering direct basket engine simulation, standalone walk-forward optimization, REST API endpoint validation, concentration cap enforcement, JSON and CSV journal export, CSV formula injection defense, dashboard UI elements, and zero inline `#` comments.
    - 523 total tests passing across Python 3.11 and Python 3.14 with 87.73% coverage.

## 2026-11-24 — SSRF-Hardened Live Fundamentals & Financial News Ingestion Adapters (ADR-041)
- Implemented ADR-041 adding SSRF-hardened live fundamentals and financial news ingestion adapters:
  - **SSRF-Hardened Context Adapter (`context_bridge.py`)**:
    - Created `ReadOnlyContextBridge` supporting `"synthetic"`, `"cache"`, and `"live"` modes.
    - SSRF defenses: HTTPS scheme enforcement, allowlisted Yahoo Finance hosts (`query1/query2/feeds.finance.yahoo.com`), `_NoRedirectHandler` (raising `URLError` on 3xx), 512 KB payload cap, 10s socket timeout, and symbol validation regex (`^[A-Za-z0-9._-]{1,32}$`).
    - XML/RSS XXE protection: scanning for `<!DOCTYPE` and `<!ENTITY` (case-insensitive) prior to XML parsing, control character filtering, entity decoding via `html.unescape`, and HTML tag stripping.
    - HMAC-SHA256 authenticated disk caching with tamper detection.
  - **Desk & Orchestrator Integration (`state.py`, `schemas.py`, `routes.py`)**:
    - Extended `DeskRunRequest` with `context_source: Literal["synthetic", "cache", "live"] = "synthetic"`.
    - Resolved real `FundamentalSnapshot`, `NewsArticle`s, and `ScheduledEvent`s outside locks and passed into `WatchlistTarget`.
    - Enabled `DataAnalyst` and `NewsAnalyst` to output `data_quality="ok"` and genuine fundamental/catalyst evaluations.
    - Automatically enforced `EVENT_BLACKOUT` and rejected proposals when upcoming earnings date falls within window (`<= 2 days`).
    - Added `GET /api/context/{exchange}/{symbol}` endpoint returning sanitized fundamental metrics, news headlines, and blackout status with `paper_only: True`.
  - **Dashboard Settings & Badges (`dashboard.py`)**:
    - Added Context Source dropdown inside `Settings ▾` (`#contextSourceSelect`).
    - Added Context pill inside Cycle Strip (`#cycleContextPill`).
    - Added `Fundamental Health & Catalyst Summary` card in Overview tab (`#overviewContextContainer`).
    - Added live Fundamental and Catalyst evaluation badges in Agent Chat cards.
    - Preserved zero external CDN dependencies and safe DOM construction via `document.createElement`.
  - **Testing & Verification**:
    - Added `tests/test_m10_fundamentals_and_news.py` with 8 comprehensive adversarial tests.
    - Zero inline `#` comments verified across all new and modified code.


## 2026-11-24 — Auto-Buy Toggle, AI Buy/Sell Price Plan Cards & Candlestick Chart with AI Overlays (ADR-038)
- Implemented ADR-038 adding Auto-Buy toggle control, AI Buy & Sell Price Plan cards, and interactive HTML5 `<canvas>` Candlestick Chart with AI Overlays:
  - **Conditional Order Execution & Plan Status (`orchestrator.py`)**:
    - Added `auto_execute: bool = True` to `TradingDeskOrchestrator.run_cycle`.
    - When `auto_execute=True` and risk gate approves: submits paper order to `PaperBroker` (`status="executed"`), records `"Stage 4 · Risk & Execution"` in `chat_trace`.
    - When `auto_execute=False` and risk gate approves: skips `broker.submit_order`, marks trade plan status as `"planned"`, and records `"Stage 4 · Risk & Plan Preview"` in `chat_trace`.
    - Added `trade_plans: tuple[dict[str, Any], ...]` and `candle_series: Mapping[str, tuple[dict[str, Any], ...]]` to `DeskCycleResult`.
    - Built comprehensive `trade_plans` across all watchlist symbols capturing `symbol`, `exchange`, `currency`, `action`, `status`, `current_price`, `buy_price`, `sell_target`, `stop_loss`, `quantity`, `reward_to_risk`, `confidence`, `rationale`, `risk_reasons`, and `executed_order_id`.
    - Captured exact input OHLCV bars in `candle_series` for every analyzed ticker.
  - **Backward-Compatible SQLite Persistence & Migration (`memory.py`)**:
    - Added `auto_buy`, `trade_plans_json`, and `candle_series_json` to `cycle_runs` table in `DecisionLog._init_sqlite`.
    - Added dynamic non-destructive `ALTER TABLE cycle_runs ADD COLUMN ...` migration for existing database files.
    - Updated `save_cycle_run`, `list_cycle_runs`, and `get_cycle_run` to persist and retrieve `auto_buy`, `trade_plans`, and `candle_series`.
  - **API Schemas & REST Endpoints (`schemas.py`, `state.py`, `routes.py`)**:
    - Added `CandleBarItem` and `TradePlanItem` schemas with `extra="forbid"`.
    - Added `auto_buy: bool = True` to `DeskRunRequest` and passed through to `orchestrator.run_cycle(auto_execute=request.auto_buy)`.
    - Extended `DeskRunResponse` and `CycleDetailResponse` with `auto_buy`, `trade_plans`, and `candle_series`.
    - Extended `CycleSummaryItem` with `auto_buy: bool = True`.
    - Populated `candles: list[CandleBarItem]` in `FeedCandlesResponse` (`GET /api/feed/{exchange}/{symbol}`).
  - **Dashboard Redesign (`dashboard.py`)**:
    - Auto-Buy Toggle Switch beside Run Desk button (`#autoBuyToggle`) with dynamic label ("Auto-Buy ON" vs "Auto-Buy OFF").
    - AI Trade Plans table (`#tradePlansContainer`) showing Symbol, Status badge (`EXECUTED`, `READY TO BUY`, `RISK BLOCKED`, `NO TRADE`, `DROPPED`), Current Price, Buy Price (sky-blue), Sell Target (green with upside %), Stop Loss (red with risk %), Qty & R:R, Rationale, and interactive **`Execute Paper Buy`** button for planned items calling `POST /api/orders`.
    - Candlestick Chart (`#candlestickCanvas`, `#chartTickerPills`, `#chartReadoutBar`) rendering OHLC green/red candles and wicks, horizontal dashed AI levels (`BUY`, `SELL TARGET`, `STOP LOSS`), soft shaded reward/risk zones, and interactive mousemove crosshair with instant OHLCV readout.
    - Zero external CDN links and strict DOM manipulation via `document.createElement` and `textContent`.
  - **Testing & Verification**:
    - Added `test_auto_buy_toggle_and_planned_orders`, `test_feed_candles_and_candle_series_response`, and `test_dashboard_contains_auto_buy_plans_and_chart` in `test_m6_api_and_dashboard.py`.
    - Extended `test_e2e_platform_audit.py` with `auto_buy`, `trade_plans`, and `candle_series` assertions.
    - Zero inline `#` comments verified across all new and modified files.

## 2026-11-24 — Abstracted Dashboard UI with Active Cycle Inspector & Agent Chat Trace (ADR-037)
- Implemented ADR-037 providing active cycle inspection and multi-agent chat trace review:
  - **Cycle Context & Chat Trace Capture (`orchestrator.py`)**:
    - Added optional `chat_trace: tuple[dict[str, Any], ...] = ()` to `DeskCycleResult`.
    - Added `_strip_control_chars` sanitizing untrusted inputs/outputs against ASCII control characters.
    - Captured granular step-by-step entries across Stages 1–4: Market Analyst, Data Analyst, News Analyst, Opportunity Scout, Strategist, Risk Gate & Execution.
    - Fixed `run_desk` in `state.py` to aggregate all watchlist targets before running `orchestrator.run_cycle`.
  - **SQLite Cycle History Persistence (`memory.py`)**:
    - Added `cycle_runs` table in `DecisionLog._init_sqlite`.
    - Implemented `save_cycle_run`, `list_cycle_runs`, and `get_cycle_run` with parameterized queries and in-memory fallback list.
  - **API Schemas & REST Endpoints (`schemas.py`, `state.py`, `routes.py`)**:
    - Added `AgentChatEntry`, `CycleSummaryItem`, and `CycleDetailResponse` schemas with `extra="forbid"` and `paper_only: Literal[True] = True`.
    - Enriched `DeskRunResponse` with `timestamp`, `watchlist`, `ollama_model`, and `chat_trace`.
    - Implemented `GET /api/cycles` and `GET /api/cycles/{run_id}` with regex validation on `run_id` (`^[A-Za-z0-9._-]{1,64}$`) and path-traversal blocking (`..`).
  - **Abstracted Dashboard UI Redesign (`dashboard.py`)**:
    - Redesigned `DASHBOARD_HTML` in dark-slate palette (`max-width: 1120px`, `#0f172a`, `#1e293b`, `#334155`).
    - Added Reviewing Cycle Context Strip displaying Cycle ID, timestamp, market, watchlist pills, feed source, model, and `<select id="cycleSelect">` history switcher.
    - Two-Tab Inspection Workspace:
      - Tab 1: Overview (candidate screening shortlist/dropped badges, executed paper orders table, risk rejections, collapsible raw report).
      - Tab 2: Agent Chat (ordered chat exchange cards for Stages 1–4 showing step number, stage/agent/model/symbol badges, status pill, and structured "Input Context Seen" and "Agent / LLM Response" bubbles).
    - Guaranteed zero external CDN scripts/styles and safe DOM construction strictly via `document.createElement` and `textContent`.
  - **Testing & Verification**:
    - Added `test_cycles_endpoints_and_chat_trace` and `test_dashboard_contains_cycle_inspector_and_chat_trace` in `test_m6_api_and_dashboard.py`.
    - Added cycle list and detail assertions in `test_e2e_platform_audit.py`.
    - Zero inline `#` comments verified across all new and modified files.

## 2026-11-24 — RC2 Remediation: Manual Order Risk Gating, Lock-Free Kill Switch, Sequential Snapshots & Cache HMAC Isolation (ADR-036)
- Remediated all 8 audit findings across API, orchestrator, feed bridge, dashboard, and documentation for Release Candidate 2 (RC2):
  - **Manual Order Risk Gating & Server-Resolved Pricing (`schemas.py`, `state.py`, `routes.py`)**:
    - Made `quote_price` optional on `SubmitOrderRequest` (`Decimal | None = None`).
    - Server resolves market price from `ReadOnlyMarketFeedBridge` when `quote_price` is omitted. If supplied, server verifies `abs(quote_price - feed_price) / feed_price <= 0.05` (`ValueError: quote_price deviates from market feed`).
    - Manual orders are evaluated against authoritative `evaluate_trade_proposal` using portfolio risk policy (`inr_risk_policy` / `usd_risk_policy`). Rejections raise `ProposalRiskRejectionError(ValueError)`, mapped to HTTP 422 in routes (e.g. `MISSING_STOP_LOSS`).
  - **Lock-Free Kill Switch & Coarse Lock Removal (`state.py`)**:
    - Removed `with self._lock:` from `set_kill_switch`, enabling immediate $O(1)$ writes/unlinks (<0.5s) without waiting on long-running backtests or desk cycles.
    - Removed coarse `with self._lock:` wrapping the entire `run_backtest` and `run_desk` methods, acquiring locks only for atomic dictionary mutations (`self._mark_prices`).
  - **Sequential Snapshot Refresh in Desk Orchestrator (`orchestrator.py`)**:
    - In `TradingDeskOrchestrator.run_cycle`, initialized `current_snapshot = snapshot` and refreshed `current_snapshot = broker.portfolio.snapshot(...)` after every filled order in Stage 4, preventing multi-ticker cumulative exposure breaches within a single cycle.
  - **Removal of Fabricated Mock Objects in Desk Runs (`state.py`)**:
    - Removed synthesized mock `FundamentalSnapshot` and fake `NewsArticle` fabrication, passing `fundamental_snapshot=None` and `news_articles=()` so desk agents evaluate genuine empty/unsupported states without hallucinations.
  - **Mark-to-Market Valuation & Numeric Residual Check (`state.py`, `dashboard.py`)**:
    - Added `self._mark_prices` tracking in `TradingLabState`. `get_portfolio_summary` uses `self._mark_prices` for mark-to-market `holdings_value` and `unrealized_pnl` while computing `conservation_residual` strictly on `cost_basis`, guaranteeing exact zero residual drift.
    - In `dashboard.py`, converted reconciliation check to numeric (`Math.abs(residualNum) > 0`), eliminating false reconciliation warnings on exact `0` or `0.00` residuals.
  - **Replay Cache HMAC Key Isolation & Configuration (`feed_bridge.py`)**:
    - `ReadOnlyMarketFeedBridge` accepts optional `hmac_key: bytes | str | None = None`, falling back to `os.environ.get("TRADING_LAB_REPLAY_HMAC_KEY")` and then per-instance `secrets.token_bytes(32)`.
    - Propagates `hmac_key` consistently to `ReplayFixtureStore` and `StoredReplayFixtureProvider`.
  - **Zero-Comment Rule Accuracy Clarification**:
    - Clarified that zero inline comment rule applies strictly to M4–M7 and new/modified code; legacy M2a modules (`adapters.py`, `ingestion.py`, `models.py`, `provider.py`, `quality.py`) retain legitimate comments.
  - **Comprehensive Platform Regression Tests (`tests/test_e2e_platform_audit.py`)**:
    - Added 5 regression tests covering manual order risk rejection (422) and price deviation (400), lock-free kill switch responsiveness (<0.5s), sequential multi-ticker snapshot exposure limits, mark-to-market valuation with zero residual, and feed bridge HMAC key isolation.
- **Validation results**:
  - Full pytest suite: **495 passed in 10.39s** on Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — End-to-End Platform Audit & Release Candidate Verification (ADR-035)
- Conducted comprehensive cross-milestone audit and end-to-end integration verification across Milestones 1 through 7:
  - **Defense-in-Depth & Paper-Only Boundary Audit**:
    - Confirmed `paper_only: Literal[True] = True` across API schemas and state responses.
    - Verified architectural boundary enforcement in `test_import_boundaries.py` guaranteeing zero live broker imports.
    - Verified loopback-only host validation, DNS-rebinding guards, cross-origin state mutation blocking, and CSP defensive headers in `app.py`.
    - Verified SSRF-hardened no-redirect HTTP openers, allowlisted Yahoo chart hosts, 1 MB payload limits, and regex symbol validation in `feed_bridge.py`.
    - Verified loopback isolation, no-redirect opener, and non-finite JSON rejection in `LocalOllamaJSONClient`.
    - Confirmed fail-closed kill switch behavior on env vars, sentinel files, and `OSError` exceptions.
  - **Accounting Conservation & Currency Isolation Audit**:
    - Confirmed exact `Decimal("0")` conservation residual across ledger, portfolio, time machine, paper broker, and API state.
    - Confirmed strict isolation between INR (`NSE`/`BSE`) and USD (`NYSE`/`NASDAQ`) virtual portfolios with zero cross-currency fills.
    - Verified parameterized SQLite queries with `with conn:` blocks in `memory.py` and thread-safe `RLock` synchronization across state, broker, and feed bridge.
  - **Causal Backtesting & Multi-Agent Determinism Audit**:
    - Confirmed causal next-open entry execution, causal signal evaluation at bar close, cancellation of final-bar pending orders (`END_OF_DATA_PENDING_CANCELLED`), and keyed HMAC-SHA256 manifest authentication in `time_machine/engine.py`.
    - Confirmed deterministic fan-out ordering under `ThreadPoolExecutor`, pre-Stage 4 kill switch re-checks, read-only `HumanLessonsStore`, and fail-closed error fallback in `TradingDeskOrchestrator`.
  - **End-to-End Platform Integration Test (`tests/test_e2e_platform_audit.py`)**:
    - Added test exercising complete platform lifecycle: isolated INR/USD accounts, synthetic feed fetches, backtest with verified manifest and zero residual, 7-agent research desk cycle with SQLite decision logging, kill switch order blocking (HTTP 409), resume, final portfolio reconciliation, and repository-wide tokenizer validation of zero inline `#` comments.
- **Validation results**:
  - Full pytest suite: **490 passed in 16.58s** on Python 3.11.9 (`.venv311`) and **490 passed in 14.72s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Dashboard UI Simplification & Human-Readable Desk Output Formatting (ADR-034)
- Redesigned local dashboard and formatted daily reporter summaries for enhanced readability, scannability, and operational focus:
  - **Human-Readable Money & Clean Report Headings (`src/agentic_trading/agents/reporter.py`)**:
    - Formatted `Money` amounts cleanly as `f"{money.amount:,.2f} {money.currency.value}"` (e.g. `1,000,000.00 INR`, `105.10 INR`), eliminating raw Python `Money(...)` reprs.
    - Replaced heavy `===` ASCII divider walls with clean section headings (`Portfolio Summary`, `Executed Orders`, `Skipped / Rejected`, `Position Reconciliation`).
    - Added `format_report = generate_eod_report` alias and preserved `DAILY DESK SUMMARY` header for 100% test compatibility.
  - **Minimalist Dark-Slate Dashboard (`src/agentic_trading/api/dashboard.py`)**:
    - Adopted a clean dark-slate layout (`max-width: 1020px`) with system sans-serif typography and muted borders.
    - Replaced full-width top banner with a single compact header featuring an amber `PAPER TRADING ONLY` status pill, live status indicator (`Active`/`Stopped`), and `Emergency Stop` button.
    - Highlighted Total Equity as the primary large figure on INR and USD portfolio cards, with compact key-value rows below and fail-closed warning banners displayed only on reconciliation discrepancies.
    - Streamlined action bar with primary `Run Desk` and `Run Backtest` buttons, plus a collapsible `Settings ▾` row for feed source and LLM backend selectors.
    - Automated portfolio refresh following desk runs, backtests, and emergency stop actions.
    - Rendered output safely via `textContent` and `createElement` with a concise status line (e.g., `Completed · cache · ollama`).
- **Validation results**:
  - Full pytest suite: **487 passed in 16.08s** on Python 3.11.9 (`.venv311`) and **487 passed in 14.20s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.33%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` passed with 0 unbaselined secrets.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 7 Adversarial Hardening: No-Redirect SSRF Opener, Symbol Path-Traversal Guard & Concurrent Cache Safety (ADR-033)
- Hardened Milestone 7 market data feed bridge, local Ollama LLM client, and API feed routes against SSRF bouncing, path traversal, race conditions, and LLM output anomalies:
  - **No-Redirect HTTP Transport (`src/agentic_trading/market_data/feed_bridge.py`, `src/agentic_trading/agents/llm_client.py`)**:
    - Created `_NoRedirectHandler(urllib.request.HTTPRedirectHandler)` raising `urllib.error.URLError("HTTP redirects are forbidden")` on `redirect_request`.
    - Integrated `urllib.request.build_opener(_NoRedirectHandler())` into default transports for both `ReadOnlyMarketFeedBridge` and `LocalOllamaJSONClient`.
  - **Strict Symbol Sanitization & Directory Traversal Defense (`src/agentic_trading/market_data/feed_bridge.py`, `src/agentic_trading/api/routes.py`, `src/agentic_trading/api/schemas.py`)**:
    - Validated all symbols against `^[A-Za-z0-9._-]{1,32}$` and explicitly blocked `".."`, `/`, `\`, null bytes, and whitespace via `_validate_symbol` and `validate_symbol`.
    - Path-traversal attempts raise `ValueError` in `ReadOnlyMarketFeedBridge` and `ReplayFixtureStore`, and return HTTP 400 in `GET /api/feed/{exchange}/{symbol}`.
  - **Concurrent Cache Synchronization (`src/agentic_trading/market_data/feed_bridge.py`)**:
    - Protected `ReplayFixtureStore` and `ReadOnlyMarketFeedBridge` cache operations with `threading.RLock()` across `save_candles`, `load_candles`, and `fetch_candles`, preventing race conditions during concurrent requests.
  - **Markdown Fence Stripping & Non-Finite Constant Rejection (`src/agentic_trading/agents/llm_client.py`)**:
    - Implemented `_extract_json_text` in `LocalOllamaJSONClient` cleanly stripping ```` ```json ... ``` ```` and ```` ``` ... ``` ```` fences.
    - Enforced `parse_constant=_reject_constant` on outer Ollama envelope, inner response text, and `FailoverLLMClient`, failing closed on `NaN` or `Infinity` constants with `ValueError` and triggering seamless fallback to deterministic offline stubs.
  - **Adversarial Regression Tests (`tests/test_m7_feeds_and_ollama.py`)**:
    - Added 4 new adversarial tests (15 total):
      - `test_feed_bridge_and_ollama_client_reject_http_redirects`
      - `test_path_traversal_symbol_rejection_in_feed_bridge_and_route`
      - `test_concurrent_feed_bridge_cache_access_thread_safety`
      - `test_ollama_markdown_fences_and_non_finite_rejection_with_failover`
- **Validation results**:
  - Full pytest suite: **487 passed in 22.56s** on Python 3.11.9 (`.venv311`) and **487 passed in 16.70s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.36%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 7 Implementation: Read-Only Market Feed Bridge, HMAC Replay Cache & Loopback Ollama Desk Integration (ADR-032)
- Implemented and verified complete Milestone 7 architecture across market data feed bridge, local Ollama LLM client, and API/dashboard integration:
  - **SSRF-Hardened Feed Bridge (`src/agentic_trading/market_data/feed_bridge.py`)**:
    - Created `ReadOnlyMarketFeedBridge` enforcing strict `https` scheme, allowlisted hostnames (`query1.finance.yahoo.com`, `query2.finance.yahoo.com`), and 1 MB payload limits.
    - Implemented `parse_constant=_reject_constant` blocking NaN/Infinity injection.
    - Added timezone-aware candle normalization (`Asia/Kolkata` for NSE/BSE, `America/New_York` for NYSE/NASDAQ).
    - Added structural & geometric `MarketDataQualityGate` validation (monotonic timestamps, uniform intervals, high/low bounds, positive OHLC, non-negative volume, 50% max bar jump).
    - Integrated Tier-2 HMAC-SHA256 `ReplayFixtureStore` for offline reproducible replay fixture caching.
    - Supported three deterministic modes: `"synthetic"`, `"cache"`, and `"delayed_feed"` with automatic fallback.
  - **Loopback-Isolated Ollama Client (`src/agentic_trading/agents/llm_client.py`)**:
    - Created `LocalOllamaJSONClient` restricted strictly to loopback addresses (`127.0.0.1`, `localhost`, `::1`, `[::1]`) and HTTP/HTTPS schemes.
    - Sanitized model names via regex (`^[A-Za-z0-9._:-]{1,64}$`) defaulting to `gemma4:12b`.
    - Enforced 256 KB response payload limit and strict JSON parsing.
    - Implemented `FailoverLLMClient(primary, fallback)` delegating gracefully to deterministic offline stub on connection, timeout, network error, or invalid JSON.
  - **API & Dashboard Integration (`src/agentic_trading/api/`)**:
    - Added `GET /api/feed/{exchange}/{symbol}` endpoint with query validation.
    - Extended `DeskRunRequest` with `llm_backend`, `ollama_model`, and `feed_source`.
    - Extended `BacktestRequest` with `feed_source`.
    - Added feed source and LLM backend selectors to local single-page dashboard with zero external CDN scripts.
  - **Adversarial Regression Tests (`tests/test_m7_feeds_and_ollama.py`)**:
    - Created 11 comprehensive adversarial tests covering SSRF rejection, payload size caps, non-finite constant rejection, quality gate geometry violations, HMAC cache roundtrip and tamper detection, loopback-only Ollama validation, 256 KB payload caps, failover resilience, feed route execution, and AST/tokenizer verification for zero inline comments and zero forbidden imports.
- **Validation results**:
  - Full pytest suite: **483 passed in 25.99s** on Python 3.11.9 (`.venv311`) and **483 passed in 23.92s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.34%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 6 Adversarial Hardening: DNS-Rebinding, Origin Defense, CSP Headers & Concurrency (ADR-031)
- Hardened Milestone 6 FastAPI application and dashboard against adversarial web attacks, payload tampering, and thread races:
  - **Host Header & DNS-Rebinding Protection (`src/agentic_trading/api/app.py`)**:
    - Added HTTP middleware validating `Host` header (normalizing case, stripping ports, and handling IPv6 bracket notation `[::1]`).
    - Rejects unauthorized hosts outside `ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}` with HTTP 403 (`{"detail": "Forbidden host header"}`).
  - **Cross-Origin CSRF Defense (`src/agentic_trading/api/app.py`)**:
    - For state-mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`), parses `Origin` and `Referer` headers via `urllib.parse.urlparse`.
    - Rejects requests from untrusted external origins with HTTP 403 (`{"detail": "Cross-origin state mutation forbidden"}`).
  - **Strict Browser Security & CSP Headers (`src/agentic_trading/api/app.py`)**:
    - Injected defensive security headers on all HTTP responses: `Content-Security-Policy` (`default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
  - **Strict Request Schema Bounds & Extra Rejection (`src/agentic_trading/api/schemas.py`, `src/agentic_trading/api/routes.py`)**:
    - Enforced `model_config = ConfigDict(extra="forbid")` across all Pydantic schemas, rejecting unknown injected parameters with HTTP 422.
    - Added explicit length caps (`max_length <= 64`) on request identifiers (`run_id`, `symbol`, `client_order_id`, `reason`).
    - Enforced bounded collections and numbers: `DeskRunRequest.watchlist` capped at 20 symbols, `BacktestRequest.bars_count` bounded to `[10, 500]`, `monte_carlo_runs` bounded to `[1, 5000]`.
    - Added validation on order cancellation route ensuring `client_order_id` in path is non-empty and `<= 64` chars.
  - **State Concurrency & Exact Conservation (`src/agentic_trading/api/state.py`)**:
    - All portfolio, order, desk, and backtest mutations synchronized under `self._lock` (`threading.RLock`).
    - Fixed `Position` snapshot evaluation to access `@property cost_basis.amount`, preventing callable errors under concurrent load and preserving exact `Decimal("0")` conservation residuals.
  - **Adversarial Regression Tests (`tests/test_m6_api_and_dashboard.py`)**:
    - Added 5 new adversarial tests covering DNS-rebinding rejection, cross-origin state mutation rejection, CSP/security header verification, schema extra field & length bounds rejection, 16-thread concurrent execution stress test, and restart persistence continuity.
- **Validation results**:
  - Full pytest suite: **472 passed in 7.58s** on Python 3.11.9 (`.venv311`) and **472 passed in 3.92s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.17%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 6 Implementation: Local-First FastAPI Backend & Dashboard (ADR-030)
- Implemented and verified complete Milestone 6 architecture across API schemas, state management, REST endpoints, and local web dashboard:
  - **Pydantic v2 Schemas (`src/agentic_trading/api/schemas.py`)**:
    - Enforced `paper_only: Literal[True] = True` across all system status, portfolio, order, backtest, and desk payloads.
    - Implemented strict currency validation (`Literal["INR", "USD"]`) and custom validators rejecting `NaN`, `Infinity`, non-positive, or boolean values for prices, quantities, and capital (returning HTTP 422).
    - Modeled `HealthResponse`, `KillSwitchRequest`/`Response`, `PortfolioSummaryResponse`, `SubmitOrderRequest`, `OrderResponse`, `BacktestRequest`/`Response`, `DeskRunRequest`/`Response`, and `DecisionRecordItem`.
  - **Thread-Safe State & Isolated Virtual Accounts (`src/agentic_trading/api/state.py`)**:
    - Created `TradingLabState` protected by `threading.RLock()`.
    - Maintained two strictly isolated virtual portfolios (INR for NSE/BSE with statutory Indian fees, USD for NYSE/NASDAQ with US fees) initialized with historical base deposit timestamps.
    - Connected shared `KillSwitch`, SQLite `DecisionLog`, `HumanLessonsStore`, `DeterministicStubLLMClient`, `TradingDeskOrchestrator`, and `BacktestEngine`.
  - **FastAPI REST Endpoints (`src/agentic_trading/api/routes.py`)**:
    - Implemented `GET /api/health`, `GET /api/status`, `POST /api/kill-switch`, `GET /api/portfolios/{currency}`, `POST /api/orders`, `POST /api/orders/{currency}/{client_order_id}/cancel`, `POST /api/backtest`, `POST /api/desk/run`, and `GET /api/decisions`.
    - Enforced HTTP 409 when `KillSwitch` is active, HTTP 400 on cross-currency/exchange mismatches or invalid cancellations, and HTTP 404 on missing orders.
  - **Self-Contained Dashboard (`src/agentic_trading/api/dashboard.py`)**:
    - Built single-page local monitoring UI with zero external CDN dependencies (zero external script or stylesheet links).
    - Featured `PAPER TRADING ONLY` banner, interactive Emergency Stop button, side-by-side INR/USD portfolio cards with 0 conservation residual badge, and safe DOM manipulation (`textContent`).
  - **App Factory (`src/agentic_trading/api/app.py`)**:
    - Configured `create_app` with clean async `lifespan` context manager closing SQLite connections on shutdown, and localhost-only binding (`127.0.0.1:8000`).
  - **Test Suite (`tests/test_m6_api_and_dashboard.py`)**:
    - Added 10 comprehensive tests covering dashboard rendering, zero external scripts, INR/USD portfolio isolation, idempotent order submission, unmarketable limit pending state and cancellation, kill switch blocking, backtest manifest verification, desk cycle run and SQLite decision log retrieval, zero inline comments, and architectural import boundaries.
- **Validation results**:
  - Full pytest suite: **467 passed in 7.94s** on Python 3.11.9 (`.venv311`) and **467 passed in 4.98s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.12%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked repository files including `requirements.lock`.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 5 Adversarial Audit & Hardening (ADR-029)
- Hardened all Milestone 5 components against adversarial failure modes, concurrency races, and prompt injections:
  - **PaperBroker Limit Price Bounds, State Machine & Concurrency (`broker.py`)**:
    - Enforced immediate validation of `limit_price` (rejecting non-positive prices with `ValueError` and currency mismatches with `CurrencyMismatchError`).
    - Evaluated slipped execution price against limit order bounds prior to execution: unmarketable BUYs (`slipped > limit`) and SELLs (`slipped < limit`) are kept in `OrderStatus.PENDING` without calling `apply_fill`, eliminating unwanted fills, ledger records, or cash mutations.
    - Added deterministic `cancel_order(client_order_id)` allowing cancellation of `PENDING` and `SUBMITTED` orders, partially cancelling unfilled balances, and rejecting cancellations on terminal statuses (`FILLED`, `REJECTED`, `CANCELLED`) with `ValueError`.
    - Guarded broker order lookups, submissions, cancellations, and reconciliations with `threading.RLock()`, guaranteeing that concurrent duplicate submissions produce exactly 1 fill and 0 residual drift.
  - **KillSwitch & Memory Hardening (`kill_switch.py`, `memory.py`)**:
    - Handled `OSError` / filesystem permission errors on sentinel path checks by failing closed (`is_active() == True`).
    - Upgraded `DecisionLog` SQLite retrieval to use parameterized queries (`?`), explicit transactional context managers, and deterministic `ORDER BY id ASC` ordering.
  - **Agent Security & Math Guards (`envelope.py`, `news_analyst.py`, `market_analyst.py`, `strategist.py`)**:
    - `invoke_with_schema_guard`: Catches non-finite `NaN`/`Infinity` floats or Decimals in input payloads and fails closed with `data_quality="missing"`.
    - `NewsAnalyst`: Strips ASCII control characters from untrusted article text, clamps `net_sentiment` strictly to `[-1.0, 1.0]` (rejecting `NaN`/`Infinity` to `0.0` and `data_quality="missing"`), and unconditionally enforces `blackout_suggested = True` when `days_to_next_event <= blackout_window_days`.
    - `MarketAnalyst`: Hallucinated numeric tokens in `evidence` trigger validation failure (`data_quality="missing"`, confidence capped at 0.3); invalidations on the wrong side of `close` fail closed to `view="neutral"` and `data_quality="missing"`.
    - `Strategist`: Non-positive or non-finite pricing levels (`entry`, `stop`, `target`), invalid confidence outside `[0, 1]`, and `reward_to_risk < min_reward_to_risk` fail closed to `action="no_trade"`.
  - **Deterministic Orchestrator Fan-Out (`orchestrator.py`)**:
    - Resolved task futures in deterministic watchlist order, guaranteeing identical `envelopes` ordering regardless of thread completion timing, and isolating per-ticker exceptions.
    - Added an explicit `kill_switch.assert_clear()` re-check immediately prior to Stage 4 order submission.
  - **Regression Tests (`tests/test_m5_paper_and_agents.py`)**:
    - Added 4 comprehensive adversarial tests covering unmarketable limit orders, cancellation state machine, concurrent thread safety, NaN sentiment / schema guard input rejection, mid-cycle kill switch trips, and deterministic fan-out ordering.
- **Validation results**:
  - Full pytest suite: **457 passed in 6.09s** on Python 3.11.9 (`.venv311`) and **457 passed in 4.08s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **87.91%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 5 Implementation: Paper Trading Engine & 7-Agent AI Research Desk (ADR-028)
- Implemented and verified complete Milestone 5 architecture across execution, risk, and multi-agent layers:
  - **Paper Trading Execution Layer (`src/agentic_trading/paper_trading/`)**:
    - `kill_switch.py`: Independent hardware-like `KillSwitch` checking env var (`TRADING_DESK_STOP`) and file sentinel (`STOP`) in O(1) time without network I/O; `is_tripped()` fails closed with `KillSwitchError`.
    - `broker.py`: `OrderStatus`, frozen `PaperOrder`, frozen `ReconciliationReport`, and `PaperBroker` with idempotent deterministic order IDs (`order_{sha256(...)[:16]}`), kill switch check, market hours check, realistic fill against candle price with always-adverse tick-grid slippage and statutory fee models, and daily reconciliation asserting exact `Decimal("0")` residual.
  - **Risk Gate Extensions (`src/agentic_trading/risk_engine/proposal_gate.py`)**:
    - Extended `PortfolioRiskPolicy` with `max_positions_per_sector` and `blackout_symbols`.
    - Extended `evaluate_trade_proposal` with `sector`, `sector_counts`, and `event_blackout`, rejecting BUY proposals with `"EVENT_BLACKOUT"` or `"SECTOR_LIMIT_EXCEEDED"`.
  - **7-Agent AI Research Desk (`src/agentic_trading/agents/`)**:
    - `envelope.py`: `AgentEnvelope`, deterministic `compute_inputs_hash`, `invoke_with_schema_guard` with 1 retry before fail-closed.
    - `llm_client.py`: Framework-agnostic `LLMClient` protocol, offline rule-based `DeterministicStubLLMClient`, and zero-dependency `LocalOllamaJSONClient`.
    - `memory.py`: 3-tier memory with `WorkingState`, append-only SQLite `DecisionLog` (with explicit connection closure), and read-only `HumanLessonsStore`.
    - `market_analyst.py`: Pure math indicator calculation (SMA 20/50/200, RSI 14, ATR 14, volume ratio) and LLM outlook validation.
    - `data_analyst.py`: `FundamentalSnapshot` evaluation with strict filing staleness check (`max_filing_age_days = 180`).
    - `news_analyst.py`: `NewsArticle` headline deduplication, untrusted article container prompt injection defense, and event blackout window.
    - `opportunity_scout.py`: Liquidity/price filtering, analyst alignment scoring, shortlist ranking capped at 3 with auditable drop reasons.
    - `strategist.py`: `TradingMandate` synthesis, deterministic code verification of reward-to-risk and bracket prices, canonical `TradeProposal` generation.
    - `reporter.py`: `DailyReporter` human-readable EOD markdown executive summary.
    - `orchestrator.py`: `TradingDeskOrchestrator` 4-stage sequential pipeline executing kill switch, parallel analysis fan-out, scouting & proposal, and authoritative risk/execution/reconciliation/reporting.
  - **Adversarial Verification Suite (`tests/test_m5_paper_and_agents.py`)**:
    - 12 comprehensive adversarial tests covering all components, multi-market cycles (NSE and NASDAQ), and tokenizer assertions verifying zero inline `#` comments and zero forbidden imports.
- **Validation results**:
  - Full pytest suite: **453 passed in 6.01s** on Python 3.11.9 (`.venv311`) and **453 passed in 4.19s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **88.04%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — Milestone 4 Adversarial Audit & Hardening (ADR-027)
- Remediated all audit items and hardened Time Machine engine (`src/agentic_trading/time_machine/`):
  - **Keyed HMAC Experiment Manifests (`manifest.py`, `engine.py`)**:
    - Added optional `hmac_key: bytes | str | None = None` to `build_experiment_manifest` and `verify_manifest_integrity`.
    - Computes HMAC-SHA256 when `hmac_key` is supplied, while preserving unkeyed SHA-256 when `None`.
    - Added `hmac_key` to `BacktestConfig` with fail-closed validation (`TypeError` on non-bytes/str, `ValueError` on empty string), passed to manifest creation during `BacktestEngine.run`.
    - Verification fails closed (`False`) on key mismatch, type error, or tampered metadata.
  - **Final-Bar Pending Signal Cancellation (`engine.py`)**:
    - In `_Session.execute()`, after bar loop completion, unexecuted pending orders are cancelled and recorded in `rejected_proposals` with reason `"END_OF_DATA_PENDING_CANCELLED"`.
  - **Zero-Trade Monte Carlo Support (`monte_carlo.py`)**:
    - Handled empty trades gracefully in `run_seeded_monte_carlo`, returning `MonteCarloSummary` with `trade_count=0`, all quantiles and ruin/loss probabilities set to `Decimal("0.0000")`.
  - **Protective Gap-Through Stop Physics Verification (`engine.py`)**:
    - Verified gap-down stops on open (`bar.open <= stop`) fill at `bar.open` with adverse slippage tick-quantized downward via `apply_fill(..., side="SELL")`.
- **Regression Tests Added**:
  - `test_manifest_keyed_hmac_and_backtest_config_validation`: Validates HMAC manifest signing with string/bytes keys, rejection on wrong keys/None, tamper detection, and `BacktestConfig` key type/empty validation.
  - `test_final_bar_pending_signal_cancelled_at_end_of_data`: Asserts final-bar pending proposal cancellation at end of data.
  - `test_protective_gap_through_stop_fills_at_open_with_adverse_slippage`: Asserts gap-through stop exit at open price minus adverse slippage.
  - Updated zero-trade Monte Carlo assertion to verify clean 0-trade summary.
- **Validation results**:
  - Full pytest suite: **441 passed in 14.13s** on Python 3.11.9 (`.venv311`) and **441 passed in 6.73s** on Python 3.14.4 (`.venv`).
  - Test coverage: **88.54%** across all source files (exceeding mandatory `--cov-fail-under=85`).
  - Ruff check: `All checks passed!`.
  - Compileall: 0 errors on Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all git diff additions.

## 2026-11-23 — M3 Hardening: Exact Cost Basis Parity & Recursive Non-Finite Validation (D1, D2, D3)
- Remediated all 3 Claude adversarial audit findings (D1, D2, D3) across simulation and market data:
  - **Unified Position Mutation & Exact Zero-Drift Math (`portfolio.py` / D1, D2)**:
    - Refactored position mutation (`BUY` and `SELL`, long and short) into a single shared internal helper `_apply_trade_to_position(...)` called by both `apply_fill` and `_replay_ledger`, guaranteeing 100% execution parity.
    - Maintained `self._total_cost_basis: dict[tuple[Exchange, str], Decimal]` as the single source of truth for open position basis; derived `Position.average_cost` strictly at snapshot time as `Money(basis / Decimal(abs(qty)), currency)`.
    - Adding to position: `self._total_cost_basis[key] = self._total_cost_basis.get(key, Decimal("0")) + (Decimal(add_qty) * exec_price_amount)` without recomputing prior basis.
    - Reducing/closing position (`reduce_qty <= abs(curr_qty)`):
      Full close (`reduce_qty == abs(curr_qty)`): `basis_removed = curr_basis`, `new_basis = Decimal("0")`.
      Partial close (`reduce_qty < abs(curr_qty)`): `basis_removed = ((curr_basis * Decimal(reduce_qty)) / Decimal(abs(curr_qty))).quantize(Decimal("1E-12"), rounding=ROUND_HALF_EVEN)`, `new_basis = curr_basis - basis_removed`. Realized P&L delta is `proceeds - basis_removed` for long reductions and `basis_removed - cover_cost` for short reductions.
    - Flip trades (`quantity > abs(curr_qty)` when `allow_short=True`) close the existing side completely (`basis_removed = curr_basis`) and open the remainder on the opposite side with `new_basis = Decimal(rem_qty) * exec_price_amount`.
    - Guaranteed that under both default 28-digit `Decimal` context and 120-digit `localcontext`, `(deposits - withdrawals + realized_pnl + dividends - fees) - (cash + open_total_cost_basis) == Decimal("0")`.
  - **Recursive Non-Finite Pre-Check in Replay Fixtures (`replay_fixtures.py` / D3)**:
    - Updated `save_replay_fixture` pre-serialization validation via `_check_finite_values` to recursively traverse nested `Mapping` (keys and values) and non-string/bytes sequences.
    - Raises `FixtureIntegrityError` if any nested `float` or `Decimal` is `NaN`, `Infinity`, or `-Infinity` (including `Decimal("NaN")`).
- **Regression Tests Added**:
  - `test_d1_claude_multi_lot_sequence_and_fuzz_residual`: Claude's exact multi-lot sequence (`BUY 4@179.99, 2@192.87, 6@183.76, 9@192.39`, `SELL 16@60.36, 1@39.90, 1@149.33`) plus 50-step randomized multi-fill round-trip fuzz checks asserting exact `Decimal("0")` residual at both default precision and `localcontext(prec=120)`.
  - `test_d2_partial_sell_ledger_replay_parity`: Tests partial-sell + ledger replay parity (`BUY 10@100`, `SELL 4@110`, reconstruct `PortfolioEngine(ledger=...)`, verify basis is `600`, then `SELL 6@120` and assert realized P&L is `160` on both live and replayed engines).
  - `test_d3_save_replay_fixture_nested_non_finite_rejection`: Verifies nested `Decimal("NaN")`, nested `float("nan")`, and nested `float("inf")` inside fixture records raise `FixtureIntegrityError`.
- **Validation results**:
  - Pytest full suite: **413 passed in 11.21s** on Python 3.11.9 (`.venv311`) and **413 passed in 7.42s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **87.27%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all new and edited files in git diff.

## 2026-11-22 — M3 Final Polish Pass: Exact Cost Basis, Positive Price Guards & Fixture Identity Verification (R1–R8)
- Remediated all 8 Claude adversarial audit residuals (R1–R8) across simulation, risk, market data, and strategy:
  - **Simulation Costs & Fill Pricing (`costs.py`, `portfolio.py` / R1, R3)**:
    - Enforced strictly positive prices in `BasisPointsSlippageModel.calculate_slippage` and `PortfolioEngine.apply_fill` (`price.amount <= Decimal("0")` raises `ValueError`).
    - In `BasisPointsSlippageModel`, when adverse `ROUND_FLOOR` on `SELL` reduces effective price below `tick_size` (or `<= 0`), raises `ValueError("Effective sell price falls below minimum tick size")` instead of clamping upward.
  - **Exact Zero-Drift Cost Basis & Conservation Residual (`portfolio.py` / R1, R2)**:
    - Tracked exact per-position total cost basis (`_total_cost_basis`) across `apply_fill` and `_replay_ledger`.
    - On partial reductions, computed `basis_removed = (total_cost_basis * Decimal(quantity)) / Decimal(curr_qty)`, subtracted from tracked basis, and deducted from proceeds to produce `trade_pnl`.
    - On full position exits, exact remaining tracked basis is removed (`_total_cost_basis.pop(key)`), guaranteeing exact zero residual drift (`Decimal("0")`) across multi-lot partial and full round trips.
  - **Proposal Gate Long-Exit Direction & Odd-Lot Liquidation (`proposal_gate.py` / R4, R8)**:
    - For `SELL` exits of held long positions (`held_qty > 0`), strictly enforced directional bounds: `stop_loss.amount < entry_price` (`INVALID_STOP_LOSS_DIRECTION`) and `take_profit.amount > entry_price` (`INVALID_TAKE_PROFIT_DIRECTION`).
    - Detected `is_exact_full_exit = (proposal.side == "SELL" and held_qty > 0 and proposal.quantity == held_qty)`. Allowed odd-lot full liquidations without `LOT_SIZE_MISMATCH` and bypassed lot-size truncation in `max_allowed_quantity`.
  - **Replay Fixture Cryptographic Identity & Naive Timestamp Rejection (`replay_fixtures.py` / R5)**:
    - Verified `manifest.fixture_id == self._fixture_id` on load, raising `FixtureIntegrityError("Fixture identity mismatch")` on tampering.
    - Rejected timezone-naive `recorded_at` in manifest with `FixtureIntegrityError("timezone-naive")`.
  - **Synthetic Provider Strict Filter & Look-Ahead Slicing (`provider.py` / R6)**:
    - In `SyntheticMarketDataProvider.fetch_historical` and `fetch_latest`, strictly validated matching `symbol`, `exchange`, and `interval` (failing closed on mismatches), and sliced records strictly on `rec_close <= request.end_time` and `rec_close <= now` to eliminate in-progress bar leakage.
  - **BarContext Non-Overlapping Invariant & Non-Finite JSON Rejection (`contracts.py`, `replay_fixtures.py` / R7)**:
    - `BarContext.__post_init__` enforces non-overlapping bars (`candle.timestamp < prev_candle.close_time` raises `ValueError`).
    - `save_replay_fixture` rejects non-finite `float` and `Decimal` (`NaN`, `Infinity`). `json.loads` rejects non-standard JSON constants with `parse_constant=_reject_constant`.
  - **Iterative Corporate Action Lineage & Deduplication (`corporate_actions.py` / R7)**:
    - Deduplicated identical corporate actions in `adjust_candles_for_corporate_actions` across `(exchange, symbol, action_type, effective_date, adjustment_factor, new_symbol)`.
    - Replaced recursive DFS in `resolve_symbol_lineage` with iterative three-color cycle detection to safely handle arbitrary lineage depths (>1,500 hops).
- **Regression Test Coverage**: Added 10 new regression tests across `test_m3_simulation_and_risk.py` (6 tests) and `test_m2c_cross_market_foundation.py` (4 tests).
- **Validation results**:
  - Pytest full suite: **410 passed in 4.34s** on Python 3.11.9 (`.venv311`) and **410 passed in 1.88s** on Python 3.14.4 (`.venv`).
  - Genuine pytest-cov coverage: **87.40%** (exceeding mandatory `--cov-fail-under=85`).
  - Ruff `src`, `tests`, and `v3-zerodha/src`: `All checks passed!`.
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` exited with code 0 on all tracked files.
  - Zero inline `#` comments verified across all new and edited files in git diff.

## 2026-11-22 — M3 Hardening Batch A: Accounting Conservation, Tick-Grid Costs & Position-Aware Risk Gate
- Implemented full M3 Hardening Batch A remediations across 4 core areas:
  - **Accounting Ledger (`ledger.py`)**:
    - Enforced semantic sign invariants on `DEPOSIT` (cash > 0, qty == 0), `WITHDRAWAL` (cash < 0, qty == 0), `BUY_FILL` (cash < 0, qty > 0, price > 0), `SELL_FILL` (cash > 0, qty < 0, price > 0), `FEE_CHARGE` (cash <= 0, qty == 0), and `DIVIDEND_CREDIT` (cash > 0, qty == 0).
    - Computed `get_total_fees` as non-abs `-sum(...)`. Added `get_total_dividends`.
  - **Portfolio Accounting (`portfolio.py`)**:
    - Maintained `_realized_pnl_by_symbol` across full position exits, preserving cumulative realized PnL in snapshots and across re-entries.
    - Implemented pre-populated ledger replay in `PortfolioEngine.__init__`.
    - Enforced short selling boundary with `InsufficientPositionError` when `allow_short=False`, tracking signed market value and cover-to-flat PnL when `allow_short=True`.
    - Added SELL fee overdraft prevention raising `InsufficientFundsError`.
    - Added `apply_dividend` API ensuring exact decimal equality in accounting conservation invariant.
  - **True Tick-Grid Quantization & Adverse Slippage (`costs.py`, `corporate_actions.py`)**:
    - Replaced `.quantize(tick_size)` with true tick-grid rounding `(val / tick_size).to_integral_value(mode) * tick_size`.
    - Implemented always-adverse slippage in `BasisPointsSlippageModel` (`ROUND_CEILING` on BUY, `ROUND_FLOOR` on SELL).
    - Added strict parameter checks on prices, quantities, tick sizes, fee rates, and fee caps.
  - **Position-Aware Risk Gate & Dead File Cleanup (`proposal_gate.py`, `risk_engine.py`)**:
    - Implemented position-aware SELL checks (`UNAUTHORIZED_SHORT`, `INSUFFICIENT_POSITION`).
    - Waived stop-loss requirement on de-risking SELL exits of held long positions.
    - Permitted risk-reducing SELL exits during kill switch (daily loss and drawdown limits apply only to BUY).
    - Added fail-closed validations for non-positive peak equity, entry price, stop loss, take profit, and limit price, and inverted directions even with `require_stop_loss=False`.
    - Computed exact `max_allowed_quantity` floored to `lot_size`.
    - Deleted stale dead file `src/agentic_trading/risk_engine.py`.
  - **Verification & Zero `#` Comments**:
    - Added 11 new adversarial tests in `tests/test_m3_simulation_and_risk.py` (total 27 tests).
    - Full test suite: **389 passed in 2.54s** on Python 3.11 (.venv311) and **389 passed in 1.68s** on Python 3.14 (.venv).
    - Test coverage: **87.18%** (exceeding `--cov-fail-under=85`).
    - Ruff linting and compileall passed with 0 errors.
    - Zero inline `#` comments verified across all new and edited M3 files.

## 2026-11-03 — M2b Remediation Batch 1: Claude A Independent Audit
- Remediated all confirmed technical findings across 5 priorities from Claude A's independent adversarial audit:
  - **Priority 1 (Candle Integrity & Session Grid)**:
    - Introduced `ExchangeSession` and `DEFAULT_EXCHANGE_SESSION` (09:15-15:30 IST) abstraction.
    - Implemented `check_session_and_grid` validating intraday candles belong to trading days, sit within session hours, and align to interval grids (`OUTSIDE_SESSION`, `OFF_GRID_TIMESTAMP`).
    - Added overlapping candle detection (`OVERLAPPING_CANDLE` in `check_sequence_monotonicity`).
    - Preserved session-truncated bar closes (H1/M30 closing at 15:15 or 15:30, M10 at 15:25 or 15:30).
    - Enforced missing final session candle detection across date boundaries and historical queries ending at session close.
  - **Priority 2 (Historical Freshness & Future Boundaries)**:
    - Enforced `retrieval_timestamp <= now` in `ingest_latest` and `ingest_historical`.
    - In `ingest_historical`, decoupled historical backfills (`end_time < now`) from live queries (`end_time >= now`). Live queries strictly enforce `FreshnessPolicy`. Historical backfills disable live staleness limits but strictly enforce future-timestamp validation.
  - **Priority 3 (Recursive Immutability & DAG Memoization)**:
    - Replaced active-frame traversal with identity memoization (`_memo[id(obj)]`) to prevent $O(2^D)$ exponential blowup in shared DAG structures.
    - Added cycle detection using active stack (`_active_stack`), a node budget of 10,000, and a depth limit of 16.
    - Unified `_deep_freeze` in `models.py` and replaced duplicate implementations across `quality.py`, `provider.py`, and `ingestion.py`.
  - **Priority 4 (Coverage & Result Consistency)**:
    - Decoupled `TRUNCATED_COVERAGE` (boundary truncation, interior intraday missing bars) from `MARKET_CALENDAR_REQUIRED` (unaccounted multi-day jumps).
    - Enforced internal consistency of result invariants across all failure and success paths.
  - **Priority 5 (Additional Confirmed Defects)**:
    - Fixed D1 `close_time` calculation to ensure positive duration when timestamp is on or after session open.
    - Enforced strict whitespace rejection for numeric strings in `StandardDictAdapter` and `models.py`.
    - Added explicit `__hash__` and `__eq__` to `FreshnessPolicy` for hashability and dataclass compatibility.
  - **Regression Test Suite**: Added 18 comprehensive regression tests in `tests/test_claude_batch1_regressions.py`.
- Validation results:
  - Pytest full suite: **206 passed in 0.19s** on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 206 passed across all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-02 — M2b Historical Coverage Correctness & Sequence Continuity
- Authorized remediation of confirmed defect in historical sequence coverage handling (`ingest_historical`):
  - **Outer Boundary vs Interior Completeness**: Disentangled boundary coverage (`candles[0].timestamp <= start` and `candles[-1].close_time >= end`) from interior sequence completeness. Reused M2a's session-aware `check_sequence_integrity` to detect missing intermediate candles, consecutive missing candles, or entire missing intermediate trading days (`MISSING_INTERVAL` or `MARKET_CALENDAR_REQUIRED`).
  - **Fail-Closed on `require_full_coverage=True`**: When `require_full_coverage=True`, any boundary truncation or interior sequence gap immediately fails closed with `error_code="TRUNCATED_COVERAGE"` and `coverage_status="TRUNCATED_COVERAGE"`, even if `check_gaps=False` was passed by the caller.
  - **Empty Provider Response**: Provider returning 0 records explicitly reports `coverage_status="EMPTY_COVERAGE"` (was previously `COVERAGE_UNVERIFIED`) alongside `EMPTY_PROVIDER_RESPONSE`.
  - **Quality Gate Gap Detection Alignment**: When M2a quality gate rejects a sequence due to missing intervals or ambiguous calendar gaps, `coverage_status` accurately reflects `TRUNCATED_COVERAGE`.
  - **Preservation of `COVERAGE_UNVERIFIED`**: Kept only when boundary matches and interior continuity passes available checks without gaps, correctly reflecting that exchange calendar evidence is required to prove absence of holiday/special trading sessions.
  - **11 Regression Tests Added**:
    1. Complete 4-candle M5 sequence passing with `COVERAGE_UNVERIFIED`.
    2. Missing first candle failing closed with `TRUNCATED_COVERAGE`.
    3. Missing last candle failing closed with `TRUNCATED_COVERAGE`.
    4. Missing middle candle with `check_gaps=True` rejected with `TRUNCATED_COVERAGE`.
    5. Missing middle candle with `check_gaps=False` and `require_full_coverage=True` failing closed with `TRUNCATED_COVERAGE`.
    6. Multiple consecutive missing middle candles detected as interior gaps.
    7. Entire intermediate trading day missing (both intraday and D1) failing closed with `TRUNCATED_COVERAGE`.
    8. Empty provider response reporting `EMPTY_COVERAGE`.
    9. `require_full_coverage=False` with `check_gaps=False` returning partial sequence with `TRUNCATED_COVERAGE`.
    10. `require_full_coverage=True` failing closed on incomplete sequence.
    11. Session boundary truncation with H1, M30, and M10 intervals.
- Validation results:
  - Pytest full suite: **188 passed in 0.15s** on both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - Python compileall: passed with exit code 0 on both 3.11 and 3.14.
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 188 passed across all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-01 — M2b Python 3.11 & D1 Freshness Audit Remediation
- Remediated the two newly discovered defects from Claude's independent review of the M2b review bundle:
  - **Python 3.11 Dataclass Compatibility**: In `FreshnessPolicy`, changed mutable class attribute default `custom_limits: Mapping[CandleInterval, timedelta] = MappingProxyType({})` to standard `field(default_factory=lambda: MappingProxyType({}))`. In Python 3.11, `MappingProxyType` is unhashable (`__hash__ = None`), triggering `ValueError: mutable default ... use default_factory` during dataclass inspection at module import time. Verified that `field.default is MISSING` and `field.default_factory` evaluates cleanly without import crash on Python 3.11 and 3.14.
  - **Daily Candle Session Completion Semantics**: In `Candle.close_time` (`src/agentic_trading/market_data/models.py`), updated `D1` property logic to reflect Indian equity exchange session boundaries (NSE/BSE). For daily bars starting at session open (`09:15:00 IST`) or date start (`00:00:00 IST`), bar completion occurs at regular market close (`15:30:00 IST`) on that session date. Allows Monday EOD analysis at 18:30 IST to recognize the bar as completed rather than erroneously rejecting as `IN_PROGRESS_CANDLE` or `RETRIEVAL_BEFORE_CLOSE`.
  - **Session-Aware D1 Freshness & Calendar Ambiguity**: In `FreshnessPolicy.get_max_staleness`, removed hardcoded 72h weekend guess that previously accepted Friday data on Sunday (ignoring possible weekend trading like Diwali Muhurat sessions) and falsely rejected Friday data on Tuesday during a Monday-holiday scenario. Established that:
    1. Same calendar day (EOD post-close from 15:30 IST to midnight): fresh within 24h.
    2. Next consecutive calendar weekday (Mon->Tue, Tue->Wed, Wed->Thu, Thu->Fri overnight / pre-market): fresh within 24h.
    3. Multi-day gaps, weekends, and holidays: Fails closed with `MarketCalendarRequiredError` (`MARKET_CALENDAR_REQUIRED`) rather than guessing without exchange calendar evidence, unless the caller provides explicit `max_staleness` / `custom_limits`.
  - **Regression Tests**: Added and updated unit tests in `tests/test_market_data_ingestion.py` covering Monday EOD ingestion (09:15 and 00:00 opens), Tuesday pre-market ingestion, Sunday weekend fail-closed behavior, Tuesday holiday scenario with calendar reporting, and Python 3.11 dataclass introspection.
- Validation results:
  - Pytest full suite: **165 passed in 0.14s** on genuine Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
  - Ruff `src` and `tests`: passed (`All checks passed!`).
  - `compileall -q -f src tests`: passed (exit code 0).
  - `git diff --check`: passed (exit code 0).
  - Determinism across seeds `0, 42, 1337, 2026`: 165 passed on all runs.
- No git commits or pushes made; working tree preserved for independent review.

## 2026-11-01 — M2b Comprehensive Audit Remediation & Defense-in-Depth Hardening
- Completed comprehensive remediation of all high-, medium-, and low-severity audit findings on `feature/reliable-foundation`:
  - **H1 (Fail-open staleness and timing)**: Required timezone-aware `now` datetime in `ingest_latest`, `ingest_historical`, and `ingest_record` via private `_require_valid_now`. Rejects None, naive datetimes, or crashing tzinfo with `ValueError`. Applied consistent default 30-minute staleness (`DEFAULT_MAX_STALENESS`).
  - **H2 (Historical request-window enforcement)**: Pipeline independently enforces `[request.start_time, request.end_time)` window in `ingest_historical`, failing closed with `BOUNDARY_VIOLATION`. Introduced `coverage_status='COVERAGE_UNVERIFIED'` on `SequenceIngestionResult`.
  - **M1 (Identity-less raw payloads)**: Added `require_payload_identity: bool = False` to `StandardDictAdapter`. `MarketDataIngestionPipeline` defaults to `True`, rejecting anonymous payloads missing symbol/exchange/interval with `RawDataValidationError`.
  - **M2 (Provider exceptions & malformed responses)**: Caught `ProviderTimeoutError`, `ProviderConnectionError`, `ProviderPayloadError`, `ProviderError`, and unexpected exceptions (`PROVIDER_EXCEPTION`). Validated `ProviderResponse` envelope type and response retrieval timestamp timezone safety.
  - **M3 (Timezone safety consolidation)**: Consolidated timezone validation into `_require_valid_tz_dt` catching non-datetime types, naive instances, and crashing/None utcoffset calculations across models, requests, responses, and ingestion.
  - **M4 (Provenance correctness)**: `StandardDictAdapter` checks in-payload `source`, validating match with configured adapter source and rejecting contradictions with `RawDataValidationError`.
  - **M5 (Result consistency & immutability)**: Enforced `__post_init__` consistency in `IngestionResult` and `SequenceIngestionResult` (success forbids error fields; failure forbids valid candles). Raw payload dictionaries are deep-frozen via `MappingProxyType`.
  - **Low-Severity Remediation**: Synthetic provider `fetch_latest` raises `ValueError` if `now` omitted when empty; `fetch_historical` excludes unparseable/naive records during range filtering; filters by `exchange` and `interval`; adapter rejects conflicting timestamp aliases; eliminated private `_SYMBOL_REGEX` import; documented testing determinism.
  - **Documentation & Invariant Precision**: Unchecked premature snapshot fixture checkbox in `DEVELOPMENT_PLAN.md`; delineated synthetic sample generation vs stored replay fixtures vs historical session replay; documented risk-engine isolation demonstration vs pipeline integration.
- Validation results:
  - Pytest: **148 passed in 0.31s** (96 base + 10 pipeline integration + 42 M2b ingestion & audit regression tests).
  - Ruff `risk_engine`: passed (0 errors).
  - Ruff `market_data` & `tests`: passed (0 errors).
  - `compileall -q -f src tests`: passed (0 errors).
  - `git diff --check`: passed (0 whitespace/EOF errors).
- No commits or pushes made; stopped for review.

## 2026-11-03 — M2b Claude B Audit Remediation Batch 2 Engineering
- Addressed all confirmed defects from Claude B's independent audit report (`m2b-remediated-batch1-bundle.zip`, SHA-256 `005eb1c8b13df1b64f88cc076caba8539a8fc921fde6aac26a07c2eba3dd7043`):
  - **Priority 1 (Exchange & Session Architecture - H-1, COV-05, COV-07, COV-09)**:
    - Added `NYSE` and `NASDAQ` to `Exchange` enum with case-insensitive normalization.
    - Implemented US Eastern timezone with DST transition fallback (`_USEasternFallback`, `US_EASTERN`).
    - Added `for_exchange(exchange)` factory on `ExchangeSession`.
    - Made `Candle.close_time` dynamically resolve session hours per exchange, removing hardcoded IST/15:30.
    - Added `EXCHANGE_MISMATCH` check preventing cross-exchange candle/session mixing.
    - Supported D1/W1/MN1 grid anchor validation (`is_valid_grid_anchor`), rejecting off-grid intraday timestamps like 03:00 IST for daily candles.
    - Added `is_special` flag to `ExchangeSession` for non-standard trading sessions (e.g. Diwali Muhurat 18:15-19:15).
  - **Priority 2 (Fail-Closed Historical Coverage Contract - H-2, COV-01)**:
    - Configured `require_full_coverage: bool = True` and `allow_partial: bool = False` as default in `ingest_historical`.
    - Truncated or incomplete backfills fail closed with `success=False` and empty `candles=()`.
    - Explicit `allow_partial=True` populates `partial_candles` while strictly preserving `success=False` and `candles=()`, ensuring downstream trading engines cannot mistake partial data for successful backfills.
    - Introduced structured `CoverageStatus` enum (`FULL_COVERAGE`, `COVERAGE_UNVERIFIED`, `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, `EMPTY_COVERAGE`).
  - **Priority 3 (Correct & Bounded Deep Freezing - H-3, M-1)**:
    - Solved CPython memory address reuse on transient mapping keys in `_deep_freeze` by storing `(orig_obj, frozen_obj, subtree_depth)` in `_memo` and checking `orig_obj is cur`.
    - Counted every node (primitives + containers) against a hard budget `max_nodes=10000`, bounding traversal to `<2ms`.
    - Enforced `depth + subtree_depth > max_depth` when retrieving memoized DAG subtrees to prevent depth-limit circumvention.
  - **Priority 4 (Calendar Evidence & Historical Windows - M-2, COV-03, COV-08)**:
    - Introduced `ExchangeCalendar` abstraction.
    - Multi-day historical intervals spanning weekends or holidays without calendar evidence emit `MARKET_CALENDAR_REQUIRED`.
    - Intervening non-trading days verified by calendar pass cleanly.
    - Added `allow_sparse=True` contract for illiquid instruments.
  - **Priority 5 (Result-Object Invariant Hardening - M-4, ARCH-03)**:
    - Enforced `__post_init__` checks in `IngestionResult` (success strictly requires valid `validation_result`).
    - Enforced `__post_init__` checks in `SequenceIngestionResult` (rejects `"BOGUS"` coverage status, rejects `raw_record_count < len(candles)`, rejects `success=True` with `TRUNCATED_COVERAGE`, `EMPTY_COVERAGE`, or populated `partial_candles`).
  - **Priority 6 (Paper-Only Broker Controls & CI Hardening - SEC-01, SEC-03)**:
    - Wrapped Kite client in `_ReadOnlyKiteWrapper` and added explicit `place_order`, `modify_order`, `cancel_order` methods raising `PermissionError("Order placement is forbidden in paper-only mode")`.
    - SHA-pinned all GitHub actions in `.github/workflows/ci.yml` and added Python 3.11/3.12 testing matrix.
    - Ignored `.venv311/`, `.ruff_cache/`, `*.egg-info/` in `.gitignore`.
    - Replaced all broad `BLE001` (`except Exception:`) suppressions with explicit exception tuples.
- Validation results:
  - Genuine Python 3.11.9 (`.venv311`): **226 passed in 0.29s**.
  - Genuine Python 3.14.4 (`.venv`): **226 passed in 0.27s**.
  - Hash seed determinism (0, 42, 1337, 2026): all passed.
  - Ruff check (`src` and `tests`): 0 errors (`All checks passed!`).
  - Python compileall (`src` and `tests`): 0 errors on both 3.11 and 3.14.
  - Git working copy preserved; no commits or pushes made.

## Session 2026-11-03 (Session 9) — Claude C Audit Batch 3 Remediations
- Remediation scope:
  - **Priority 1 (Calendar evidence must never fail open)**:
    - Added `is_populated`, `has_evidence_for_date`, and `has_evidence_for_range` to `ExchangeCalendar`.
    - Unpopulated calendars return `is_populated is False` and never claim evidence or provide `FULL_COVERAGE`.
    - Reject candles occurring on declared exchange holidays with `DataQualityErrorCode.OUTSIDE_SESSION`.
    - Required calendar evidence covering the entire query window before reporting `FULL_COVERAGE`.
    - Differentiated verified holidays, missing calendar evidence (`MARKET_CALENDAR_REQUIRED`), and actual missing trading days (`MISSING_INTERVAL`).
  - **Priority 2 (Enforce Zerodha paper-only boundary)**:
    - Replaced denylist forwarding with strict `_READ_ONLY_ALLOWLIST` on `_ReadOnlyKiteWrapper`.
    - Blocked private attribute access (`_client`, `__client`, `_raw_client`) to underlying KiteConnect client.
    - Explicitly blocked `place_order`, `modify_order`, `cancel_order`, `exit_order`, `place_gtt`, `modify_gtt`, `delete_gtt`, `convert_position`, `place_mf_order`, `cancel_mf_order`, `_post`, `_request`, `_put`, `_delete` raising `PermissionError`.
    - Documented that Python in-process wrappers are software policy, not an OS sandbox.
  - **Priority 3 (Make coverage success trustworthy & explicit sparse mode)**:
    - Implemented `CoverageStatus.SPARSE_COVERAGE`.
    - Relaxed boundary edge-bar requirements when `allow_sparse=True`, supporting illiquid feeds without treating interior gaps as valid.
    - Implemented `require_full_coverage` contract: fails closed (`success=False`) on unverified (`COVERAGE_UNVERIFIED`) or sparse (`SPARSE_COVERAGE`) data.
  - **Priority 4 (CI and reproducibility)**:
    - Added multi-version CI matrix for Python 3.11, 3.12, 3.13, 3.14-dev in `.github/workflows/ci.yml`.
    - Configured Ruff with explicit rule selection (`F, E4, E7, E9, B, BLE, I`) in `pyproject.toml`.
    - Added coverage threshold (`--cov-fail-under=85`) and `pip-audit` security step.
    - Added architectural import boundary tests in `tests/test_import_boundaries.py`.
    - Created reproducible dependency lockfile `requirements.lock`.
  - **Priority 5 (Result-object constructor invariants)**:
    - Enforced `Candle` instance types in `SequenceIngestionResult.__post_init__`.
    - Enforced consistent symbol and exchange across all candles in sequence.
    - Validated strictly monotonic timestamps.
    - Forbade `success=True` with `TRUNCATED_COVERAGE`, `MARKET_CALENDAR_REQUIRED`, or `EMPTY_COVERAGE`.
    - Forbade single intraday candle claiming `FULL_COVERAGE`.
    - Forbade `success=False` with `FULL_COVERAGE`.
  - **Additional Correctness Fixes**:
    - MN1 monthly close: Exact calendar month boundaries using `calendar.monthrange` (handling Feb 28/29, 30/31 days).
    - US Eastern fallback: Raised explicit `ValueError` for historical dates prior to 2007.
    - D1 midnight boundaries: Handled midnight-ending requests consistently.
    - Caller-supplied `now`: Constrained injected `now` parameter against distant future timestamps > 365 days.
    - Exception safety: Replaced all broad `except Exception:` blocks with explicit exception tuples including `RuntimeError`.
- Validation results:
  - Genuine Python 3.11.9 (`.venv311`): **248 passed in 0.33s**.
  - Genuine Python 3.14.4 (`.venv`): **248 passed in 0.35s**.
  - Hash seed determinism (0, 42, 1337, 2026): all passed (248/248 passed on each seed).
  - Ruff check (`src` and `tests`): 0 errors (`All checks passed!`).
  - Python compileall (`src` and `tests`): 0 errors on both 3.11 and 3.14.
  - `git diff --check`: 0 errors.
  - Git working copy preserved; no commits or pushes made.

## Session 2026-11-07 — M2b Remediation Batch 4 (Final Blocker Resolution)
- **Goal:** Resolve remaining actionable findings from Claude D's Batch 3 independent audit (H-1, N-1, H-2, M-2, M-3).
- **Actions Completed:**
  - Hardened `zerodha_connector.py` via `__slots__ = ("__weakref__",)` and `WeakKeyDictionary` dispatch, eliminating all 9 demonstrated raw-client escape paths.
  - Corrected `ingestion.py` failure handling to prevent contradictory `FULL_COVERAGE` on rejected holiday candles, resolving unhandled `ValueError`.
  - Upgraded `models.py` `ExchangeCalendar` with explicit `complete: bool = False` contract and removed single-holiday year-level inference.
  - Made `.github/workflows/ci.yml` strictly enforceable (stable 3.14, blocking pip-audit, secret scanning, `--cov-fail-under=85`).
  - Rewrote `requirements.lock` with transparent zero-runtime-dependency specification.
  - Added 21 focused regression tests in `tests/test_claude_batch4_regressions.py`.
  - Achieved **87.12% genuine coverage** and **269 passed tests** on both Python 3.11.9 and 3.14.4.

## Session 2026-11-07 — M2b Remediation Batch 5 (Final Targeted Fixes)
- **Goal:** Resolve confirmed defects from Claude's Batch 4 targeted verification (F-1, F-2, F-3).
- **Actions Completed:**
  - **F-1 (Critical): Zerodha Raw-Client Exposure Removed:**
    - Removed module-level `_wrapper_clients`, `_connector_clients`, `_get_client_for_wrapper`, and `_get_client_for_connector`.
    - Implemented closure-held dispatch in `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` using `__slots__ = ("_dispatch", "__weakref__")`.
    - Blocked all reflection bypasses (`vars()`, `__dict__`, `object.__getattribute__`) via `__getattribute__` raising `PermissionError`.
    - Neutralized all order mutation methods on the underlying client instance upon initialization.
    - Verified all 20 allowlisted read-only methods remain accessible with `__self__ is wrapper`.
  - **F-2 (High): Incomplete Calendar Evidence Fails Closed:**
    - Bounded `ExchangeCalendar` auto-population of `coverage_start` and `coverage_end` from `trading_days` to occur ONLY when `complete=True`.
    - Enforced that when `complete=False`, `has_evidence_for_date(d)` returns `True` ONLY for explicitly declared dates.
    - Guaranteed that unlisted weekdays are NEVER verified as non-trading days when `complete=False`.
    - Ensured `has_evidence_for_range` fails closed unless every intermediate date has explicit evidence.
    - Verified that D1 and M5 sequence ingestion fail closed and reject `require_full_coverage=True` across NSE, BSE, NYSE, and NASDAQ.
  - **F-3 (Medium): Blocking Secret Scanning in CI:**
    - Generated `.secrets.baseline` in UTF-8 binary encoding at repository root with 0 leaked secrets.
    - Updated `.github/workflows/ci.yml` secret scanning step to run `detect-secrets-hook --baseline .secrets.baseline`, blocking CI on unmanaged secrets.
  - **Test Suite Isolation:**
    - Fixed test isolation in `tests/test_claude_batch4_regressions.py` and `tests/test_claude_batch2_regressions.py` where `sys.modules["keyring"]` was mocked without restoration.
    - Added 14 targeted adversarial tests in `tests/test_claude_batch5_regressions.py`.
- **Validation Results:**
  - Genuine Python 3.11.9 (`.venv311`): **283 passed in 0.93s** with **87.12% coverage** (`--cov-fail-under=85`).
  - Genuine Python 3.14.4 (`.venv`): **283 passed in 0.74s** with **87.12% coverage** (`--cov-fail-under=85`).
  - Ruff check (`src`, `tests`, `v3-zerodha/src`): **All checks passed!**
  - Python compileall (`src`, `tests`, `v3-zerodha/src`): **0 errors** on both Python versions.
  - `git diff --check`: **0 errors**.
  - All original bundles and working tree preserved; no Git commits or branch changes made.


## 2026-11-07 — Session: M2b Remediation Batch 6 Implementation & Verification

- **Task:** Remediate all confirmed technical defects from Claude A's Batch 5 audit report (REJECT on `m2b-remediated-batch5-bundle.zip`, SHA-256 `e708153be0bbbef6cbe7962f1d3e497e1bceb40704cfcd241be1057eac83013c`).
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `src/agentic_trading/market_data/models.py`
  - `src/agentic_trading/market_data/ingestion.py`
  - `.github/workflows/ci.yml`
  - `.secrets.baseline`
  - `tests/test_claude_batch2_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `tests/test_claude_batch5_regressions.py`
  - `tests/test_claude_batch6_regressions.py` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-017)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md`
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `docs/project-memory/AGENT_HANDOFF.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. Priority 1 (F1-A, F1-B, F1-D):
     - Redesigned Zerodha read-only boundary using slotted facade composition (`__slots__ = ("_target", "__weakref__")`).
     - Stopped mutating caller-supplied KiteConnect instances; caller methods and attributes remain 100% unmutated.
     - Added `ReadOnlyTransportAdapter(HTTPAdapter)` intercepting requests at transport level to block any non-GET request with `PermissionError`.
     - Implemented `ReadOnlyKiteConnect` which mounts `ReadOnlyTransportAdapter` and overrides `_request` and write methods.
     - Implemented bound method dispatch via `types.MethodType` ensuring `wrapper.method.__self__ is wrapper`.
     - Full API audit blocking all order methods, autoslice orders, GTT, MF, MF SIP, convert_position, session mutation (`generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`), and raw HTTP methods (`_post`, `_put`, `_delete`, `_request`).
     - Safe keyring helpers catch backend errors; missing or unconfigured keyrings never break connector construction.
  2. Priority 2 (F2-A, F2-B, F2-C):
     - Implemented contradiction rejection in `ExchangeCalendar.__post_init__` for trading_days/holidays overlap and special session conflicts.
     - Completeness contract: complete calendar requires explicit holiday evidence for omitted weekdays; incomplete calendar unlisted weekdays have no evidence and fail closed.
     - Incomplete calendar fail-closed: sequences across unverified multi-day gaps fail closed with exact error code `MARKET_CALENDAR_REQUIRED` and coverage status `CoverageStatus.MARKET_CALENDAR_REQUIRED.value`.
     - Ingestion across missing intermediate trading days without calendar evidence fails closed with exact error code `TRUNCATED_COVERAGE` and coverage status `TRUNCATED_COVERAGE`.
     - Tested across all four exchanges: NSE, BSE, NYSE, NASDAQ for D1 and M5 sequences.
  3. Priority 3 (F3-A, F3-B):
     - Anchored exclusion regex strictly avoids masking `.github/` or `.gitlab-ci.yml`.
     - Pinned `detect-secrets==1.5.0` in CI with `.secrets.baseline` containing version 1.5.0 and zero unbaselined secrets.
     - Verified detection of dummy AWS secrets across `.github/workflows/leak.yml`, `.github/leak.txt`, `.gitlab-ci.yml`, `src/leak.py`, `.env`, and nested ZIP files.
  4. Priority 4 & Verification:
     - Verified genuine `kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `pytest-cov`, and `ruff` in Python 3.11 (`.venv311`) and Python 3.14 (`.venv`).
     - Full test suite: **310 passed in 1.59s** on Python 3.11.9 and **310 passed in 0.84s** on Python 3.14.4.
     - Test coverage: **85.49%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
     - Generated separate test reports: `python311_verification_report.txt`, `python314_verification_report.txt`.
     - Ruff check passed with zero errors (`All checks passed!`).
     - Python compileall passed with zero errors on both interpreters.
     - `detect-secrets-hook` passed with zero errors across all tracked files.
     - `pip-audit` passed with zero known vulnerabilities.


## 2026-11-22 — Session: M2b Remediation Batch 7 Implementation & Verification

- **Task:** Remediate all 7 confirmed technical defects (D1–D7) from Claude's Batch 6 independent audit.
- **Specialist Sequence:** `agency-security-architect` -> `agency-backend-architect` -> `agency-reality-checker` -> `agency-code-reviewer`.
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `src/agentic_trading/market_data/ingestion.py`
  - `src/agentic_trading/market_data/models.py`
  - `pyproject.toml`
  - `requirements.lock`
  - `.github/workflows/ci.yml`
  - `.secrets.baseline`
  - `tests/test_claude_batch1_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `tests/test_claude_batch6_regressions.py`
  - `tests/test_market_data_ingestion.py`
  - `tests/test_claude_batch7_regressions.py` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-018)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md`
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. **D1 (Hide raw client completely):**
     - Removed `_target` from `__slots__` on `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (`__slots__ = ("__weakref__",)` only).
     - Stored underlying clients strictly in closure-encapsulated `WeakKeyDictionary` registries with zero instance attributes, zero slots, and zero module-level dictionaries.
     - Enforced `PermissionError` in `__getattribute__` for `_target`, `_client`, `__client`, `_raw_client`, `_dispatch`, `__dict__`, and `reqsession`.
     - Bound allowlisted read methods via `types.MethodType(bound_call, self)` ensuring `method.__self__ is wrapper`.
     - Preserved caller-supplied `KiteConnect` instances 100% unmutated.
  2. **D2 & D3 (Uniform session-mutation blocking):**
     - Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`.
     - Made `ZerodhaReadOnlyConnector.complete_login` consistently fail closed with `PermissionError`.
     - Updated previous tests to assert fail-closed behavior.
  3. **D4 (In-memory token bypass for locked keyrings):**
     - Updated `_require_session()` to verify in-memory `access_token` on the client first; read methods execute cleanly without querying keyring.
     - Keyring is queried only when no in-memory token exists, catching backend errors as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`.
  4. **D5 (Ingestion error code alignment):**
     - When `ingest_historical` encounters missing intermediate trading days (`MISSING_INTERVAL`), set both `coverage_status = "TRUNCATED_COVERAGE"` and `error_code = "TRUNCATED_COVERAGE"`.
     - Updated `ExchangeCalendar` docstring in `models.py` to clarify that unlisted weekdays do NOT count as non-trading days without explicit holiday evidence.
  5. **D6 & D7 (Secret scanning & dependency pinning):**
     - Removed `is_lock_file` filter from `.secrets.baseline` so lockfiles are actively scanned.
     - Removed stray `# pragma: allowlist secret` comment from `.github/workflows/ci.yml`.
     - Added `requests>=2.32.0` in `pyproject.toml`.
     - Populated `requirements.lock` with exact verified pins (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`).
     - Updated CI to install from `requirements.lock`.
  6. **Verification Evidence:**
     - Full test suite: **327 passed in 1.98s** on Python 3.11.9 (`.venv311`) and **327 passed in 0.89s** on Python 3.14.4 (`.venv`).
     - Test coverage: **85.55%** (exceeding mandatory 85% threshold with `--cov-fail-under=85`).
     - Generated separate test reports: `python311_verification_report.txt`, `python314_verification_report.txt`.
     - Ruff check passed with zero errors (`All checks passed!`).
     - Python compileall passed with zero errors on both interpreters.
     - `detect-secrets-hook` passed with zero errors across all tracked files, actively scanning `requirements.lock`.
     - `pip-audit` passed with zero known vulnerabilities.


## 2026-11-22 — Session: M2b Remediation Batch 7b Polish & Packaging

- **Task:** Remediate two targeted findings (F1, F3) from Claude's verification review of the Zerodha read-only boundary.
- **Files Modified:**
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`
  - `tests/test_claude_batch7_regressions.py`
  - `tests/test_claude_batch4_regressions.py`
  - `docs/project-memory/BATCH7B_VERIFICATION.md` (new)
  - `docs/project-memory/DECISION_LOG.md` (ADR-019)
  - `docs/project-memory/CURRENT_STATE.md`
  - `docs/project-memory/ISSUES_AND_RISKS.md` (R-034, R-035)
  - `docs/project-memory/NEXT_ACTIONS.md`
  - `docs/project-memory/SESSION_LOG.md`
  - `AUDIT_BRIEF.md`
- **Actions Taken:**
  1. **F1 (Zero mutation of caller-injected clients):**
     - Stored `(client, injected: bool)` tuple in closure-encapsulated `_connector_registry`.
     - In `_require_session()`: if `injected` is True, verified `raw_client.access_token` is already a non-empty string; if missing/empty, raises `KiteConfigurationError("Injected client must be pre-authenticated with an active access_token")` without calling `set_access_token()` or querying keyring.
     - In `logout()`: if `injected` is True, deleted only local keyring token and left caller client completely untouched.
     - Injected genuine `KiteConnect.__dict__` and `reqsession.headers` verified identical before and after wrapping, reading, and `logout()`.
  2. **F3 (Block POST margin/contract-note endpoints):**
     - Removed `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`.
     - Added explicit method overrides on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` before transport.
     - Added messages in `_OPERATION_MESSAGES`.
  3. **Regression Tests:**
     - Added 11 new tests in `tests/test_claude_batch7_regressions.py` covering F1, F3, and wrapper edge cases.
     - Total tests in suite: **338 passed** across both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
     - Test coverage: **85.02%** (exceeds `--cov-fail-under=85`).
  4. **Quality Gates:**
     - Ruff check: 0 errors (`All checks passed!`).
     - Compileall: 0 errors on both 3.11 and 3.14.
     - detect-secrets hook: 0 unbaselined leaks across all tracked files, scanning `requirements.lock`.
     - pip-audit: 0 known vulnerabilities.
  5. **Packaging:**
     - Packaged `m2b-remediated-batch7b-bundle.zip` in parent directory and computed SHA-256 hash.


## 2026-11-22 — Session: Milestone 2c (Cross-Market Foundation, Instrument Registry, Corporate Actions, and Stored Replay Fixtures)

- **Task:** Implement Milestone 2c on `feature/reliable-foundation` across 4 specialist roles (`agency-backend-architect` -> `agency-security-architect` -> `agency-reality-checker` -> `agency-code-reviewer`) adhering strictly to paper-only constraints and zero inline `#` comments.
- **Files Created/Modified:**
  - `src/agentic_trading/market_data/instruments.py` (new)
  - `src/agentic_trading/market_data/corporate_actions.py` (new)
  - `src/agentic_trading/market_data/replay_fixtures.py` (new)
  - `src/agentic_trading/market_data/__init__.py` (modified: clean exports)
  - `tests/test_m2c_cross_market_foundation.py` (new: 24 adversarial tests)
  - `docs/project-memory/DECISION_LOG.md` (ADR-020)
  - `docs/project-memory/CURRENT_STATE.md` (updated)
  - `docs/project-memory/NEXT_ACTIONS.md` (updated)
  - `docs/project-memory/SESSION_LOG.md` (updated)
- **Actions Taken:**
  1. **Cross-Market Instruments & Currency Isolation (`instruments.py`):**
     - Defined `Currency` enum (`INR`, `USD`) and `CurrencyMismatchError`.
     - Implemented immutable `Money` dataclass with strict currency safety: validates non-negative finite `Decimal`, rejects `float`, `bool`, and `bytes`. Addition and subtraction require matching currency; scalar multiplication supports `Decimal` and `int` (rejecting `float`/`bool`).
     - Defined `AssetClass` (`EQUITY`, `COMMODITY`, `INDEX`, `FOREX`, `CRYPTO`).
     - Implemented `Instrument` with strict exchange-currency pairing validation (`NSE`/`BSE` requires `INR`; `NYSE`/`NASDAQ` requires `USD`), positive finite `tick_size`, positive integer `lot_size`, and immutable `provider_tokens` dictionary (`MappingProxyType`).
     - Implemented `InstrumentRegistry` with duplicate detection, thread-safe lookup, and O(1) resolution by `(exchange, symbol)` or `(provider, token)` failing closed with `UnknownInstrumentError`.
  2. **Corporate Actions & Symbol Lineage (`corporate_actions.py`):**
     - Modeled `CorporateAction` and `CorporateActionType` (`SPLIT`, `BONUS`, `DIVIDEND`, `SYMBOL_CHANGE`).
     - Implemented `resolve_symbol_lineage` to trace rename histories bidirectionally with topological graph cycle detection (`ValueError`).
     - Implemented `adjust_candles_for_corporate_actions` applying cumulative adjustment factors to historical OHLC, preserving OHLC invariants, quantizing prices to `tick_size` using `ROUND_HALF_EVEN`, and inverse-scaling volumes.
  3. **Tier-2 Stored Replay Fixtures (`replay_fixtures.py`):**
     - Defined `FixtureManifest` with SHA-256 payload digest.
     - Implemented `save_replay_fixture` with canonical JSON serialization, path-traversal prevention, and atomic manifest generation.
     - Implemented `StoredReplayFixtureProvider` extending `MarketDataProvider`: cryptographically verifies raw payload integrity on load via `hmac.compare_digest` against manifest SHA-256 (raising `FixtureIntegrityError` on tampering or mismatch), and provides deterministic `[start_time, end_time)` window filtering.
  5. **Adversarial Regression Tests (`test_m2c_cross_market_foundation.py`):**
     - 24 comprehensive tests covering currency arithmetic, instrument validation, duplicate prevention, corporate action price/volume adjustment, cyclic rename graph rejection, and replay fixture tampering/mismatch detection.
     - 0 inline `#` comments in all code and test files.
- **Verification Evidence:**
  - Full pytest suite: **362 passed in 4.67s** on Python 3.11.9 (`.venv311`) and **362 passed in 2.06s** on Python 3.14.4 (`.venv`).
  - Total test coverage: **86.56%** (exceeds mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff check: clean (0 errors) on `src`, `tests`, and `v3-zerodha/src`.
  - Python compileall: 0 errors on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` clean (0 leaks).
  - Comment check: verified 0 `#` comment characters across all 5 new/edited files.


## 2026-11-22 — Session: Milestone 3 (Append-Only Ledger, Multi-Currency Portfolio, Cost Models, Strategy Contracts & Deterministic Risk Gate)

- **Task:** Implement Milestone 3 on `feature/reliable-foundation` sequentially across 5 specialist roles (`agency-backend-architect` -> `agency-ai-engineer` -> `agency-security-architect` -> `agency-reality-checker` -> `agency-code-reviewer`) adhering strictly to paper-only constraints and zero inline `#` comments.
- **Files Created/Modified:**
  - `src/agentic_trading/market_data/instruments.py` (updated: point-in-time listed/delisted date survivorship guards, `is_active_on`, `get_as_of`, `list_active_on`)
  - `src/agentic_trading/market_data/corporate_actions.py` (updated: `announcement_date` validation, `as_of_date` look-ahead filtering)
  - `src/agentic_trading/simulation/ledger.py` (new: strictly append-only `AccountingLedger` and immutable `LedgerEntry`)
  - `src/agentic_trading/simulation/costs.py` (new: `IndiaEquityFeeModel`, `USEquityFeeModel`, `ZeroFeeModel`, `BasisPointsSlippageModel`)
  - `src/agentic_trading/simulation/portfolio.py` (new: multi-currency `PortfolioEngine`, `Position`, `PortfolioSnapshot`, `InsufficientFundsError`)
  - `src/agentic_trading/simulation/__init__.py` (new: simulation exports)
  - `src/agentic_trading/strategy/contracts.py` (new: `SignalDirection`, `BarContext`, `Signal`, `TradeProposal`, `Strategy`)
  - `src/agentic_trading/strategy/indicators.py` (new: pure deterministic `sma`, `ema`, `rsi`, `atr` with warmup checks)
  - `src/agentic_trading/strategy/__init__.py` (new: strategy exports)
  - `src/agentic_trading/risk_engine/core.py` (new: original `OrderProposal`, `Side`, `evaluate_order`, `RiskDecision`)
  - `src/agentic_trading/risk_engine/proposal_gate.py` (new: `PortfolioRiskPolicy`, `ProposalRiskDecision`, authoritative `evaluate_trade_proposal`)
  - `src/agentic_trading/risk_engine/__init__.py` (new: risk engine exports)
  - `src/agentic_trading/risk_engine.py` (updated: module bridge for backward compatibility)
  - `tests/test_m3_simulation_and_risk.py` (new: 16 comprehensive adversarial tests with zero `#` comments)
  - `tests/test_import_boundaries.py` (updated: directory-aware risk engine boundary test)
  - `docs/project-memory/AI_MASTER_CONTEXT.md` (new: master reconciled architectural context)
  - `docs/project-memory/DECISION_LOG.md` (ADR-021)
  - `docs/project-memory/CURRENT_STATE.md` (updated)
  - `docs/project-memory/NEXT_ACTIONS.md` (updated)
  - `docs/project-memory/SESSION_LOG.md` (updated)
- **Actions Taken:**
  1. **Point-in-Time Universe & Corporate Action Look-Ahead Guards (`instruments.py`, `corporate_actions.py`):**
     - Added `listed_date`, `delisted_date`, `version`, and `is_active_on` to `Instrument`.
     - Added `get_as_of` and `list_active_on` to `InstrumentRegistry`, raising `UnknownInstrumentError` for inactive instruments.
     - Added `announcement_date` to `CorporateAction` and `as_of_date` filtering to `adjust_candles_for_corporate_actions`.
  2. **Append-Only Accounting Ledger & Transaction Costs (`simulation/`):**
     - Implemented `AccountingLedger` and immutable `LedgerEntry` with sequence ID monotonicity and causal timestamp enforcement.
     - Implemented statutory `IndiaEquityFeeModel` (brokerage caps, STT, exchange txn fee, SEBI fee, stamp duty, GST) and `USEquityFeeModel` (commission min/cap, SEC fee, FINRA TAF).
     - Implemented `BasisPointsSlippageModel` with tick_size quantization.
     - Implemented `PortfolioEngine` guaranteeing strict accounting conservation: Deposits - Withdrawals + Realized PnL - Fees == Cash + Cost Basis of Open Positions.
  3. **Strategy Contracts & Technical Indicators (`strategy/`):**
     - Implemented `BarContext` with strict causal look-ahead guard rejecting future bar closes (`candle.close_time > decision_time`).
     - Defined `SignalDirection`, `Signal`, `TradeProposal`, and `Strategy` ABC.
     - Implemented pure deterministic `sma`, `ema`, `rsi`, and `atr` functions with explicit warmup checks.
  4. **Authoritative Deterministic Risk Gate (`risk_engine/`):**
     - Packaged risk engine into `core` and `proposal_gate`.
     - Implemented `evaluate_trade_proposal` failing closed on currency mismatches, lot size violations, missing/reversed stop-losses, per-trade risk limits, concentration caps, total exposure limits, daily loss limits, and drawdown circuit breakers.
  5. **Adversarial Verification:**
     - 16 adversarial tests in `tests/test_m3_simulation_and_risk.py` with zero inline `#` comments.
- **Verification Evidence:**
  - Full pytest suite: **378 passed in 2.99s** on Python 3.11.9 (`.venv311`) and **378 passed in 2.07s** on Python 3.14.4 (`.venv`).
  - Total test coverage: **87.89%** (exceeds mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff check: clean (0 errors) across all packages and tests.
  - Python compileall: 0 errors on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` clean (0 leaks).
  - Comment check: verified 0 `#` comment characters across all M3 files.

## 2026-11-22 — M3 Hardening Batch B: Replay Fixture Integrity, BarContext Guards & Zerodha Transport Hardening
- **Task:** Implement Milestone 3 Hardening Batch B covering findings H5, H6, H7, L7, M7, M8, M9, L3, L4, L5, and L8 across 4 specialist roles (`agency-security-architect` -> `agency-backend-architect` -> `agency-reality-checker` -> `agency-code-reviewer`).
- **Files Modified:**
  - `src/agentic_trading/market_data/replay_fixtures.py`: H5 historical filter mismatch returns empty records; H6 close-time window slicing (`close_time <= end_time` and `close_time <= now`) preventing look-ahead of in-progress bars; H7 & L7 keyed HMAC-SHA256 (`_compute_fixture_hmac`) covering canonical manifest metadata + payload, `overwrite=False` raising `FixtureIntegrityError`, `allow_nan=False` serialization, manifest field validation, and fail-closed missing timestamp detection (`ProviderPayloadError`).
  - `src/agentic_trading/strategy/contracts.py`: M7 `BarContext.__post_init__` enforcing strictly increasing bar timestamps, uniform intervals, positive OHLC prices, high/low bounds (`high >= max(open, close)` and `low <= min(open, close)`), and non-negative volume.
  - `src/agentic_trading/strategy/indicators.py`: M8 `rsi` returns `Decimal("50")` on flat zero-volatility price series (avg_gain == 0 and avg_loss == 0).
  - `src/agentic_trading/market_data/corporate_actions.py`: M9 deduplicate identical `CorporateAction` entries before computing cumulative factor in `adjust_candles_for_corporate_actions`; L5 scope cycle detection in `resolve_symbol_lineage` strictly to connected component of target symbol.
  - `src/agentic_trading/market_data/instruments.py`: L3 `threading.RLock` protecting all `InstrumentRegistry` reads and writes; L4 reject `datetime` instances in `Instrument.is_active_on`, `InstrumentRegistry.get_as_of`, and `InstrumentRegistry.list_active_on` with `TypeError`.
  - `v3-zerodha/src/agentic_trading/zerodha_connector.py`: `ReadOnlyKiteConnect._request` aligned to kiteconnect signature (`route, method, url_args=None, params=None, is_json=False, query_params=None`), blocking non-GET methods before transport; L8 `ZerodhaReadOnlyConnector.logout()` on injected client is an immediate no-op, preserving caller client and keyring token.
  - `tests/test_m2c_cross_market_foundation.py`: added 7 regression tests for H5, H6, H7, L7, M9, L5, L3, L4.
  - `tests/test_m3_simulation_and_risk.py`: added regression tests for M7 and M8.
  - `tests/test_zerodha_kiteconnect_integration.py`: added regression tests for `_request` signature/blocking and injected client `logout()` isolation.
  - `tests/test_claude_batch4_regressions.py`: updated test assertion to verify `delete_password.assert_not_called()` on injected logout per L8.
  - `docs/project-memory/DECISION_LOG.md`: recorded ADR-023.
  - `docs/project-memory/CURRENT_STATE.md`: updated status to 400 passed tests.
  - `docs/project-memory/NEXT_ACTIONS.md`: updated with Batch B completion.
  - `docs/project-memory/SESSION_LOG.md`: recorded this session.
- **Verification Evidence:**
  - Full pytest suite: **400 passed in 2.54s** on Python 3.11.9 (`.venv311`) and **400 passed in 2.06s** on Python 3.14.4 (`.venv`).
  - Total test coverage: **87.18%** (exceeds mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff check: clean (0 errors) across `src/`, `tests/`, and `v3-zerodha/src/`.
  - Python compileall: clean (0 errors) on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` clean (0 leaks).
  - Comment check: verified 0 `#` comment characters across all new and edited Python code and tests.

## 2026-11-23 — Session: Milestone 4 (Time Machine) Implementation
- **Scope:** new package `src/agentic_trading/time_machine/` (`__init__`, `manifest`, `metrics`, `engine`, `validation`, `monte_carlo`), `tests/test_m4_time_machine.py`, ADR-026, and updates to `AUDIT_BRIEF.md`, `CURRENT_STATE.md`, `DECISION_LOG.md`, `NEXT_ACTIONS.md`. No M3 source files were modified. No git operations were performed.
- **Environment limits:** work done in a Linux Python 3.12 sandbox from `full-project-m3-final-bundle.zip` (SHA-256 `e3d4693cfe09b812985952ee75396601f450acea4c99392491a42dd35a1d6b5b`, verified). No git metadata, no `.venv311` / `.venv`, no network.
- **Evidence:** 25/25 M4 tests pass under a minimal local `pytest` stand-in; 9/9 deliberate mutations detected; `compileall -q src tests v3-zerodha/src` clean on 3.12; zero `#` comment tokens in new Python files (asserted by test).
- **Not run:** Ruff, real pytest, full-suite regression, coverage gate, detect-secrets, Python 3.11/3.14 runs.

## 2026-11-24 — Session: Milestone 8 Workstation Upgrade (ADR-038 & ADR-039) & Release v1.0.0
- **Scope:**
  - Implemented ADR-038: Auto-Buy Toggle, AI Buy/Sell Price Plan Cards, and HTML5 `<canvas id="candlestickCanvas">` Candlestick Chart with AI Overlays.
  - Implemented ADR-039: Concrete Strategy Library (`src/agentic_trading/strategy/library.py` and `__init__.py` with `EMAPullbackStrategy`, `RSIMeanReversionStrategy`, `ATRBreakoutStrategy`, `SmaCrossStrategy`, and `STRATEGY_REGISTRY`), Open Positions tracking (`GET /api/positions`) & One-Click Sell liquidation (`POST /api/positions/close`), Strategy-selectable Time Machine backtesting with visual line chart `<canvas id="equityCurveCanvas">` (`POST /api/backtest`), SQLite-backed Trading Lessons Manager (`GET /api/lessons`, `POST /api/lessons`), and Safeguarded Paper Sandbox Reset (`POST /api/sandbox/reset`).
  - Extended local single-page dashboard (`src/agentic_trading/api/dashboard.py`) with Reset Sandbox button in header, Strategy dropdown beside Run Backtest, and 3 new tabs (`Positions`, `Backtest`, `Lessons`) rendered strictly via `document.createElement` and `textContent`.
  - Added comprehensive regression suite `tests/test_m8_workstation_features.py` (7 tests).
- **Verification Evidence:**
  - Full pytest suite: **507 passed in 15.68s** on Python 3.11.9 (`.venv311`) and **507 passed in 12.69s** on Python 3.14.4 (`.venv`).
  - Total test coverage: **88.35%** (exceeds mandatory 85% requirement with `--cov-fail-under=85`).
  - Ruff check: clean (0 errors) across `src/`, `tests/`, and `v3-zerodha/src/`.
  - Python compileall: clean (0 errors) on both Python 3.11 and 3.14.
  - Secret scanning: `detect-secrets-hook --baseline .secrets.baseline` clean (0 leaks).
  - Comment check: verified 0 `#` comment characters across all new and edited Python code and tests.
  - Import boundaries check: all domain boundary invariant tests passed cleanly.
