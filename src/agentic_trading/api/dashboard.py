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
      gap: 10px;
      flex-wrap: wrap;
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
        <div class="cycle-detail-item"><strong>Feed:</strong> <span id="cycleFeedPill" class="pill pill-blue">—</span></div>
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
        <button id="runBacktestBtn" class="btn btn-secondary">Run Backtest</button>
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
  </div>

  <script>
    let killSwitchActive = false;
    let loadedCycles = [];
    let currentSelectedRunId = null;

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
      const overviewBtn = document.getElementById("tabOverviewBtn");
      const chatBtn = document.getElementById("tabChatBtn");
      const overviewPane = document.getElementById("tabOverviewPane");
      const chatPane = document.getElementById("tabChatPane");

      if (tabName === "overview") {
        overviewBtn.className = "tab-btn active";
        chatBtn.className = "tab-btn";
        overviewPane.className = "tab-pane active";
        chatPane.className = "tab-pane";
      } else {
        overviewBtn.className = "tab-btn";
        chatBtn.className = "tab-btn active";
        overviewPane.className = "tab-pane";
        chatPane.className = "tab-pane active";
      }
    }

    function renderStatusPill(status) {
      const pill = document.createElement("span");
      pill.className = "pill";
      if (status === "ok" || status === "approved") {
        pill.classList.add("pill-success");
      } else if (status === "rejected") {
        pill.classList.add("pill-danger");
      } else if (status === "no_trade") {
        pill.classList.add("pill-slate");
      } else if (status === "missing") {
        pill.classList.add("pill-amber");
      } else {
        pill.classList.add("pill-blue");
      }
      pill.textContent = status;
      return pill;
    }

    function updateCycleStrip(detail) {
      document.getElementById("cycleIdText").textContent = detail.run_id;
      const ts = new Date(detail.timestamp);
      document.getElementById("cycleTimeText").textContent = isNaN(ts.getTime()) ? detail.timestamp : ts.toLocaleString();
      document.getElementById("cycleMarketText").textContent = detail.currency;
      document.getElementById("cycleFeedPill").textContent = detail.feed_source;
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
          opt.textContent = c.run_id + " (" + timeStr + ", " + c.currency + ")";
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
      const llmBackend = document.getElementById("llmBackendSelect").value;
      const ollamaModel = document.getElementById("ollamaModelInput").value.trim() || "gemma4:12b";

      showStatus("Initiating 7-Agent Research Desk cycle (" + feedSource + ", " + llmBackend + ")...", false);
      try {
        const res = await fetch("/api/desk/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            watchlist: watchlist,
            exchange: exchange,
            currency: currency,
            feed_source: feedSource,
            llm_backend: llmBackend,
            ollama_model: ollamaModel
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

    async function runBacktest() {
      const market = document.getElementById("marketSelect").value;
      const currency = (market === "NSE") ? "INR" : "USD";
      const exchange = market;
      const rawWl = document.getElementById("watchlistInput").value;
      const symbols = rawWl.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      const symbol = symbols.length > 0 ? symbols[0] : (market === "NSE" ? "RELIANCE" : "AAPL");
      const feedSource = document.getElementById("feedSourceSelect").value;
      const initialCapital = (currency === "INR") ? "1000000" : "25000";

      showStatus("Executing Time Machine backtest (" + symbol + ", " + exchange + ", " + feedSource + ")...", false);
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
            feed_source: feedSource
          })
        });
        if (!res.ok) {
          const err = await res.json();
          showStatus("Backtest failed: " + (err.detail || res.statusText), true);
          return;
        }
        const data = await res.json();
        const lines = [
          "TIME MACHINE BACKTEST COMPLETED",
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
        showStatus("Backtest completed (" + data.trade_count + " trades, manifest: " + data.manifest_id + ")", false);
        await refreshAll();
      } catch (err) {
        showStatus("Backtest error: " + err, true);
      }
    }

    async function refreshAll() {
      await fetchHealth();
      await loadPortfolio("INR");
      await loadPortfolio("USD");
    }

    document.getElementById("toggleKillBtn").addEventListener("click", toggleKillSwitch);
    document.getElementById("runDeskBtn").addEventListener("click", runDeskCycle);
    document.getElementById("runBacktestBtn").addEventListener("click", runBacktest);
    document.getElementById("toggleSettingsBtn").addEventListener("click", toggleSettings);
    document.getElementById("tabOverviewBtn").addEventListener("click", () => switchTab("overview"));
    document.getElementById("tabChatBtn").addEventListener("click", () => switchTab("chat"));
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
