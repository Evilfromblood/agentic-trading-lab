"""Adversarial tests for Milestone 11: Multi-Symbol Basket Backtester, Walk-Forward Optimizer & Journal Export."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_trading.api.app import create_app
from agentic_trading.api.state import TradingLabState
from agentic_trading.market_data.instruments import Currency, Instrument, Money
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange
from agentic_trading.simulation.costs import BasisPointsSlippageModel, IndiaEquityFeeModel
from agentic_trading.simulation.ledger import LedgerEventType
from agentic_trading.time_machine.basket import (
    BasketBacktestResult,
    run_basket_backtest,
    run_walk_forward_optimization,
)
from agentic_trading.time_machine.engine import BacktestConfig


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    state = TradingLabState(
        stop_file=tmp_path / "stop.txt",
        db_path=tmp_path / "decisions.db",
    )
    test_app = create_app(state=state)
    return TestClient(test_app)


def _generate_synthetic_candles(
    exchange: Exchange,
    symbol: str,
    count: int = 100,
    base_price: float = 1000.0,
) -> list[Candle]:
    candles: list[Candle] = []
    curr = base_price
    t0 = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    for i in range(count):
        t = t0 + timedelta(days=i)
        c_time = t + timedelta(days=1)
        drift = (i % 5 - 2) * 5.0
        op = round(curr + drift, 2)
        hi = round(op + 15.0, 2)
        lo = round(max(10.0, op - 15.0), 2)
        cl = round(op + (i % 3 - 1) * 6.0, 2)
        vol = 10000 + (i * 100)
        curr = cl
        candles.append(
            Candle(
                symbol=symbol,
                exchange=exchange,
                interval=CandleInterval.D1,
                open=Decimal(str(op)),
                high=Decimal(str(hi)),
                low=Decimal(str(lo)),
                close=Decimal(str(cl)),
                volume=vol,
                timestamp=t,
                source="SYNTHETIC",
                retrieval_timestamp=c_time,
            )
        )
    return candles


def test_basket_backtest_direct_engine(tmp_path: Path) -> None:
    exchange = Exchange.NSE
    currency = Currency.INR
    symbols = ["RELIANCE", "TCS", "INFY"]

    instruments = [
        Instrument(
            exchange=exchange,
            symbol=sym,
            currency=currency,
            tick_size=Decimal("0.05"),
            lot_size=1,
        )
        for sym in symbols
    ]

    candles_by_symbol = {
        sym: _generate_synthetic_candles(exchange, sym, count=80, base_price=1000.0 + (idx * 500.0))
        for idx, sym in enumerate(symbols)
    }

    state = TradingLabState(stop_file=tmp_path / "stop.txt", db_path=tmp_path / "decisions.db")
    config = BacktestConfig(
        initial_capital=Money(Decimal("1000000"), currency),
        risk_policy=state.inr_risk_policy,
        fee_model=IndiaEquityFeeModel(),
        slippage_model=BasisPointsSlippageModel(),
        position_size_pct=Decimal("0.10"),
        default_stop_loss_pct=Decimal("0.03"),
        default_take_profit_pct=Decimal("0.06"),
        random_seed=42,
    )

    result = run_basket_backtest(
        instruments=instruments,
        candles_by_symbol=candles_by_symbol,
        strategy_name="ema_pullback",
        config=config,
        run_walk_forward=True,
    )

    assert isinstance(result, BasketBacktestResult)
    assert result.conservation_residual == Decimal("0")
    assert result.manifest_verified is True
    assert result.manifest_id.startswith("BASKET-")
    assert len(result.equity_curve) > 0

    assert len(result.per_symbol_attribution) == 3
    for sym in symbols:
        attr = result.per_symbol_attribution[sym]
        assert attr.symbol == sym
        assert attr.exchange == "NSE"
        assert isinstance(attr.trades, int)
        assert isinstance(attr.win_rate_pct, Decimal)

    if result.walk_forward is not None:
        assert result.walk_forward.split_ratio == "70/30"
        assert "total_return_pct" in result.walk_forward.in_sample_metrics
        assert "total_return_pct" in result.walk_forward.out_of_sample_metrics
        assert result.walk_forward.in_sample_range["start"] < result.walk_forward.out_of_sample_range["end"]


def test_walk_forward_optimizer_standalone(tmp_path: Path) -> None:
    exchange = Exchange.NSE
    currency = Currency.INR
    inst = Instrument(exchange=exchange, symbol="TCS", currency=currency, tick_size=Decimal("0.05"), lot_size=1)
    candles = _generate_synthetic_candles(exchange, "TCS", count=60, base_price=3500.0)

    state = TradingLabState(stop_file=tmp_path / "stop.txt", db_path=tmp_path / "decisions.db")
    config = BacktestConfig(
        initial_capital=Money(Decimal("1000000"), currency),
        risk_policy=state.inr_risk_policy,
        fee_model=IndiaEquityFeeModel(),
        slippage_model=BasisPointsSlippageModel(),
    )

    wf_res = run_walk_forward_optimization(
        instrument=inst,
        candles=candles,
        strategy_name="ema_pullback",
        config=config,
    )

    assert wf_res.strategy_name == "ema_pullback"
    assert "fast_period" in wf_res.best_params
    assert "slow_period" in wf_res.best_params
    assert wf_res.best_params["fast_period"] < wf_res.best_params["slow_period"]
    assert "sharpe_ratio" in wf_res.in_sample_metrics
    assert "sharpe_ratio" in wf_res.out_of_sample_metrics


def test_post_basket_backtest_endpoint(client: TestClient) -> None:
    payload = {
        "symbols": ["RELIANCE", "TCS", "INFY"],
        "exchange": "NSE",
        "currency": "INR",
        "initial_capital": "1000000",
        "bars_count": 80,
        "strategy_name": "ema_pullback",
        "feed_source": "synthetic",
        "run_walk_forward": True,
        "random_seed": 42,
    }

    res = client.post("/api/backtest/basket", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["paper_only"] is True
    assert data["manifest_verified"] is True
    assert Decimal(str(data["conservation_residual"])) == Decimal("0")
    assert "portfolio_metrics" in data
    assert "per_symbol_attribution" in data
    assert len(data["per_symbol_attribution"]) == 3
    assert len(data["equity_curve"]) > 0

    if data["walk_forward_summary"]:
        wf = data["walk_forward_summary"]
        assert wf["split_ratio"] == "70/30"
        assert "in_sample_metrics" in wf
        assert "out_of_sample_metrics" in wf


def test_basket_backtest_rejections(client: TestClient) -> None:
    res_mismatch = client.post(
        "/api/backtest/basket",
        json={"symbols": ["RELIANCE"], "exchange": "NSE", "currency": "USD"},
    )
    assert res_mismatch.status_code == 400

    res_empty_sym = client.post(
        "/api/backtest/basket",
        json={"symbols": [], "exchange": "NSE", "currency": "INR"},
    )
    assert res_empty_sym.status_code == 422

    res_extra = client.post(
        "/api/backtest/basket",
        json={"symbols": ["RELIANCE"], "unsupported_field": "test"},
    )
    assert res_extra.status_code == 422


def test_journal_export_json_and_csv(client: TestClient) -> None:
    res_desk = client.post(
        "/api/desk/run",
        json={"watchlist": ["RELIANCE"], "exchange": "NSE", "currency": "INR", "feed_source": "synthetic", "auto_buy": True},
    )
    assert res_desk.status_code == 200

    res_json = client.get("/api/journal/export?format=json")
    assert res_json.status_code == 200
    data_json = res_json.json()
    assert data_json["paper_only"] is True
    assert "ledger_entries" in data_json
    assert "trade_orders" in data_json
    assert data_json["total_ledger_entries"] >= 1

    res_csv = client.get("/api/journal/export?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "attachment;" in res_csv.headers["content-disposition"]
    csv_text = res_csv.text
    assert "SECTION,LEDGER_ENTRIES" in csv_text
    assert "SECTION,PAPER_ORDERS" in csv_text


def test_csv_formula_injection_defense(tmp_path: Path) -> None:
    state = TradingLabState(stop_file=tmp_path / "stop.txt", db_path=tmp_path / "decisions.db")

    state.inr_broker.portfolio.ledger.append(
        timestamp=datetime.now(timezone.utc),
        event_type=LedgerEventType.DEPOSIT,
        currency=Currency.INR,
        cash_delta=Money(Decimal("100"), Currency.INR),
        reference_id="=cmd|' /C calc'!A0",
    )

    csv_data = state.export_journal(format="csv", currency="INR")
    reader = csv.reader(io.StringIO(csv_data))
    found_ref = False
    for row in reader:
        for cell in row:
            if "calc" in cell:
                found_ref = True
                assert cell.startswith("'="), f"Formula injection not neutralized: {cell}"
    assert found_ref, "Injected reference was not found in CSV"


def test_dashboard_contains_basket_and_journal_controls(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    assert "runBasketBacktestBtn" in html
    assert "exportJournalCsvBtn" in html
    assert "exportJournalJsonBtn" in html
    assert "walkForwardGrid" in html
    assert "basketAttributionCard" in html
    assert "basketAttributionContainer" in html

    for forbidden in ["http://", "https://"]:
        assert forbidden not in html


def test_no_inline_comments_in_m11_code() -> None:
    root = Path(__file__).resolve().parent.parent
    files_to_check = [
        Path(__file__).resolve(),
        root / "src" / "agentic_trading" / "time_machine" / "basket.py",
        root / "src" / "agentic_trading" / "api" / "schemas.py",
        root / "src" / "agentic_trading" / "api" / "state.py",
        root / "src" / "agentic_trading" / "api" / "routes.py",
        root / "src" / "agentic_trading" / "api" / "dashboard.py",
    ]

    import tokenize
    for p in files_to_check:
        with open(p, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                assert tok.type != tokenize.COMMENT, f"Comment found in {p.name} line {tok.start[0]}: {tok.string}"
