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
      --bg: #0b0f19;
      --card-bg: #111827;
      --border: #1f2937;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --danger: #ef4444;
      --danger-hover: #dc2626;
      --danger-bg: rgba(239, 68, 68, 0.12);
      --danger-border: rgba(239, 68, 68, 0.3);
      --success: #10b981;
      --success-bg: rgba(16, 185, 129, 0.12);
      --amber: #f59e0b;
      --amber-bg: rgba(245, 158, 11, 0.12);
      --amber-border: rgba(245, 158, 11, 0.3);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 32px 20px;
    }
    .container {
      max-width: 1020px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }
    .header-left h1 {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .header-right {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.04em;
    }
    .pill-amber {
      background: var(--amber-bg);
      color: var(--amber);
      border: 1px solid var(--amber-border);
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
    .status-indicator.stopped .status-dot {
      background: var(--danger);
    }
    .status-indicator.stopped {
      color: var(--danger);
    }
    .btn {
      cursor: pointer;
      font-weight: 600;
      border-radius: 6px;
      padding: 8px 14px;
      font-size: 0.85rem;
      border: 1px solid transparent;
      transition: background-color 0.15s, opacity 0.15s;
    }
    .btn:hover { opacity: 0.92; }
    .btn:active { transform: scale(0.98); }
    .btn-primary {
      background: var(--accent);
      color: #ffffff;
    }
    .btn-secondary {
      background: #1e293b;
      color: var(--text);
      border-color: var(--border);
    }
    .btn-secondary:hover {
      background: #334155;
    }
    .btn-ghost {
      background: transparent;
      color: var(--text-muted);
      border-color: var(--border);
    }
    .btn-ghost:hover {
      background: #1e293b;
      color: var(--text);
    }
    .btn-danger-outline {
      background: var(--danger-bg);
      color: #fca5a5;
      border-color: var(--danger-border);
    }
    .btn-danger-outline:hover {
      background: rgba(239, 68, 68, 0.2);
    }
    .btn-success-outline {
      background: var(--success-bg);
      color: #86efac;
      border-color: rgba(16, 185, 129, 0.3);
    }
    .portfolio-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .card-title {
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .card-tag {
      font-size: 0.75rem;
      color: var(--text-dim);
    }
    .equity-figure {
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 16px;
      font-variant-numeric: tabular-nums;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      padding: 7px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      font-size: 0.85rem;
    }
    .metric-row:last-child {
      border-bottom: none;
    }
    .metric-name {
      color: var(--text-muted);
    }
    .metric-num {
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .warning-badge {
      margin-top: 12px;
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
      margin-bottom: 24px;
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
      gap: 16px;
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
      font-size: 0.83rem;
      color: var(--text-muted);
    }
    .setting-group select {
      background: #0f172a;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 10px;
      border-radius: 5px;
      font-size: 0.83rem;
    }
    .output-section {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
    }
    .output-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .output-title {
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .output-meta {
      font-size: 0.78rem;
      color: var(--accent);
      font-family: monospace;
    }
    .output-pre {
      background: #080d1a;
      border: 1px solid #172033;
      padding: 14px;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.82rem;
      color: #cbd5e1;
      overflow-x: auto;
      white-space: pre-wrap;
      max-height: 480px;
      overflow-y: auto;
      line-height: 1.6;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-left">
        <h1>Agentic Trading Lab</h1>
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
          <label for="feedSourceSelect">Feed Source:</label>
          <select id="feedSourceSelect">
            <option value="cache">Replay Fixture Cache</option>
            <option value="delayed_feed">Delayed Public Feed</option>
            <option value="synthetic" selected>Synthetic (Deterministic)</option>
          </select>
        </div>
        <div class="setting-group">
          <label for="llmBackendSelect">LLM Backend:</label>
          <select id="llmBackendSelect">
            <option value="stub" selected>Deterministic Stub</option>
            <option value="ollama">Local Ollama (gemma4:12b)</option>
          </select>
        </div>
      </div>
    </div>

    <div class="output-section">
      <div class="output-header">
        <span class="output-title">Desk Output</span>
        <span id="outputMeta" class="output-meta">Idle</span>
      </div>
      <pre id="outputContainer" class="output-pre">Ready. Click an action above to start a cycle.</pre>
    </div>
  </div>

  <script>
    let killSwitchActive = false;

    function formatMoney(amountStr, currency) {
      const num = parseFloat(amountStr);
      if (isNaN(num)) return amountStr + " " + currency;
      return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " " + currency;
    }

    function setOutput(statusLine, contentText) {
      const meta = document.getElementById("outputMeta");
      meta.textContent = statusLine;
      const container = document.getElementById("outputContainer");
      container.textContent = contentText;
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
        setOutput("Error", "Health check error: " + err);
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
          await refreshAll();
          setOutput(nextState ? "Stopped" : "Active", "Kill switch toggled: active=" + nextState);
        } else {
          const errData = await res.json();
          setOutput("Error", "Kill switch toggle failed: " + (errData.detail || res.statusText));
        }
      } catch (err) {
        setOutput("Error", "Kill switch request failed: " + err);
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
        setOutput("Error", "Failed to load portfolio " + curr + ": " + err);
      }
    }

    async function refreshAll() {
      await fetchHealth();
      await loadPortfolio("INR");
      await loadPortfolio("USD");
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

    async function runDeskCycle() {
      const feedSource = document.getElementById("feedSourceSelect").value;
      const llmBackend = document.getElementById("llmBackendSelect").value;
      setOutput("Running...", "Initiating 7-Agent Research Desk cycle (Feed: " + feedSource + ", LLM: " + llmBackend + ")...");
      try {
        const res = await fetch("/api/desk/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            watchlist: ["RELIANCE", "TCS"],
            exchange: "NSE",
            currency: "INR",
            feed_source: feedSource,
            llm_backend: llmBackend,
            ollama_model: "gemma4:12b"
          })
        });
        if (!res.ok) {
          const err = await res.json();
          setOutput("Rejected", "Desk run rejected: " + (err.detail || res.statusText));
          return;
        }
        const data = await res.json();
        setOutput("Completed · " + feedSource + " · " + llmBackend, data.report_markdown);
        await refreshAll();
      } catch (err) {
        setOutput("Error", "Desk run error: " + err);
      }
    }

    async function runBacktest() {
      const feedSource = document.getElementById("feedSourceSelect").value;
      setOutput("Running...", "Executing Time Machine backtest (Feed: " + feedSource + ", RELIANCE, NSE)...");
      try {
        const res = await fetch("/api/backtest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: "RELIANCE",
            exchange: "NSE",
            currency: "INR",
            initial_capital: "1000000",
            bars_count: 100,
            random_seed: 42,
            monte_carlo_runs: 500,
            feed_source: feedSource
          })
        });
        if (!res.ok) {
          const err = await res.json();
          setOutput("Failed", "Backtest failed: " + (err.detail || res.statusText));
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
        setOutput("Completed · " + data.feed_source + " · Time Machine", lines.join("\\n"));
        await refreshAll();
      } catch (err) {
        setOutput("Error", "Backtest error: " + err);
      }
    }

    document.getElementById("toggleKillBtn").addEventListener("click", toggleKillSwitch);
    document.getElementById("runDeskBtn").addEventListener("click", runDeskCycle);
    document.getElementById("runBacktestBtn").addEventListener("click", runBacktest);
    document.getElementById("toggleSettingsBtn").addEventListener("click", toggleSettings);

    refreshAll();
  </script>
</body>
</html>
"""


def get_dashboard_html() -> str:
    return DASHBOARD_HTML
