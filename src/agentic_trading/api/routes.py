"""FastAPI endpoints for paper portfolio management, Kill Switch, orders, backtesting, and research desk."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from agentic_trading.api.schemas import (
    AddLessonRequest,
    BacktestRequest,
    BacktestResponse,
    BasketBacktestRequest,
    BasketBacktestResponse,
    ClosePositionRequest,
    ContextResponse,
    CycleDetailResponse,
    CycleSummaryItem,
    DecisionRecordItem,
    DeskRunRequest,
    DeskRunResponse,
    FeedCandlesResponse,
    HealthResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    LessonsListResponse,
    OrderResponse,
    PortfolioSummaryResponse,
    PositionsListResponse,
    ResetSandboxRequest,
    ResetSandboxResponse,
    SubmitOrderRequest,
)
from agentic_trading.api.state import ProposalRiskRejectionError, TradingLabState
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
    except ProposalRiskRejectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.post("/backtest/basket", response_model=BasketBacktestResponse)
def run_basket_backtest(
    payload: BasketBacktestRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> BasketBacktestResponse:
    try:
        return state.run_basket_backtest(payload)
    except (CurrencyMismatchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/journal/export")
def export_journal(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    format: Literal["json", "csv"] = Query("json"),
    currency: Literal["ALL", "INR", "USD"] = Query("ALL"),
) -> Response:
    try:
        data = state.export_journal(format=format, currency=currency)
        if format == "csv":
            return Response(
                content=data,
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="trade_journal.csv"'},
            )
        return JSONResponse(content=data)
    except ValueError as exc:
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


@router.get("/feed/{exchange}/{symbol}", response_model=FeedCandlesResponse)
def get_feed_candles(
    exchange: str,
    symbol: str,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    source: Literal["synthetic", "cache", "delayed_feed"] = Query(default="synthetic"),
    bars: int = Query(default=30, ge=1, le=250),
) -> FeedCandlesResponse:
    ex_clean = exchange.strip().upper()
    if ex_clean not in {"NSE", "BSE", "NYSE", "NASDAQ"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported exchange '{exchange}'",
        )
    sym_clean = symbol.strip().upper()
    if not sym_clean or len(sym_clean) > 32 or not re.match(r"^[A-Za-z0-9._-]{1,32}$", sym_clean) or ".." in sym_clean:
        raise HTTPException(
            status_code=400,
            detail="symbol must match ^[A-Za-z0-9._-]{1,32}$ and cannot contain '..'",
        )
    try:
        return state.get_feed_candles(
            exchange_str=ex_clean,
            symbol_str=sym_clean,
            source=source,
            bars=bars,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/context/{exchange}/{symbol}", response_model=ContextResponse)
def get_context(
    exchange: str,
    symbol: str,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    source: Literal["synthetic", "cache", "live"] = Query(default="synthetic"),
) -> ContextResponse:
    ex_clean = exchange.strip().upper()
    if ex_clean not in {"NSE", "BSE", "NYSE", "NASDAQ"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported exchange '{exchange}'",
        )
    sym_clean = symbol.strip().upper()
    if (
        not sym_clean
        or len(sym_clean) > 32
        or not re.match(r"^[A-Za-z0-9._-]{1,32}$", sym_clean)
        or ".." in sym_clean
    ):
        raise HTTPException(
            status_code=400,
            detail="symbol must match ^[A-Za-z0-9._-]{1,32}$ and cannot contain '..'",
        )
    try:
        return state.get_context(
            exchange_str=ex_clean,
            symbol_str=sym_clean,
            source=source,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cycles", response_model=list[CycleSummaryItem])
def list_cycles(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[CycleSummaryItem]:
    return state.list_cycles(limit=limit)


@router.get("/cycles/{run_id}", response_model=CycleDetailResponse)
def get_cycle(
    run_id: str,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> CycleDetailResponse:
    clean_id = run_id.strip()
    if (
        not clean_id
        or len(clean_id) > 64
        or not re.match(r"^[A-Za-z0-9._-]{1,64}$", clean_id)
        or ".." in clean_id
    ):
        raise HTTPException(status_code=400, detail="Invalid run_id format")
    detail = state.get_cycle_detail(clean_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Cycle '{clean_id}' not found")
    return detail


@router.get("/positions", response_model=PositionsListResponse)
def get_positions(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
    currency: Literal["INR", "USD"] | None = Query(default=None),
) -> PositionsListResponse:
    try:
        return state.get_positions(currency=currency)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.post("/positions/close", response_model=OrderResponse)
def close_position(
    payload: ClosePositionRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> OrderResponse:
    if state.kill_switch.is_active():
        reason = state.kill_switch.reason() or "Emergency kill switch is active"
        raise HTTPException(status_code=409, detail=f"Position close rejected: {reason}")
    try:
        return state.close_position(payload)
    except ProposalRiskRejectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CurrencyMismatchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KillSwitchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/lessons", response_model=LessonsListResponse)
def get_lessons(
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> LessonsListResponse:
    try:
        return LessonsListResponse(lessons=state.get_lessons())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.post("/lessons", response_model=LessonsListResponse)
def add_lesson(
    payload: AddLessonRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> LessonsListResponse:
    try:
        state.add_lesson(payload.lesson)
        return LessonsListResponse(lessons=state.get_lessons())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.post("/sandbox/reset", response_model=ResetSandboxResponse)
def reset_sandbox(
    payload: ResetSandboxRequest,
    state: Annotated[TradingLabState, Depends(get_lab_state)],
) -> ResetSandboxResponse:
    if state.kill_switch.is_active():
        reason = state.kill_switch.reason() or "Emergency kill switch is active"
        raise HTTPException(status_code=409, detail=f"Sandbox reset rejected: {reason}")
    try:
        res = state.reset_sandbox()
        return ResetSandboxResponse(
            status=res["status"],
            message=res["message"],
            paper_only=res["paper_only"],
        )
    except KillSwitchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
