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
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --danger: #ef4444;
      --success: #22c55e;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 20px;
    }
    .banner {
      background: #7f1d1d;
      color: #fecaca;
      font-weight: 700;
      text-align: center;
      padding: 12px;
      border-radius: 8px;
      margin-bottom: 24px;
      border: 1px solid #b91c1c;
      letter-spacing: 0.05em;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    h1 { font-size: 1.5rem; }
    .status-badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      background: #14532d;
      color: #86efac;
    }
    .status-badge.stopped {
      background: #7f1d1d;
      color: #fca5a5;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }
    .card-title {
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .metric {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .metric:last-child { border-bottom: none; }
    .metric-label { color: var(--text-muted); }
    .metric-val { font-weight: 600; font-family: monospace; }
    .residual-tag {
      display: inline-block;
      margin-top: 14px;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      background: #064e3b;
      color: #a7f3d0;
      border: 1px solid #059669;
    }
    .btn {
      cursor: pointer;
      font-weight: 600;
      border-radius: 6px;
      padding: 10px 16px;
      border: none;
      transition: opacity 0.2s;
    }
    .btn:hover { opacity: 0.9; }
    .btn:active { transform: scale(0.98); }
    .btn-danger { background: var(--danger); color: #fff; }
    .btn-accent { background: var(--accent); color: #0f172a; margin-right: 10px; }
    .btn-success { background: var(--success); color: #0f172a; }
    .actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }
    .output-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
      min-height: 180px;
    }
    .console-pre {
      background: #090d16;
      border: 1px solid #1e293b;
      padding: 14px;
      border-radius: 6px;
      font-family: monospace;
      font-size: 0.85rem;
      color: #cbd5e1;
      overflow-x: auto;
      white-space: pre-wrap;
      max-height: 400px;
      overflow-y: auto;
    }
  </style>
</head>
<body>
  <div class="banner">
    ⚠️ PAPER TRADING ONLY — ALL SIMULATED EXECUTION — ZERO REAL-MONEY BROKER ROUTING ⚠️
  </div>

  <header>
    <div>
      <h1>Agentic Trading Lab</h1>
      <p style="color: var(--text-muted); font-size: 0.9rem;">Milestone 6: Local-First Research Desk & Time Machine</p>
    </div>
    <div style="display: flex; align-items: center; gap: 14px;">
      <span id="killStatusBadge" class="status-badge">DESK RUNNING</span>
      <button id="toggleKillBtn" class="btn btn-danger">EMERGENCY STOP</button>
    </div>
  </header>

  <div class="grid">
    <div class="card" id="inrCard">
      <div class="card-title">
        <span>INR Portfolio</span>
        <span style="font-size: 0.8rem; color: var(--accent);">NSE / BSE</span>
      </div>
      <div class="metric"><span class="metric-label">Cash</span><span class="metric-val" id="inrCash">—</span></div>
      <div class="metric"><span class="metric-label">Holdings</span><span class="metric-val" id="inrHoldings">—</span></div>
      <div class="metric"><span class="metric-label">Total Equity</span><span class="metric-val" id="inrEquity">—</span></div>
      <div class="metric"><span class="metric-label">Realized P&amp;L</span><span class="metric-val" id="inrRealized">—</span></div>
      <div class="metric"><span class="metric-label">Open Positions</span><span class="metric-val" id="inrPosCount">—</span></div>
      <div><span class="residual-tag" id="inrResidual">Conservation Residual: 0.000000000000</span></div>
    </div>

    <div class="card" id="usdCard">
      <div class="card-title">
        <span>USD Portfolio</span>
        <span style="font-size: 0.8rem; color: var(--accent);">NYSE / NASDAQ</span>
      </div>
      <div class="metric"><span class="metric-label">Cash</span><span class="metric-val" id="usdCash">—</span></div>
      <div class="metric"><span class="metric-label">Holdings</span><span class="metric-val" id="usdHoldings">—</span></div>
      <div class="metric"><span class="metric-label">Total Equity</span><span class="metric-val" id="usdEquity">—</span></div>
      <div class="metric"><span class="metric-label">Realized P&amp;L</span><span class="metric-val" id="usdRealized">—</span></div>
      <div class="metric"><span class="metric-label">Open Positions</span><span class="metric-val" id="usdPosCount">—</span></div>
      <div><span class="residual-tag" id="usdResidual">Conservation Residual: 0.000000000000</span></div>
    </div>
  </div>

  <div class="actions">
    <button id="runDeskBtn" class="btn btn-accent">Run 7-Agent Desk Cycle (RELIANCE/TCS)</button>
    <button id="runBacktestBtn" class="btn btn-success">Run Time Machine Backtest (100 Bars)</button>
    <button id="refreshBtn" class="btn" style="background: #334155; color: #fff;">Refresh Portfolios</button>
  </div>

  <div class="output-card">
    <div class="card-title">Execution Log / Desk Output</div>
    <div id="outputContainer" class="console-pre">Ready. Click an action above to start a cycle.</div>
  </div>

  <script>
    let killSwitchActive = false;

    function renderOutput(text) {
      const container = document.getElementById("outputContainer");
      container.textContent = text;
    }

    async function fetchHealth() {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) return;
        const data = await res.json();
        killSwitchActive = Boolean(data.kill_switch_active);
        const badge = document.getElementById("killStatusBadge");
        const btn = document.getElementById("toggleKillBtn");
        if (killSwitchActive) {
          badge.textContent = "STOPPED (KILL SWITCH ACTIVE)";
          badge.className = "status-badge stopped";
          btn.textContent = "CLEAR KILL SWITCH";
          btn.className = "btn btn-success";
        } else {
          badge.textContent = "DESK RUNNING";
          badge.className = "status-badge";
          btn.textContent = "EMERGENCY STOP";
          btn.className = "btn btn-danger";
        }
      } catch (err) {
        renderOutput("Health check error: " + err);
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
          renderOutput("Kill switch toggled: active=" + nextState);
        } else {
          const errData = await res.json();
          renderOutput("Kill switch toggle failed: " + (errData.detail || res.statusText));
        }
      } catch (err) {
        renderOutput("Kill switch request failed: " + err);
      }
    }

    async function loadPortfolio(curr) {
      try {
        const res = await fetch("/api/portfolios/" + curr);
        if (!res.ok) return;
        const data = await res.json();
        const prefix = curr.toLowerCase();
        document.getElementById(prefix + "Cash").textContent = data.cash + " " + curr;
        document.getElementById(prefix + "Holdings").textContent = data.holdings_value + " " + curr;
        document.getElementById(prefix + "Equity").textContent = data.total_equity + " " + curr;
        document.getElementById(prefix + "Realized").textContent = data.realized_pnl + " " + curr;
        document.getElementById(prefix + "PosCount").textContent = data.positions.length;
        document.getElementById(prefix + "Residual").textContent = "Conservation Residual: " + data.conservation_residual;
      } catch (err) {
        renderOutput("Failed to load portfolio " + curr + ": " + err);
      }
    }

    async function refreshAll() {
      await fetchHealth();
      await loadPortfolio("INR");
      await loadPortfolio("USD");
    }

    async function runDeskCycle() {
      renderOutput("Initiating 7-Agent Research Desk cycle for RELIANCE & TCS...");
      try {
        const res = await fetch("/api/desk/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            watchlist: ["RELIANCE", "TCS"],
            exchange: "NSE",
            currency: "INR"
          })
        });
        if (!res.ok) {
          const err = await res.json();
          renderOutput("Desk run rejected: " + (err.detail || res.statusText));
          return;
        }
        const data = await res.json();
        renderOutput(data.report_markdown);
        await refreshAll();
      } catch (err) {
        renderOutput("Desk run error: " + err);
      }
    }

    async function runBacktest() {
      renderOutput("Executing Time Machine backtest (100 synthetic bars, RELIANCE, NSE)...");
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
            monte_carlo_runs: 500
          })
        });
        if (!res.ok) {
          const err = await res.json();
          renderOutput("Backtest failed: " + (err.detail || res.statusText));
          return;
        }
        const data = await res.json();
        const lines = [
          "============================================================",
          "TIME MACHINE BACKTEST COMPLETED",
          "============================================================",
          "Manifest ID:          " + data.manifest_id,
          "Manifest SHA-256:     " + data.manifest_sha256,
          "Manifest Verified:    " + data.manifest_verified,
          "Completed Trades:     " + data.trade_count,
          "Conservation Resid:   " + data.conservation_residual,
          "",
          "PERFORMANCE METRICS:",
          "  Total Trades:       " + data.metrics.total_trades,
          "  Winning Trades:     " + data.metrics.winning_trades,
          "  Win Rate:           " + data.metrics.win_rate_pct + "%",
          "  Total Return:       " + data.metrics.total_return_pct + "%",
          "  Max Drawdown:       " + data.metrics.max_drawdown_pct + "%",
          "  Sharpe Ratio:       " + data.metrics.sharpe_ratio,
          "",
          "SEEDED MONTE CARLO (500 Runs):",
          "  Return p50:         " + data.monte_carlo.return_pct_p50 + "%",
          "  Return p05 / p95:   " + data.monte_carlo.return_pct_p05 + "% / " + data.monte_carlo.return_pct_p95 + "%",
          "  Max Drawdown p95:   " + data.monte_carlo.max_drawdown_pct_p95 + "%",
          "  Probability of Loss:" + data.monte_carlo.probability_of_loss_pct + "%",
          "============================================================"
        ];
        renderOutput(lines.join("\\n"));
      } catch (err) {
        renderOutput("Backtest error: " + err);
      }
    }

    document.getElementById("toggleKillBtn").addEventListener("click", toggleKillSwitch);
    document.getElementById("runDeskBtn").addEventListener("click", runDeskCycle);
    document.getElementById("runBacktestBtn").addEventListener("click", runBacktest);
    document.getElementById("refreshBtn").addEventListener("click", refreshAll);

    refreshAll();
  </script>
</body>
</html>
"""


def get_dashboard_html() -> str:
    return DASHBOARD_HTML
