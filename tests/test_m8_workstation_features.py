"""Comprehensive tests for Milestone 8 workstation features (ADR-038 & ADR-039)."""
from __future__ import annotations

import re
import tokenize
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.instruments import AssetClass, Currency, Exchange, Instrument
from agentic_trading.market_data.models import IST, Candle, CandleInterval
from agentic_trading.strategy.contracts import BarContext
from agentic_trading.strategy.library import (
    STRATEGY_REGISTRY,
    ATRBreakoutStrategy,
    EMAPullbackStrategy,
    RSIMeanReversionStrategy,
)


def _make_dummy_candles(count: int = 40, base_price: float = 100.0) -> tuple[Candle, ...]:
    bars: list[Candle] = []
    curr = base_price
    start_date = date(2025, 1, 6)
    for i in range(count):
        curr += 0.5 if i % 2 == 0 else -0.2
        high = curr + 1.0
        low = curr - 1.0
        close = curr + 0.1
        d = start_date + timedelta(days=i)
        ts = datetime(d.year, d.month, d.day, 9, 30, tzinfo=IST)
        bars.append(
            Candle(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                interval=CandleInterval.D1,
                open=Decimal(str(round(curr, 2))),
                high=Decimal(str(round(high, 2))),
                low=Decimal(str(round(low, 2))),
                close=Decimal(str(round(close, 2))),
                volume=10000,
                timestamp=ts,
                source="TEST",
                retrieval_timestamp=ts + timedelta(days=1),
            )
        )
    return tuple(bars)


def test_strategy_library_direct_evaluation_and_registry() -> None:
    assert "ema_pullback" in STRATEGY_REGISTRY
    assert "rsi_mean_reversion" in STRATEGY_REGISTRY
    assert "atr_breakout" in STRATEGY_REGISTRY
    assert "sma_cross" in STRATEGY_REGISTRY

    instrument = Instrument(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        asset_class=AssetClass.EQUITY,
        lot_size=1,
        tick_size=Decimal("0.05"),
        listed_date=date(2020, 1, 1),
    )

    bars = _make_dummy_candles(count=45, base_price=100.0)
    ctx = BarContext(instrument=instrument, decision_time=bars[-1].close_time, bars=bars)

    ema_strat = EMAPullbackStrategy()
    sig1 = ema_strat.evaluate(ctx)
    assert sig1 is None or sig1.symbol == "RELIANCE"

    rsi_strat = RSIMeanReversionStrategy()
    sig2 = rsi_strat.evaluate(ctx)
    assert sig2 is None or sig2.symbol == "RELIANCE"

    atr_strat = ATRBreakoutStrategy()
    sig3 = atr_strat.evaluate(ctx)
    assert sig3 is None or sig3.symbol == "RELIANCE"


def test_backtest_with_different_strategies_and_equity_curve(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        for strat in ("ema_pullback", "rsi_mean_reversion", "atr_breakout", "sma_cross"):
            resp = client.post(
                "/api/backtest",
                json={
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "currency": "INR",
                    "initial_capital": "1000000",
                    "bars_count": 80,
                    "random_seed": 42,
                    "monte_carlo_runs": 100,
                    "feed_source": "synthetic",
                    "strategy_name": strat,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["strategy_name"] == strat
            assert data["manifest_verified"] is True
            assert isinstance(data["equity_curve"], list)
            assert len(data["equity_curve"]) > 0
            first_pt = data["equity_curve"][0]
            assert "timestamp" in first_pt
            assert "total_equity" in first_pt or "equity" in first_pt
            assert "drawdown_pct" in first_pt

        bad_resp = client.post(
            "/api/backtest",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "currency": "INR",
                "strategy_name": "non_existent_strat",
            },
        )
        assert bad_resp.status_code == 422


def test_positions_list_and_close_position(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        init_pos = client.get("/api/positions").json()
        assert init_pos["positions"] == []

        feed_p = state.feed_bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=1).candles[-1].close
        order_resp = client.post(
            "/api/orders",
            json={
                "run_id": "test-pos-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": str(feed_p),
                "stop_loss": str((feed_p * Decimal("0.95")).quantize(Decimal("0.05"))),
                "client_order_id": "cid-buy-pos",
            },
        )
        assert order_resp.status_code == 200

        pos_resp = client.get("/api/positions").json()
        assert len(pos_resp["positions"]) == 1
        pos = pos_resp["positions"][0]
        assert pos["symbol"] == "RELIANCE"
        assert pos["exchange"] == "NSE"
        assert pos["currency"] == "INR"
        assert pos["quantity"] == 10
        assert Decimal(str(pos["average_cost"])) > Decimal("0")

        usd_pos = client.get("/api/positions?currency=USD").json()
        assert len(usd_pos["positions"]) == 0

        inr_pos = client.get("/api/positions?currency=INR").json()
        assert len(inr_pos["positions"]) == 1

        client.post("/api/kill-switch", json={"active": True, "reason": "TEST_KILL"})
        close_blocked = client.post(
            "/api/positions/close",
            json={
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "currency": "INR",
            },
        )
        assert close_blocked.status_code == 409
        client.post("/api/kill-switch", json={"active": False})

        close_resp = client.post(
            "/api/positions/close",
            json={
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "currency": "INR",
            },
        )
        assert close_resp.status_code == 200
        close_data = close_resp.json()
        assert close_data["status"] == "FILLED"
        assert close_data["side"] == "SELL"
        assert close_data["filled_quantity"] == 10

        after_pos = client.get("/api/positions").json()
        assert len(after_pos["positions"]) == 0

        portfolio_inr = client.get("/api/portfolios/INR").json()
        assert Decimal(str(portfolio_inr["conservation_residual"])) == Decimal("0")

        bad_close = client.post(
            "/api/positions/close",
            json={
                "exchange": "NSE",
                "symbol": "TCS",
                "currency": "INR",
            },
        )
        assert bad_close.status_code == 400


def test_lessons_store_sqlite_persistence_and_orchestrator(tmp_path: Path) -> None:
    db_file = tmp_path / "decisions.db"
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=db_file,
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        init_lessons = client.get("/api/lessons").json()
        assert isinstance(init_lessons["lessons"], list)

        add_resp = client.post(
            "/api/lessons",
            json={"lesson": "Never trade without clear stop loss"},
        )
        assert add_resp.status_code == 200
        lessons_data = add_resp.json()
        assert "Never trade without clear stop loss" in lessons_data["lessons"]

        state2 = TradingLabState(
            stop_file=tmp_path / "STOP2",
            db_path=db_file,
        )
        app2 = create_app(state=state2)
        with TestClient(app2) as client2:
            reloaded = client2.get("/api/lessons").json()
            assert "Never trade without clear stop loss" in reloaded["lessons"]

            desk_resp = client2.post(
                "/api/desk/run",
                json={
                    "watchlist": ["RELIANCE"],
                    "exchange": "NSE",
                    "currency": "INR",
                    "feed_source": "synthetic",
                    "llm_backend": "stub",
                    "auto_buy": False,
                },
            )
            assert desk_resp.status_code == 200

        bad_lesson = client.post("/api/lessons", json={"lesson": "   "})
        assert bad_lesson.status_code == 422


def test_sandbox_reset(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
        initial_usd_deposit=Decimal("25000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        feed_p = state.feed_bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=1).candles[-1].close
        order_resp = client.post(
            "/api/orders",
            json={
                "run_id": "test-reset-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 5,
                "quote_price": str(feed_p),
                "stop_loss": str((feed_p * Decimal("0.95")).quantize(Decimal("0.05"))),
                "client_order_id": "cid-reset-buy",
            },
        )
        assert order_resp.status_code == 200
        inr_before = client.get("/api/portfolios/INR").json()
        assert Decimal(str(inr_before["cash"])) < Decimal("1000000")

        client.post("/api/kill-switch", json={"active": True, "reason": "STOP"})
        blocked_reset = client.post("/api/sandbox/reset", json={"confirm": True})
        assert blocked_reset.status_code == 409
        client.post("/api/kill-switch", json={"active": False})

        reset_resp = client.post("/api/sandbox/reset", json={"confirm": True})
        assert reset_resp.status_code == 200
        reset_data = reset_resp.json()
        assert reset_data["status"] == "ok"
        assert reset_data["paper_only"] is True

        inr_after = client.get("/api/portfolios/INR").json()
        assert Decimal(str(inr_after["cash"])) == Decimal("1000000")
        assert len(inr_after["positions"]) == 0

        usd_after = client.get("/api/portfolios/USD").json()
        assert Decimal(str(usd_after["cash"])) == Decimal("25000")
        assert len(usd_after["positions"]) == 0


def test_dashboard_ui_m8_elements_and_hygiene(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text

        expected_elements = [
            "resetSandboxBtn",
            "backtestStrategySelect",
            "tabPositionsBtn",
            "tabBacktestBtn",
            "tabLessonsBtn",
            "positionsContainer",
            "equityCurveCanvas",
            "refreshPositionsBtn",
            "addLessonBtn",
            "lessonInput",
        ]
        for el in expected_elements:
            assert el in html

        external_scripts = re.findall(r'<script[^>]+src=["\']https?://', html)
        assert len(external_scripts) == 0
        external_css = re.findall(r'<link[^>]+href=["\']https?://', html)
        assert len(external_css) == 0


def test_no_inline_comments_in_workstation_test_file() -> None:
    test_file = Path(__file__)
    with open(test_file, "rb") as f:
        tokens = list(tokenize.tokenize(f.readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert len(comments) == 0
