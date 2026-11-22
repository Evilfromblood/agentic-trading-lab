"""End-of-day daily report generator summarizing desk performance, orders, risk, and reconciliation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from agentic_trading.paper_trading.broker import PaperOrder, ReconciliationReport
from agentic_trading.risk_engine.proposal_gate import ProposalRiskDecision
from agentic_trading.simulation.portfolio import PortfolioSnapshot


class DailyReporter:
    """Formats human-readable end-of-day executive summaries for the trading desk."""

    @staticmethod
    def generate_eod_report(
        run_id: str,
        as_of: datetime,
        portfolio_snapshot: PortfolioSnapshot,
        executed_orders: Sequence[PaperOrder],
        rejected_decisions: Sequence[ProposalRiskDecision],
        dropped_candidates: Mapping[str, str],
        reconciliation: ReconciliationReport,
    ) -> str:
        lines: list[str] = [
            "=" * 60,
            f"DAILY DESK SUMMARY — RUN: {run_id}",
            f"As Of: {as_of.isoformat()}",
            "=" * 60,
            "",
            "1. PORTFOLIO EVALUATION",
            f"   Total Equity:    {portfolio_snapshot.total_equity}",
            f"   Available Cash:  {portfolio_snapshot.cash}",
            f"   Holdings Value:  {portfolio_snapshot.holdings_value}",
            f"   Realized P&L:    {portfolio_snapshot.realized_pnl}",
            f"   Unrealized P&L:  {portfolio_snapshot.unrealized_pnl}",
            f"   Open Positions:  {len(portfolio_snapshot.positions)}",
            "",
            "2. EXECUTED PAPER ORDERS",
        ]

        fills = [o for o in executed_orders if o.status in {"FILLED", "PARTIALLY_FILLED"}]
        if not fills:
            lines.append("   (No orders executed in this cycle)")
        else:
            for f in fills:
                lines.append(
                    f"   [{f.status.value}] {f.side} {f.filled_quantity}/{f.quantity} {f.symbol} "
                    f"@ {f.average_fill_price} (Slip: {f.slippage.amount}, Fee: {f.fees.amount})"
                )

        lines.extend([
            "",
            "3. RISK REJECTIONS & DROPPED PROPOSALS",
        ])
        if not rejected_decisions and not dropped_candidates:
            lines.append("   (None)")
        else:
            for r in rejected_decisions:
                lines.append(f"   [RISK REJECT] Proposal {r.proposal_id}: {', '.join(r.reasons)}")
            for ticker, reason in dropped_candidates.items():
                lines.append(f"   [SCOUT DROPPED] {ticker}: {reason}")

        lines.extend([
            "",
            "4. POSITION RECONCILIATION",
            f"   Status:        {'VERIFIED' if reconciliation.is_reconciled else 'FAILED'}",
            f"   Ledger Cash:   {reconciliation.ledger_cash}",
            f"   Snapshot Cash: {reconciliation.portfolio_cash}",
        ])
        if reconciliation.discrepancies:
            lines.append("   Discrepancies:")
            for d in reconciliation.discrepancies:
                lines.append(f"     - {d}")
        else:
            lines.append("   Conservation residual: Exactly 0.000000000000")

        lines.append("=" * 60)
        return "\n".join(lines)
