"""Self-contained local-first HTML dashboard for monitoring paper portfolios and running simulations."""
from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agentic Trading Lab — Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-alt: #172554;
      --border: #334155;
      --border-focus: #38bdf8;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --danger: #ef4444;
      --danger-hover: #dc2626;
      --danger-bg: rgba(239, 68, 68, 0.15);
      --danger-border: rgba(239, 68, 68, 0.4);
      --success: #22c55e;
      --success-bg: rgba(34, 197, 94, 0.15);
      --success-border: rgba(34, 197, 94, 0.35);
      --amber: #eab308;
      --amber-bg: rgba(234, 179, 8, 0.15);
      --amber-border: rgba(234, 179, 8, 0.35);
      --purple: #a855f7;
      --purple-bg: rgba(168, 85, 247, 0.15);
      --purple-border: rgba(168, 85, 247, 0.35);
      --blue-bg: rgba(56, 189, 248, 0.15);
      --blue-border: rgba(56, 189, 248, 0.35);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 28px 16px;
    }
    .container {
      max-width: 1120px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 12px;
    }
    .header-left h1 {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .header-subtitle {
      font-size: 0.78rem;
      color: var(--text-dim);
    }
    .header-right {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      padding: 3px 9px;
      border-radius: 9999px;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.03em;
    }
    .pill-amber { background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber-border); }
    .pill-success { background: var(--success-bg); color: var(--success); border: 1px solid var(--success-border); }
    .pill-danger { background: var(--danger-bg); color: #fca5a5; border: 1px solid var(--danger-border); }
    .pill-blue { background: var(--blue-bg); color: var(--accent); border: 1px solid var(--blue-border); }
    .pill-purple { background: var(--purple-bg); color: var(--purple); border: 1px solid var(--purple-border); }
    .pill-slate { background: rgba(148, 163, 184, 0.12); color: var(--text-muted); border: 1px solid var(--border); }
    .pill-group {
      display: inline-flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }
    .status-indicator {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--text-muted);
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
    }
    .status-indicator.stopped .status-dot { background: var(--danger); }
    .status-indicator.stopped { color: var(--danger); }
    .btn {
      cursor: pointer;
      font-weight: 600;
      border-radius: 6px;
      padding: 7px 13px;
      font-size: 0.83rem;
      border: 1px solid transparent;
      transition: background-color 0.15s, opacity 0.15s;
    }
    .btn:hover { opacity: 0.92; }
    .btn:active { transform: scale(0.98); }
    .btn-primary { background: var(--accent); color: #0f172a; }
    .btn-secondary { background: #334155; color: var(--text); border-color: var(--border); }
    .btn-secondary:hover { background: #475569; }
    .btn-ghost { background: transparent; color: var(--text-muted); border-color: var(--border); }
    .btn-ghost:hover { background: #1e293b; color: var(--text); }
    .btn-danger-outline { background: var(--danger-bg); color: #fca5a5; border-color: var(--danger-border); }
    .btn-danger-outline:hover { background: rgba(239, 68, 68, 0.25); }
    .btn-success-outline { background: var(--success-bg); color: #86efac; border-color: var(--success-border); }
    .btn-sm { padding: 4px 8px; font-size: 0.75rem; }
    .cycle-strip {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 18px;
      margin-bottom: 20px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .cycle-strip-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }
    .cycle-label {
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--accent);
    }
    .cycle-switcher {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .cycle-switcher select {
      background: #0f172a;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 5px 10px;
      border-radius: 6px;
      font-size: 0.8rem;
      max-width: 260px;
    }
    .cycle-strip-details {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      font-size: 0.82rem;
      color: var(--text-muted);
    }
    .cycle-detail-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .cycle-detail-item strong {
      color: var(--text);
    }
    .portfolio-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .card-title {
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .card-tag {
      font-size: 0.74rem;
      color: var(--text-dim);
    }
    .equity-figure {
      font-size: 1.7rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 12px;
      font-variant-numeric: tabular-nums;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      font-size: 0.83rem;
    }
    .metric-row:last-child { border-bottom: none; }
    .metric-name { color: var(--text-muted); }
    .metric-num { font-weight: 600; font-variant-numeric: tabular-nums; }
    .warning-badge {
      margin-top: 10px;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 600;
      background: var(--danger-bg);
      color: #fca5a5;
      border: 1px solid var(--danger-border);
    }
    .action-bar {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 20px;
    }
    .action-buttons {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .switch-container {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
      font-size: 0.82rem;
      font-weight: 600;
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid var(--border);
      padding: 5px 12px;
      border-radius: 9999px;
      transition: border-color 0.15s;
    }
    .switch-container:hover {
      border-color: var(--border-focus);
    }
    .switch-input {
      display: none;
    }
    .switch-slider {
      position: relative;
      width: 34px;
      height: 18px;
      background: #334155;
      border-radius: 9999px;
      transition: background-color 0.2s;
    }
    .switch-slider::before {
      content: "";
      position: absolute;
      top: 2px;
      left: 2px;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: #f8fafc;
      transition: transform 0.2s;
    }
    .switch-input:checked + .switch-slider {
      background: var(--accent);
    }
    .switch-input:checked + .switch-slider::before {
      transform: translateX(16px);
      background: #0f172a;
    }
    .switch-label {
      color: var(--accent);
      font-size: 0.78rem;
      letter-spacing: 0.02em;
    }
    .settings-panel {
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
      background: var(--card-bg);
      border: 1px solid var(--border);
      padding: 12px 16px;
      border-radius: 8px;
    }
    .setting-group {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.82rem;
      color: var(--text-muted);
    }
    .setting-group select, .setting-group input {
      background: #0f172a;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 5px 9px;
      border-radius: 5px;
      font-size: 0.82rem;
    }
    .tabs-bar {
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
    }
    .tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      padding: 8px 16px;
      font-size: 0.88rem;
      font-weight: 600;
      cursor: pointer;
      transition: color 0.15s, border-color 0.15s;
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .overview-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }
    .section-title {
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .badge-cluster {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-height: 32px;
      align-items: center;
    }
    .plans-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }
    .plans-table th {
      text-align: left;
      padding: 8px 10px;
      color: var(--text-dim);
      border-bottom: 1px solid var(--border);
      font-weight: 500;
    }
    .plans-table td {
      padding: 8px 10px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      vertical-align: middle;
    }
    .plans-table tr:last-child td { border-bottom: none; }
    .price-buy { color: var(--accent); font-weight: 600; font-variant-numeric: tabular-nums; }
    .price-target { color: var(--success); font-weight: 600; font-variant-numeric: tabular-nums; }
    .price-stop { color: #fca5a5; font-weight: 600; font-variant-numeric: tabular-nums; }
    .ticker-pill-btn {
      cursor: pointer;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 0.74rem;
      font-weight: 600;
      border: 1px solid var(--border);
      background: rgba(148, 163, 184, 0.1);
      color: var(--text-muted);
      transition: all 0.15s;
    }
    .ticker-pill-btn:hover { background: rgba(56, 189, 248, 0.15); color: var(--accent); }
    .ticker-pill-btn.active {
      background: var(--blue-bg);
      color: var(--accent);
      border-color: var(--border-focus);
    }
    .chart-readout {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.76rem;
      color: #94a3b8;
      padding: 6px 12px;
      background: #080d1a;
      border-radius: 6px;
      border: 1px solid #172033;
      margin-top: 8px;
      margin-bottom: 8px;
      min-height: 32px;
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .orders-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }
    .orders-table th {
      text-align: left;
      padding: 6px 8px;
      color: var(--text-dim);
      border-bottom: 1px solid var(--border);
      font-weight: 500;
    }
    .orders-table td {
      padding: 6px 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    }
    .orders-table tr:last-child td { border-bottom: none; }
    .chat-stream {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .chat-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .chat-card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      padding-bottom: 8px;
    }
    .chat-card-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .chat-step-badge {
      font-family: monospace;
      font-size: 0.72rem;
      color: var(--accent);
      font-weight: 700;
    }
    .chat-stage-badge {
      font-weight: 600;
      font-size: 0.8rem;
      color: var(--text);
    }
    .chat-bubble-container {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
    }
    .chat-bubble {
      background: #0b1120;
      border: 1px solid #1e293b;
      border-radius: 6px;
      padding: 10px 12px;
    }
    .chat-bubble-title {
      font-size: 0.74rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-dim);
      margin-bottom: 6px;
    }
    .chat-bubble pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.78rem;
      color: #cbd5e1;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.45;
      max-height: 260px;
      overflow-y: auto;
    }
    .raw-report-details {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      margin-top: 16px;
    }
    .raw-report-details summary {
      cursor: pointer;
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--text-muted);
      user-select: none;
    }
    .raw-report-details summary:hover { color: var(--text); }
    .raw-report-pre {
      margin-top: 10px;
      background: #080d1a;
      border: 1px solid #172033;
      padding: 12px;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.8rem;
      color: #cbd5e1;
      white-space: pre-wrap;
      max-height: 400px;
      overflow-y: auto;
      line-height: 1.5;
    }
    .empty-placeholder {
      padding: 24px;
      text-align: center;
      color: var(--text-dim);
      font-size: 0.85rem;
    }
    .status-banner {
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      margin-bottom: 16px;
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-left">
        <h1>Agentic Trading Lab</h1>
        <div class="header-subtitle">Local-First Simulation &amp; 7-Agent Research Desk</div>
      </div>
      <div class="header-right">
        <span class="pill pill-amber">PAPER TRADING ONLY</span>
        <span id="killStatusIndicator" class="status-indicator">
          <span class="status-dot"></span>
          <span id="killStatusText">Active</span>
        </span>
        <button id="toggleKillBtn" class="btn btn-danger-outline">Emergency Stop</button>
        <button id="resetSandboxBtn" class="btn btn-ghost btn-sm" style="color:var(--text-dim);">Reset Sandbox</button>
      </div>
    </header>

    <div class="cycle-strip">
      <div class="cycle-strip-top">
        <div class="cycle-label">Reviewing Paper Trading Cycle</div>
        <div class="cycle-switcher">
          <label for="cycleSelect" style="font-size:0.78rem;color:var(--text-muted);">Cycle History:</label>
          <select id="cycleSelect">
            <option value="">No cycles loaded</option>
          </select>
        </div>
      </div>
      <div class="cycle-strip-details">
        <div class="cycle-detail-item"><strong>ID:</strong> <span id="cycleIdText" style="font-family:monospace;color:var(--text);">—</span></div>
        <div class="cycle-detail-item"><strong>Time:</strong> <span id="cycleTimeText">—</span></div>
        <div class="cycle-detail-item"><strong>Market:</strong> <span id="cycleMarketText">—</span></div>
        <div class="cycle-detail-item"><strong>Auto-Buy:</strong> <span id="cycleAutoBuyPill" class="pill pill-blue">—</span></div>
        <div class="cycle-detail-item"><strong>Feed:</strong> <span id="cycleFeedPill" class="pill pill-blue">—</span></div>
        <div class="cycle-detail-item"><strong>Context:</strong> <span id="cycleContextPill" class="pill pill-blue">—</span></div>
        <div class="cycle-detail-item"><strong>Model:</strong> <span id="cycleModelPill" class="pill pill-purple">—</span></div>
        <div class="cycle-detail-item"><strong>Watchlist:</strong> <span id="cycleWatchlistGroup" class="pill-group"></span></div>
      </div>
    </div>

    <div class="portfolio-grid">
      <div class="card" id="inrCard">
        <div class="card-head">
          <span class="card-title">INR Portfolio</span>
          <span class="card-tag">NSE / BSE</span>
        </div>
        <div class="equity-figure" id="inrEquity">—</div>
        <div class="metric-row"><span class="metric-name">Cash</span><span class="metric-num" id="inrCash">—</span></div>
        <div class="metric-row"><span class="metric-name">Holdings</span><span class="metric-num" id="inrHoldings">—</span></div>
        <div class="metric-row"><span class="metric-name">Realized P&amp;L</span><span class="metric-num" id="inrRealized">—</span></div>
        <div class="metric-row"><span class="metric-name">Open Positions</span><span class="metric-num" id="inrPosCount">—</span></div>
        <div id="inrWarning" class="warning-badge" style="display: none;"></div>
      </div>

      <div class="card" id="usdCard">
        <div class="card-head">
          <span class="card-title">USD Portfolio</span>
          <span class="card-tag">NYSE / NASDAQ</span>
        </div>
        <div class="equity-figure" id="usdEquity">—</div>
        <div class="metric-row"><span class="metric-name">Cash</span><span class="metric-num" id="usdCash">—</span></div>
        <div class="metric-row"><span class="metric-name">Holdings</span><span class="metric-num" id="usdHoldings">—</span></div>
        <div class="metric-row"><span class="metric-name">Realized P&amp;L</span><span class="metric-num" id="usdRealized">—</span></div>
        <div class="metric-row"><span class="metric-name">Open Positions</span><span class="metric-num" id="usdPosCount">—</span></div>
        <div id="usdWarning" class="warning-badge" style="display: none;"></div>
      </div>
    </div>

    <div class="action-bar">
      <div class="action-buttons">
        <button id="runDeskBtn" class="btn btn-primary">Run Desk</button>
        <label class="switch-container" title="When ON, approved proposals automatically submit paper orders. When OFF, plans remain in READY TO BUY state for manual confirmation.">
          <input type="checkbox" id="autoBuyToggle" class="switch-input" checked>
          <span class="switch-slider"></span>
          <span id="autoBuyLabel" class="switch-label">Auto-Buy ON</span>
        </label>
        <button id="runBacktestBtn" class="btn btn-secondary">Run Backtest</button>
        <button id="runBasketBacktestBtn" class="btn btn-primary">Run Basket &amp; Walk-Forward</button>
        <select id="backtestStrategySelect" style="background:#0f172a;color:var(--text);border:1px solid var(--border);padding:6px 10px;border-radius:6px;font-size:0.83rem;">
          <option value="ema_pullback" selected>EMA Pullback (9/21)</option>
          <option value="rsi_mean_reversion">RSI Mean Reversion (14)</option>
          <option value="atr_breakout">ATR Breakout (20)</option>
          <option value="sma_cross">SMA Cross (5/15)</option>
        </select>
        <button id="exportJournalCsvBtn" class="btn btn-ghost" title="Export Ledger &amp; Trade Journal as CSV">Export CSV</button>
        <button id="exportJournalJsonBtn" class="btn btn-ghost" title="Export Ledger &amp; Trade Journal as JSON">Export JSON</button>
        <button id="toggleSettingsBtn" class="btn btn-ghost">Settings ▾</button>
      </div>
      <div id="settingsPanel" class="settings-panel" style="display: none;">
        <div class="setting-group">
          <label for="marketSelect">Market:</label>
          <select id="marketSelect">
            <option value="NSE" selected>NSE · INR</option>
            <option value="NASDAQ">NASDAQ · USD</option>
          </select>
        </div>
        <div class="setting-group">
          <label for="watchlistInput">Watchlist:</label>
          <input id="watchlistInput" type="text" value="RELIANCE, TCS" style="width:140px;">
        </div>
        <div class="setting-group">
          <label for="feedSourceSelect">Feed Source:</label>
          <select id="feedSourceSelect">
            <option value="synthetic" selected>Synthetic (Deterministic)</option>
            <option value="cache">Replay Fixture Cache</option>
            <option value="delayed_feed">Delayed Public Feed</option>
          </select>
        </div>
        <div class="setting-group">
          <label for="contextSourceSelect">Context Source:</label>
          <select id="contextSourceSelect">
            <option value="synthetic" selected>Synthetic (Deterministic)</option>
            <option value="cache">Replay Fixture Cache</option>
            <option value="live">Live RSS / Public</option>
          </select>
        </div>
        <div class="setting-group">
          <label for="llmBackendSelect">LLM Backend:</label>
          <select id="llmBackendSelect">
            <option value="stub" selected>Deterministic Stub</option>
            <option value="ollama">Local Ollama</option>
          </select>
        </div>
        <div class="setting-group">
          <label for="ollamaModelInput">Model:</label>
          <input id="ollamaModelInput" type="text" value="gemma4:12b" style="width:110px;">
        </div>
      </div>
    </div>

    <div id="statusNotification" class="status-banner" style="display: none;"></div>

    <div class="tabs-bar">
      <button id="tabOverviewBtn" class="tab-btn active">Overview</button>
      <button id="tabChatBtn" class="tab-btn">Agent Chat</button>
      <button id="tabPositionsBtn" class="tab-btn">Positions</button>
      <button id="tabBacktestBtn" class="tab-btn">Backtest</button>
      <button id="tabLessonsBtn" class="tab-btn">Lessons</button>
    </div>

    <div id="tabOverviewPane" class="tab-pane active">
      <div class="overview-grid">
        <div class="card">
          <div class="section-title">Candidate Screening</div>
          <div style="font-size:0.76rem;color:var(--text-dim);margin-bottom:6px;">Shortlisted:</div>
          <div id="overviewShortlist" class="badge-cluster">
            <span style="font-size:0.78rem;color:var(--text-dim);">No cycle reviewed</span>
          </div>
          <div style="font-size:0.76rem;color:var(--text-dim);margin-top:10px;margin-bottom:6px;">Dropped:</div>
          <div id="overviewDropped" class="badge-cluster">
            <span style="font-size:0.78rem;color:var(--text-dim);">None</span>
          </div>
        </div>

        <div class="card">
          <div class="section-title">Risk Gating &amp; Rejections</div>
          <div id="overviewRejections" class="badge-cluster">
            <span style="font-size:0.78rem;color:var(--text-dim);">No rejections</span>
          </div>
        </div>

        <div class="card" style="grid-column: 1 / -1;">
          <div class="section-title">Fundamental Health &amp; Catalyst Summary</div>
          <div id="overviewContextContainer" class="badge-cluster">
            <span style="font-size:0.78rem;color:var(--text-dim);">No context data loaded</span>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">AI Trade Plans · Buy &amp; Sell Levels</div>
          <span style="font-size:0.74rem;color:var(--text-dim);">Entry Bracket &amp; Target Modeling</span>
        </div>
        <div id="tradePlansContainer" style="margin-top:10px;">
          <div class="empty-placeholder">No trade plans recorded in this cycle</div>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">Candlestick Chart · AI Levels</div>
          <div id="chartTickerPills" class="pill-group"></div>
        </div>
        <div id="chartReadoutBar" class="chart-readout">
          <span>Select a ticker to view candlestick chart and AI brackets</span>
        </div>
        <div style="position:relative; width:100%; height:320px; margin-top:8px;">
          <canvas id="candlestickCanvas" width="1080" height="320" style="width:100%; height:320px; display:block; border-radius:6px; background:#0b1120;"></canvas>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px;">
        <div class="section-title">Executed Paper Orders</div>
        <div id="overviewOrdersContainer">
          <div class="empty-placeholder">No orders executed in this cycle</div>
        </div>
      </div>

      <details class="raw-report-details">
        <summary>Collapsible Raw Report</summary>
        <pre id="overviewRawReport" class="raw-report-pre">Ready. Run a desk cycle or backtest to view report.</pre>
      </details>
    </div>

    <div id="tabChatPane" class="tab-pane">
      <div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:14px;">
        Agent Chat Trace · Step-by-step inputs observed and rationales produced across Stages 1 through 4
      </div>
      <div id="chatTraceContainer" class="chat-stream">
        <div class="empty-placeholder">No agent chat trace recorded for this cycle</div>
      </div>
    </div>

    <div id="tabPositionsPane" class="tab-pane">
      <div class="card" style="margin-bottom:16px;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">Open Portfolio Positions</div>
          <button id="refreshPositionsBtn" class="btn btn-ghost btn-sm">Refresh Positions</button>
        </div>
        <div id="positionsContainer" style="margin-top:10px;">
          <div class="empty-placeholder">No open positions</div>
        </div>
      </div>
    </div>

    <div id="tabBacktestPane" class="tab-pane">
      <div class="overview-grid" id="backtestMetricsGrid" style="margin-bottom:16px;">
        <div class="card">
          <div class="card-head">
            <span class="card-title">Backtest Result</span>
            <span id="backtestStrategyBadge" class="pill pill-blue">—</span>
          </div>
          <div class="equity-figure" id="backtestNetReturn">—</div>
          <div class="metric-row"><span class="metric-name">Sharpe Ratio</span><span class="metric-num" id="backtestSharpe">—</span></div>
          <div class="metric-row"><span class="metric-name">Max Drawdown</span><span class="metric-num" id="backtestDrawdown">—</span></div>
          <div class="metric-row"><span class="metric-name">Win Rate</span><span class="metric-num" id="backtestWinRate">—</span></div>
          <div class="metric-row"><span class="metric-name">Trades Count</span><span class="metric-num" id="backtestTradesCount">—</span></div>
        </div>
        <div class="card">
          <div class="card-head">
            <span class="card-title">Risk &amp; Verification</span>
            <span id="backtestHmacBadge" class="pill pill-success">HMAC Verified</span>
          </div>
          <div class="metric-row"><span class="metric-name">Monte Carlo 95% VaR</span><span class="metric-num" id="backtestVar">—</span></div>
          <div class="metric-row"><span class="metric-name">Profit Factor</span><span class="metric-num" id="backtestProfitFactor">—</span></div>
          <div class="metric-row"><span class="metric-name">Expectancy</span><span class="metric-num" id="backtestExpectancy">—</span></div>
          <div class="metric-row"><span class="metric-name">Bars Evaluated</span><span class="metric-num" id="backtestBars">—</span></div>
        </div>
      </div>
      <div id="walkForwardGrid" class="overview-grid" style="margin-bottom:16px; display:none;">
        <div class="card">
          <div class="card-head">
            <span class="card-title">In-Sample Training (70%)</span>
            <span class="pill pill-blue">In-Sample</span>
          </div>
          <div class="metric-row"><span class="metric-name">Total Return</span><span class="metric-num" id="wfInReturn">—</span></div>
          <div class="metric-row"><span class="metric-name">Sharpe Ratio</span><span class="metric-num" id="wfInSharpe">—</span></div>
          <div class="metric-row"><span class="metric-name">Max Drawdown</span><span class="metric-num" id="wfInDrawdown">—</span></div>
          <div class="metric-row"><span class="metric-name">Win Rate</span><span class="metric-num" id="wfInWinRate">—</span></div>
          <div class="metric-row"><span class="metric-name">Total Trades</span><span class="metric-num" id="wfInTrades">—</span></div>
        </div>
        <div class="card">
          <div class="card-head">
            <span class="card-title">Out-of-Sample Validation (30%)</span>
            <span class="pill pill-success">Untouched</span>
          </div>
          <div class="metric-row"><span class="metric-name">Total Return</span><span class="metric-num" id="wfOutReturn">—</span></div>
          <div class="metric-row"><span class="metric-name">Sharpe Ratio</span><span class="metric-num" id="wfOutSharpe">—</span></div>
          <div class="metric-row"><span class="metric-name">Max Drawdown</span><span class="metric-num" id="wfOutDrawdown">—</span></div>
          <div class="metric-row"><span class="metric-name">Win Rate</span><span class="metric-num" id="wfOutWinRate">—</span></div>
          <div class="metric-row"><span class="metric-name">Optimal Parameters</span><span class="metric-num" id="wfBestParams" style="font-size:0.75rem;">—</span></div>
        </div>
      </div>
      <div class="card" style="margin-bottom:16px;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">Equity Curve · Time Machine</div>
          <span style="font-size:0.74rem;color:var(--text-dim);">Historical Portfolio Equity</span>
        </div>
        <div id="equityCurveReadoutBar" class="chart-readout">
          <span>Hover over chart to inspect historical equity point</span>
        </div>
        <div style="position:relative; width:100%; height:280px; margin-top:8px;">
          <canvas id="equityCurveCanvas" width="1080" height="280" style="width:100%; height:280px; display:block; border-radius:6px; background:#0b1120;"></canvas>
        </div>
      </div>
      <div class="card" id="basketAttributionCard" style="margin-bottom:16px; display:none;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">Per-Symbol Basket Attribution</div>
          <span id="basketSymbolCountBadge" class="pill pill-blue">Attribution</span>
        </div>
        <div id="basketAttributionContainer" style="margin-top:12px;"></div>
      </div>
    </div>

    <div id="tabLessonsPane" class="tab-pane">
      <div class="card" style="margin-bottom:16px;">
        <div class="card-head">
          <div class="section-title" style="margin-bottom:0;">Active Trading Lessons &amp; Risk Rules</div>
          <span class="pill pill-purple">SQLite Backed</span>
        </div>
        <div style="font-size:0.8rem;color:var(--text-muted);margin:8px 0 14px 0;">
          These lessons are injected directly into the Strategist and Risk Guardian agent reasoning prompts on every cycle.
        </div>
        <div style="display:flex;gap:10px;margin-bottom:16px;">
          <input type="text" id="lessonInput" placeholder="Enter custom trading rule or lesson (e.g. 'Never trade counter-trend on Friday afternoons')" style="flex:1;background:#0f172a;color:var(--text);border:1px solid var(--border);padding:8px 12px;border-radius:6px;font-size:0.83rem;">
          <button id="addLessonBtn" class="btn btn-primary">Add Rule</button>
        </div>
        <div id="lessonsContainer">
          <div class="empty-placeholder">No active trading lessons stored</div>
        </div>
      </div>
    </div>
  </div>

  <script>
    let killSwitchActive = false;
    let loadedCycles = [];
    let currentSelectedRunId = null;
    let currentDetailData = null;
    let activeChartSymbol = null;

    function formatMoney(amountStr, currency) {
      const num = parseFloat(amountStr);
      if (isNaN(num)) return amountStr + " " + currency;
      return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " " + currency;
    }

    function showStatus(text, isError) {
      const el = document.getElementById("statusNotification");
      el.textContent = text;
      el.style.display = "block";
      if (isError) {
        el.style.background = "var(--danger-bg)";
        el.style.borderColor = "var(--danger-border)";
        el.style.color = "#fca5a5";
      } else {
        el.style.background = "rgba(56, 189, 248, 0.1)";
        el.style.borderColor = "rgba(56, 189, 248, 0.3)";
        el.style.color = "var(--accent)";
      }
    }

    async function fetchHealth() {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) return;
        const data = await res.json();
        killSwitchActive = Boolean(data.kill_switch_active);
        const indicator = document.getElementById("killStatusIndicator");
        const statusText = document.getElementById("killStatusText");
        const btn = document.getElementById("toggleKillBtn");
        if (killSwitchActive) {
          indicator.className = "status-indicator stopped";
          statusText.textContent = "Stopped";
          btn.textContent = "Resume Trading";
          btn.className = "btn btn-success-outline";
        } else {
          indicator.className = "status-indicator";
          statusText.textContent = "Active";
          btn.textContent = "Emergency Stop";
          btn.className = "btn btn-danger-outline";
        }
      } catch (err) {
        showStatus("Health check error: " + err, true);
      }
    }

    async function toggleKillSwitch() {
      try {
        const nextState = !killSwitchActive;
        const res = await fetch("/api/kill-switch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active: nextState, reason: nextState ? "MANUAL_UI_STOP" : "MANUAL_UI_RESUME" })
        });
        if (res.ok) {
          await fetchHealth();
          await loadPortfolio("INR");
          await loadPortfolio("USD");
          showStatus("Kill switch toggled: active=" + nextState, false);
        } else {
          const errData = await res.json();
          showStatus("Kill switch toggle failed: " + (errData.detail || res.statusText), true);
        }
      } catch (err) {
        showStatus("Kill switch request error: " + err, true);
      }
    }

    async function loadPortfolio(curr) {
      try {
        const res = await fetch("/api/portfolios/" + curr);
        if (!res.ok) return;
        const data = await res.json();
        const prefix = curr.toLowerCase();
        document.getElementById(prefix + "Equity").textContent = formatMoney(data.total_equity, curr);
        document.getElementById(prefix + "Cash").textContent = formatMoney(data.cash, curr);
        document.getElementById(prefix + "Holdings").textContent = formatMoney(data.holdings_value, curr);
        document.getElementById(prefix + "Realized").textContent = formatMoney(data.realized_pnl, curr);
        document.getElementById(prefix + "PosCount").textContent = String(data.positions.length);

        const warnEl = document.getElementById(prefix + "Warning");
        while (warnEl.firstChild) warnEl.removeChild(warnEl.firstChild);
        const isReconciled = (data.is_reconciled !== undefined) ? data.is_reconciled : data.reconciled;
        const residualNum = Number(data.conservation_residual || 0);
        if (!isReconciled || Math.abs(residualNum) > 0) {
          const warnText = document.createTextNode("Reconciliation Warning: residual " + data.conservation_residual);
          warnEl.appendChild(warnText);
          warnEl.style.display = "block";
        } else {
          warnEl.style.display = "none";
        }
      } catch (err) {
        showStatus("Failed to load portfolio " + curr + ": " + err, true);
      }
    }

    function toggleSettings() {
      const panel = document.getElementById("settingsPanel");
      const btn = document.getElementById("toggleSettingsBtn");
      if (panel.style.display === "none") {
        panel.style.display = "flex";
        btn.textContent = "Settings ▴";
      } else {
        panel.style.display = "none";
        btn.textContent = "Settings ▾";
      }
    }

    function switchTab(tabName) {
      const tabs = ["overview", "chat", "positions", "backtest", "lessons"];
      tabs.forEach(t => {
        const cap = t.charAt(0).toUpperCase() + t.slice(1);
        const btn = document.getElementById("tab" + cap + "Btn");
        const pane = document.getElementById("tab" + cap + "Pane");
        if (btn && pane) {
          if (t === tabName) {
            btn.className = "tab-btn active";
            pane.className = "tab-pane active";
          } else {
            btn.className = "tab-btn";
            pane.className = "tab-pane";
          }
        }
      });
      if (tabName === "positions") {
        loadPositions();
      } else if (tabName === "lessons") {
        loadLessons();
      }
    }

    function renderStatusPill(status) {
      const pill = document.createElement("span");
      pill.className = "pill";
      if (status === "ok" || status === "approved" || status === "executed") {
        pill.classList.add("pill-success");
      } else if (status === "rejected" || status === "risk_rejected") {
        pill.classList.add("pill-danger");
      } else if (status === "planned") {
        pill.classList.add("pill-blue");
      } else if (status === "no_trade") {
        pill.classList.add("pill-slate");
      } else if (status === "missing" || status === "dropped") {
        pill.classList.add("pill-amber");
      } else {
        pill.classList.add("pill-blue");
      }
      pill.textContent = status === "planned" ? "READY TO BUY" : status.toUpperCase();
      return pill;
    }

    function updateCycleStrip(detail) {
      document.getElementById("cycleIdText").textContent = detail.run_id;
      const ts = new Date(detail.timestamp);
      document.getElementById("cycleTimeText").textContent = isNaN(ts.getTime()) ? detail.timestamp : ts.toLocaleString();
      document.getElementById("cycleMarketText").textContent = detail.currency;

      const autoBuyPill = document.getElementById("cycleAutoBuyPill");
      const isAuto = (detail.auto_buy !== undefined) ? detail.auto_buy : true;
      autoBuyPill.textContent = isAuto ? "Auto-Buy ON" : "Auto-Buy OFF";
      autoBuyPill.className = isAuto ? "pill pill-success" : "pill pill-amber";

      document.getElementById("cycleFeedPill").textContent = detail.feed_source;
      const ctxPill = document.getElementById("cycleContextPill");
      if (ctxPill) {
        ctxPill.textContent = detail.context_source || "synthetic";
      }
      document.getElementById("cycleModelPill").textContent = detail.llm_backend === "ollama" ? detail.ollama_model : detail.llm_backend;

      const wlGroup = document.getElementById("cycleWatchlistGroup");
      while (wlGroup.firstChild) wlGroup.removeChild(wlGroup.firstChild);
      (detail.watchlist || []).forEach(sym => {
        const p = document.createElement("span");
        p.className = "pill pill-slate";
        p.textContent = sym;
        wlGroup.appendChild(p);
      });
    }

    async function submitPlannedOrder(plan) {
      if (!plan) return;
      showStatus("Submitting paper order for " + plan.symbol + " (qty: " + plan.quantity + ")...", false);
      try {
        const res = await fetch("/api/orders", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            run_id: currentSelectedRunId || "manual",
            exchange: plan.exchange,
            symbol: plan.symbol,
            side: "BUY",
            quantity: plan.quantity,
            quote_price: plan.current_price,
            stop_loss: plan.stop_loss,
            take_profit: plan.sell_target
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Order submission failed: " + (err.detail || res.statusText), true);
          return;
        }
        const data = await res.json();
        showStatus("Order " + data.client_order_id + " executed successfully", false);
        await refreshAll();
        if (currentSelectedRunId) {
          await loadCycleDetail(currentSelectedRunId);
        }
      } catch (err) {
        showStatus("Order execution error: " + err, true);
      }
    }

    function renderTradePlans(detail) {
      const container = document.getElementById("tradePlansContainer");
      while (container.firstChild) container.removeChild(container.firstChild);

      const plans = detail.trade_plans || [];
      if (plans.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-placeholder";
        empty.textContent = "No trade plans recorded for this cycle";
        container.appendChild(empty);
        return;
      }

      const table = document.createElement("table");
      table.className = "plans-table";
      const thead = document.createElement("thead");
      const trHead = document.createElement("tr");
      ["Symbol", "Status", "Current", "Buy Price", "Sell Target", "Stop Loss", "Qty & R:R", "Rationale", "Action"].forEach(h => {
        const th = document.createElement("th");
        th.textContent = h;
        trHead.appendChild(th);
      });
      thead.appendChild(trHead);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      plans.forEach(p => {
        const tr = document.createElement("tr");

        const tdSym = document.createElement("td");
        tdSym.style.fontWeight = "700";
        tdSym.textContent = p.symbol;
        tr.appendChild(tdSym);

        const tdStat = document.createElement("td");
        tdStat.appendChild(renderStatusPill(p.status));
        tr.appendChild(tdStat);

        const tdCurr = document.createElement("td");
        tdCurr.style.fontVariantNumeric = "tabular-nums";
        tdCurr.textContent = p.current_price ? Number(p.current_price).toFixed(2) : "—";
        tr.appendChild(tdCurr);

        const tdBuy = document.createElement("td");
        tdBuy.className = "price-buy";
        tdBuy.textContent = p.buy_price ? Number(p.buy_price).toFixed(2) : "—";
        tr.appendChild(tdBuy);

        const tdTarget = document.createElement("td");
        tdTarget.className = "price-target";
        if (p.sell_target) {
          const tVal = Number(p.sell_target);
          const bVal = Number(p.buy_price || p.current_price || 1);
          const pct = (((tVal - bVal) / bVal) * 100).toFixed(1);
          tdTarget.textContent = tVal.toFixed(2) + " (+" + pct + "%)";
        } else {
          tdTarget.textContent = "—";
        }
        tr.appendChild(tdTarget);

        const tdStop = document.createElement("td");
        tdStop.className = "price-stop";
        if (p.stop_loss) {
          const sVal = Number(p.stop_loss);
          const bVal = Number(p.buy_price || p.current_price || 1);
          const pct = (((sVal - bVal) / bVal) * 100).toFixed(1);
          tdStop.textContent = sVal.toFixed(2) + " (" + pct + "%)";
        } else {
          tdStop.textContent = "—";
        }
        tr.appendChild(tdStop);

        const tdQty = document.createElement("td");
        if (p.quantity && p.quantity > 0) {
          const rrStr = p.reward_to_risk ? " | R:R " + Number(p.reward_to_risk).toFixed(2) : "";
          tdQty.textContent = p.quantity + " shs" + rrStr;
        } else {
          tdQty.textContent = "—";
        }
        tr.appendChild(tdQty);

        const tdRat = document.createElement("td");
        tdRat.style.fontSize = "0.76rem";
        tdRat.style.color = "var(--text-muted)";
        tdRat.style.maxWidth = "220px";
        const ratText = p.rationale || (p.risk_reasons && p.risk_reasons.length > 0 ? p.risk_reasons.join("; ") : "No action suggested");
        tdRat.textContent = ratText;
        tr.appendChild(tdRat);

        const tdAct = document.createElement("td");
        if (p.status === "planned") {
          const execBtn = document.createElement("button");
          execBtn.className = "btn btn-primary btn-sm";
          execBtn.textContent = "Execute Paper Buy";
          execBtn.addEventListener("click", () => submitPlannedOrder(p));
          tdAct.appendChild(execBtn);
        } else if (p.status === "executed") {
          const span = document.createElement("span");
          span.style.fontSize = "0.74rem";
          span.style.color = "var(--success)";
          span.textContent = p.executed_order_id ? "Order: " + p.executed_order_id.slice(-8) : "Filled";
          tdAct.appendChild(span);
        } else {
          const span = document.createElement("span");
          span.style.fontSize = "0.74rem";
          span.style.color = "var(--text-dim)";
          span.textContent = "No action";
          tdAct.appendChild(span);
        }
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      container.appendChild(table);
    }

    function setupCandlestickChart(detail) {
      const pillsContainer = document.getElementById("chartTickerPills");
      while (pillsContainer.firstChild) pillsContainer.removeChild(pillsContainer.firstChild);

      const seriesMap = detail.candle_series || {};
      const symbols = Object.keys(seriesMap);

      if (symbols.length === 0) {
        document.getElementById("chartReadoutBar").textContent = "No candlestick series recorded for this cycle";
        drawEmptyChart("No candlestick series available");
        return;
      }

      if (!activeChartSymbol || !symbols.includes(activeChartSymbol)) {
        activeChartSymbol = symbols[0];
      }

      symbols.forEach(sym => {
        const btn = document.createElement("button");
        btn.className = "ticker-pill-btn" + (sym === activeChartSymbol ? " active" : "");
        btn.textContent = sym;
        btn.addEventListener("click", () => {
          activeChartSymbol = sym;
          const allBtns = pillsContainer.querySelectorAll(".ticker-pill-btn");
          allBtns.forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          renderSelectedChart();
        });
        pillsContainer.appendChild(btn);
      });

      renderSelectedChart();
    }

    function drawEmptyChart(msg) {
      const canvas = document.getElementById("candlestickCanvas");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0b1120";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#64748b";
      ctx.font = "14px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(msg, canvas.width / 2, canvas.height / 2);
    }

    function renderSelectedChart() {
      if (!currentDetailData || !activeChartSymbol) return;
      const seriesMap = currentDetailData.candle_series || {};
      const bars = seriesMap[activeChartSymbol] || [];
      const plans = currentDetailData.trade_plans || [];
      const plan = plans.find(p => p.symbol === activeChartSymbol) || null;

      const canvas = document.getElementById("candlestickCanvas");
      const ctx = canvas.getContext("2d");
      const width = canvas.width;
      const height = canvas.height;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#0b1120";
      ctx.fillRect(0, 0, width, height);

      if (bars.length === 0) {
        drawEmptyChart("No candle bars for " + activeChartSymbol);
        return;
      }

      const padTop = 24;
      const padBottom = 28;
      const padLeft = 20;
      const padRight = 110;
      const plotWidth = width - padLeft - padRight;
      const plotHeight = height - padTop - padBottom;

      let minP = Infinity;
      let maxP = -Infinity;
      bars.forEach(b => {
        const l = Number(b.low);
        const h = Number(b.high);
        if (l < minP) minP = l;
        if (h > maxP) maxP = h;
      });

      if (plan) {
        if (plan.buy_price) {
          const bp = Number(plan.buy_price);
          if (bp < minP) minP = bp;
          if (bp > maxP) maxP = bp;
        }
        if (plan.sell_target) {
          const st = Number(plan.sell_target);
          if (st < minP) minP = st;
          if (st > maxP) maxP = st;
        }
        if (plan.stop_loss) {
          const sl = Number(plan.stop_loss);
          if (sl < minP) minP = sl;
          if (sl > maxP) maxP = sl;
        }
      }

      const pRange = (maxP - minP) || 1.0;
      minP -= pRange * 0.04;
      maxP += pRange * 0.04;
      const fullRange = maxP - minP;

      function scaleY(p) {
        return padTop + (1.0 - (p - minP) / fullRange) * plotHeight;
      }

      ctx.fillStyle = "rgba(255, 255, 255, 0.03)";
      ctx.fillRect(padLeft, padTop, plotWidth, plotHeight);

      if (plan && plan.buy_price && plan.sell_target) {
        const yBuy = scaleY(Number(plan.buy_price));
        const yTarget = scaleY(Number(plan.sell_target));
        ctx.fillStyle = "rgba(34, 197, 94, 0.07)";
        ctx.fillRect(padLeft, Math.min(yBuy, yTarget), plotWidth, Math.abs(yBuy - yTarget));
      }
      if (plan && plan.buy_price && plan.stop_loss) {
        const yBuy = scaleY(Number(plan.buy_price));
        const yStop = scaleY(Number(plan.stop_loss));
        ctx.fillStyle = "rgba(239, 68, 68, 0.07)";
        ctx.fillRect(padLeft, Math.min(yBuy, yStop), plotWidth, Math.abs(yBuy - yStop));
      }

      ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#64748b";
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";

      const gridSteps = 5;
      for (let s = 0; s <= gridSteps; s++) {
        const val = minP + (fullRange * (s / gridSteps));
        const y = scaleY(val);
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(padLeft + plotWidth, y);
        ctx.stroke();
        ctx.fillText(val.toFixed(2), padLeft + plotWidth + 8, y);
      }

      const barSlot = plotWidth / bars.length;
      const candleWidth = Math.max(Math.min(barSlot * 0.65, 18), 3);

      bars.forEach((b, idx) => {
        const x = padLeft + (idx + 0.5) * barSlot;
        const o = Number(b.open);
        const h = Number(b.high);
        const l = Number(b.low);
        const c = Number(b.close);

        const yOpen = scaleY(o);
        const yClose = scaleY(c);
        const yHigh = scaleY(h);
        const yLow = scaleY(l);

        const isBull = c >= o;
        const color = isBull ? "#22c55e" : "#ef4444";

        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        ctx.fillStyle = color;
        const bodyTop = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(Math.abs(yClose - yOpen), 1.5);
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
      });

      if (plan) {
        ctx.lineWidth = 1.5;
        ctx.font = "bold 10px monospace";
        ctx.setLineDash([4, 4]);

        if (plan.sell_target) {
          const y = scaleY(Number(plan.sell_target));
          ctx.strokeStyle = "#22c55e";
          ctx.beginPath();
          ctx.moveTo(padLeft, y);
          ctx.lineTo(padLeft + plotWidth, y);
          ctx.stroke();
          ctx.fillStyle = "#22c55e";
          const label = "TARGET: " + Number(plan.sell_target).toFixed(2);
          ctx.fillText(label, padLeft + plotWidth + 8, y);
        }

        if (plan.buy_price) {
          const y = scaleY(Number(plan.buy_price));
          ctx.strokeStyle = "#38bdf8";
          ctx.beginPath();
          ctx.moveTo(padLeft, y);
          ctx.lineTo(padLeft + plotWidth, y);
          ctx.stroke();
          ctx.fillStyle = "#38bdf8";
          const label = "BUY: " + Number(plan.buy_price).toFixed(2);
          ctx.fillText(label, padLeft + plotWidth + 8, y);
        }

        if (plan.stop_loss) {
          const y = scaleY(Number(plan.stop_loss));
          ctx.strokeStyle = "#ef4444";
          ctx.beginPath();
          ctx.moveTo(padLeft, y);
          ctx.lineTo(padLeft + plotWidth, y);
          ctx.stroke();
          ctx.fillStyle = "#ef4444";
          const label = "STOP: " + Number(plan.stop_loss).toFixed(2);
          ctx.fillText(label, padLeft + plotWidth + 8, y);
        }

        ctx.setLineDash([]);
      }

      const readout = document.getElementById("chartReadoutBar");
      const latestBar = bars[bars.length - 1];
      const planStr = plan && plan.buy_price
        ? " | Buy: " + Number(plan.buy_price).toFixed(2) + " · Target: " + Number(plan.sell_target || 0).toFixed(2) + " · Stop: " + Number(plan.stop_loss || 0).toFixed(2)
        : "";
      readout.textContent = activeChartSymbol + " · Latest: " + Number(latestBar.close).toFixed(2) + " (" + (latestBar.timestamp || "").slice(0, 10) + ")" + planStr;

      canvas.onmousemove = function(ev) {
        const rect = canvas.getBoundingClientRect();
        const mouseX = (ev.clientX - rect.left) * (canvas.width / rect.width);
        const mouseY = (ev.clientY - rect.top) * (canvas.height / rect.height);

        if (mouseX >= padLeft && mouseX <= padLeft + plotWidth && mouseY >= padTop && mouseY <= padTop + plotHeight) {
          const relX = mouseX - padLeft;
          const idx = Math.floor(relX / barSlot);
          if (idx >= 0 && idx < bars.length) {
            const b = bars[idx];
            const tsDate = (b.timestamp || "").slice(0, 10);
            readout.textContent = activeChartSymbol + " · " + tsDate + " · O: " + Number(b.open).toFixed(2) + " · H: " + Number(b.high).toFixed(2) + " · L: " + Number(b.low).toFixed(2) + " · C: " + Number(b.close).toFixed(2) + " · Vol: " + Number(b.volume).toLocaleString();
          }
        }
      };

      canvas.onmouseleave = function() {
        readout.textContent = activeChartSymbol + " · Latest: " + Number(latestBar.close).toFixed(2) + " (" + (latestBar.timestamp || "").slice(0, 10) + ")" + planStr;
      };
    }

    function renderOverview(detail) {
      const shortlistContainer = document.getElementById("overviewShortlist");
      while (shortlistContainer.firstChild) shortlistContainer.removeChild(shortlistContainer.firstChild);
      if (detail.shortlist && detail.shortlist.length > 0) {
        detail.shortlist.forEach(sym => {
          const pill = document.createElement("span");
          pill.className = "pill pill-success";
          pill.textContent = sym;
          shortlistContainer.appendChild(pill);
        });
      } else {
        const span = document.createElement("span");
        span.style.fontSize = "0.78rem";
        span.style.color = "var(--text-dim)";
        span.textContent = "None";
        shortlistContainer.appendChild(span);
      }

      const droppedContainer = document.getElementById("overviewDropped");
      while (droppedContainer.firstChild) droppedContainer.removeChild(droppedContainer.firstChild);
      const droppedKeys = Object.keys(detail.dropped || {});
      if (droppedKeys.length > 0) {
        droppedKeys.forEach(sym => {
          const pill = document.createElement("span");
          pill.className = "pill pill-danger";
          pill.textContent = sym + ": " + detail.dropped[sym];
          droppedContainer.appendChild(pill);
        });
      } else {
        const span = document.createElement("span");
        span.style.fontSize = "0.78rem";
        span.style.color = "var(--text-dim)";
        span.textContent = "None";
        droppedContainer.appendChild(span);
      }

      const rejectionsContainer = document.getElementById("overviewRejections");
      while (rejectionsContainer.firstChild) rejectionsContainer.removeChild(rejectionsContainer.firstChild);
      if (detail.rejected_proposals && detail.rejected_proposals.length > 0) {
        detail.rejected_proposals.forEach(rej => {
          const pill = document.createElement("span");
          pill.className = "pill pill-danger";
          const reasons = (rej.reasons || []).join(", ");
          pill.textContent = (rej.proposal_id || "Proposal") + (reasons ? ": " + reasons : "");
          rejectionsContainer.appendChild(pill);
        });
      } else {
        const span = document.createElement("span");
        span.style.fontSize = "0.78rem";
        span.style.color = "var(--text-dim)";
        span.textContent = "Zero risk rejections";
        rejectionsContainer.appendChild(span);
      }

      const contextContainer = document.getElementById("overviewContextContainer");
      if (contextContainer) {
        while (contextContainer.firstChild) contextContainer.removeChild(contextContainer.firstChild);
        const traceEntries = detail.chat_trace || [];
        const tickerSymbols = detail.watchlist || [];
        const byTicker = {};
        tickerSymbols.forEach(sym => { byTicker[sym] = {}; });
        traceEntries.forEach(entry => {
          if (entry.symbol) {
            if (!byTicker[entry.symbol]) byTicker[entry.symbol] = {};
            if (entry.agent === "data_analyst") {
              byTicker[entry.symbol].data = entry.output_message || {};
            } else if (entry.agent === "news_analyst") {
              byTicker[entry.symbol].news = entry.output_message || {};
            }
          }
        });
        const syms = Object.keys(byTicker);
        if (syms.length > 0) {
          syms.forEach(sym => {
            const wrap = document.createElement("div");
            wrap.style.display = "inline-flex";
            wrap.style.alignItems = "center";
            wrap.style.gap = "6px";
            wrap.style.marginRight = "10px";
            wrap.style.marginBottom = "6px";

            const symPill = document.createElement("span");
            symPill.className = "pill pill-slate";
            symPill.textContent = sym;
            wrap.appendChild(symPill);

            const dData = byTicker[sym].data || {};
            const q = dData.quality !== undefined ? dData.quality : "—";
            const g = dData.growth !== undefined ? dData.growth : "—";
            const s = dData.safety !== undefined ? dData.safety : "—";
            const fHealth = document.createElement("span");
            fHealth.className = "pill pill-blue";
            fHealth.textContent = "Q:" + q + " G:" + g + " S:" + s;
            wrap.appendChild(fHealth);

            const nData = byTicker[sym].news || {};
            const sentVal = nData.net_sentiment !== undefined ? Number(nData.net_sentiment).toFixed(2) : "0.00";
            const sentPill = document.createElement("span");
            sentPill.className = "pill " + (Number(sentVal) >= 0 ? "pill-success" : "pill-danger");
            sentPill.textContent = (Number(sentVal) > 0 ? "+" : "") + sentVal + " Sent";
            wrap.appendChild(sentPill);

            const isBlk = Boolean(nData.blackout_suggested);
            const blkPill = document.createElement("span");
            blkPill.className = "pill " + (isBlk ? "pill-danger" : "pill-success");
            blkPill.textContent = isBlk ? "EVENT BLACKOUT" : "CATALYST CLEAR";
            wrap.appendChild(blkPill);

            contextContainer.appendChild(wrap);
          });
        } else {
          const span = document.createElement("span");
          span.style.fontSize = "0.78rem";
          span.style.color = "var(--text-dim)";
          span.textContent = "No context data available for this cycle";
          contextContainer.appendChild(span);
        }
      }

      renderTradePlans(detail);
      setupCandlestickChart(detail);

      const ordersContainer = document.getElementById("overviewOrdersContainer");
      while (ordersContainer.firstChild) ordersContainer.removeChild(ordersContainer.firstChild);
      if (detail.approved_orders && detail.approved_orders.length > 0) {
        const table = document.createElement("table");
        table.className = "orders-table";
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        ["Order ID", "Symbol", "Side", "Qty", "Fill Price", "Status"].forEach(h => {
          const th = document.createElement("th");
          th.textContent = h;
          trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        detail.approved_orders.forEach(o => {
          const tr = document.createElement("tr");
          const tdId = document.createElement("td");
          tdId.style.fontFamily = "monospace";
          tdId.textContent = o.client_order_id || "—";
          tr.appendChild(tdId);

          const tdSym = document.createElement("td");
          tdSym.style.fontWeight = "600";
          tdSym.textContent = o.symbol || "—";
          tr.appendChild(tdSym);

          const tdSide = document.createElement("td");
          const sidePill = document.createElement("span");
          sidePill.className = "pill " + (o.side === "BUY" ? "pill-success" : "pill-danger");
          sidePill.textContent = o.side;
          tdSide.appendChild(sidePill);
          tr.appendChild(tdSide);

          const tdQty = document.createElement("td");
          tdQty.textContent = String(o.filled_quantity || o.quantity || 0);
          tr.appendChild(tdQty);

          const tdPrice = document.createElement("td");
          tdPrice.textContent = o.average_fill_price ? String(o.average_fill_price) : "Market";
          tr.appendChild(tdPrice);

          const tdStat = document.createElement("td");
          tdStat.appendChild(renderStatusPill(o.status || "FILLED"));
          tr.appendChild(tdStat);

          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        ordersContainer.appendChild(table);
      } else {
        const empty = document.createElement("div");
        empty.className = "empty-placeholder";
        empty.textContent = "No orders executed in this cycle";
        ordersContainer.appendChild(empty);
      }

      document.getElementById("overviewRawReport").textContent = detail.report_markdown || "No report generated.";
    }

    function renderAgentChat(detail) {
      const container = document.getElementById("chatTraceContainer");
      while (container.firstChild) container.removeChild(container.firstChild);

      const trace = detail.chat_trace || [];
      if (trace.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-placeholder";
        empty.textContent = "No agent chat trace recorded for this cycle";
        container.appendChild(empty);
        return;
      }

      trace.forEach(entry => {
        const card = document.createElement("div");
        card.className = "chat-card";

        const head = document.createElement("div");
        head.className = "chat-card-head";

        const meta = document.createElement("div");
        meta.className = "chat-card-meta";

        const stepBadge = document.createElement("span");
        stepBadge.className = "chat-step-badge";
        stepBadge.textContent = "#" + entry.step;
        meta.appendChild(stepBadge);

        const stageBadge = document.createElement("span");
        stageBadge.className = "chat-stage-badge";
        stageBadge.textContent = entry.stage;
        meta.appendChild(stageBadge);

        if (entry.symbol) {
          const symBadge = document.createElement("span");
          symBadge.className = "pill pill-slate";
          symBadge.textContent = entry.symbol;
          meta.appendChild(symBadge);
        }

        const modelBadge = document.createElement("span");
        modelBadge.className = "pill pill-purple";
        modelBadge.textContent = entry.model;
        meta.appendChild(modelBadge);

        if (entry.agent === "data_analyst" && entry.output_message) {
          const out = entry.output_message;
          const qVal = out.quality !== undefined ? out.quality : 1;
          const gVal = out.growth !== undefined ? out.growth : 1;
          const sVal = out.safety !== undefined ? out.safety : 1;
          const qBadge = document.createElement("span");
          qBadge.className = "pill pill-blue";
          qBadge.textContent = "Fundamental: Q" + qVal + " G" + gVal + " S" + sVal;
          meta.appendChild(qBadge);
        } else if (entry.agent === "news_analyst" && entry.output_message) {
          const out = entry.output_message;
          const sentVal = out.net_sentiment !== undefined ? Number(out.net_sentiment).toFixed(2) : "0.00";
          const sentBadge = document.createElement("span");
          sentBadge.className = "pill " + (Number(sentVal) >= 0 ? "pill-success" : "pill-danger");
          sentBadge.textContent = "Catalyst: " + (Number(sentVal) > 0 ? "+" : "") + sentVal;
          meta.appendChild(sentBadge);

          if (out.blackout_suggested) {
            const blkBadge = document.createElement("span");
            blkBadge.className = "pill pill-danger";
            blkBadge.textContent = "EVENT BLACKOUT";
            meta.appendChild(blkBadge);
          }
        }

        head.appendChild(meta);
        head.appendChild(renderStatusPill(entry.status));
        card.appendChild(head);

        const bubbleContainer = document.createElement("div");
        bubbleContainer.className = "chat-bubble-container";

        const inBubble = document.createElement("div");
        inBubble.className = "chat-bubble";
        const inTitle = document.createElement("div");
        inTitle.className = "chat-bubble-title";
        inTitle.textContent = "Input Context Seen";
        inBubble.appendChild(inTitle);
        const inPre = document.createElement("pre");
        inPre.textContent = JSON.stringify(entry.input_context || {}, null, 2);
        inBubble.appendChild(inPre);
        bubbleContainer.appendChild(inBubble);

        const outBubble = document.createElement("div");
        outBubble.className = "chat-bubble";
        const outTitle = document.createElement("div");
        outTitle.className = "chat-bubble-title";
        outTitle.textContent = "Agent / LLM Response";
        outBubble.appendChild(outTitle);
        const outPre = document.createElement("pre");
        outPre.textContent = JSON.stringify(entry.output_message || {}, null, 2);
        outBubble.appendChild(outPre);
        bubbleContainer.appendChild(outBubble);

        card.appendChild(bubbleContainer);
        container.appendChild(card);
      });
    }

    async function loadCycleDetail(runId) {
      if (!runId) return;
      currentSelectedRunId = runId;
      try {
        const res = await fetch("/api/cycles/" + encodeURIComponent(runId));
        if (!res.ok) {
          showStatus("Failed to load cycle detail: " + res.statusText, true);
          return;
        }
        const detail = await res.json();
        currentDetailData = detail;
        updateCycleStrip(detail);
        renderOverview(detail);
        renderAgentChat(detail);
      } catch (err) {
        showStatus("Error loading cycle detail: " + err, true);
      }
    }

    async function loadCycleList(autoSelectId) {
      try {
        const res = await fetch("/api/cycles?limit=25");
        if (!res.ok) return;
        loadedCycles = await res.json();
        const sel = document.getElementById("cycleSelect");
        while (sel.firstChild) sel.removeChild(sel.firstChild);

        if (loadedCycles.length === 0) {
          const opt = document.createElement("option");
          opt.value = "";
          opt.textContent = "No cycles recorded yet";
          sel.appendChild(opt);
          return;
        }

        loadedCycles.forEach(c => {
          const opt = document.createElement("option");
          opt.value = c.run_id;
          const ts = new Date(c.timestamp);
          const timeStr = isNaN(ts.getTime()) ? c.timestamp : ts.toLocaleTimeString();
          const autoStr = c.auto_buy === false ? ", Auto-Off" : "";
          opt.textContent = c.run_id + " (" + timeStr + ", " + c.currency + autoStr + ")";
          sel.appendChild(opt);
        });

        const targetId = autoSelectId || currentSelectedRunId || loadedCycles[0].run_id;
        sel.value = targetId;
        await loadCycleDetail(targetId);
      } catch (err) {
        showStatus("Failed to load cycle history: " + err, true);
      }
    }

    async function runDeskCycle() {
      const market = document.getElementById("marketSelect").value;
      const currency = (market === "NSE") ? "INR" : "USD";
      const exchange = market;
      const rawWl = document.getElementById("watchlistInput").value;
      const watchlist = rawWl.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      if (watchlist.length === 0) {
        showStatus("Watchlist must contain at least one ticker symbol", true);
        return;
      }
      const feedSource = document.getElementById("feedSourceSelect").value;
      const contextSource = document.getElementById("contextSourceSelect") ? document.getElementById("contextSourceSelect").value : "synthetic";
      const llmBackend = document.getElementById("llmBackendSelect").value;
      const ollamaModel = document.getElementById("ollamaModelInput").value.trim() || "gemma4:12b";
      const autoBuy = document.getElementById("autoBuyToggle").checked;

      showStatus("Initiating 7-Agent Research Desk cycle (" + feedSource + " / " + contextSource + ", auto-buy=" + autoBuy + ")...", false);
      try {
        const res = await fetch("/api/desk/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            watchlist: watchlist,
            exchange: exchange,
            currency: currency,
            feed_source: feedSource,
            context_source: contextSource,
            llm_backend: llmBackend,
            ollama_model: ollamaModel,
            auto_buy: autoBuy
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Desk run rejected: " + (err.detail || res.statusText), true);
          return;
        }
        const data = await res.json();
        showStatus("Cycle " + data.run_id + " completed successfully", false);
        await refreshAll();
        await loadCycleList(data.run_id);
      } catch (err) {
        showStatus("Desk run error: " + err, true);
      }
    }

    async function loadPositions() {
      const container = document.getElementById("positionsContainer");
      try {
        const res = await fetch("/api/positions");
        if (!res.ok) {
          showStatus("Failed to load positions: " + res.statusText, true);
          return;
        }
        const data = await res.json();
        const positions = data.positions || [];
        while (container.firstChild) container.removeChild(container.firstChild);

        if (positions.length === 0) {
          const empty = document.createElement("div");
          empty.className = "empty-placeholder";
          empty.textContent = "No open positions currently in INR or USD paper portfolios";
          container.appendChild(empty);
          return;
        }

        const table = document.createElement("table");
        table.className = "plans-table";
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        ["Symbol", "Exchange", "Currency", "Quantity", "Avg Cost", "Mark Price", "Market Value", "Unrealized P&L", "Action"].forEach(h => {
          const th = document.createElement("th");
          th.textContent = h;
          trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        positions.forEach(pos => {
          const tr = document.createElement("tr");

          const tdSym = document.createElement("td");
          tdSym.style.fontWeight = "600";
          tdSym.textContent = pos.symbol;
          tr.appendChild(tdSym);

          const tdEx = document.createElement("td");
          tdEx.textContent = pos.exchange;
          tr.appendChild(tdEx);

          const tdCurr = document.createElement("td");
          tdCurr.textContent = pos.currency;
          tr.appendChild(tdCurr);

          const tdQty = document.createElement("td");
          tdQty.textContent = pos.quantity;
          tr.appendChild(tdQty);

          const tdAvg = document.createElement("td");
          tdAvg.textContent = Number(pos.average_cost).toFixed(2);
          tr.appendChild(tdAvg);

          const tdMark = document.createElement("td");
          tdMark.textContent = Number(pos.mark_price).toFixed(2);
          tr.appendChild(tdMark);

          const tdVal = document.createElement("td");
          tdVal.textContent = Number(pos.market_value).toFixed(2);
          tr.appendChild(tdVal);

          const tdPnl = document.createElement("td");
          const pnlNum = Number(pos.unrealized_pnl);
          tdPnl.textContent = (pnlNum >= 0 ? "+" : "") + pnlNum.toFixed(2);
          tdPnl.style.fontWeight = "600";
          tdPnl.style.color = pnlNum >= 0 ? "var(--success)" : "var(--danger)";
          tr.appendChild(tdPnl);

          const tdAct = document.createElement("td");
          const sellBtn = document.createElement("button");
          sellBtn.className = "btn btn-danger-outline btn-sm";
          sellBtn.textContent = "Sell / Close";
          sellBtn.onclick = () => closePosition(pos);
          tdAct.appendChild(sellBtn);
          tr.appendChild(tdAct);

          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);
      } catch (err) {
        showStatus("Error loading positions: " + err, true);
      }
    }

    async function closePosition(pos) {
      if (!confirm("Are you sure you want to close position in " + pos.symbol + " (" + pos.quantity + " units)?")) {
        return;
      }
      showStatus("Submitting close order for " + pos.symbol + "...", false);
      try {
        const res = await fetch("/api/positions/close", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            exchange: pos.exchange,
            symbol: pos.symbol,
            currency: pos.currency
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Close position failed: " + (err.detail || res.statusText), true);
          return;
        }
        showStatus("Position closed for " + pos.symbol, false);
        await refreshAll();
        await loadPositions();
      } catch (err) {
        showStatus("Close position error: " + err, true);
      }
    }

    async function loadLessons() {
      const container = document.getElementById("lessonsContainer");
      try {
        const res = await fetch("/api/lessons");
        if (!res.ok) return;
        const data = await res.json();
        const lessons = data.lessons || [];
        while (container.firstChild) container.removeChild(container.firstChild);

        if (lessons.length === 0) {
          const empty = document.createElement("div");
          empty.className = "empty-placeholder";
          empty.textContent = "No active trading lessons stored in database";
          container.appendChild(empty);
          return;
        }

        const list = document.createElement("div");
        list.style.display = "flex";
        list.style.flexDirection = "column";
        list.style.gap = "8px";

        lessons.forEach((l, idx) => {
          const item = document.createElement("div");
          item.style.padding = "10px 14px";
          item.style.background = "#0b1120";
          item.style.border = "1px solid #1e293b";
          item.style.borderRadius = "6px";
          item.style.fontSize = "0.82rem";
          item.style.display = "flex";
          item.style.alignItems = "center";
          item.style.gap = "10px";

          const badge = document.createElement("span");
          badge.className = "pill pill-purple";
          badge.textContent = "#" + (idx + 1);
          item.appendChild(badge);

          const txt = document.createElement("span");
          txt.style.color = "var(--text)";
          txt.textContent = l;
          item.appendChild(txt);

          list.appendChild(item);
        });

        container.appendChild(list);
      } catch (err) {
        showStatus("Error loading lessons: " + err, true);
      }
    }

    async function addLesson() {
      const input = document.getElementById("lessonInput");
      const text = input.value.trim();
      if (!text) return;
      try {
        const res = await fetch("/api/lessons", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lesson: text })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Failed to add rule: " + (err.detail || res.statusText), true);
          return;
        }
        input.value = "";
        showStatus("Trading rule added to persistent knowledge base", false);
        await loadLessons();
      } catch (err) {
        showStatus("Error adding lesson: " + err, true);
      }
    }

    async function resetSandbox() {
      if (!confirm("Reset Paper Trading Sandbox? This will restore INR to 1,000,000, USD to 25,000, and clear all positions.")) {
        return;
      }
      try {
        const res = await fetch("/api/sandbox/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Reset failed: " + (err.detail || res.statusText), true);
          return;
        }
        showStatus("Sandbox reset successfully to initial capital", false);
        await refreshAll();
        await loadPositions();
      } catch (err) {
        showStatus("Reset error: " + err, true);
      }
    }

    let currentEquityCurve = [];
    function renderEquityCurve(equityCurve, metrics) {
      currentEquityCurve = equityCurve || [];
      const canvas = document.getElementById("equityCurveCanvas");
      const ctx = canvas.getContext("2d");
      const width = canvas.width;
      const height = canvas.height;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#0b1120";
      ctx.fillRect(0, 0, width, height);

      const readout = document.getElementById("equityCurveReadoutBar");

      if (currentEquityCurve.length === 0) {
        ctx.fillStyle = "#64748b";
        ctx.font = "14px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("No equity curve data available for this backtest", width / 2, height / 2);
        readout.textContent = "No equity curve data available";
        return;
      }

      const padTop = 20;
      const padBottom = 28;
      const padLeft = 70;
      const padRight = 30;
      const plotWidth = width - padLeft - padRight;
      const plotHeight = height - padTop - padBottom;

      let minEq = Infinity;
      let maxEq = -Infinity;
      currentEquityCurve.forEach(pt => {
        const eq = Number(pt.equity !== undefined ? pt.equity : pt.total_equity);
        if (eq < minEq) minEq = eq;
        if (eq > maxEq) maxEq = eq;
      });

      const range = (maxEq - minEq) || 1.0;
      minEq -= range * 0.05;
      maxEq += range * 0.05;
      const fullRange = maxEq - minEq;

      function scaleX(idx) {
        return padLeft + (idx / Math.max(1, currentEquityCurve.length - 1)) * plotWidth;
      }
      function scaleY(val) {
        return padTop + (1.0 - (val - minEq) / fullRange) * plotHeight;
      }

      ctx.fillStyle = "rgba(255, 255, 255, 0.02)";
      ctx.fillRect(padLeft, padTop, plotWidth, plotHeight);

      ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
      ctx.lineWidth = 1;
      const gridSteps = 4;
      ctx.fillStyle = "#64748b";
      ctx.font = "10px monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= gridSteps; i++) {
        const val = minEq + (i / gridSteps) * fullRange;
        const y = scaleY(val);
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(padLeft + plotWidth, y);
        ctx.stroke();
        ctx.fillText(Number(val).toFixed(0), padLeft - 8, y);
      }

      const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotHeight);
      grad.addColorStop(0, "rgba(34, 197, 94, 0.25)");
      grad.addColorStop(1, "rgba(34, 197, 94, 0.0)");

      ctx.beginPath();
      currentEquityCurve.forEach((pt, idx) => {
        const eq = Number(pt.equity !== undefined ? pt.equity : pt.total_equity);
        const x = scaleX(idx);
        const y = scaleY(eq);
        if (idx === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.lineTo(scaleX(currentEquityCurve.length - 1), padTop + plotHeight);
      ctx.lineTo(scaleX(0), padTop + plotHeight);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      currentEquityCurve.forEach((pt, idx) => {
        const eq = Number(pt.equity !== undefined ? pt.equity : pt.total_equity);
        const x = scaleX(idx);
        const y = scaleY(eq);
        if (idx === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 2;
      ctx.stroke();

      const lastPt = currentEquityCurve[currentEquityCurve.length - 1];
      const lastEq = Number(lastPt.equity !== undefined ? lastPt.equity : lastPt.total_equity);
      readout.textContent = "Final Equity: " + lastEq.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " · Points: " + currentEquityCurve.length + " · Return: " + (metrics ? metrics.total_return_pct + "%" : "—");

      canvas.onmousemove = function(ev) {
        const rect = canvas.getBoundingClientRect();
        const mouseX = (ev.clientX - rect.left) * (canvas.width / rect.width);
        if (mouseX >= padLeft && mouseX <= padLeft + plotWidth) {
          const ratio = (mouseX - padLeft) / plotWidth;
          const idx = Math.min(currentEquityCurve.length - 1, Math.max(0, Math.round(ratio * (currentEquityCurve.length - 1))));
          const pt = currentEquityCurve[idx];
          const eqVal = Number(pt.equity !== undefined ? pt.equity : pt.total_equity);
          const tsStr = (pt.timestamp || "").slice(0, 19).replace("T", " ");
          readout.textContent = "Point #" + (idx + 1) + " · " + tsStr + " · Equity: " + eqVal.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (pt.drawdown_pct ? " · DD: " + pt.drawdown_pct + "%" : "");
        }
      };

      canvas.onmouseleave = function() {
        readout.textContent = "Final Equity: " + lastEq.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " · Points: " + currentEquityCurve.length + " · Return: " + (metrics ? metrics.total_return_pct + "%" : "—");
      };
    }

    async function runBacktest() {
      const market = document.getElementById("marketSelect").value;
      const currency = (market === "NSE") ? "INR" : "USD";
      const exchange = market;
      const rawWl = document.getElementById("watchlistInput").value;
      const symbols = rawWl.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      const symbol = symbols.length > 0 ? symbols[0] : (market === "NSE" ? "RELIANCE" : "AAPL");
      const feedSource = document.getElementById("feedSourceSelect").value;
      const strategyName = document.getElementById("backtestStrategySelect").value;
      const initialCapital = (currency === "INR") ? "1000000" : "25000";

      showStatus("Executing Time Machine backtest (" + symbol + ", " + strategyName + ", " + feedSource + ")...", false);
      try {
        const res = await fetch("/api/backtest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: symbol,
            exchange: exchange,
            currency: currency,
            initial_capital: initialCapital,
            bars_count: 100,
            random_seed: 42,
            monte_carlo_runs: 500,
            feed_source: feedSource,
            strategy_name: strategyName
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Backtest failed: " + (err.detail || res.statusText), true);
          return;
        }
        const data = await res.json();

        document.getElementById("backtestStrategyBadge").textContent = data.strategy_name || strategyName;
        document.getElementById("backtestNetReturn").textContent = data.metrics.total_return_pct + "%";
        document.getElementById("backtestNetReturn").style.color = Number(data.metrics.total_return_pct) >= 0 ? "var(--success)" : "var(--danger)";
        document.getElementById("backtestSharpe").textContent = String(data.metrics.sharpe_ratio);
        document.getElementById("backtestDrawdown").textContent = data.metrics.max_drawdown_pct + "%";
        document.getElementById("backtestWinRate").textContent = data.metrics.win_rate_pct + "%";
        document.getElementById("backtestTradesCount").textContent = String(data.metrics.total_trades);
        document.getElementById("backtestVar").textContent = data.monte_carlo.max_drawdown_pct_p95 + "%";
        document.getElementById("backtestProfitFactor").textContent = String(data.metrics.profit_factor);
        document.getElementById("backtestExpectancy").textContent = formatMoney(data.metrics.expectancy, currency);
        document.getElementById("backtestBars").textContent = String(data.bars_evaluated);

        renderEquityCurve(data.equity_curve, data.metrics);
        switchTab("backtest");

        const lines = [
          "TIME MACHINE BACKTEST COMPLETED",
          "Strategy:             " + (data.strategy_name || strategyName),
          "Manifest ID:          " + data.manifest_id,
          "Manifest SHA-256:     " + data.manifest_sha256,
          "Manifest Verified:    " + data.manifest_verified,
          "Feed Source:          " + data.feed_source,
          "Completed Trades:     " + data.trade_count,
          "Conservation Resid:   " + data.conservation_residual,
          "",
          "Performance Metrics:",
          "  Total Trades:       " + data.metrics.total_trades,
          "  Winning Trades:     " + data.metrics.winning_trades,
          "  Win Rate:           " + data.metrics.win_rate_pct + "%",
          "  Total Return:       " + data.metrics.total_return_pct + "%",
          "  Max Drawdown:       " + data.metrics.max_drawdown_pct + "%",
          "  Sharpe Ratio:       " + data.metrics.sharpe_ratio,
          "",
          "Seeded Monte Carlo (500 Runs):",
          "  Return p50:         " + data.monte_carlo.return_pct_p50 + "%",
          "  Return p05 / p95:   " + data.monte_carlo.return_pct_p05 + "% / " + data.monte_carlo.return_pct_p95 + "%",
          "  Max Drawdown p95:   " + data.monte_carlo.max_drawdown_pct_p95 + "%",
          "  Probability of Loss:" + data.monte_carlo.probability_of_loss_pct + "%"
        ];
        document.getElementById("overviewRawReport").textContent = lines.join("\\n");
        showStatus("Backtest completed (" + data.trade_count + " trades, strategy: " + (data.strategy_name || strategyName) + ")", false);
        await refreshAll();
      } catch (err) {
        showStatus("Backtest error: " + err, true);
      }
    }

    async function runBasketBacktest() {
      const market = document.getElementById("marketSelect").value;
      const currency = (market === "NSE") ? "INR" : "USD";
      const exchange = market;
      const rawWl = document.getElementById("watchlistInput").value;
      const symbols = rawWl.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      const feedSource = document.getElementById("feedSourceSelect").value;
      const strategyName = document.getElementById("backtestStrategySelect").value;
      const initialCapital = (currency === "INR") ? "1000000" : "25000";

      showStatus("Executing Basket & Walk-Forward backtest (" + symbols.join(", ") + ")...", false);
      try {
        const res = await fetch("/api/backtest/basket", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbols: symbols.length > 0 ? symbols : (market === "NSE" ? ["RELIANCE", "TCS", "INFY"] : ["AAPL", "MSFT", "NVDA"]),
            exchange: exchange,
            currency: currency,
            initial_capital: initialCapital,
            bars_count: 100,
            strategy_name: strategyName,
            feed_source: feedSource,
            run_walk_forward: true
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Basket backtest failed: " + (err.detail || res.statusText), true);
          return;
        }
        const data = await res.json();

        document.getElementById("backtestStrategyBadge").textContent = (data.strategy_name || strategyName) + " · Basket";
        document.getElementById("backtestNetReturn").textContent = data.portfolio_metrics.total_return_pct + "%";
        document.getElementById("backtestNetReturn").style.color = Number(data.portfolio_metrics.total_return_pct) >= 0 ? "var(--success)" : "var(--danger)";
        document.getElementById("backtestSharpe").textContent = String(data.portfolio_metrics.sharpe_ratio);
        document.getElementById("backtestDrawdown").textContent = data.portfolio_metrics.max_drawdown_pct + "%";
        document.getElementById("backtestWinRate").textContent = data.portfolio_metrics.win_rate_pct + "%";
        document.getElementById("backtestTradesCount").textContent = String(data.trade_count);
        document.getElementById("backtestVar").textContent = "—";
        document.getElementById("backtestProfitFactor").textContent = String(data.portfolio_metrics.profit_factor);
        document.getElementById("backtestExpectancy").textContent = String(data.portfolio_metrics.expectancy_r) + " R";
        document.getElementById("backtestBars").textContent = String(data.portfolio_metrics.total_trades);

        const wfGrid = document.getElementById("walkForwardGrid");
        if (data.walk_forward_summary) {
          wfGrid.style.display = "grid";
          const inM = data.walk_forward_summary.in_sample_metrics;
          const outM = data.walk_forward_summary.out_of_sample_metrics;
          document.getElementById("wfInReturn").textContent = inM.total_return_pct + "%";
          document.getElementById("wfInSharpe").textContent = inM.sharpe_ratio;
          document.getElementById("wfInDrawdown").textContent = inM.max_drawdown_pct + "%";
          document.getElementById("wfInWinRate").textContent = inM.win_rate_pct + "%";
          document.getElementById("wfInTrades").textContent = String(inM.total_trades);

          document.getElementById("wfOutReturn").textContent = outM.total_return_pct + "%";
          document.getElementById("wfOutReturn").style.color = Number(outM.total_return_pct) >= 0 ? "var(--success)" : "var(--danger)";
          document.getElementById("wfOutSharpe").textContent = outM.sharpe_ratio;
          document.getElementById("wfOutDrawdown").textContent = outM.max_drawdown_pct + "%";
          document.getElementById("wfOutWinRate").textContent = outM.win_rate_pct + "%";
          document.getElementById("wfBestParams").textContent = JSON.stringify(data.walk_forward_summary.best_params);
        } else {
          wfGrid.style.display = "none";
        }

        const attrCard = document.getElementById("basketAttributionCard");
        const attrContainer = document.getElementById("basketAttributionContainer");
        while (attrContainer.firstChild) attrContainer.removeChild(attrContainer.firstChild);

        if (data.per_symbol_attribution && Object.keys(data.per_symbol_attribution).length > 0) {
          attrCard.style.display = "block";
          document.getElementById("basketSymbolCountBadge").textContent = Object.keys(data.per_symbol_attribution).length + " Symbols";

          const table = document.createElement("table");
          table.className = "table";
          const thead = document.createElement("thead");
          const trHead = document.createElement("tr");
          ["Symbol", "Exchange", "Trades", "Win Rate", "Realized PnL", "Return %"].forEach(h => {
            const th = document.createElement("th");
            th.textContent = h;
            trHead.appendChild(th);
          });
          thead.appendChild(trHead);
          table.appendChild(thead);

          const tbody = document.createElement("tbody");
          for (const sym of Object.keys(data.per_symbol_attribution)) {
            const item = data.per_symbol_attribution[sym];
            const tr = document.createElement("tr");

            const tdSym = document.createElement("td");
            tdSym.style.fontWeight = "600";
            tdSym.textContent = item.symbol;
            tr.appendChild(tdSym);

            const tdEx = document.createElement("td");
            tdEx.textContent = item.exchange;
            tr.appendChild(tdEx);

            const tdTr = document.createElement("td");
            tdTr.textContent = String(item.trades);
            tr.appendChild(tdTr);

            const tdWr = document.createElement("td");
            tdWr.textContent = item.win_rate_pct + "%";
            tr.appendChild(tdWr);

            const tdPnl = document.createElement("td");
            tdPnl.textContent = formatMoney(item.realized_pnl, currency);
            tdPnl.style.color = Number(item.realized_pnl) >= 0 ? "var(--success)" : "var(--danger)";
            tr.appendChild(tdPnl);

            const tdRet = document.createElement("td");
            tdRet.textContent = item.total_return_pct + "%";
            tdRet.style.color = Number(item.total_return_pct) >= 0 ? "var(--success)" : "var(--danger)";
            tr.appendChild(tdRet);

            tbody.appendChild(tr);
          }
          table.appendChild(tbody);
          attrContainer.appendChild(table);
        } else {
          attrCard.style.display = "none";
        }

        renderEquityCurve(data.equity_curve, data.portfolio_metrics);
        switchTab("backtest");
        showStatus("Basket backtest completed (" + data.trade_count + " total trades, residual: " + data.conservation_residual + ")", false);
        await refreshAll();
      } catch (err) {
        showStatus("Basket backtest error: " + err, true);
      }
    }

    function exportJournal(fmt) {
      window.open("/api/journal/export?format=" + encodeURIComponent(fmt), "_blank");
    }

    async function refreshAll() {
      await fetchHealth();
      await loadPortfolio("INR");
      await loadPortfolio("USD");
    }

    document.getElementById("toggleKillBtn").addEventListener("click", toggleKillSwitch);
    document.getElementById("resetSandboxBtn").addEventListener("click", resetSandbox);
    document.getElementById("refreshPositionsBtn").addEventListener("click", loadPositions);
    document.getElementById("addLessonBtn").addEventListener("click", addLesson);
    document.getElementById("lessonInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addLesson();
    });
    document.getElementById("autoBuyToggle").addEventListener("change", (e) => {
      const label = document.getElementById("autoBuyLabel");
      if (e.target.checked) {
        label.textContent = "Auto-Buy ON";
        label.style.color = "var(--accent)";
      } else {
        label.textContent = "Auto-Buy OFF";
        label.style.color = "var(--amber)";
      }
    });
    document.getElementById("runDeskBtn").addEventListener("click", runDeskCycle);
    document.getElementById("runBacktestBtn").addEventListener("click", runBacktest);
    document.getElementById("runBasketBacktestBtn").addEventListener("click", runBasketBacktest);
    document.getElementById("exportJournalCsvBtn").addEventListener("click", () => exportJournal("csv"));
    document.getElementById("exportJournalJsonBtn").addEventListener("click", () => exportJournal("json"));
    document.getElementById("toggleSettingsBtn").addEventListener("click", toggleSettings);
    document.getElementById("tabOverviewBtn").addEventListener("click", () => switchTab("overview"));
    document.getElementById("tabChatBtn").addEventListener("click", () => switchTab("chat"));
    document.getElementById("tabPositionsBtn").addEventListener("click", () => switchTab("positions"));
    document.getElementById("tabBacktestBtn").addEventListener("click", () => switchTab("backtest"));
    document.getElementById("tabLessonsBtn").addEventListener("click", () => switchTab("lessons"));
    document.getElementById("cycleSelect").addEventListener("change", (e) => {
      if (e.target.value) loadCycleDetail(e.target.value);
    });

    refreshAll();
    loadCycleList();
  </script>
</body>
</html>
"""


def get_dashboard_html() -> str:
    return DASHBOARD_HTML
