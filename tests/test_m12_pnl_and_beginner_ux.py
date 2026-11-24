"""Adversarial and functional test suite for Milestone 12 (ADR-043): Per-symbol pricing, PnL scorecard, closed trades, scenarios, and beginner UX."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_trading.api.app import create_app
from agentic_trading.api.schemas import ClosePositionRequest, SubmitOrderRequest
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.feed_bridge import ReadOnlyMarketFeedBridge
from agentic_trading.market_data.instruments import Exchange


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    state = TradingLabState(
        stop_file=tmp_path / "stop.txt",
        db_path=tmp_path / "decisions.db",
    )
    test_app = create_app(state=state)
    return TestClient(test_app)


def test_feed_bridge_unique_symbol_pricing() -> None:
    bridge = ReadOnlyMarketFeedBridge()

    rel_candles = bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=20).candles
    tcs_candles = bridge.fetch_candles(Exchange.NSE, "TCS", bars_count=20).candles
    aapl_candles = bridge.fetch_candles(Exchange.NASDAQ, "AAPL", bars_count=20).candles

    assert len(rel_candles) == 20
    assert len(tcs_candles) == 20
    assert len(aapl_candles) == 20

    rel_last = rel_candles[-1].close
    tcs_last = tcs_candles[-1].close
    aapl_last = aapl_candles[-1].close

    assert Decimal("2500") <= rel_last <= Decimal("3500")
    assert Decimal("3400") <= tcs_last <= Decimal("4500")
    assert Decimal("180") <= aapl_last <= Decimal("300")

    assert rel_last != tcs_last
    assert tcs_last != aapl_last


def test_feed_bridge_scenario_biases() -> None:
    bridge = ReadOnlyMarketFeedBridge()

    norm_candles = bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=30, sim_step=3, scenario_bias="normal").candles
    bull_candles = bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=30, sim_step=3, scenario_bias="bull_rally").candles
    crash_candles = bridge.fetch_candles(Exchange.NSE, "RELIANCE", bars_count=30, sim_step=3, scenario_bias="sudden_crash").candles

    norm_last = norm_candles[-1].close
    bull_last = bull_candles[-1].close
    crash_last = crash_candles[-1].close

    assert bull_last > norm_last
    assert crash_last < norm_last


def test_pnl_summary_empty_portfolio(client: TestClient) -> None:
    res = client.get("/api/pnl")
    assert res.status_code == 200
    data = res.json()

    assert "inr" in data
    assert "usd" in data
    assert "closed_trades" in data
    assert data["closed_trades"] == []

    inr = data["inr"]
    assert inr["currency"] == "INR"
    assert Decimal(str(inr["win_rate_pct"])) == Decimal("0")
    assert Decimal(str(inr["net_pnl"])) == Decimal("0")
    assert inr["closed_trades_count"] == 0


def test_pnl_summary_buy_and_close_trade_lifecycle(tmp_path: Path) -> None:
    state = TradingLabState(stop_file=tmp_path / "stop.txt", db_path=tmp_path / "decisions.db")

    order_req = SubmitOrderRequest(
        run_id="TEST-RUN-1",
        exchange="NSE",
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        stop_loss=Decimal("2800"),
        take_profit=Decimal("3300"),
    )
    fill = state.submit_order(order_req)
    assert fill is not None

    positions = state.inr_broker.portfolio._positions
    assert (Exchange.NSE, "RELIANCE") in positions

    pnl_mid = state.get_pnl_summary()
    assert len(pnl_mid.closed_trades) == 0

    close_req = ClosePositionRequest(exchange="NSE", symbol="RELIANCE", currency="INR")
    close_res = state.close_position(close_req)
    assert close_res.symbol == "RELIANCE"
    assert close_res.status == "FILLED"

    pnl_after = state.get_pnl_summary()
    assert len(pnl_after.closed_trades) == 1
    tr = pnl_after.closed_trades[0]
    assert tr.symbol == "RELIANCE"
    assert tr.currency == "INR"
    assert tr.exit_reason == "MANUAL_SELL"
    assert tr.bought_at > Decimal("0")
    assert tr.sold_at > Decimal("0")

    inr_summary = pnl_after.inr
    assert inr_summary.closed_trades_count == 1
    assert inr_summary.winning_trades + inr_summary.losing_trades == 1


def test_scenario_endpoint_and_stop_loss_trigger(tmp_path: Path) -> None:
    state = TradingLabState(stop_file=tmp_path / "stop.txt", db_path=tmp_path / "decisions.db")
    app = create_app(state=state)
    local_client = TestClient(app)

    order_req = {
        "run_id": "TEST-RUN-2",
        "exchange": "NSE",
        "symbol": "RELIANCE",
        "side": "BUY",
        "quantity": 5,
        "stop_loss": "3100.00",
        "take_profit": "3500.00",
    }
    buy_res = local_client.post("/api/orders", json=order_req)
    assert buy_res.status_code == 200

    scen_res = local_client.post("/api/sandbox/scenario", json={"scenario": "sudden_crash"})
    assert scen_res.status_code == 200
    scen_data = scen_res.json()
    assert scen_data["scenario"] == "sudden_crash"
    assert scen_data["sim_step"] >= 1
    assert len(scen_data["sweep_events"]) >= 1

    pnl_res = local_client.get("/api/pnl")
    assert pnl_res.status_code == 200
    pnl_data = pnl_res.json()
    assert len(pnl_data["closed_trades"]) >= 1
    assert pnl_data["closed_trades"][0]["exit_reason"] == "STOP_LOSS_TRIGGERED"

    invalid_res = local_client.post("/api/sandbox/scenario", json={"scenario": "invalid_mode"})
    assert invalid_res.status_code == 422


def test_backtest_expectancy_and_bars_evaluated_numeric(client: TestClient) -> None:
    bt_req = {
        "exchange": "NSE",
        "symbol": "RELIANCE",
        "strategy_name": "ema_pullback",
        "feed_source": "synthetic",
        "bars_count": 60,
    }
    res = client.post("/api/backtest", json=bt_req)
    assert res.status_code == 200
    data = res.json()

    assert "expectancy" in data
    assert "bars_evaluated" in data
    assert isinstance(data["bars_evaluated"], int)
    assert data["bars_evaluated"] > 0
    assert data["expectancy"] is not None
    assert Decimal(str(data["expectancy"])) is not None


def test_dashboard_m12_dom_elements_and_zero_external_links(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    expected_ids = [
        "beginnerGuideBanner",
        "toggleGuideBtn",
        "pnlGrid",
        "inrPnlCard",
        "usdPnlCard",
        "scenarioBullBtn",
        "scenarioCrashBtn",
        "scenarioChopBtn",
        "liveModeToggleBtn",
        "closedTradesContainer",
        "presetNiftySafeBtn",
        "presetItMoversBtn",
        "presetUsLeadersBtn",
    ]
    for element_id in expected_ids:
        assert element_id in html, f"Missing element ID: {element_id}"

    for forbidden in ["http://", "https://"]:
        assert forbidden not in html, f"Found external reference: {forbidden}"


def test_no_inline_comments_in_m12_code() -> None:
    import tokenize

    root = Path(__file__).resolve().parent.parent
    files_to_check = [
        Path(__file__).resolve(),
        root / "src" / "agentic_trading" / "market_data" / "feed_bridge.py",
        root / "src" / "agentic_trading" / "api" / "schemas.py",
        root / "src" / "agentic_trading" / "api" / "state.py",
        root / "src" / "agentic_trading" / "api" / "routes.py",
        root / "src" / "agentic_trading" / "api" / "dashboard.py",
    ]

    for p in files_to_check:
        with open(p, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                assert tok.type != tokenize.COMMENT, f"Comment found in {p.name} line {tok.start[0]}: {tok.string}"
