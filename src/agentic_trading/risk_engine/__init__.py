"""Deterministic, fail-closed risk checks for paper orders and trade proposals."""
from __future__ import annotations

from agentic_trading.risk_engine.core import (
    OrderProposal,
    RiskDecision,
    Side,
    _decimal,
    evaluate_order,
)
from agentic_trading.risk_engine.proposal_gate import (
    PortfolioRiskPolicy,
    ProposalRiskDecision,
    evaluate_trade_proposal,
)

__all__ = [
    "OrderProposal",
    "PortfolioRiskPolicy",
    "ProposalRiskDecision",
    "RiskDecision",
    "Side",
    "_decimal",
    "evaluate_order",
    "evaluate_trade_proposal",
]
