"""Comprehensive tests for Milestone 6 FastAPI backend, routes, and local dashboard."""
from __future__ import annotations

import re
import tokenize
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from test_import_boundaries import (
    test_market_data_has_no_broker_or_risk_engine_imports,
    test_risk_engine_has_no_live_broker_imports,
)

from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState


def test_dashboard_renders_and_health_endpoints_pass(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "PAPER TRADING ONLY" in html
        external_scripts = re.findall(r'<script[^>]+src=["\']https?://', html)
        assert len(external_scripts) == 0
        external_css = re.findall(r'<link[^>]+href=["\']https?://', html)
        assert len(external_css) == 0

        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "ok"
        assert health_data["paper_only"] is True
        assert health_data["kill_switch_active"] is False

        status_resp = client.get("/api/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "ok"
        assert status_data["paper_only"] is True


def test_inr_and_usd_portfolio_isolation(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
        initial_usd_deposit=Decimal("25000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        inr_resp = client.get("/api/portfolios/INR")
        assert inr_resp.status_code == 200
        inr_data = inr_resp.json()
        assert inr_data["currency"] == "INR"
        assert Decimal(str(inr_data["cash"])) == Decimal("1000000")
        assert Decimal(str(inr_data["conservation_residual"])) == Decimal("0")
        assert inr_data["is_reconciled"] is True

        usd_resp = client.get("/api/portfolios/USD")
        assert usd_resp.status_code == 200
        usd_data = usd_resp.json()
        assert usd_data["currency"] == "USD"
        assert Decimal(str(usd_data["cash"])) == Decimal("25000")
        assert Decimal(str(usd_data["conservation_residual"])) == Decimal("0")
        assert usd_data["is_reconciled"] is True

        bad_resp = client.get("/api/portfolios/EUR")
        assert bad_resp.status_code == 400

        invalid_num_resp = client.post(
            "/api/orders",
            json={
                "run_id": "test-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "NaN",
            },
        )
        assert invalid_num_resp.status_code == 422

        neg_price_resp = client.post(
            "/api/orders",
            json={
                "run_id": "test-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "-10.00",
            },
        )
        assert neg_price_resp.status_code == 422

        order_resp = client.post(
            "/api/orders",
            json={
                "run_id": "test-inr-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "2000.00",
                "client_order_id": "cid-inr-isolated",
            },
        )
        assert order_resp.status_code == 200

        usd_after = client.get("/api/portfolios/USD").json()
        assert Decimal(str(usd_after["cash"])) == Decimal("25000")
        assert len(usd_after["positions"]) == 0


def test_idempotent_order_submission_limit_pending_and_cancel(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        order_payload = {
            "run_id": "idempotent-run",
            "exchange": "NSE",
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 5,
            "quote_price": "3500.00",
            "client_order_id": "cid-idempotent-1",
        }
        res1 = client.post("/api/orders", json=order_payload)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "FILLED"
        assert data1["filled_quantity"] == 5

        res2 = client.post("/api/orders", json=order_payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["client_order_id"] == data1["client_order_id"]
        assert data2["filled_quantity"] == data1["filled_quantity"]

        limit_payload = {
            "run_id": "pending-run",
            "exchange": "NSE",
            "symbol": "INFY",
            "side": "BUY",
            "quantity": 10,
            "quote_price": "1500.00",
            "limit_price": "1400.00",
            "client_order_id": "cid-pending-1",
        }
        res3 = client.post("/api/orders", json=limit_payload)
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["status"] == "PENDING"
        assert data3["filled_quantity"] == 0
        assert data3["reject_reason"] == "LIMIT_PRICE_UNMET"

        cancel_res = client.post("/api/orders/INR/cid-pending-1/cancel")
        assert cancel_res.status_code == 200
        cancel_data = cancel_res.json()
        assert cancel_data["status"] == "CANCELLED"
        assert cancel_data["reject_reason"] == "ORDER_CANCELLED"

        cancel_again = client.post("/api/orders/INR/cid-pending-1/cancel")
        assert cancel_again.status_code == 400

        cancel_missing = client.post("/api/orders/INR/cid-does-not-exist/cancel")
        assert cancel_missing.status_code == 404


def test_kill_switch_activation_blocks_orders_and_desk(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        stop_res = client.post(
            "/api/kill-switch",
            json={"active": True, "reason": "TEST_EMERGENCY"},
        )
        assert stop_res.status_code == 200
        stop_data = stop_res.json()
        assert stop_data["active"] is True

        order_res = client.post(
            "/api/orders",
            json={
                "run_id": "blocked-run",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 5,
                "quote_price": "3500.00",
            },
        )
        assert order_res.status_code == 409

        desk_res = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["TCS"],
                "exchange": "NSE",
                "currency": "INR",
            },
        )
        assert desk_res.status_code == 409

        clear_res = client.post(
            "/api/kill-switch",
            json={"active": False, "reason": "TEST_RESUME"},
        )
        assert clear_res.status_code == 200
        assert clear_res.json()["active"] is False

        order_ok = client.post(
            "/api/orders",
            json={
                "run_id": "resumed-run",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 5,
                "quote_price": "3500.00",
            },
        )
        assert order_ok.status_code == 200


def test_backtest_execution_and_verified_manifest(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        bt_res = client.post(
            "/api/backtest",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "initial_capital": "1000000",
                "currency": "INR",
                "bars_count": 50,
                "random_seed": 42,
                "monte_carlo_runs": 100,
            },
        )
        assert bt_res.status_code == 200
        bt_data = bt_res.json()
        assert bt_data["paper_only"] is True
        assert bt_data["manifest_verified"] is True
        assert len(bt_data["manifest_sha256"]) == 64
        assert Decimal(str(bt_data["conservation_residual"])) == Decimal("0")
        assert "win_rate_pct" in bt_data["metrics"]
        assert "return_pct_p50" in bt_data["monte_carlo"]


def test_desk_run_and_decision_log_retrieval(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        desk_res = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE", "TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "audit-desk-run-101",
            },
        )
        assert desk_res.status_code == 200
        desk_data = desk_res.json()
        assert desk_data["paper_only"] is True
        assert desk_data["reconciled"] is True
        assert "DAILY DESK SUMMARY" in desk_data["report_markdown"]
        assert len(desk_data["shortlist"]) > 0

        dec_res = client.get("/api/decisions?run_id=audit-desk-run-101")
        assert dec_res.status_code == 200
        dec_data = dec_res.json()
        assert len(dec_data) > 0
        assert dec_data[0]["run_id"] == "audit-desk-run-101"


def test_no_inline_comments_in_m6_code() -> None:
    api_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading" / "api"
    test_file = Path(__file__).resolve()
    files_to_check = list(api_dir.glob("*.py")) + [test_file]
    assert len(files_to_check) >= 6

    for file_path in files_to_check:
        with open(file_path, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    raise AssertionError(
                        f"Inline comment found in {file_path.name} at line {tok.start[0]}: {tok.string}"
                    )


def test_import_boundaries_maintained() -> None:
    test_market_data_has_no_broker_or_risk_engine_imports()
    test_risk_engine_has_no_live_broker_imports()
