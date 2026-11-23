"""Out-of-sample train/test and rolling walk-forward validation."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from agentic_trading.market_data.corporate_actions import CorporateAction
from agentic_trading.market_data.instruments import Instrument
from agentic_trading.market_data.models import Candle
from agentic_trading.strategy.contracts import Strategy
from agentic_trading.time_machine.engine import BacktestConfig, BacktestEngine, BacktestResult

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class WalkForwardWindow:
    window_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_result: BacktestResult
    test_result: BacktestResult


@dataclass(frozen=True)
class WalkForwardResult:
    windows: tuple[WalkForwardWindow, ...]
    aggregate_oos_return_pct: Decimal
    aggregate_oos_win_rate_pct: Decimal
    aggregate_oos_max_drawdown_pct: Decimal
    total_oos_trades: int


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1, got {value!r}")
    return value


def _build_window(
    index: int,
    instrument: Instrument,
    train: Sequence[Candle],
    test: Sequence[Candle],
    strategy_factory: Callable[[], Strategy],
    config: BacktestConfig,
    corporate_actions: Sequence[CorporateAction],
) -> WalkForwardWindow:
    if not train or not test:
        raise ValueError("train and test segments must both be non-empty")
    train_end = train[-1].close_time
    test_start = test[0].timestamp
    if train_end > test_start:
        raise ValueError("train segment must end before the test segment starts")
    engine = BacktestEngine()
    train_result = engine.run(instrument, train, strategy_factory(), config, corporate_actions)
    test_result = engine.run(instrument, test, strategy_factory(), config, corporate_actions)
    return WalkForwardWindow(
        window_index=index,
        train_start=train[0].timestamp,
        train_end=train_end,
        test_start=test_start,
        test_end=test[-1].close_time,
        train_result=train_result,
        test_result=test_result,
    )


def run_train_test_split(
    instrument: Instrument,
    candles: Sequence[Candle],
    strategy_factory: Callable[[], Strategy],
    config: BacktestConfig,
    split_ratio: Decimal = Decimal("0.70"),
    corporate_actions: Sequence[CorporateAction] = (),
) -> WalkForwardWindow:
    if (
        isinstance(split_ratio, (bool, float))
        or not isinstance(split_ratio, Decimal)
        or not split_ratio.is_finite()
        or not (ZERO < split_ratio < ONE)
    ):
        raise ValueError("split_ratio must be a Decimal strictly between 0 and 1")
    bars = tuple(candles)
    split = int((Decimal(len(bars)) * split_ratio).to_integral_value(rounding=ROUND_FLOOR))
    if split < 1 or split > len(bars) - 1:
        raise ValueError("split_ratio leaves an empty train or test segment")
    return _build_window(
        0, instrument, bars[:split], bars[split:], strategy_factory, config, corporate_actions
    )


def run_walk_forward(
    instrument: Instrument,
    candles: Sequence[Candle],
    strategy_factory: Callable[[], Strategy],
    config: BacktestConfig,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    corporate_actions: Sequence[CorporateAction] = (),
) -> WalkForwardResult:
    _positive_int(train_bars, "train_bars")
    _positive_int(test_bars, "test_bars")
    _positive_int(step_bars, "step_bars")
    if step_bars < test_bars:
        raise ValueError("step_bars must be >= test_bars so out-of-sample windows never overlap")
    bars = tuple(candles)
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + train_bars + test_bars <= len(bars):
        boundary = start + train_bars
        windows.append(
            _build_window(
                len(windows),
                instrument,
                bars[start:boundary],
                bars[boundary : boundary + test_bars],
                strategy_factory,
                config,
                corporate_actions,
            )
        )
        start += step_bars
    if not windows:
        raise ValueError("not enough candles for a single train/test window")

    compounded = ONE
    total_trades = 0
    total_wins = 0
    worst_drawdown = ZERO
    for window in windows:
        metrics = window.test_result.metrics
        compounded *= ONE + metrics.total_return_pct / HUNDRED
        total_trades += metrics.total_trades
        total_wins += metrics.winning_trades
        worst_drawdown = max(worst_drawdown, metrics.max_drawdown_pct)
    win_rate = Decimal(total_wins) / Decimal(total_trades) * HUNDRED if total_trades else ZERO
    return WalkForwardResult(
        windows=tuple(windows),
        aggregate_oos_return_pct=((compounded - ONE) * HUNDRED).quantize(
            _QUANTUM, rounding=ROUND_HALF_EVEN
        ),
        aggregate_oos_win_rate_pct=win_rate.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN),
        aggregate_oos_max_drawdown_pct=worst_drawdown,
        total_oos_trades=total_trades,
    )
