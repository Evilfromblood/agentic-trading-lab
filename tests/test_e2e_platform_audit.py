"""End-to-End Platform Audit and Release Candidate Verification (Milestones 1-7)."""
from __future__ import annotations

import tokenize
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from test_import_boundaries import (
    test_market_data_has_no_broker_or_risk_engine_imports as _check_market_data_imports,
)
from test_import_boundaries import (
    test_risk_engine_has_no_live_broker_imports as _check_risk_engine_imports,
)

from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState


def test_end_to_end_platform_lifecycle_audit(tmp_path: Path) -> None:
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
        assert inr_data["paper_only"] is True
        assert Decimal(str(inr_data["cash"])) == Decimal("1000000")
        assert Decimal(str(inr_data["conservation_residual"])) == Decimal("0")
        assert inr_data["is_reconciled"] is True

        usd_resp = client.get("/api/portfolios/USD")
        assert usd_resp.status_code == 200
        usd_data = usd_resp.json()
        assert usd_data["currency"] == "USD"
        assert usd_data["paper_only"] is True
        assert Decimal(str(usd_data["cash"])) == Decimal("25000")
        assert Decimal(str(usd_data["conservation_residual"])) == Decimal("0")
        assert usd_data["is_reconciled"] is True

        feed_inr = client.get("/api/feed/NSE/RELIANCE?source=synthetic")
        assert feed_inr.status_code == 200
        data_inr = feed_inr.json()
        assert data_inr["paper_only"] is True
        assert data_inr["symbol"] == "RELIANCE"
        assert data_inr["candle_count"] > 0
        assert Decimal(str(data_inr["latest_close"])) > Decimal("0")

        feed_usd = client.get("/api/feed/NASDAQ/AAPL?source=synthetic")
        assert feed_usd.status_code == 200
        data_usd = feed_usd.json()
        assert data_usd["paper_only"] is True
        assert data_usd["symbol"] == "AAPL"
        assert data_usd["candle_count"] > 0
        assert Decimal(str(data_usd["latest_close"])) > Decimal("0")

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

        run_id = "rc1-audit-desk-001"
        desk_res = client.post(
            "/api/desk/run",
            json={
                "watchlist": ["RELIANCE", "TCS"],
                "exchange": "NSE",
                "currency": "INR",
                "run_id": run_id,
                "llm_backend": "stub",
            },
        )
        assert desk_res.status_code == 200
        desk_data = desk_res.json()
        assert desk_data["paper_only"] is True
        assert desk_data["reconciled"] is True
        assert "DAILY DESK SUMMARY" in desk_data["report_markdown"]
        assert len(desk_data["shortlist"]) > 0

        dec_res = client.get(f"/api/decisions?run_id={run_id}")
        assert dec_res.status_code == 200
        dec_data = dec_res.json()
        assert len(dec_data) > 0
        assert dec_data[0]["run_id"] == run_id

        ks_on = client.post(
            "/api/kill-switch",
            json={"active": True, "reason": "RC1_AUDIT_ENGAGE"},
        )
        assert ks_on.status_code == 200
        assert ks_on.json()["active"] is True

        order_res = client.post(
            "/api/orders",
            json={
                "run_id": "blocked-rc1-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "2500.00",
            },
        )
        assert order_res.status_code == 409

        ks_off = client.post(
            "/api/kill-switch",
            json={"active": False, "reason": "RC1_AUDIT_CLEAR"},
        )
        assert ks_off.status_code == 200
        assert ks_off.json()["active"] is False

        inr_final = client.get("/api/portfolios/INR")
        assert inr_final.status_code == 200
        assert inr_final.json()["is_reconciled"] is True
        assert Decimal(str(inr_final.json()["conservation_residual"])) == Decimal("0")

        usd_final = client.get("/api/portfolios/USD")
        assert usd_final.status_code == 200
        assert usd_final.json()["is_reconciled"] is True
        assert Decimal(str(usd_final.json()["conservation_residual"])) == Decimal("0")


def test_repository_wide_zero_inline_comments() -> None:
    src_dir = Path(__file__).resolve().parent.parent / "src" / "agentic_trading"
    assert src_dir.is_dir(), f"Source directory not found: {src_dir}"

    legacy_m2a_files = {
        "adapters.py",
        "ingestion.py",
        "models.py",
        "provider.py",
        "quality.py",
    }
    py_files = [p for p in src_dir.rglob("*.py") if p.name not in legacy_m2a_files]
    assert len(py_files) >= 25, "Expected at least 25 Python source files across audited modules"

    for file_path in py_files:
        with open(file_path, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    raise AssertionError(
                        f"Inline comment found in {file_path.name} at line {tok.start[0]}: {tok.string}"
                    )


def test_import_boundaries_maintained() -> None:
    _check_market_data_imports()
    _check_risk_engine_imports()
