"""FastAPI endpoints for paper portfolio management, Kill Switch, orders, backtesting, and research desk."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agentic_trading.api.schemas import (
    BacktestRequest,
    BacktestResponse,
    DecisionRecordItem,
    DeskRunRequest,
    DeskRunResponse,
    HealthResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    OrderResponse,
    PortfolioSummaryResponse,
    SubmitOrderRequest,
)
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.instruments import CurrencyMismatchError
from agentic_trading.paper_trading.kill_switch import KillSwitchError

router = APIRouter(prefix="/api", tags=["trading-lab"])


def get_lab_state(request: Request) -> TradingLabState:
    lab_state: TradingLabState = request.app.state.lab_state
    return lab_state


@router.get("/health", response_model=HealthResponse)
@router.get("/status", response_model=HealthResponse)
def get_health(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        paper_only=True,
        kill_switch_active=state.kill_switch.is_active(),
        kill_switch_reason=state.kill_switch.reason(),
    )


@router.post("/kill-switch", response_model=KillSwitchResponse)
def toggle_kill_switch(
    payload: KillSwitchRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> KillSwitchResponse:
    is_active = state.set_kill_switch(payload.active, payload.reason)
    return KillSwitchResponse(
        active=is_active,
        reason=state.kill_switch.reason(),
        paper_only=True,
    )


@router.get("/portfolios/{currency}", response_model=PortfolioSummaryResponse)
def get_portfolio(
    currency: str,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> PortfolioSummaryResponse:
    curr = currency.strip().upper()
    if curr not in {"INR", "USD"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported currency '{currency}'; supported currencies are INR and USD",
        )
    try:
        return state.get_portfolio_summary(curr)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/orders", response_model=OrderResponse)
def submit_order(
    payload: SubmitOrderRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> OrderResponse:
    if state.kill_switch.is_active():
        reason = state.kill_switch.reason() or "Emergency kill switch is active"
        raise HTTPException(status_code=409, detail=f"Order rejected: {reason}")
    try:
        return state.submit_order(payload)
    except (CurrencyMismatchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KillSwitchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/orders/{currency}/{client_order_id}/cancel",
    response_model=OrderResponse,
)
def cancel_order(
    currency: str,
    client_order_id: str,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> OrderResponse:
    curr = currency.strip().upper()
    if curr not in {"INR", "USD"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported currency '{currency}'",
        )
    clean_cid = client_order_id.strip()
    if not clean_cid or len(clean_cid) > 64:
        raise HTTPException(
            status_code=400,
            detail="client_order_id must be non-empty and at most 64 characters",
        )
    if state.kill_switch.is_active():
        reason = state.kill_switch.reason() or "Emergency kill switch is active"
        raise HTTPException(status_code=409, detail=f"Cancel rejected: {reason}")
    try:
        return state.cancel_order(curr, clean_cid)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Order '{clean_cid}' not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(
    payload: BacktestRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> BacktestResponse:
    try:
        return state.run_backtest(payload)
    except (CurrencyMismatchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/desk/run", response_model=DeskRunResponse)
def run_desk(
    payload: DeskRunRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> DeskRunResponse:
    if state.kill_switch.is_active():
        reason = state.kill_switch.reason() or "Emergency kill switch is active"
        raise HTTPException(status_code=409, detail=f"Desk run halted: {reason}")
    try:
        return state.run_desk(payload)
    except (CurrencyMismatchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KillSwitchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/decisions", response_model=list[DecisionRecordItem])
def get_decisions(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    run_id: str | None = Query(default=None, max_length=64),
) -> list[DecisionRecordItem]:
    return state.get_decisions(run_id=run_id)
