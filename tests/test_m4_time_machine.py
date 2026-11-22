"""Adversarial tests for Milestone 4: causal backtest engine, manifests, validation, Monte Carlo."""
from __future__ import annotations

import ast
import dataclasses
import io
import tokenize
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agentic_trading.market_data.corporate_actions import CorporateAction, CorporateActionType
from agentic_trading.market_data.instruments import (
    Currency,
    CurrencyMismatchError,
    Instrument,
    Money,
)
from agentic_trading.market_data.models import IST, US_EASTERN, Candle, CandleInterval, Exchange
from agentic_trading.risk_engine.proposal_gate import PortfolioRiskPolicy
from agentic_trading.simulation.costs import (
    BasisPointsSlippageModel,
    IndiaEquityFeeModel,
    USEquityFeeModel,
    ZeroFeeModel,
)
from agentic_trading.simulation.ledger import LedgerEventType
from agentic_trading.strategy.contracts import BarContext, Signal, SignalDirection, Strategy
from agentic_trading.time_machine import (
    BacktestConfig,
    BacktestEngine,
    CompletedTrade,
    CorporateActionConflictError,
    EquityPoint,
    build_experiment_manifest,
    compute_backtest_metrics,
    compute_benchmark_return_pct,
    compute_dataset_sha256,
    ledger_conservation_residual,
    run_seeded_monte_carlo,
    run_train_test_split,
    run_walk_forward,
    verify_manifest_integrity,
)

LONG = SignalDirection.LONG
EXIT = SignalDirection.EXIT
START = date(2025, 1, 6)
LENIENT = PortfolioRiskPolicy(
    max_drawdown_pct=Decimal("0.50"), max_daily_loss_pct=Decimal("0.50")
)
FLAT = (100, 101, 99, 100)


def _ts(exchange: Exchange, day: date) -> datetime:
    if exchange in (Exchange.NSE, Exchange.BSE):
        return datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    return datetime(day.year, day.month, day.day, 9, 30, tzinfo=US_EASTERN)


def make_bars(
    rows: Sequence[Sequence[object]],
    exchange: Exchange = Exchange.NSE,
    symbol: str = "TESTCO",
) -> tuple[Candle, ...]:
    bars = []
    for i, row in enumerate(rows):
        o, h, lo, c = (Decimal(str(x)) for x in row[:4])
        volume = int(row[4]) if len(row) > 4 else 1_000_000
        ts = _ts(exchange, START + timedelta(days=i))
        probe = Candle(symbol, exchange, CandleInterval.D1, o, h, lo, c, volume, ts, "TEST", ts)
        bars.append(
            Candle(
                symbol,
                exchange,
                CandleInterval.D1,
                o,
                h,
                lo,
                c,
                volume,
                ts,
                "TEST",
                probe.close_time + timedelta(hours=1),
            )
        )
    return tuple(bars)


class Scripted(Strategy):
    def __init__(self, actions: Mapping[int, SignalDirection], warmup: int = 1) -> None:
        self.strategy_id = "scripted"
        self.warmup_bars = warmup
        self._actions = dict(actions)
        self.log: list[tuple[int, Decimal]] = []

    def evaluate(self, context: BarContext) -> Signal | None:
        count = len(context.bars)
        self.log.append((count, context.bars[-1].close))
        assert max(b.close_time for b in context.bars) <= context.decision_time
        direction = self._actions.get(count)
        if direction is None:
            return None
        return Signal(
            exchange=context.instrument.exchange,
            symbol=context.instrument.symbol,
            timestamp=context.decision_time,
            direction=direction,
            confidence=Decimal("1"),
        )


def nse_instrument(**kwargs: object) -> Instrument:
    return Instrument("TESTCO", Exchange.NSE, Currency.INR, **kwargs)


def make_config(
    currency: Currency = Currency.INR,
    capital: str = "1000000",
    fee: object = None,
    slip: object = None,
    **kwargs: object,
) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=Money(Decimal(capital), currency),
        risk_policy=kwargs.pop("risk_policy", LENIENT),
        fee_model=fee or ZeroFeeModel(),
        slippage_model=slip or BasisPointsSlippageModel(Decimal("0")),
        **kwargs,
    )


def flat_rows(count: int) -> list[tuple[int, int, int, int]]:
    return [FLAT] * count


def entry_fill(result):
    return next(e for e in result.ledger.entries if e.event_type == LedgerEventType.BUY_FILL)


def test_signal_executes_at_next_open_not_signal_close() -> None:
    rows = flat_rows(3) + [(101, 102, 99, 100)] + flat_rows(4)
    bars = make_bars(rows)
    result = BacktestEngine().run(nse_instrument(), bars, Scripted({3: LONG}), make_config())
    fill = entry_fill(result)
    assert fill.timestamp == bars[3].timestamp
    assert fill.execution_price.amount == Decimal("101")
    assert fill.execution_price.amount != bars[2].close
    assert fill.quantity_delta == 990
    assert result.trades[0].exit_reason == "END_OF_DATA"


def test_changing_future_bars_never_changes_earlier_decisions() -> None:
    base = flat_rows(3) + [(101, 102, 99, 100)] + flat_rows(8)
    altered = base[:6] + [(50, 51, 49, 50)] * 6
    first, second = Scripted({3: LONG, 9: EXIT}), Scripted({3: LONG, 9: EXIT})
    res_a = BacktestEngine().run(nse_instrument(), make_bars(base), first, make_config())
    res_b = BacktestEngine().run(nse_instrument(), make_bars(altered), second, make_config())
    assert [x for x in first.log if x[0] <= 6] == [x for x in second.log if x[0] <= 6]
    assert res_a.equity_curve[:6] == res_b.equity_curve[:6]
    cutoff = make_bars(base)[5].timestamp
    early_a = [e for e in res_a.ledger.entries if e.timestamp <= cutoff]
    early_b = [e for e in res_b.ledger.entries if e.timestamp <= cutoff]
    assert early_a == early_b and early_a


def test_gap_through_stop_fills_at_gap_open() -> None:
    rows = flat_rows(3) + [FLAT, (95, 96, 94, 95)] + [(95, 96, 94, 95)] * 3
    result = BacktestEngine().run(nse_instrument(), make_bars(rows), Scripted({3: LONG}), make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price.amount == Decimal("95")
    assert trade.stop_loss.amount == Decimal("98.00")
    assert trade.net_pnl.amount == Decimal("-5000")


def test_intrabar_collision_policies_and_single_trigger_exits() -> None:
    both = flat_rows(3) + [FLAT, (100, 105, 97, 100)] + flat_rows(2)
    stop_first = BacktestEngine().run(
        nse_instrument(), make_bars(both), Scripted({3: LONG}), make_config()
    ).trades[0]
    target_first = BacktestEngine().run(
        nse_instrument(),
        make_bars(both),
        Scripted({3: LONG}),
        make_config(intrabar_collision_policy="TARGET_FIRST"),
    ).trades[0]
    assert (stop_first.exit_reason, stop_first.exit_price.amount) == ("STOP_LOSS", Decimal("98.00"))
    assert (target_first.exit_reason, target_first.exit_price.amount) == (
        "TAKE_PROFIT",
        Decimal("104.00"),
    )
    only_target = flat_rows(3) + [FLAT, (100, 105, 99, 100)] + flat_rows(2)
    only_stop = flat_rows(3) + [FLAT, (100, 101, 97, 100)] + flat_rows(2)
    t_trade = BacktestEngine().run(
        nse_instrument(), make_bars(only_target), Scripted({3: LONG}), make_config()
    ).trades[0]
    s_trade = BacktestEngine().run(
        nse_instrument(), make_bars(only_stop), Scripted({3: LONG}), make_config()
    ).trades[0]
    assert (t_trade.exit_reason, t_trade.exit_price.amount) == ("TAKE_PROFIT", Decimal("104.00"))
    assert (s_trade.exit_reason, s_trade.exit_price.amount) == ("STOP_LOSS", Decimal("98.00"))


def test_liquidity_participation_cap_and_sub_lot_rejection() -> None:
    thin = flat_rows(3) + [(100, 101, 99, 100, 500)] + flat_rows(3)
    result = BacktestEngine().run(nse_instrument(), make_bars(thin), Scripted({3: LONG}), make_config())
    assert entry_fill(result).quantity_delta == 50
    dust = flat_rows(3) + [(100, 101, 99, 100, 5)] + flat_rows(3)
    blocked = BacktestEngine().run(nse_instrument(), make_bars(dust), Scripted({3: LONG}), make_config())
    assert not blocked.trades
    assert [d.reasons for d in blocked.rejected_proposals] == [("LIQUIDITY_BELOW_LOT_SIZE",)]
    assert not any(e.event_type == LedgerEventType.BUY_FILL for e in blocked.ledger.entries)


def test_delisting_forces_liquidation_at_open_and_halts_trading() -> None:
    rows = flat_rows(6) + [(90, 91, 89, 90)] + [(90, 91, 89, 90)] * 4
    bars = make_bars(rows)
    instrument = nse_instrument(delisted_date=START + timedelta(days=6))
    result = BacktestEngine().run(instrument, bars, Scripted({3: LONG, 9: LONG}), make_config())
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "DELISTED"
    assert trade.exit_price.amount == Decimal("90")
    assert trade.exit_time == bars[6].timestamp
    buys = [e for e in result.ledger.entries if e.event_type == LedgerEventType.BUY_FILL]
    assert len(buys) == 1
    assert len(result.equity_curve) == len(bars)


def _trending_rows(count: int) -> list[tuple[str, str, str, str]]:
    rows = []
    previous = Decimal("100")
    for i in range(count):
        close = Decimal("100") + Decimal(i) / Decimal("4") + (Decimal("0.5") if i % 5 == 0 else 0)
        rows.append((str(previous), str(max(previous, close) + Decimal("0.3")), str(min(previous, close) - Decimal("0.3")), str(close)))
        previous = close
    return rows


def _assert_conserved(result, initial: Decimal) -> None:
    assert ledger_conservation_residual(result.ledger, result.final_snapshot) == Decimal("0")
    assert len(result.trades) >= 3
    final_equity = result.equity_curve[-1].total_equity.amount
    assert final_equity - initial == sum((t.net_pnl.amount for t in result.trades), Decimal("0"))
    assert result.final_snapshot.positions == {}


def test_cross_market_conservation_nse_inr_and_nasdaq_usd() -> None:
    actions = {3: LONG, 9: EXIT, 12: LONG, 18: EXIT, 21: LONG}
    rows = _trending_rows(30)
    nse = BacktestEngine().run(
        nse_instrument(),
        make_bars(rows),
        Scripted(actions),
        make_config(fee=IndiaEquityFeeModel(), slip=BasisPointsSlippageModel(Decimal("5"))),
    )
    _assert_conserved(nse, Decimal("1000000"))
    assert nse.metrics.total_fees > 0
    usd = Instrument("TESTCO", Exchange.NASDAQ, Currency.USD)
    nasdaq = BacktestEngine().run(
        usd,
        make_bars(rows, Exchange.NASDAQ),
        Scripted(actions),
        make_config(
            Currency.USD,
            "100000",
            fee=USEquityFeeModel(),
            slip=BasisPointsSlippageModel(Decimal("5")),
        ),
    )
    _assert_conserved(nasdaq, Decimal("100000"))
    assert all(t.currency == Currency.USD for t in nasdaq.trades)


def test_signal_exit_executes_at_next_open() -> None:
    rows = flat_rows(3) + [FLAT] * 3 + [(102, 103, 100, 101)] + flat_rows(2)
    bars = make_bars(rows)
    result = BacktestEngine().run(nse_instrument(), bars, Scripted({3: LONG, 6: EXIT}), make_config())
    trade = result.trades[0]
    assert trade.exit_reason == "SIGNAL_EXIT"
    assert trade.exit_price.amount == Decimal("102")
    assert trade.exit_time == bars[6].timestamp


def test_risk_gate_rejection_is_recorded_and_no_fill_occurs() -> None:
    rows = flat_rows(3) + [(97, 98, 96, 97)] + flat_rows(3)
    result = BacktestEngine().run(nse_instrument(), make_bars(rows), Scripted({3: LONG}), make_config())
    assert not result.trades
    assert "INVALID_STOP_LOSS_DIRECTION" in result.rejected_proposals[0].reasons
    assert result.final_snapshot.cash.amount == Decimal("1000000")


def test_manifest_reproducibility_and_tamper_detection() -> None:
    bars = make_bars(_trending_rows(20))

    def run():
        return BacktestEngine().run(
            nse_instrument(),
            bars,
            Scripted({3: LONG, 9: EXIT}),
            make_config(fee=IndiaEquityFeeModel(), slip=BasisPointsSlippageModel(Decimal("5"))),
        )

    first, second = run(), run()
    assert first.manifest == second.manifest
    assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256
    assert first.ledger.entries == second.ledger.entries
    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve
    assert first.metrics == second.metrics
    assert first.final_snapshot == second.final_snapshot
    manifest = first.manifest
    assert verify_manifest_integrity(manifest)
    mutations = {
        "manifest_id": "exp-other",
        "created_at": manifest.created_at + timedelta(seconds=1),
        "dataset_sha256": "0" * 64,
        "provider_source": "other",
        "exchange": Exchange.BSE,
        "symbol": "OTHER",
        "interval": CandleInterval.H1,
        "start_time": manifest.start_time + timedelta(days=1),
        "end_time": manifest.end_time + timedelta(days=1),
        "instrument_version": 2,
        "corporate_action_policy": "NONE:tampered",
        "strategy_id": "other",
        "strategy_params": {"x": 1},
        "fee_model_name": "ZeroFeeModel",
        "slippage_model_name": "other",
        "risk_policy": {"portfolio": {}},
        "initial_capital": Money(Decimal("1"), Currency.INR),
        "random_seed": 43,
        "git_commit": "deadbeef",
        "manifest_sha256": "0" * 64,
    }
    for name, value in mutations.items():
        assert not verify_manifest_integrity(dataclasses.replace(manifest, **{name: value})), name
    changed_inputs = BacktestEngine().run(
        nse_instrument(),
        bars,
        Scripted({3: LONG, 9: EXIT}),
        make_config(fee=IndiaEquityFeeModel(), slip=BasisPointsSlippageModel(Decimal("6"))),
    )
    assert changed_inputs.manifest.manifest_sha256 != manifest.manifest_sha256


def test_dataset_hash_is_sensitive_to_every_candle_field() -> None:
    bars = make_bars(flat_rows(5))
    baseline = compute_dataset_sha256(bars)
    assert baseline == compute_dataset_sha256(list(bars))
    for index, field in ((2, "open"), (2, "high"), (2, "low"), (2, "close"), (2, "volume")):
        value = getattr(bars[index], field)
        bumped = value + (1 if field == "volume" else Decimal("0.01"))
        mutated = list(bars)
        mutated[index] = dataclasses.replace(bars[index], **{field: bumped})
        assert compute_dataset_sha256(mutated) != baseline, field
    assert compute_dataset_sha256(bars[:-1]) != baseline


def test_manifest_rejects_floats_naive_datetimes_and_empty_candles() -> None:
    instrument = nse_instrument()
    kwargs = {
        "instrument": instrument,
        "provider_source": "x",
        "corporate_action_policy": "NONE",
        "strategy_id": "s",
        "strategy_params": {},
        "fee_model_name": "f",
        "slippage_model_name": "s",
        "risk_policy": {},
        "initial_capital": Money(Decimal("1"), Currency.INR),
        "random_seed": 1,
        "git_commit": "abc",
    }
    with pytest.raises(ValueError):
        build_experiment_manifest(candles=(), **kwargs)
    bars = make_bars(flat_rows(2))
    with pytest.raises(ValueError):
        build_experiment_manifest(candles=bars, created_at=datetime(2025, 1, 1), **kwargs)
    nan_params = dict(kwargs, strategy_params={"x": float("nan")})
    with pytest.raises(ValueError):
        build_experiment_manifest(candles=bars, **nan_params)
    ok = build_experiment_manifest(candles=bars, **dict(kwargs, strategy_params={"x": 0.5}))
    assert verify_manifest_integrity(ok)


def _factory_recorder():
    made: list[Scripted] = []

    def factory() -> Scripted:
        strategy = Scripted({3: LONG, 6: EXIT})
        made.append(strategy)
        return strategy

    return made, factory


def test_train_test_split_temporal_separation() -> None:
    bars = make_bars(_trending_rows(40))
    made, factory = _factory_recorder()
    window = run_train_test_split(nse_instrument(), bars, factory, make_config())
    assert len(made) == 2 and made[0] is not made[1]
    assert window.train_start == bars[0].timestamp
    assert window.train_end == bars[27].close_time
    assert window.test_start == bars[28].timestamp
    assert window.train_end <= window.test_start
    assert len(window.train_result.equity_curve) == 28
    assert len(window.test_result.equity_curve) == 12
    train_dates = {p.timestamp for p in window.train_result.equity_curve}
    assert not train_dates & {p.timestamp for p in window.test_result.equity_curve}
    assert made[1].log[0][0] == 1
    for bad in (Decimal("0"), Decimal("1"), Decimal("-0.1"), 0.7):
        with pytest.raises(ValueError):
            run_train_test_split(nse_instrument(), bars, factory, make_config(), split_ratio=bad)
    with pytest.raises(ValueError):
        run_train_test_split(nse_instrument(), bars[:1], factory, make_config())


def test_walk_forward_windows_are_ordered_non_overlapping_and_isolated() -> None:
    bars = make_bars(_trending_rows(40))
    made, factory = _factory_recorder()
    result = run_walk_forward(nse_instrument(), bars, factory, make_config(), 15, 5, 5)
    assert len(result.windows) == 5
    assert len(made) == 10 and len({id(s) for s in made}) == 10
    for previous, current in zip(result.windows, result.windows[1:], strict=False):
        assert previous.test_end <= current.test_start
    for window in result.windows:
        assert window.train_end <= window.test_start
        assert window.test_result.manifest.start_time == window.test_start
        assert window.train_result.manifest.dataset_sha256 != window.test_result.manifest.dataset_sha256
    assert result.total_oos_trades == sum(w.test_result.metrics.total_trades for w in result.windows)
    assert result.aggregate_oos_max_drawdown_pct == max(
        w.test_result.metrics.max_drawdown_pct for w in result.windows
    )
    for args in ((0, 5, 5), (15, 0, 5), (15, 5, 0), (15, 5, 4), (30, 20, 20)):
        with pytest.raises(ValueError):
            run_walk_forward(nse_instrument(), bars, factory, make_config(), *args)


def make_trade(net: str, currency: Currency = Currency.INR) -> CompletedTrade:
    moment = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price = Money(Decimal("100"), currency)
    pnl = Money(Decimal(net), currency)
    return CompletedTrade(
        trade_id="t",
        exchange=Exchange.NSE,
        symbol="TESTCO",
        currency=currency,
        entry_time=moment,
        exit_time=moment,
        quantity=1,
        entry_price=price,
        exit_price=price,
        stop_loss=None,
        take_profit=None,
        gross_pnl=pnl,
        fees=Money(Decimal("0"), currency),
        net_pnl=pnl,
        r_multiple=Decimal("1"),
        exit_reason="SIGNAL_EXIT",
    )


def test_seeded_monte_carlo_is_reproducible_and_seed_sensitive() -> None:
    trades = [make_trade(x) for x in ("1000", "-500", "250", "-1200", "800", "-300", "600")]
    capital = Money(Decimal("100000"), Currency.INR)
    first = run_seeded_monte_carlo(trades, capital, iterations=300, seed=7)
    again = run_seeded_monte_carlo(list(trades), capital, iterations=300, seed=7)
    other = run_seeded_monte_carlo(trades, capital, iterations=300, seed=8)
    assert first == again
    assert other.seed == 8
    assert dataclasses.replace(other, seed=first.seed) != first
    assert first.trade_count == 7 and first.iterations == 300
    assert (
        first.return_pct_p05 <= first.return_pct_p25 <= first.return_pct_p50
        <= first.return_pct_p75 <= first.return_pct_p95
    )
    assert first.max_drawdown_pct_p50 <= first.max_drawdown_pct_p95
    assert "not a guarantee" in first.disclaimer


def test_monte_carlo_degenerate_cases_and_validation() -> None:
    capital = Money(Decimal("100000"), Currency.INR)
    winners = run_seeded_monte_carlo([make_trade("1000")] * 3, capital, iterations=50)
    assert winners.return_pct_p05 == winners.return_pct_p95 == Decimal("3.0000")
    assert winners.probability_of_loss_pct == Decimal("0.0000")
    assert winners.probability_of_ruin_pct == Decimal("0.0000")
    assert winners.max_drawdown_pct_p95 == Decimal("0.0000")
    wipeout = run_seeded_monte_carlo([make_trade("-30000")], capital, iterations=20)
    assert wipeout.probability_of_ruin_pct == Decimal("100.0000")
    assert wipeout.probability_of_loss_pct == Decimal("100.0000")
    trades = [make_trade("1")]
    with pytest.raises(ValueError):
        run_seeded_monte_carlo(trades, capital, iterations=0)
    with pytest.raises(ValueError):
        run_seeded_monte_carlo(trades, Money(Decimal("0"), Currency.INR))
    with pytest.raises(ValueError):
        run_seeded_monte_carlo(trades, capital, ruin_drawdown_pct=Decimal("0"))
    empty_mc = run_seeded_monte_carlo([], capital)
    assert empty_mc.trade_count == 0
    assert empty_mc.return_pct_p50 == Decimal("0.0000")
    assert empty_mc.max_drawdown_pct_p50 == Decimal("0.0000")
    assert empty_mc.probability_of_loss_pct == Decimal("0.0000")
    assert empty_mc.probability_of_ruin_pct == Decimal("0.0000")
    with pytest.raises(CurrencyMismatchError):
        run_seeded_monte_carlo([make_trade("1", Currency.USD)], capital)


def _points(values: Sequence[str], step_days: int = 1) -> list[EquityPoint]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    zero = Money(Decimal("0"), Currency.INR)
    return [
        EquityPoint(
            base + timedelta(days=step_days * i),
            zero,
            zero,
            Money(Decimal(v), Currency.INR),
            Decimal("0"),
        )
        for i, v in enumerate(values)
    ]


def test_metrics_are_finite_and_safe_on_degenerate_inputs() -> None:
    capital = Money(Decimal("100"), Currency.INR)
    empty = compute_backtest_metrics([], [], capital, Decimal("0"), 0, 0, Decimal("0"))
    flat = compute_backtest_metrics(
        _points(["100", "100", "100"]), [], capital, Decimal("0"), 0, 3, Decimal("0")
    )
    rising = compute_backtest_metrics(
        _points(["101", "102", "103"]),
        [make_trade("3")],
        capital,
        Decimal("1"),
        3,
        3,
        Decimal("1"),
    )
    for metrics in (empty, flat, rising):
        for value in dataclasses.astuple(metrics):
            if isinstance(value, Decimal):
                assert value.is_finite()
    assert flat.sharpe_ratio == flat.sortino_ratio == Decimal("0")
    assert rising.sortino_ratio == Decimal("0")
    assert rising.profit_factor == Decimal("0")
    assert rising.average_loss == Decimal("0")
    assert rising.win_rate_pct == Decimal("100.0000")
    assert rising.exposure_pct == Decimal("100.0000")
    assert rising.excess_return_pct == Decimal("2.0000")
    with pytest.raises(ValueError):
        compute_backtest_metrics([], [], Money(Decimal("0"), Currency.INR), Decimal("0"), 0, 0, Decimal("0"))
    with pytest.raises(ValueError):
        compute_backtest_metrics([], [], capital, Decimal("0"), 5, 3, Decimal("0"))


def test_metrics_drawdown_cagr_and_ratios() -> None:
    capital = Money(Decimal("100"), Currency.INR)
    curve = _points(["120", "90", "110"], step_days=200)
    metrics = compute_backtest_metrics(curve, [], capital, Decimal("0"), 0, 3, Decimal("0"))
    assert metrics.max_drawdown_pct == Decimal("25.0000")
    assert metrics.total_return_pct == Decimal("10.0000")
    assert metrics.cagr_pct > 0
    assert metrics.sharpe_ratio != 0 and metrics.sortino_ratio != 0
    ruin = compute_backtest_metrics(_points(["0"], 400), [], capital, Decimal("0"), 0, 1, Decimal("0"))
    assert ruin.max_drawdown_pct == Decimal("100.0000")
    mixed = [make_trade("300"), make_trade("-100"), make_trade("-100")]
    stats = compute_backtest_metrics(_points(["100"]), mixed, capital, Decimal("0"), 0, 1, Decimal("0"))
    assert stats.profit_factor == Decimal("1.5000")
    assert stats.average_loss == Decimal("-100.0000")
    assert stats.winning_trades == 1 and stats.losing_trades == 2


def test_benchmark_is_first_open_to_last_close() -> None:
    bars = make_bars([(100, 101, 99, 100), (100, 111, 99, 110)])
    assert compute_benchmark_return_pct(bars) == Decimal("10.0000")
    result = BacktestEngine().run(nse_instrument(), bars, Scripted({}), make_config())
    assert result.metrics.benchmark_return_pct == Decimal("10.0000")
    assert result.metrics.total_return_pct == Decimal("0.0000")
    assert result.metrics.excess_return_pct == Decimal("-10.0000")
    with pytest.raises(ValueError):
        compute_benchmark_return_pct(())


def test_input_validation_fails_closed() -> None:
    bars = make_bars(flat_rows(5))
    engine, strategy = BacktestEngine(), Scripted({})
    with pytest.raises(ValueError):
        engine.run(nse_instrument(), (), strategy, make_config())
    with pytest.raises(ValueError, match="does not match instrument"):
        engine.run(Instrument("OTHER", Exchange.NSE, Currency.INR), bars, strategy, make_config())
    with pytest.raises(CurrencyMismatchError):
        engine.run(nse_instrument(), bars, strategy, make_config(Currency.USD))
    with pytest.raises(ValueError):
        engine.run(nse_instrument(), bars[::-1], strategy, make_config())
    with pytest.raises(ValueError):
        engine.run(nse_instrument(), bars + (bars[-1],), strategy, make_config())
    broken = dataclasses.replace(bars[2], high=Decimal("50"))
    with pytest.raises(ValueError, match="bound open and close"):
        engine.run(nse_instrument(), bars[:2] + (broken,), strategy, make_config())
    negative = dataclasses.replace(bars[2], volume=-1)
    with pytest.raises(ValueError):
        engine.run(nse_instrument(), bars[:2] + (negative,), strategy, make_config())
    with pytest.raises(ValueError):
        engine.run(nse_instrument(), bars, Scripted({}, warmup=-1), make_config())


def test_config_validation_fails_closed() -> None:
    for kwargs in (
        {"intrabar_collision_policy": "BOTH"},
        {"position_size_pct": Decimal("0")},
        {"position_size_pct": Decimal("1.5")},
        {"default_stop_loss_pct": Decimal("1")},
        {"default_take_profit_pct": Decimal("-1")},
        {"max_volume_participation": Decimal("0")},
        {"random_seed": True},
        {"git_commit": " "},
        {"adjust_corporate_actions": 1},
    ):
        with pytest.raises((ValueError, TypeError)):
            make_config(**kwargs)
    with pytest.raises(ValueError):
        make_config(capital="0")


def test_dividend_credit_and_split_with_open_position_fails_closed() -> None:
    bars = make_bars(flat_rows(8))
    dividend = CorporateAction(
        Exchange.NSE,
        "TESTCO",
        CorporateActionType.DIVIDEND,
        START + timedelta(days=5),
        adjustment_factor=Decimal("0.98"),
        cash_amount=Money(Decimal("2"), Currency.INR),
    )
    result = BacktestEngine().run(
        nse_instrument(), bars, Scripted({3: LONG}), make_config(), (dividend,)
    )
    quantity = result.trades[0].quantity
    assert result.ledger.get_total_dividends(Currency.INR).amount == Decimal(quantity) * 2
    assert ledger_conservation_residual(result.ledger, result.final_snapshot) == Decimal("0")
    assert result.manifest.corporate_action_policy.startswith("POINT_IN_TIME_ADJUSTED:")
    split = CorporateAction(
        Exchange.NSE,
        "TESTCO",
        CorporateActionType.SPLIT,
        START + timedelta(days=5),
        adjustment_factor=Decimal("0.5"),
    )
    with pytest.raises(CorporateActionConflictError):
        BacktestEngine().run(nse_instrument(), bars, Scripted({3: LONG}), make_config(), (split,))
    disabled = BacktestEngine().run(
        nse_instrument(),
        bars,
        Scripted({3: LONG}),
        make_config(adjust_corporate_actions=False),
        (split,),
    )
    assert disabled.manifest.corporate_action_policy.startswith("DISABLED:")
    flat_before_split = BacktestEngine().run(
        nse_instrument(), bars, Scripted({6: LONG}), make_config(), (split,)
    )
    assert flat_before_split.manifest.manifest_sha256 != result.manifest.manifest_sha256


def test_strategy_sees_point_in_time_adjusted_history_only() -> None:
    bars = make_bars(flat_rows(8))
    announced = CorporateAction(
        Exchange.NSE,
        "TESTCO",
        CorporateActionType.SPLIT,
        START + timedelta(days=6),
        adjustment_factor=Decimal("0.5"),
        announcement_date=START + timedelta(days=4),
    )
    strategy = Scripted({})
    BacktestEngine().run(nse_instrument(), bars, strategy, make_config(), (announced,))
    seen = {count: close for count, close in strategy.log}
    assert seen[4] == Decimal("100")
    assert seen[5] == Decimal("50.0")
    assert seen[8] == Decimal("100")


def test_equity_curve_exposure_and_ledger_order() -> None:
    bars = make_bars(_trending_rows(15))
    result = BacktestEngine().run(
        nse_instrument(), bars, Scripted({3: LONG, 9: EXIT}), make_config()
    )
    assert len(result.equity_curve) == len(bars)
    assert all(p.drawdown_pct >= 0 for p in result.equity_curve)
    assert all(
        p.total_equity.amount == p.cash.amount + p.holdings_value.amount for p in result.equity_curve
    )
    stamps = [e.timestamp for e in result.ledger.entries]
    assert stamps == sorted(stamps)
    assert 0 < result.metrics.exposure_pct < 100


def test_manifest_keyed_hmac_and_backtest_config_validation() -> None:
    bars = make_bars(_trending_rows(10))
    key = "lab-audit-secret-key"
    key_bytes = b"lab-audit-secret-key"
    config = make_config(hmac_key=key)
    result = BacktestEngine().run(nse_instrument(), bars, Scripted({2: LONG, 5: EXIT}), config)
    manifest = result.manifest
    assert verify_manifest_integrity(manifest, hmac_key=key)
    assert verify_manifest_integrity(manifest, hmac_key=key_bytes)
    assert not verify_manifest_integrity(manifest, hmac_key="wrong-key")
    assert not verify_manifest_integrity(manifest, hmac_key=None)
    assert not verify_manifest_integrity(manifest)
    unkeyed_config = make_config(hmac_key=None)
    unkeyed_result = BacktestEngine().run(
        nse_instrument(), bars, Scripted({2: LONG, 5: EXIT}), unkeyed_config
    )
    assert verify_manifest_integrity(unkeyed_result.manifest)
    assert verify_manifest_integrity(unkeyed_result.manifest, hmac_key=None)
    assert not verify_manifest_integrity(unkeyed_result.manifest, hmac_key=key)
    tampered = dataclasses.replace(manifest, symbol="TAMPERED")
    assert not verify_manifest_integrity(tampered, hmac_key=key)
    assert not verify_manifest_integrity(manifest, hmac_key=123)
    with pytest.raises(TypeError):
        make_config(hmac_key=12345)
    with pytest.raises(TypeError):
        make_config(hmac_key=True)
    with pytest.raises(ValueError):
        make_config(hmac_key="")
    with pytest.raises(ValueError):
        build_experiment_manifest(
            instrument=nse_instrument(),
            candles=bars,
            provider_source="test",
            corporate_action_policy="NONE",
            strategy_id="test",
            strategy_params={},
            fee_model_name="ZeroFeeModel",
            slippage_model_name="ZeroSlippageModel",
            risk_policy={},
            initial_capital=Money(Decimal("100000"), Currency.INR),
            random_seed=42,
            git_commit="head",
            hmac_key="",
        )


def test_final_bar_pending_signal_cancelled_at_end_of_data() -> None:
    bars = make_bars(_trending_rows(5))
    strategy = Scripted({len(bars): LONG})
    result = BacktestEngine().run(nse_instrument(), bars, strategy, make_config())
    assert len(result.trades) == 0
    assert len(result.rejected_proposals) == 1
    decision = result.rejected_proposals[0]
    assert not decision.approved
    assert decision.reasons == ("END_OF_DATA_PENDING_CANCELLED",)


def test_protective_gap_through_stop_fills_at_open_with_adverse_slippage() -> None:
    rows = flat_rows(3) + [FLAT, (80, 82, 75, 78)] + flat_rows(3)
    slip_bps = Decimal("50")
    config = make_config(
        default_stop_loss_pct=Decimal("0.05"),
        slip=BasisPointsSlippageModel(slip_bps),
    )
    result = BacktestEngine().run(nse_instrument(), make_bars(rows), Scripted({3: LONG}), config)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.stop_loss is not None and trade.stop_loss.amount == Decimal("95.00")
    assert trade.exit_price.amount == Decimal("79.60")


def test_time_machine_sources_have_no_inline_comments_or_forbidden_imports() -> None:
    root = Path(__file__).resolve().parent.parent
    files = list((root / "src" / "agentic_trading" / "time_machine").glob("*.py"))
    files.append(Path(__file__).resolve())
    assert len(files) >= 7
    for path in files:
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            assert token.type != tokenize.COMMENT, f"{path.name}:{token.start[0]}"
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert "zerodha" not in name.lower() and "kiteconnect" not in name.lower(), path.name
