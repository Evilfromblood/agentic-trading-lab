"""Comprehensive tests for Milestone 6 FastAPI backend, routes, and local dashboard."""
from __future__ import annotations

import concurrent.futures
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
                "quote_price": "100.00",
                "stop_loss": "95.00",
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
            "quote_price": "100.00",
            "stop_loss": "95.00",
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
            "quote_price": "100.00",
            "limit_price": "90.00",
            "stop_loss": "85.00",
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
                "quote_price": "100.00",
                "stop_loss": "95.00",
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


def test_dns_rebinding_and_cross_origin_state_mutation_blocked(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        forbidden_host_resp = client.get("/api/health", headers={"host": "evil.example.com"})
        assert forbidden_host_resp.status_code == 403
        assert "Forbidden host header" in forbidden_host_resp.json()["detail"]

        forbidden_host_port_resp = client.get("/", headers={"host": "attacker.com:8080"})
        assert forbidden_host_port_resp.status_code == 403

        cors_origin_resp = client.post(
            "/api/orders",
            headers={"origin": "https://malicious.org"},
            json={
                "run_id": "run-cors",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "quote_price": "3000.00",
            },
        )
        assert cors_origin_resp.status_code == 403
        assert "Cross-origin state mutation forbidden" in cors_origin_resp.json()["detail"]

        cors_referer_resp = client.post(
            "/api/kill-switch",
            headers={"referer": "https://evil-phish.net/page"},
            json={"active": True, "reason": "UNAUTHORIZED_CORS"},
        )
        assert cors_referer_resp.status_code == 403
        assert "Cross-origin state mutation forbidden" in cors_referer_resp.json()["detail"]

        valid_host_resp = client.get("/api/health", headers={"host": "localhost:8000"})
        assert valid_host_resp.status_code == 200

        valid_ip_resp = client.get("/api/health", headers={"host": "127.0.0.1:8000"})
        assert valid_ip_resp.status_code == 200

        valid_ipv6_resp = client.get("/api/health", headers={"host": "[::1]:8000"})
        assert valid_ipv6_resp.status_code == 200

        valid_origin_resp = client.post(
            "/api/orders",
            headers={"origin": "http://localhost:8000"},
            json={
                "run_id": "run-valid-origin",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "quote_price": "100.00",
                "stop_loss": "95.00",
            },
        )
        assert valid_origin_resp.status_code == 200


def test_security_headers_present(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        headers = resp.headers
        expected_csp = (
            "default-src 'none'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )
        assert headers.get("content-security-policy") == expected_csp
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-frame-options") == "DENY"
        assert headers.get("referrer-policy") == "no-referrer"

        health_resp = client.get("/api/health")
        assert health_resp.headers.get("content-security-policy") == expected_csp
        assert health_resp.headers.get("x-content-type-options") == "nosniff"
        assert health_resp.headers.get("x-frame-options") == "DENY"
        assert health_resp.headers.get("referrer-policy") == "no-referrer"


def test_schema_extra_forbid_and_bounds_rejection(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        extra_order_res = client.post(
            "/api/orders",
            json={
                "run_id": "valid-run",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "quote_price": "3000.00",
                "extra_malicious_key": "injected_payload",
            },
        )
        assert extra_order_res.status_code == 422

        extra_kill_res = client.post(
            "/api/kill-switch",
            json={"active": True, "reason": "STOP", "forbid_me": 1},
        )
        assert extra_kill_res.status_code == 422

        extra_bt_res = client.post(
            "/api/backtest",
            json={"symbol": "TCS", "unexpected": "value"},
        )
        assert extra_bt_res.status_code == 422

        extra_desk_res = client.post(
            "/api/desk/run",
            json={"watchlist": ["TCS"], "exploit": True},
        )
        assert extra_desk_res.status_code == 422

        oversized_run_id_res = client.post(
            "/api/orders",
            json={
                "run_id": "X" * 65,
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "quote_price": "3000.00",
            },
        )
        assert oversized_run_id_res.status_code == 422

        oversized_symbol_res = client.post(
            "/api/orders",
            json={
                "run_id": "run-1",
                "exchange": "NSE",
                "symbol": "S" * 65,
                "side": "BUY",
                "quantity": 1,
                "quote_price": "3000.00",
            },
        )
        assert oversized_symbol_res.status_code == 422

        oversized_cid_res = client.post(
            "/api/orders",
            json={
                "run_id": "run-1",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "quote_price": "3000.00",
                "client_order_id": "C" * 65,
            },
        )
        assert oversized_cid_res.status_code == 422

        oversized_reason_res = client.post(
            "/api/kill-switch",
            json={"active": True, "reason": "R" * 65},
        )
        assert oversized_reason_res.status_code == 422

        oversized_bars_res = client.post(
            "/api/backtest",
            json={"symbol": "RELIANCE", "bars_count": 501},
        )
        assert oversized_bars_res.status_code == 422

        undersized_bars_res = client.post(
            "/api/backtest",
            json={"symbol": "RELIANCE", "bars_count": 5},
        )
        assert undersized_bars_res.status_code == 422

        oversized_watchlist_res = client.post(
            "/api/desk/run",
            json={"watchlist": [f"SYM{i}" for i in range(21)]},
        )
        assert oversized_watchlist_res.status_code == 422


def test_concurrent_state_and_portfolio_conservation(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
        initial_usd_deposit=Decimal("50000"),
    )
    app = create_app(state=state)

    def submit_inr(i: int) -> int:
        with TestClient(app) as client:
            resp = client.post(
                "/api/orders",
                json={
                    "run_id": f"conc-inr-{i}",
                    "exchange": "NSE",
                    "symbol": "RELIANCE",
                    "side": "BUY",
                    "quantity": 2,
                    "quote_price": "100.00",
                    "stop_loss": "95.00",
                    "client_order_id": f"conc-inr-cid-{i}",
                },
            )
            return resp.status_code

    def submit_usd(i: int) -> int:
        with TestClient(app) as client:
            resp = client.post(
                "/api/orders",
                json={
                    "run_id": f"conc-usd-{i}",
                    "exchange": "NASDAQ",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": 1,
                    "quote_price": "100.00",
                    "stop_loss": "95.00",
                    "client_order_id": f"conc-usd-cid-{i}",
                },
            )
            return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        inr_futures = [executor.submit(submit_inr, i) for i in range(8)]
        usd_futures = [executor.submit(submit_usd, i) for i in range(8)]
        inr_results = [f.result() for f in inr_futures]
        usd_results = [f.result() for f in usd_futures]

    assert all(code == 200 for code in inr_results)
    assert all(code == 200 for code in usd_results)

    with TestClient(app) as client:
        inr_summary = client.get("/api/portfolios/INR").json()
        assert inr_summary["is_reconciled"] is True
        assert Decimal(str(inr_summary["conservation_residual"])) == Decimal("0")

        usd_summary = client.get("/api/portfolios/USD").json()
        assert usd_summary["is_reconciled"] is True
        assert Decimal(str(usd_summary["conservation_residual"])) == Decimal("0")


def test_restart_continuity(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    db_path = tmp_path / "decisions.db"

    state1 = TradingLabState(stop_file=stop_file, db_path=db_path)
    app1 = create_app(state=state1)
    with TestClient(app1) as client1:
        desk_res = client1.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "persist-desk-001",
            },
        )
        assert desk_res.status_code == 200

        kill_res = client1.post(
            "/api/kill-switch",
            json={"active": True, "reason": "PERSIST_RESTART_STOP"},
        )
        assert kill_res.status_code == 200
        assert kill_res.json()["active"] is True

    state2 = TradingLabState(stop_file=stop_file, db_path=db_path)
    app2 = create_app(state=state2)
    with TestClient(app2) as client2:
        health_res = client2.get("/api/health")
        assert health_res.status_code == 200
        health_data = health_res.json()
        assert health_data["kill_switch_active"] is True
        assert health_data["kill_switch_reason"] is not None and "STOP exists" in health_data["kill_switch_reason"]

        dec_res = client2.get("/api/decisions?run_id=persist-desk-001")
        assert dec_res.status_code == 200
        dec_data = dec_res.json()
        assert len(dec_data) > 0
        assert dec_data[0]["run_id"] == "persist-desk-001"

        clear_res = client2.post(
            "/api/kill-switch",
            json={"active": False, "reason": "RESUMED_AFTER_RESTART"},
        )
        assert clear_res.status_code == 200
        assert clear_res.json()["active"] is False
        assert not stop_file.exists()


def test_cycles_endpoints_and_chat_trace(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        desk_res = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE", "TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "test-cycle-001",
                "llm_backend": "stub",
                "feed_source": "synthetic",
            },
        )
        assert desk_res.status_code == 200
        desk_data = desk_res.json()
        assert desk_data["run_id"] == "test-cycle-001"
        assert desk_data["paper_only"] is True
        assert "timestamp" in desk_data
        assert desk_data["watchlist"] == ["RELIANCE", "TCS"]
        assert desk_data["ollama_model"] == "gemma4:12b"
        assert isinstance(desk_data["chat_trace"], list)
        assert len(desk_data["chat_trace"]) >= 4

        stages_in_trace = {entry["stage"] for entry in desk_data["chat_trace"]}
        assert "Stage 1 · Market Analyst" in stages_in_trace
        assert "Stage 1 · Data Analyst" in stages_in_trace
        assert "Stage 1 · News Analyst" in stages_in_trace
        assert "Stage 2 · Opportunity Scout" in stages_in_trace
        assert "Stage 3 · Strategist" in stages_in_trace
        assert "Stage 4 · Risk & Execution" in stages_in_trace

        for entry in desk_data["chat_trace"]:
            assert isinstance(entry["step"], int)
            assert entry["step"] >= 1
            assert len(entry["stage"]) > 0
            assert len(entry["agent"]) > 0
            assert len(entry["model"]) > 0
            assert isinstance(entry["input_context"], dict)
            assert isinstance(entry["output_message"], dict)
            assert entry["status"] in {"ok", "approved", "rejected", "no_trade", "missing"}

        cycles_res = client.get("/api/cycles")
        assert cycles_res.status_code == 200
        cycles_list = cycles_res.json()
        assert len(cycles_list) == 1
        summary = cycles_list[0]
        assert summary["run_id"] == "test-cycle-001"
        assert summary["currency"] == "INR"
        assert summary["watchlist"] == ["RELIANCE", "TCS"]
        assert summary["feed_source"] == "synthetic"
        assert summary["llm_backend"] == "stub"
        assert summary["paper_only"] is True
        assert isinstance(summary["approved_count"], int)
        assert isinstance(summary["rejected_count"], int)
        assert summary["reconciled"] is True
        assert summary["auto_buy"] is True

        detail_res = client.get("/api/cycles/test-cycle-001")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["run_id"] == "test-cycle-001"
        assert detail["currency"] == "INR"
        assert detail["watchlist"] == ["RELIANCE", "TCS"]
        assert detail["feed_source"] == "synthetic"
        assert detail["llm_backend"] == "stub"
        assert detail["paper_only"] is True
        assert detail["auto_buy"] is True
        assert len(detail["trade_plans"]) >= 2
        assert "RELIANCE" in detail["candle_series"]
        assert len(detail["chat_trace"]) == len(desk_data["chat_trace"])
        assert detail["reconciled"] is True
        assert "DAILY DESK SUMMARY" in detail["report_markdown"]

        bad_id_res = client.get("/api/cycles/invalid..path")
        assert bad_id_res.status_code == 400

        bad_format_res = client.get("/api/cycles/invalid%20space")
        assert bad_format_res.status_code == 400

        not_found_res = client.get("/api/cycles/nonexistent-run-id")
        assert not_found_res.status_code == 404


def test_dashboard_contains_cycle_inspector_and_chat_trace(tmp_path: Path) -> None:
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
        assert "Reviewing Paper Trading Cycle" in html
        assert 'id="cycleSelect"' in html
        assert 'id="tabOverviewBtn"' in html
        assert 'id="tabChatBtn"' in html
        assert 'id="tabOverviewPane"' in html
        assert 'id="tabChatPane"' in html
        assert 'id="overviewShortlist"' in html
        assert 'id="overviewDropped"' in html
        assert 'id="overviewOrdersContainer"' in html
        assert 'id="chatTraceContainer"' in html
        assert 'id="marketSelect"' in html
        assert 'id="watchlistInput"' in html

        external_scripts = re.findall(r'<script[^>]+src=["\']https?://', html)
        assert len(external_scripts) == 0
        external_css = re.findall(r'<link[^>]+href=["\']https?://', html)
        assert len(external_css) == 0


def test_auto_buy_toggle_and_planned_orders(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        res_off = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE", "TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "cycle-auto-off-001",
                "llm_backend": "stub",
                "auto_buy": False,
            },
        )
        assert res_off.status_code == 200
        data_off = res_off.json()
        assert data_off["auto_buy"] is False
        assert len(data_off["approved_orders"]) == 0
        assert len(data_off["trade_plans"]) >= 2
        planned_plans = [p for p in data_off["trade_plans"] if p["status"] == "planned"]
        assert len(planned_plans) >= 1
        p0 = planned_plans[0]
        assert p0["symbol"] == "RELIANCE"
        assert p0["buy_price"] is not None
        assert p0["sell_target"] is not None
        assert p0["stop_loss"] is not None
        assert p0["quantity"] > 0
        assert p0["reward_to_risk"] is not None
        assert Decimal(str(p0["reward_to_risk"])) >= Decimal("1.5")
        assert any("Stage 4 · Risk & Plan Preview" in e["stage"] for e in data_off["chat_trace"])

        p_check = client.get("/api/portfolios/INR").json()
        assert Decimal(str(p_check["cash"])) == Decimal("1000000")
        assert len(p_check["positions"]) == 0

        detail_res = client.get("/api/cycles/cycle-auto-off-001")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["auto_buy"] is False
        assert len(detail_data["trade_plans"]) == len(data_off["trade_plans"])
        assert "RELIANCE" in detail_data["candle_series"]
        assert len(detail_data["candle_series"]["RELIANCE"]) > 0

        manual_buy = client.post(
            "/api/orders",
            json={
                "run_id": "cycle-auto-off-001",
                "exchange": p0["exchange"],
                "symbol": p0["symbol"],
                "side": "BUY",
                "quantity": p0["quantity"],
                "quote_price": p0["current_price"],
                "stop_loss": p0["stop_loss"],
                "take_profit": p0["sell_target"],
            },
        )
        assert manual_buy.status_code == 200
        assert manual_buy.json()["status"] == "FILLED"
        p_after_manual = client.get("/api/portfolios/INR").json()
        assert Decimal(str(p_after_manual["cash"])) < Decimal("1000000")

        res_on = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": "cycle-auto-on-002",
                "llm_backend": "stub",
                "auto_buy": True,
            },
        )
        assert res_on.status_code == 200
        data_on = res_on.json()
        assert data_on["auto_buy"] is True
        assert len(data_on["approved_orders"]) >= 1
        assert any("Stage 4 · Risk & Execution" in e["stage"] for e in data_on["chat_trace"])
        exec_plans = [p for p in data_on["trade_plans"] if p["status"] == "executed"]
        assert len(exec_plans) >= 1
        assert exec_plans[0]["executed_order_id"] is not None


def test_feed_candles_and_candle_series_response(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        feed_res = client.get("/api/feed/NSE/RELIANCE?bars=15")
        assert feed_res.status_code == 200
        feed_data = feed_res.json()
        assert feed_data["symbol"] == "RELIANCE"
        assert feed_data["candle_count"] == 15
        assert len(feed_data["candles"]) == 15
        c0 = feed_data["candles"][0]
        assert "open" in c0
        assert "high" in c0
        assert "low" in c0
        assert "close" in c0
        assert "volume" in c0
        assert "timestamp" in c0


def test_dashboard_contains_auto_buy_plans_and_chart(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="autoBuyToggle"' in html
        assert 'id="autoBuyLabel"' in html
        assert 'id="tradePlansContainer"' in html
        assert 'id="candlestickCanvas"' in html
        assert 'id="chartTickerPills"' in html
        assert 'id="chartReadoutBar"' in html
        assert 'id="cycleAutoBuyPill"' in html


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
