"""Pydantic v2 schemas for local-first paper trading API and web dashboard."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    status: str = Field(default="ok", max_length=64)
    paper_only: Literal[True] = True
    kill_switch_active: bool
    kill_switch_reason: str | None = Field(default=None, max_length=512)


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str = Field(default="MANUAL_UI_STOP", max_length=64)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        clean = v.strip() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("reason must be a non-empty string")
        if len(clean) > 64:
            raise ValueError("reason must not exceed 64 characters")
        return clean


class KillSwitchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str | None = Field(default=None, max_length=512)
    paper_only: Literal[True] = True


class PositionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
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

    run_id: str = Field(..., max_length=64)
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"]
    symbol: str = Field(..., max_length=64)
    side: Literal["BUY", "SELL"]
    quantity: int = Field(..., gt=0)
    quote_price: Decimal | None = None
    limit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    client_order_id: str | None = Field(default=None, max_length=64)

    @field_validator("run_id", "symbol")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        clean = v.strip().upper() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("must be a non-empty string")
        if len(clean) > 64:
            raise ValueError("must not exceed 64 characters")
        return clean

    @field_validator("client_order_id")
    @classmethod
    def validate_client_order_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        clean = v.strip() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("client_order_id cannot be blank")
        if len(clean) > 64:
            raise ValueError("client_order_id must not exceed 64 characters")
        return clean

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v: Any) -> int:
        return _check_positive_int(v)

    @field_validator("quote_price", mode="before")
    @classmethod
    def validate_quote_price(cls, v: Any) -> Decimal | None:
        return _check_optional_finite_positive(v)

    @field_validator("limit_price", "stop_loss", "take_profit", mode="before")
    @classmethod
    def validate_optional_prices(cls, v: Any) -> Decimal | None:
        return _check_optional_finite_positive(v)



class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(..., max_length=64)
    run_id: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
    symbol: str = Field(..., max_length=64)
    side: str = Field(..., max_length=64)
    quantity: int
    filled_quantity: int
    status: str = Field(..., max_length=64)
    limit_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    average_fill_price: Decimal | None = None
    fees: Decimal
    slippage: Decimal
    reject_reason: str | None = Field(default=None, max_length=256)
    submitted_at: datetime
    filled_at: datetime | None = None
    paper_only: Literal[True] = True


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(default="RELIANCE", max_length=64)
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"] = "NSE"
    initial_capital: Decimal = Decimal("1000000")
    currency: Literal["INR", "USD"] = "INR"
    bars_count: int = Field(default=100, ge=10, le=500)
    random_seed: int = Field(default=42, ge=0)
    monte_carlo_runs: int = Field(default=500, ge=1, le=5000)
    feed_source: Literal["synthetic", "cache", "delayed_feed"] = "synthetic"
    strategy_name: str = Field(default="ema_pullback", max_length=64)

    @field_validator("strategy_name")
    @classmethod
    def validate_strategy_name(cls, v: str) -> str:
        clean = v.strip().lower() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("strategy_name must be non-empty")
        allowed = {"ema_pullback", "rsi_mean_reversion", "atr_breakout", "sma_cross"}
        if clean not in allowed:
            raise ValueError(f"Unknown strategy_name '{v}'; supported: {sorted(allowed)}")
        return clean

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        clean = v.strip().upper() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("symbol must be a non-empty string")
        if len(clean) > 64:
            raise ValueError("symbol must not exceed 64 characters")
        return clean

    @field_validator("initial_capital", mode="before")
    @classmethod
    def validate_capital(cls, v: Any) -> Decimal:
        return _check_finite_positive(v)

    @field_validator("bars_count", mode="before")
    @classmethod
    def validate_bars_count(cls, v: Any) -> int:
        count = _check_positive_int(v)
        if count < 10 or count > 500:
            raise ValueError("bars_count must be between 10 and 500")
        return count

    @field_validator("monte_carlo_runs", mode="before")
    @classmethod
    def validate_monte_carlo_runs(cls, v: Any) -> int:
        runs = _check_positive_int(v)
        if runs < 1 or runs > 5000:
            raise ValueError("monte_carlo_runs must be between 1 and 5000")
        return runs


class BacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_id: str = Field(..., max_length=64)
    manifest_sha256: str = Field(..., max_length=64)
    manifest_verified: bool
    metrics: dict[str, Any]
    monte_carlo: dict[str, Any]
    trade_count: int
    conservation_residual: Decimal
    feed_source: str = Field(default="synthetic", max_length=64)
    strategy_name: str = Field(default="ema_pullback", max_length=64)
    equity_curve: list[dict[str, str]] = []
    expectancy: Decimal = Decimal("0")
    bars_evaluated: int = 0
    total_return_pct: Decimal = Decimal("0")
    sharpe_ratio: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    win_rate: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    total_trades: int = 0
    mc_var_95_pct: Decimal = Decimal("0")
    paper_only: Literal[True] = True


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["normal", "bull_rally", "sudden_crash", "sideways_chop"]


class SweepTriggerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
    currency: str = Field(..., max_length=64)
    trigger_type: str = Field(..., max_length=64)
    trigger_price: Decimal
    mark_price: Decimal
    quantity: int
    net_pnl: Decimal
    client_order_id: str = Field(..., max_length=64)


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["normal", "bull_rally", "sudden_crash", "sideways_chop"]
    sim_step: int
    paper_only: Literal[True] = True
    message: str = Field(..., max_length=512)
    sweep_events: list[SweepTriggerEvent] = []


class ClosedTradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
    currency: Literal["INR", "USD"]
    quantity: int
    bought_at: Decimal
    sold_at: Decimal
    net_pnl: Decimal
    pnl_pct: Decimal
    exit_reason: str = Field(..., max_length=64)
    closed_at: str = Field(..., max_length=64)


class PnlBreakdownItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["INR", "USD"]
    starting_capital: Decimal
    current_equity: Decimal
    net_pnl: Decimal
    net_return_pct: Decimal
    realized_pnl: Decimal
    realized_gains: Decimal
    realized_losses: Decimal
    unrealized_pnl: Decimal
    unrealized_gains: Decimal
    unrealized_losses: Decimal
    total_fees: Decimal
    closed_trades_count: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: Decimal
    best_trade_pnl: Decimal
    worst_trade_pnl: Decimal


class PnlSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    inr: PnlBreakdownItem
    usd: PnlBreakdownItem
    closed_trades: list[ClosedTradeRecord] = []


class BasketBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default=["RELIANCE", "TCS", "INFY"], min_length=1, max_length=10)
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"] = "NSE"
    currency: Literal["INR", "USD"] = "INR"
    initial_capital: Decimal = Decimal("1000000")
    bars_count: int = Field(default=100, ge=20, le=500)
    strategy_name: str = Field(default="ema_pullback", max_length=64)
    feed_source: Literal["synthetic", "cache", "delayed_feed"] = "synthetic"
    run_walk_forward: bool = True
    random_seed: int = Field(default=42, ge=0)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("symbols list must not be empty")
        cleaned: list[str] = []
        for s in v:
            c = s.strip().upper() if isinstance(s, str) else ""
            if not c or len(c) > 32:
                raise ValueError("symbol must be a non-empty string of max length 32")
            if c not in cleaned:
                cleaned.append(c)
        return cleaned

    @field_validator("strategy_name")
    @classmethod
    def validate_strategy_name(cls, v: str) -> str:
        clean = v.strip().lower() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("strategy_name must be non-empty")
        allowed = {"ema_pullback", "rsi_mean_reversion", "atr_breakout", "sma_cross"}
        if clean not in allowed:
            raise ValueError(f"Unknown strategy_name '{v}'; supported: {sorted(allowed)}")
        return clean

    @field_validator("initial_capital", mode="before")
    @classmethod
    def validate_capital(cls, v: Any) -> Decimal:
        return _check_finite_positive(v)

    @field_validator("bars_count", mode="before")
    @classmethod
    def validate_bars(cls, v: Any) -> int:
        count = _check_positive_int(v)
        if count < 20 or count > 500:
            raise ValueError("bars_count must be between 20 and 500")
        return count


class PerSymbolAttributionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange: str
    trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: str
    realized_pnl: str
    total_return_pct: str


class WalkForwardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    best_params: dict[str, Any]
    in_sample_metrics: dict[str, Any]
    out_of_sample_metrics: dict[str, Any]
    in_sample_range: dict[str, str]
    out_of_sample_range: dict[str, str]
    split_ratio: str = "70/30"


class BasketBacktestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_id: str = Field(..., max_length=64)
    manifest_sha256: str = Field(..., max_length=64)
    manifest_verified: bool
    conservation_residual: Decimal
    strategy_name: str = Field(default="ema_pullback", max_length=64)
    feed_source: str = Field(default="synthetic", max_length=64)
    portfolio_metrics: dict[str, Any]
    per_symbol_attribution: dict[str, PerSymbolAttributionItem]
    walk_forward_summary: WalkForwardSummary | None = None
    equity_curve: list[dict[str, str]] = []
    trade_count: int
    paper_only: Literal[True] = True


class JournalExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    exported_at: str
    total_ledger_entries: int
    total_orders: int
    ledger_entries: list[dict[str, Any]]
    trade_orders: list[dict[str, Any]]


class DeskRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist: list[str] = Field(default=["RELIANCE", "TCS"], min_length=1, max_length=20)
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"] = "NSE"
    currency: Literal["INR", "USD"] = "INR"
    run_id: str | None = Field(default=None, max_length=64)
    llm_backend: Literal["stub", "ollama"] = "stub"
    ollama_model: str = Field(default="gemma4:12b", min_length=1, max_length=64)
    feed_source: Literal["synthetic", "cache", "delayed_feed"] = "synthetic"
    context_source: Literal["synthetic", "cache", "live"] = "synthetic"
    auto_buy: bool = True

    @field_validator("watchlist")
    @classmethod
    def validate_watchlist(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("watchlist must not be empty")
        if len(v) > 20:
            raise ValueError("watchlist must not exceed 20 symbols")
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str) or not item.strip():
                continue
            item_clean = item.strip().upper()
            if len(item_clean) > 64:
                raise ValueError("symbol must not exceed 64 characters")
            cleaned.append(item_clean)
        if not cleaned:
            raise ValueError("watchlist must contain at least one valid ticker")
        if len(cleaned) > 20:
            raise ValueError("watchlist must not exceed 20 symbols")
        return cleaned

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        clean = v.strip() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("run_id cannot be blank")
        if len(clean) > 64:
            raise ValueError("run_id must not exceed 64 characters")
        return clean

    @field_validator("ollama_model")
    @classmethod
    def validate_ollama_model(cls, v: str) -> str:
        clean = v.strip() if isinstance(v, str) else ""
        if not clean:
            raise ValueError("ollama_model must be a non-empty string")
        if len(clean) > 64:
            raise ValueError("ollama_model must not exceed 64 characters")
        return clean


class CandleBarItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(..., max_length=64)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(default=0, ge=0)


class TradePlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
    currency: str = Field(..., max_length=64)
    action: str = Field(..., max_length=32)
    status: str = Field(..., max_length=32)
    current_price: Decimal
    buy_price: Decimal | None = None
    sell_target: Decimal | None = None
    stop_loss: Decimal | None = None
    quantity: int = Field(default=0, ge=0)
    reward_to_risk: Decimal | None = None
    confidence: Decimal = Decimal("0")
    rationale: str = Field(default="", max_length=1024)
    risk_reasons: list[str] = []
    executed_order_id: str | None = Field(default=None, max_length=64)


class AgentChatEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    stage: str = Field(..., max_length=64)
    agent: str = Field(..., max_length=64)
    symbol: str | None = Field(default=None, max_length=64)
    model: str = Field(..., max_length=64)
    input_context: dict[str, Any] = {}
    output_message: dict[str, Any] = {}
    status: str = Field(..., max_length=32)


class DeskRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., max_length=64)
    currency: str = Field(..., max_length=64)
    shortlist: list[str]
    dropped: dict[str, str]
    approved_orders: list[dict[str, Any]]
    rejected_proposals: list[dict[str, Any]]
    report_markdown: str
    reconciled: bool
    llm_backend: str = Field(default="stub", max_length=64)
    feed_source: str = Field(default="synthetic", max_length=64)
    context_source: str = Field(default="synthetic", max_length=64)
    timestamp: datetime
    watchlist: list[str] = []
    ollama_model: str = Field(default="gemma4:12b", max_length=64)
    chat_trace: list[AgentChatEntry] = []
    auto_buy: bool = True
    trade_plans: list[TradePlanItem] = []
    candle_series: dict[str, list[CandleBarItem]] = {}
    paper_only: Literal[True] = True


class CycleSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., max_length=64)
    timestamp: datetime
    currency: str = Field(..., max_length=64)
    watchlist: list[str]
    feed_source: str = Field(..., max_length=64)
    context_source: str = Field(default="synthetic", max_length=64)
    llm_backend: str = Field(..., max_length=64)
    ollama_model: str = Field(..., max_length=64)
    approved_count: int
    rejected_count: int
    reconciled: bool
    auto_buy: bool = True
    paper_only: Literal[True] = True


class CycleDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., max_length=64)
    timestamp: datetime
    currency: str = Field(..., max_length=64)
    watchlist: list[str]
    feed_source: str = Field(..., max_length=64)
    context_source: str = Field(default="synthetic", max_length=64)
    llm_backend: str = Field(..., max_length=64)
    ollama_model: str = Field(..., max_length=64)
    shortlist: list[str]
    dropped: dict[str, str]
    approved_orders: list[dict[str, Any]]
    rejected_proposals: list[dict[str, Any]]
    chat_trace: list[AgentChatEntry]
    report_markdown: str
    reconciled: bool
    auto_buy: bool = True
    trade_plans: list[TradePlanItem] = []
    candle_series: dict[str, list[CandleBarItem]] = {}
    paper_only: Literal[True] = True


class DecisionRecordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., max_length=64)
    timestamp: datetime
    ticker: str = Field(..., max_length=64)
    inputs_hash: str = Field(..., max_length=128)
    shortlist_rank: int | None = None
    analyst_envelopes: dict[str, Any] = {}
    strategist_proposal: dict[str, Any] | None = None
    risk_decision: dict[str, Any] | None = None
    paper_order: dict[str, Any] | None = None


class FeedCandlesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    exchange: str = Field(..., max_length=64)
    symbol: str = Field(..., max_length=32)
    currency: str = Field(..., max_length=64)
    interval: str = Field(..., max_length=64)
    source: str = Field(..., max_length=64)
    candle_count: int
    latest_close: Decimal
    latest_timestamp: datetime
    warnings: list[str] = []
    candles: list[CandleBarItem] = []


class PositionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3)
    exchange: str = Field(min_length=1, max_length=16)
    symbol: str = Field(min_length=1, max_length=32)
    quantity: int
    average_cost: Decimal
    mark_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal


class PositionsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    positions: list[PositionItem] = []


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["INR", "USD"]
    exchange: Literal["NSE", "BSE", "NYSE", "NASDAQ"]
    symbol: str = Field(min_length=1, max_length=32)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        clean = v.strip().upper() if isinstance(v, str) else ""
        if not clean or len(clean) > 32 or ".." in clean or not re.match(r"^[A-Za-z0-9._-]{1,32}$", clean):
            raise ValueError("symbol must match ^[A-Za-z0-9._-]{1,32}$ and cannot contain '..'")
        return clean


class AddLessonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson: str = Field(min_length=1, max_length=240)

    @field_validator("lesson")
    @classmethod
    def validate_lesson(cls, v: str) -> str:
        clean = " ".join(v.strip().split()) if isinstance(v, str) else ""
        clean = "".join(ch for ch in clean if ord(ch) >= 32 or ch in "\n\t")
        if not clean:
            raise ValueError("lesson cannot be empty")
        if len(clean) > 240:
            raise ValueError("lesson must be at most 240 characters")
        return clean


class LessonsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    lessons: list[str] = []


class ResetSandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal[True] = True


class ResetSandboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    message: str = "Sandbox reset successfully"
    paper_only: Literal[True] = True


class FundamentalSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., max_length=64)
    as_of_filing: str = Field(..., max_length=64)
    revenue_growth_yoy: Decimal
    operating_margin: Decimal
    fcf_margin: Decimal
    debt_to_equity: Decimal
    interest_coverage: Decimal
    pe_vs_peer_median: Decimal
    dilution_yoy: Decimal
    peer_set: list[str] = []


class NewsArticleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., max_length=512)
    source: str = Field(..., max_length=128)
    source_tier: int = Field(default=1, ge=1, le=3)
    published_at: str = Field(..., max_length=64)
    summary: str = Field(default="", max_length=2048)


class ScheduledEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str = Field(..., max_length=256)
    event_date: str = Field(..., max_length=64)
    event_type: str = Field(..., max_length=64)


class ContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    symbol: str = Field(..., max_length=64)
    exchange: str = Field(..., max_length=64)
    currency: str = Field(..., max_length=64)
    source: str = Field(..., max_length=64)
    is_blackout: bool
    snapshot: FundamentalSnapshotItem
    articles: list[NewsArticleItem] = []
    scheduled_events: list[ScheduledEventItem] = []
    warnings: list[str] = []
