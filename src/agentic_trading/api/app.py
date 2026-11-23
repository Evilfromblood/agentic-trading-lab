"""FastAPI application factory, lifespan management, and root dashboard routing."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agentic_trading.api.dashboard import get_dashboard_html
from agentic_trading.api.routes import router
from agentic_trading.api.state import TradingLabState


def create_app(state: TradingLabState | None = None) -> FastAPI:
    lab_state = state or TradingLabState()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.lab_state = lab_state
        try:
            yield
        finally:
            if hasattr(app.state, "lab_state") and app.state.lab_state is not None:
                app.state.lab_state.close()

    app = FastAPI(
        title="Agentic Trading Lab API",
        description="Local-first paper trading API and research desk monitor",
        version="0.6.0",
        lifespan=lifespan,
    )
    app.state.lab_state = lab_state

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
