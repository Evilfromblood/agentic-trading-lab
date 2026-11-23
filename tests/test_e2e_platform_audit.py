"""End-to-End Platform Audit and Release Candidate Verification (Milestones 1-7)."""
from __future__ import annotations

import time
import tokenize
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_import_boundaries import (
    test_market_data_has_no_broker_or_risk_engine_imports as _check_market_data_imports,
)
from test_import_boundaries import (
    test_risk_engine_has_no_live_broker_imports as _check_risk_engine_imports,
)

from agentic_trading.agents.data_analyst import DataAnalyst
from agentic_trading.agents.llm_client import DeterministicStubLLMClient
from agentic_trading.agents.market_analyst import MarketAnalyst
from agentic_trading.agents.memory import DecisionLog, HumanLessonsStore
from agentic_trading.agents.news_analyst import NewsAnalyst
from agentic_trading.agents.opportunity_scout import OpportunityScout
from agentic_trading.agents.orchestrator import TradingDeskOrchestrator, WatchlistTarget
from agentic_trading.agents.strategist import Strategist, TradingMandate
from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.feed_bridge import ReadOnlyMarketFeedBridge
from agentic_trading.market_data.instruments import Currency, Instrument, Money
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange
from agentic_trading.paper_trading.broker import PaperBroker
from agentic_trading.risk_engine.proposal_gate import PortfolioRiskPolicy
from agentic_trading.simulation.costs import BasisPointsSlippageModel, IndiaEquityFeeModel
from agentic_trading.simulation.portfolio import PortfolioEngine
from agentic_trading.strategy.contracts import BarContext


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


def test_manual_order_risk_gate_and_price_deviation(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        res_no_stop = client.post(
            "/api/orders",
            json={
                "run_id": "test-risk-gate-1",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "100.00",
            },
        )
        assert res_no_stop.status_code == 422
        assert "MISSING_STOP_LOSS" in res_no_stop.json()["detail"]

        res_bad_price = client.post(
            "/api/orders",
            json={
                "run_id": "test-risk-gate-2",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "200.00",
                "stop_loss": "95.00",
            },
        )
        assert res_bad_price.status_code == 400
        assert "quote_price deviates from market feed" in res_bad_price.json()["detail"]

        res_ok = client.post(
            "/api/orders",
            json={
                "run_id": "test-risk-gate-3",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "100.00",
                "stop_loss": "95.00",
            },
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "FILLED"

        res_server_price = client.post(
            "/api/orders",
            json={
                "run_id": "test-risk-gate-4",
                "exchange": "NSE",
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 5,
                "stop_loss": "95.00",
            },
        )
        assert res_server_price.status_code == 200
        assert res_server_price.json()["status"] == "FILLED"


def test_lock_free_kill_switch_responsiveness(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
    )
    t0 = time.perf_counter()
    state.set_kill_switch(True, "EMERGENCY_HALT")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5
    assert state.kill_switch.is_active() is True
    assert "STOP exists" in (state.kill_switch.reason() or "")
    assert state.stop_file.read_text(encoding="utf-8") == "EMERGENCY_HALT"

    app = create_app(state=state)
    with TestClient(app) as client:
        resp = client.post(
            "/api/orders",
            json={
                "run_id": "kill-test",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 5,
                "stop_loss": "95.00",
            },
        )
        assert resp.status_code == 409
        assert "STOP exists" in resp.json()["detail"]

    t1 = time.perf_counter()
    state.set_kill_switch(False)
    elapsed_clear = time.perf_counter() - t1
    assert elapsed_clear < 0.5
    assert state.kill_switch.is_active() is False


def test_multi_ticker_sequential_snapshot_updates_prevent_exposure_breach(tmp_path: Path) -> None:
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    portfolio = PortfolioEngine(
        Currency.INR,
        fee_model=IndiaEquityFeeModel(),
        slippage_model=BasisPointsSlippageModel(),
    )
    portfolio.deposit(Money(Decimal("1000"), Currency.INR), now, "INITIAL")
    policy = PortfolioRiskPolicy(
        max_risk_per_trade_pct=Decimal("0.05"),
        max_position_pct=Decimal("0.50"),
        max_total_exposure_pct=Decimal("0.60"),
    )
    broker = PaperBroker(portfolio)
    orchestrator = TradingDeskOrchestrator(
        paper_broker=broker,
        risk_policy=policy,
        mandate=TradingMandate(horizon_days=5, min_reward_to_risk=Decimal("1.5")),
        market_analyst=MarketAnalyst(DeterministicStubLLMClient()),
        data_analyst=DataAnalyst(DeterministicStubLLMClient()),
        news_analyst=NewsAnalyst(DeterministicStubLLMClient()),
        opportunity_scout=OpportunityScout(),
        strategist=Strategist(DeterministicStubLLMClient()),
        decision_log=DecisionLog(db_path=tmp_path / "decisions.db"),
        lessons_store=HumanLessonsStore(),
    )

    t1_inst = Instrument(symbol="TICKER1", exchange=Exchange.NSE, currency=Currency.INR, tick_size=Decimal("0.05"), lot_size=1)
    t2_inst = Instrument(symbol="TICKER2", exchange=Exchange.NSE, currency=Currency.INR, tick_size=Decimal("0.05"), lot_size=1)
    start_bar = now - timedelta(days=1)
    c1 = Candle("TICKER1", Exchange.NSE, CandleInterval.D1, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1000, start_bar, "src", now)
    c2 = Candle("TICKER2", Exchange.NSE, CandleInterval.D1, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1000, start_bar, "src", now)
    ctx1 = BarContext(t1_inst, now, (c1,))
    ctx2 = BarContext(t2_inst, now, (c2,))
    w1 = WatchlistTarget(t1_inst, c1, ctx1)
    w2 = WatchlistTarget(t2_inst, c2, ctx2)

    result = orchestrator.run_cycle("seq-cycle", now, [w1, w2])
    total_exposure = sum(
        (o.filled_quantity * 100 for o in result.orders if o.status.value == "FILLED"),
        0,
    )
    assert total_exposure <= 600


def test_mark_to_market_holdings_and_conservation_residual(tmp_path: Path) -> None:
    state = TradingLabState(
        stop_file=tmp_path / "STOP",
        db_path=tmp_path / "decisions.db",
        initial_inr_deposit=Decimal("1000000"),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        order_res = client.post(
            "/api/orders",
            json={
                "run_id": "mtm-run",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "quote_price": "100.00",
                "stop_loss": "95.00",
            },
        )
        assert order_res.status_code == 200

        state._mark_prices[(Exchange.NSE, "RELIANCE")] = Money(Decimal("150.00"), Currency.INR)

        summary_res = client.get("/api/portfolios/INR")
        assert summary_res.status_code == 200
        data = summary_res.json()
        assert Decimal(str(data["unrealized_pnl"])) > Decimal("0")
        assert Decimal(str(data["holdings_value"])) == Decimal("1500.00")
        assert Decimal(str(data["conservation_residual"])) == Decimal("0")
        assert data["is_reconciled"] is True


def test_feed_bridge_per_instance_hmac_isolation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TRADING_LAB_REPLAY_HMAC_KEY", raising=False)
    b1 = ReadOnlyMarketFeedBridge(cache_dir=tmp_path / "b1")
    b2 = ReadOnlyMarketFeedBridge(cache_dir=tmp_path / "b2")
    assert b1.store.hmac_key != b2.store.hmac_key
    assert len(b1.store.hmac_key) == 32
    assert len(b2.store.hmac_key) == 32

    explicit_key = b"constant_test_key_01234567890123"
    b3 = ReadOnlyMarketFeedBridge(cache_dir=tmp_path / "b3", hmac_key=explicit_key)
    assert b3.store.hmac_key == explicit_key
