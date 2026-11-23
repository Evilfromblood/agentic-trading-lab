"""End-of-day daily report generator summarizing desk performance, orders, risk, and reconciliation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from agentic_trading.paper_trading.broker import PaperOrder, ReconciliationReport
from agentic_trading.risk_engine.proposal_gate import ProposalRiskDecision
from agentic_trading.simulation.portfolio import PortfolioSnapshot


def _format_value(val: Any) -> str:
    if hasattr(val, "amount") and hasattr(val, "currency"):
        curr = getattr(val.currency, "value", str(val.currency))
        return f"{val.amount:,.2f} {curr}"
    if isinstance(val, (int, float, Decimal)):
        return f"{val:,.2f}"
    return str(val)


class DailyReporter:
    """Formats human-readable end-of-day executive summaries for the trading desk."""

    @classmethod
    def generate_eod_report(
        cls,
        run_id: str,
        as_of: datetime,
        portfolio_snapshot: PortfolioSnapshot,
        executed_orders: Sequence[PaperOrder],
        rejected_decisions: Sequence[ProposalRiskDecision],
        dropped_candidates: Mapping[str, str],
        reconciliation: ReconciliationReport,
    ) -> str:
        as_of_str = as_of.strftime("%Y-%m-%d %H:%M:%S UTC") if as_of.tzinfo else as_of.isoformat()
        lines: list[str] = [
            f"DAILY DESK SUMMARY — {run_id}",
            f"As Of: {as_of_str}",
            "",
            "Portfolio Summary",
            f"  Total Equity:    {_format_value(portfolio_snapshot.total_equity)}",
            f"  Available Cash:  {_format_value(portfolio_snapshot.cash)}",
            f"  Holdings Value:  {_format_value(portfolio_snapshot.holdings_value)}",
            f"  Realized P&L:    {_format_value(portfolio_snapshot.realized_pnl)}",
            f"  Unrealized P&L:  {_format_value(portfolio_snapshot.unrealized_pnl)}",
            f"  Open Positions:  {len(portfolio_snapshot.positions)}",
            "",
            "Executed Orders",
        ]

        fills = [o for o in executed_orders if o.status in {"FILLED", "PARTIALLY_FILLED"}]
        if not fills:
            lines.append("  (No orders executed in this cycle)")
        else:
            for f in fills:
                lines.append(
                    f"  [{f.status.value}] {f.side} {f.filled_quantity}/{f.quantity} {f.symbol} "
                    f"@ {_format_value(f.average_fill_price)} (Slippage: {_format_value(f.slippage)}, Fee: {_format_value(f.fees)})"
                )

        lines.extend([
            "",
            "Skipped / Rejected",
        ])
        if not rejected_decisions and not dropped_candidates:
            lines.append("  (None)")
        else:
            for r in rejected_decisions:
                lines.append(f"  [RISK REJECT] Proposal {r.proposal_id}: {', '.join(r.reasons)}")
            for ticker, reason in dropped_candidates.items():
                lines.append(f"  [SCOUT DROPPED] {ticker}: {reason}")

        lines.extend([
            "",
            "Position Reconciliation",
            f"  Status:        {'VERIFIED' if reconciliation.is_reconciled else 'FAILED'}",
            f"  Ledger Cash:   {_format_value(reconciliation.ledger_cash)}",
            f"  Snapshot Cash: {_format_value(reconciliation.portfolio_cash)}",
        ])
        if reconciliation.discrepancies:
            lines.append("  Discrepancies:")
            for d in reconciliation.discrepancies:
                lines.append(f"    - {d}")
        else:
            lines.append("  Conservation:  Exact 0 residual verified")

        return "\n".join(lines)

    format_report = generate_eod_report
