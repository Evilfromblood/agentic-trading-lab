"""Local-first FastAPI REST API and interactive web dashboard for Agentic Trading Lab."""
from __future__ import annotations

from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState

__all__ = ["TradingLabState", "create_app"]
