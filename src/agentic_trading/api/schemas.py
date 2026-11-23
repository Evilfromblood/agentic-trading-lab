"""Pydantic v2 schemas for local-first paper trading API and web dashboard."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _check_finite_positive(v: Any) -> Decimal:
    if isinstance(v, bool):
        raise ValueError("boolean values are disallowed for monetary or price quantities")
    if isinstance(v, float):
        raise ValueError("floating point values are disallowed; use Decimal or numeric string")
    try:
        dec = Decimal(str(v))
    except Exception as exc:
        raise ValueError(f"invalid decimal value: {v}") from exc
    if not dec.is_finite():
        raise ValueError("value must be finite; NaN and Infinity are disallowed")
    if dec <= Decimal("0"):
        raise ValueError("value must be strictly positive (> 0)")
    return dec


def _check_optional_finite_positive(v: Any) -> Decimal | None:
    if v is None:
        return None
    return _check_finite_positive(v)


def _check_positive_int(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError("boolean values are disallowed for integer counts")
    if not isinstance(v, int):
        try:
            v = int(v)
        except Exception as exc:
            raise ValueError(f"invalid integer: {v}") from exc
    if v <= 0:
        raise ValueError("integer value must be strictly positive (> 0)")
    return v


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    paper_only: Literal[True] = True
    kill_switch_active: bool
    kill_switch_reason: str | None = None


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str = "MANUAL_UI_STOP"


class KillSwitchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str | None = None
    paper_only: Literal[True] = True


class PositionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange: str
    quantity: int
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


class PortfolioSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["INR", "USD"]
    paper_only: Literal[True] = True
    cash: Decimal
    holdings_value: Decimal
    total_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees_paid: Decimal
    conservation_residual: Decimal
    is_reconciled: bool
    positions: list[PositionSummary] = []
    recent_events: list[dict[str, Any]] = []
    discrepancies: list[str] = []


class SubmitOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"]
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    quote_price: Decimal
    limit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    client_order_id: str | None = None

    @field_validator("run_id", "symbol")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        clean = v.strip().upper() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("must be a non-empty string")
        return clean

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v: Any) -> int:
        return _check_positive_int(v)

    @field_validator("quote_price", mode="before")
    @classmethod
    def validate_quote_price(cls, v: Any) -> Decimal:
        return _check_finite_positive(v)

    @field_validator("limit_price", "stop_loss", "take_profit", mode="before")
    @classmethod
    def validate_optional_prices(cls, v: Any) -> Decimal | None:
        return _check_optional_finite_positive(v)


class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    run_id: str
    exchange: str
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    status: str
    limit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    average_fill_price: Decimal | None = None
    fees: Decimal
    slippage: Decimal
    reject_reason: str | None = None
    submitted_at: datetime
    filled_at: datetime | None = None
    paper_only: Literal[True] = True


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = "RELIANCE"
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"] = "NSE"
    initial_capital: Decimal = Decimal("1000000")
    currency: Literal["INR", "USD"] = "INR"
    bars_count: int = 100
    random_seed: int = 42
    monte_carlo_runs: int = 500

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        clean = v.strip().upper() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("symbol must be a non-empty string")
        return clean

    @field_validator("initial_capital", mode="before")
    @classmethod
    def validate_capital(cls, v: Any) -> Decimal:
        return _check_finite_positive(v)

    @field_validator("bars_count", mode="before")
    @classmethod
    def validate_bars_count(cls, v: Any) -> int:
        count = _check_positive_int(v)
        if count < 10:
            raise ValueError("bars_count must be at least 10")
        return count

    @field_validator("monte_carlo_runs", mode="before")
    @classmethod
    def validate_monte_carlo_runs(cls, v: Any) -> int:
        runs = _check_positive_int(v)
        if runs < 1:
            raise ValueError("monte_carlo_runs must be at least 1")
        return runs


class BacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    manifest_sha256: str
    manifest_verified: bool
    metrics: dict[str, Any]
    monte_carlo: dict[str, Any]
    trade_count: int
    conservation_residual: Decimal
    paper_only: Literal[True] = True


class DeskRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist: list[str] = ["RELIANCE", "TCS"]
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"] = "NSE"
    currency: Literal["INR", "USD"] = "INR"
    run_id: str | None = None

    @field_validator("watchlist")
    @classmethod
    def validate_watchlist(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("watchlist must not be empty")
        cleaned = [item.strip().upper() for item in v if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("watchlist must contain at least one valid ticker")
        return cleaned


class DeskRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    currency: str
    shortlist: list[str]
    dropped: dict[str, str]
    approved_orders: list[dict[str, Any]]
    rejected_proposals: list[dict[str, Any]]
    report_markdown: str
    reconciled: bool
    paper_only: Literal[True] = True


class DecisionRecordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    timestamp: datetime
    ticker: str
    inputs_hash: str
    shortlist_rank: int | None = None
    analyst_envelopes: dict[str, Any] = {}
    strategist_proposal: dict[str, Any] | None = None
    risk_decision: dict[str, Any] | None = None
    paper_order: dict[str, Any] | None = None
