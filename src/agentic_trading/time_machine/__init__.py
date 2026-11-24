"""Time Machine: causal backtesting, walk-forward validation, seeded Monte Carlo, manifests."""
from __future__ import annotations

from agentic_trading.time_machine.basket import (
    BasketBacktestResult,
    PerSymbolAttribution,
    WalkForwardOptimizationResult,
    run_basket_backtest,
    run_walk_forward_optimization,
)
from agentic_trading.time_machine.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    CompletedTrade,
    CorporateActionConflictError,
    EquityPoint,
    LedgerConservationError,
    ledger_conservation_residual,
)
from agentic_trading.time_machine.manifest import (
    ExperimentManifest,
    build_experiment_manifest,
    compute_dataset_sha256,
    verify_manifest_integrity,
)
from agentic_trading.time_machine.metrics import (
    BacktestMetrics,
    compute_backtest_metrics,
    compute_benchmark_return_pct,
)
from agentic_trading.time_machine.monte_carlo import MonteCarloSummary, run_seeded_monte_carlo
from agentic_trading.time_machine.validation import (
    WalkForwardResult,
    WalkForwardWindow,
    run_train_test_split,
    run_walk_forward,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestMetrics",
    "BacktestResult",
    "BasketBacktestResult",
    "CompletedTrade",
    "CorporateActionConflictError",
    "EquityPoint",
    "ExperimentManifest",
    "LedgerConservationError",
    "MonteCarloSummary",
    "PerSymbolAttribution",
    "WalkForwardOptimizationResult",
    "WalkForwardResult",
    "WalkForwardWindow",
    "build_experiment_manifest",
    "compute_backtest_metrics",
    "compute_benchmark_return_pct",
    "compute_dataset_sha256",
    "ledger_conservation_residual",
    "run_basket_backtest",
    "run_seeded_monte_carlo",
    "run_train_test_split",
    "run_walk_forward",
    "run_walk_forward_optimization",
    "verify_manifest_integrity",
]
