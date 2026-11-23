"""FastAPI application factory, lifespan management, and root dashboard routing."""
from __future__ import annotations

import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from agentic_trading.api.dashboard import get_dashboard_html
from agentic_trading.api.routes import router
from agentic_trading.api.state import TradingLabState

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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

    @app.middleware("http")
    async def security_middleware(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        raw_host = request.headers.get("host", "").strip()
        if raw_host.startswith("["):
            bracket_idx = raw_host.find("]")
            if bracket_idx != -1:
                host_val = raw_host[1:bracket_idx].lower()
            else:
                host_val = raw_host.lower()
        else:
            host_val = raw_host.split(":")[0].strip().lower()

        if host_val not in ALLOWED_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden host header"},
            )

        if request.method in MUTATING_METHODS:
            origin = request.headers.get("origin")
            if origin:
                origin_host = (urllib.parse.urlparse(origin).hostname or "").lower()
                if origin_host not in ALLOWED_HOSTS:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin state mutation forbidden"},
                    )
            referer = request.headers.get("referer")
            if referer:
                referer_host = (urllib.parse.urlparse(referer).hostname or "").lower()
                if referer_host not in ALLOWED_HOSTS:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin state mutation forbidden"},
                    )

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
