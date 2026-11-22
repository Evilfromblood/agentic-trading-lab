"""Adversarial tests for Milestone 3 simulation, portfolio, strategy contracts, and risk gate."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentic_trading.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionType,
    adjust_candles_for_corporate_actions,
)
from agentic_trading.market_data.instruments import (
    AssetClass,
    Currency,
    CurrencyMismatchError,
    Instrument,
    InstrumentRegistry,
    Money,
    UnknownInstrumentError,
)
from agentic_trading.market_data.models import Candle, CandleInterval, Exchange
from agentic_trading.risk_engine.proposal_gate import (
    PortfolioRiskPolicy,
    ProposalRiskDecision,
    evaluate_trade_proposal,
)
from agentic_trading.simulation.costs import (
    BasisPointsSlippageModel,
    FeeModel,
    IndiaEquityFeeModel,
    USEquityFeeModel,
    ZeroFeeModel,
)
from agentic_trading.simulation.ledger import (
    AccountingLedger,
    LedgerEntry,
    LedgerEventType,
)
from agentic_trading.simulation.portfolio import (
    InsufficientFundsError,
    InsufficientPositionError,
    PortfolioEngine,
    PortfolioSnapshot,
    Position,
)
from agentic_trading.strategy.contracts import (
    BarContext,
    Signal,
    SignalDirection,
    TradeProposal,
)
from agentic_trading.strategy.indicators import atr, ema, rsi, sma

UTC = timezone.utc


def test_instrument_point_in_time_active_status() -> None:
    inst = Instrument(
        symbol="INFY",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        listed_date=date(2020, 1, 1),
        delisted_date=date(2025, 12, 31),
    )
    assert not inst.is_active_on(date(2019, 12, 31))
    assert inst.is_active_on(date(2020, 1, 1))
    assert inst.is_active_on(date(2023, 6, 15))
    assert inst.is_active_on(date(2025, 12, 31))
    assert not inst.is_active_on(date(2026, 1, 1))

    with pytest.raises(TypeError):
        inst.is_active_on("2023-01-01")


def test_instrument_invalid_dates_and_version() -> None:
    with pytest.raises(ValueError):
        Instrument(
            symbol="INFY",
            exchange=Exchange.NSE,
            currency=Currency.INR,
            listed_date=date(2025, 1, 1),
            delisted_date=date(2020, 1, 1),
        )

    with pytest.raises(TypeError):
        Instrument(
            symbol="INFY",
            exchange=Exchange.NSE,
            currency=Currency.INR,
            listed_date="2020-01-01",
        )

    with pytest.raises(ValueError):
        Instrument(
            symbol="INFY",
            exchange=Exchange.NSE,
            currency=Currency.INR,
            version=0,
        )


def test_registry_get_as_of_and_list_active_on() -> None:
    reg = InstrumentRegistry()
    active_inst = Instrument(
        symbol="TCS",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        listed_date=date(2010, 1, 1),
    )
    delisted_inst = Instrument(
        symbol="OLDCO",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        listed_date=date(2010, 1, 1),
        delisted_date=date(2020, 1, 1),
    )
    reg.register(active_inst)
    reg.register(delisted_inst)

    target_date = date(2024, 1, 1)
    assert reg.get_as_of(Exchange.NSE, "TCS", target_date) == active_inst

    with pytest.raises(UnknownInstrumentError):
        reg.get_as_of(Exchange.NSE, "OLDCO", target_date)

    active_list = reg.list_active_on(Exchange.NSE, target_date)
    assert active_list == (active_inst,)
    assert active_inst.asset_class == AssetClass.EQUITY
    assert AssetClass("equity") == AssetClass.EQUITY


def test_corporate_action_announcement_date_look_ahead_guard() -> None:
    with pytest.raises(ValueError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 1),
            announcement_date=date(2024, 6, 2),
            adjustment_factor=Decimal("0.5"),
        )

    with pytest.raises(TypeError):
        CorporateAction(
            exchange=Exchange.NSE,
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2024, 6, 1),
            announcement_date="2024-05-01",
            adjustment_factor=Decimal("0.5"),
        )

    action = CorporateAction(
        exchange=Exchange.NSE,
        symbol="RELIANCE",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2024, 6, 1),
        announcement_date=date(2024, 5, 15),
        adjustment_factor=Decimal("0.5"),
    )

    t0 = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
    c1 = Candle(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("2000"),
        high=Decimal("2100"),
        low=Decimal("1950"),
        close=Decimal("2050"),
        volume=1000,
        timestamp=t0,
        source="test",
        retrieval_timestamp=t0,
    )

    unadjusted = adjust_candles_for_corporate_actions(
        candles=[c1],
        actions=[action],
        as_of_date=date(2024, 5, 10),
    )
    assert unadjusted[0].close == Decimal("2050")

    adjusted = adjust_candles_for_corporate_actions(
        candles=[c1],
        actions=[action],
        as_of_date=date(2024, 5, 20),
    )
    assert adjusted[0].close == Decimal("1025.0")


def test_accounting_ledger_monotonicity_and_projections() -> None:
    ledger = AccountingLedger()
    t1 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    t2 = datetime(2024, 1, 1, 10, 5, tzinfo=UTC)
    t_bad = datetime(2024, 1, 1, 9, 55, tzinfo=UTC)

    e1 = ledger.append(
        timestamp=t1,
        event_type=LedgerEventType.DEPOSIT,
        currency=Currency.INR,
        cash_delta=Money(Decimal("100000"), Currency.INR),
    )
    assert e1.sequence_id == 1

    e2 = ledger.append(
        timestamp=t2,
        event_type=LedgerEventType.FEE_CHARGE,
        currency=Currency.INR,
        cash_delta=Money(Decimal("-50"), Currency.INR),
    )
    assert e2.sequence_id == 2

    with pytest.raises(ValueError):
        ledger.append(
            timestamp=t_bad,
            event_type=LedgerEventType.DEPOSIT,
            currency=Currency.INR,
            cash_delta=Money(Decimal("1000"), Currency.INR),
        )

    assert ledger.get_cash_balance(Currency.INR) == Money(Decimal("99950"), Currency.INR)
    assert ledger.get_total_deposits(Currency.INR) == Money(Decimal("100000"), Currency.INR)
    assert ledger.get_total_fees(Currency.INR) == Money(Decimal("50"), Currency.INR)
    assert len(ledger.entries) == 2
    assert isinstance(e1, LedgerEntry)
    assert LedgerEventType("deposit") == LedgerEventType.DEPOSIT


def test_fee_models_india_and_us() -> None:
    in_fee = IndiaEquityFeeModel()
    price_inr = Money(Decimal("1000"), Currency.INR)
    fee_buy = in_fee.calculate_fees(Exchange.NSE, "INFY", "BUY", 100, price_inr)
    fee_sell = in_fee.calculate_fees(Exchange.NSE, "INFY", "SELL", 100, price_inr)
    assert fee_buy.amount > Decimal("0")
    assert fee_sell.amount > Decimal("0")
    assert fee_buy.currency == Currency.INR

    with pytest.raises(CurrencyMismatchError):
        in_fee.calculate_fees(Exchange.NSE, "INFY", "BUY", 100, Money(Decimal("10"), Currency.USD))

    us_fee = USEquityFeeModel()
    price_usd = Money(Decimal("150"), Currency.USD)
    fee_us_buy = us_fee.calculate_fees(Exchange.NASDAQ, "AAPL", "BUY", 10, price_usd)
    fee_us_sell = us_fee.calculate_fees(Exchange.NASDAQ, "AAPL", "SELL", 10, price_usd)
    assert fee_us_buy.amount == Decimal("1.00")
    assert fee_us_sell.amount >= Decimal("1.00")
    assert fee_us_sell.currency == Currency.USD

    zero_fee = ZeroFeeModel()
    assert zero_fee.calculate_fees(Exchange.NSE, "INFY", "BUY", 100, price_inr) == Money(Decimal("0.00"), Currency.INR)


def test_basis_points_slippage_model() -> None:
    slip = BasisPointsSlippageModel(basis_points=Decimal("10"))
    p = Money(Decimal("100.00"), Currency.USD)
    p_buy = slip.calculate_slippage(p, "BUY", Decimal("0.01"))
    p_sell = slip.calculate_slippage(p, "SELL", Decimal("0.01"))
    assert p_buy.amount == Decimal("100.10")
    assert p_sell.amount == Decimal("99.90")


def test_portfolio_engine_deposits_withdrawals_overdraft() -> None:
    engine = PortfolioEngine(currency=Currency.USD)
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)

    engine.deposit(Money(Decimal("5000"), Currency.USD), t0)
    assert engine.ledger.get_cash_balance(Currency.USD) == Money(Decimal("5000"), Currency.USD)

    t1 = t0 + timedelta(minutes=5)
    engine.withdraw(Money(Decimal("2000"), Currency.USD), t1)
    assert engine.ledger.get_cash_balance(Currency.USD) == Money(Decimal("3000"), Currency.USD)

    t2 = t1 + timedelta(minutes=5)
    with pytest.raises(InsufficientFundsError):
        engine.withdraw(Money(Decimal("4000"), Currency.USD), t2)


def test_portfolio_engine_accounting_conservation_cycle() -> None:
    engine = PortfolioEngine(
        currency=Currency.INR,
        fee_model=IndiaEquityFeeModel(),
        slippage_model=BasisPointsSlippageModel(Decimal("0")),
    )
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    engine.deposit(Money(Decimal("100000.00"), Currency.INR), t)

    t += timedelta(minutes=1)
    engine.apply_fill(
        timestamp=t,
        exchange=Exchange.NSE,
        symbol="TCS",
        side="BUY",
        quantity=20,
        execution_price=Money(Decimal("3000.00"), Currency.INR),
        tick_size=Decimal("0.05"),
    )

    t += timedelta(minutes=1)
    engine.apply_fill(
        timestamp=t,
        exchange=Exchange.NSE,
        symbol="TCS",
        side="BUY",
        quantity=10,
        execution_price=Money(Decimal("3300.00"), Currency.INR),
        tick_size=Decimal("0.05"),
    )

    t += timedelta(minutes=1)
    engine.apply_fill(
        timestamp=t,
        exchange=Exchange.NSE,
        symbol="TCS",
        side="SELL",
        quantity=15,
        execution_price=Money(Decimal("3500.00"), Currency.INR),
        tick_size=Decimal("0.05"),
    )

    snap = engine.snapshot(
        currency=Currency.INR,
        mark_prices={(Exchange.NSE, "TCS"): Money(Decimal("3600.00"), Currency.INR)},
        timestamp=t + timedelta(minutes=1),
    )

    total_dep = engine.ledger.get_total_deposits(Currency.INR).amount
    total_with = engine.ledger.get_total_withdrawals(Currency.INR).amount
    total_fees = engine.ledger.get_total_fees(Currency.INR).amount
    realized = snap.realized_pnl.amount
    cash = snap.cash.amount
    cost_basis_open = sum(
        (pos.cost_basis.amount for pos in snap.positions.values()),
        Decimal("0"),
    )

    accounting_left = total_dep - total_with + realized - total_fees
    accounting_right = cash + cost_basis_open
    assert accounting_left == accounting_right

    pos_sample = Position(
        exchange=Exchange.NSE,
        symbol="TCS",
        currency=Currency.INR,
        quantity=10,
        average_cost=Money(Decimal("3000.00"), Currency.INR),
        realized_pnl=Money(Decimal("500.00"), Currency.INR),
    )
    assert pos_sample.cost_basis == Money(Decimal("30000.00"), Currency.INR)


def test_bar_context_look_ahead_guard() -> None:
    inst = Instrument(symbol="AAPL", exchange=Exchange.NASDAQ, currency=Currency.USD)
    dec_time = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    c_past = Candle(
        symbol="AAPL",
        exchange=Exchange.NASDAQ,
        interval=CandleInterval.M5,
        open=Decimal("150"),
        high=Decimal("151"),
        low=Decimal("149"),
        close=Decimal("150.5"),
        volume=100,
        timestamp=dec_time - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=dec_time,
    )
    c_future = Candle(
        symbol="AAPL",
        exchange=Exchange.NASDAQ,
        interval=CandleInterval.M5,
        open=Decimal("150.5"),
        high=Decimal("152"),
        low=Decimal("150"),
        close=Decimal("151.5"),
        volume=100,
        timestamp=dec_time + timedelta(minutes=5),
        source="test",
        retrieval_timestamp=dec_time + timedelta(minutes=10),
    )

    ctx_valid = BarContext(instrument=inst, decision_time=dec_time, bars=(c_past,))
    assert len(ctx_valid.bars) == 1

    with pytest.raises(ValueError):
        BarContext(instrument=inst, decision_time=dec_time, bars=(c_past, c_future))


def test_technical_indicators_warmup_and_accuracy() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    candles = [
        Candle(
            symbol="TEST",
            exchange=Exchange.NSE,
            interval=CandleInterval.D1,
            open=Decimal(str(100 + i)),
            high=Decimal(str(105 + i)),
            low=Decimal(str(95 + i)),
            close=Decimal(str(100 + i)),
            volume=1000,
            timestamp=t0 + timedelta(days=i),
            source="test",
            retrieval_timestamp=t0 + timedelta(days=i),
        )
        for i in range(20)
    ]

    with pytest.raises(ValueError):
        sma(candles, 0)
    with pytest.raises(ValueError):
        ema(candles, -5)

    assert sma(candles[:3], 5) is None
    assert ema(candles[:3], 5) is None
    assert rsi(candles[:10], 14) is None
    assert atr(candles[:10], 14) is None

    s = sma(candles, 5)
    assert s is not None and s == Decimal("117")

    e = ema(candles, 5)
    assert e is not None and e > Decimal("100")

    r = rsi(candles, 14)
    assert r is not None and r == Decimal("100")

    a = atr(candles, 14)
    assert a is not None and a == Decimal("10.0000")


def test_proposal_risk_gate_comprehensive_matrix() -> None:
    inst = Instrument(
        symbol="INFY",
        exchange=Exchange.NSE,
        currency=Currency.INR,
        lot_size=10,
    )
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    policy = PortfolioRiskPolicy(
        max_position_pct=Decimal("0.20"),
        max_total_exposure_pct=Decimal("0.80"),
        max_daily_loss_pct=Decimal("0.05"),
        max_drawdown_pct=Decimal("0.10"),
        require_stop_loss=True,
        max_risk_per_trade_pct=Decimal("0.02"),
    )

    port_ok = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("100000"), Currency.INR),
        holdings_value=Money(Decimal("0"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={},
    )

    p_clean = TradeProposal(
        proposal_id="P1",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=10,
        limit_price=Money(Decimal("1000"), Currency.INR),
        stop_loss=Money(Decimal("950"), Currency.INR),
    )
    entry_price = Money(Decimal("1000"), Currency.INR)

    dec_clean = evaluate_trade_proposal(
        proposal=p_clean,
        portfolio=port_ok,
        entry_price=entry_price,
        policy=policy,
        daily_pnl=Money(Decimal("0"), Currency.INR),
        peak_equity=Money(Decimal("100000"), Currency.INR),
    )
    assert isinstance(dec_clean, ProposalRiskDecision)
    assert dec_clean.approved
    assert dec_clean.max_allowed_quantity == 10

    sig = Signal(
        exchange=Exchange.NSE,
        symbol="INFY",
        timestamp=t,
        direction=SignalDirection.LONG,
        confidence=Decimal("0.85"),
        stop_loss=Money(Decimal("950"), Currency.INR),
        take_profit=Money(Decimal("1100"), Currency.INR),
        rationale="momentum breakout",
    )
    assert sig.direction == SignalDirection.LONG
    assert SignalDirection("long") == SignalDirection.LONG

    p_lot_fail = TradeProposal(
        proposal_id="P2",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=15,
        limit_price=Money(Decimal("1000"), Currency.INR),
        stop_loss=Money(Decimal("950"), Currency.INR),
    )
    dec_lot = evaluate_trade_proposal(
        p_lot_fail, port_ok, entry_price, policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_lot.approved
    assert "LOT_SIZE_MISMATCH" in dec_lot.reasons

    p_no_stop = TradeProposal(
        proposal_id="P3",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=10,
        limit_price=Money(Decimal("1000"), Currency.INR),
    )
    dec_no_stop = evaluate_trade_proposal(
        p_no_stop, port_ok, entry_price, policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_no_stop.approved
    assert "MISSING_STOP_LOSS" in dec_no_stop.reasons

    p_bad_stop = TradeProposal(
        proposal_id="P4",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=10,
        limit_price=Money(Decimal("1000"), Currency.INR),
        stop_loss=Money(Decimal("1050"), Currency.INR),
    )
    dec_bad_stop = evaluate_trade_proposal(
        p_bad_stop, port_ok, entry_price, policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_bad_stop.approved
    assert "INVALID_STOP_LOSS_DIRECTION" in dec_bad_stop.reasons

    p_high_risk = TradeProposal(
        proposal_id="P5",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=10,
        limit_price=Money(Decimal("1000"), Currency.INR),
        stop_loss=Money(Decimal("700"), Currency.INR),
    )
    dec_high_risk = evaluate_trade_proposal(
        p_high_risk, port_ok, entry_price, policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_high_risk.approved
    assert "PER_TRADE_RISK_LIMIT_EXCEEDED" in dec_high_risk.reasons

    p_conc = TradeProposal(
        proposal_id="P6",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=30,
        limit_price=Money(Decimal("1000"), Currency.INR),
        stop_loss=Money(Decimal("990"), Currency.INR),
    )
    dec_conc = evaluate_trade_proposal(
        p_conc, port_ok, entry_price, policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_conc.approved
    assert "POSITION_CONCENTRATION_EXCEEDED" in dec_conc.reasons

    dec_daily_loss = evaluate_trade_proposal(
        p_clean,
        port_ok,
        entry_price,
        policy,
        daily_pnl=Money(Decimal("-6000"), Currency.INR),
        peak_equity=Money(Decimal("100000"), Currency.INR),
    )
    assert not dec_daily_loss.approved
    assert "DAILY_LOSS_LIMIT_REACHED" in dec_daily_loss.reasons

    dec_drawdown = evaluate_trade_proposal(
        p_clean,
        port_ok,
        entry_price,
        policy,
        daily_pnl=Money(Decimal("0"), Currency.INR),
        peak_equity=Money(Decimal("120000"), Currency.INR),
    )
    assert not dec_drawdown.approved
    assert "DRAWDOWN_LIMIT_REACHED" in dec_drawdown.reasons

    inst_us = Instrument(symbol="AAPL", exchange=Exchange.NASDAQ, currency=Currency.USD)
    p_us = TradeProposal(
        proposal_id="P7",
        strategy_id="S1",
        instrument=inst_us,
        timestamp=t,
        side="BUY",
        quantity=1,
        limit_price=Money(Decimal("150"), Currency.USD),
        stop_loss=Money(Decimal("140"), Currency.USD),
    )
    dec_curr = evaluate_trade_proposal(
        p_us, port_ok, Money(Decimal("150"), Currency.USD), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_curr.approved
    assert "CURRENCY_MISMATCH" in dec_curr.reasons


def test_ledger_edge_validation_branches() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        LedgerEntry(0, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR))

    with pytest.raises(TypeError):
        LedgerEntry(1, "2024-01-01", LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR))

    naive_t = datetime(2024, 1, 1, 10, 0)
    with pytest.raises(ValueError):
        LedgerEntry(1, naive_t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR))

    with pytest.raises(TypeError):
        LedgerEntry(1, t, "DEPOSIT", Currency.INR, Money(Decimal("10"), Currency.INR))

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, "INR", Money(Decimal("10"), Currency.INR))

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Decimal("10"))

    with pytest.raises(ValueError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.USD))

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), exchange="NSE")

    with pytest.raises(ValueError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), symbol="")

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), quantity_delta="10")

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), execution_price="100")

    with pytest.raises(ValueError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), execution_price=Money(Decimal("10"), Currency.USD))

    with pytest.raises(TypeError):
        LedgerEntry(1, t, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("10"), Currency.INR), reference_id=123)

    ledger = AccountingLedger()
    with pytest.raises(TypeError):
        ledger.get_cash_balance("INR")
    with pytest.raises(TypeError):
        ledger.get_position_quantity("NSE", "TCS")
    with pytest.raises(ValueError):
        ledger.get_position_quantity(Exchange.NSE, "")
    with pytest.raises(TypeError):
        ledger.get_total_fees("INR")
    with pytest.raises(TypeError):
        ledger.get_total_deposits("INR")
    with pytest.raises(TypeError):
        ledger.get_total_withdrawals("INR")

    ledger.append(
        t,
        LedgerEventType.BUY_FILL,
        Currency.INR,
        Money(Decimal("-1000"), Currency.INR),
        exchange=Exchange.NSE,
        symbol="INFY",
        quantity_delta=10,
        execution_price=Money(Decimal("100"), Currency.INR),
    )
    assert ledger.get_position_quantity(Exchange.NSE, "INFY") == 10
    assert ledger.get_total_withdrawals(Currency.INR) == Money(Decimal("0"), Currency.INR)


def test_portfolio_engine_validation_branches() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    with pytest.raises(TypeError):
        PortfolioEngine(currency="INR")

    engine = PortfolioEngine(currency=Currency.INR)
    with pytest.raises(TypeError):
        engine.deposit("1000", t)
    with pytest.raises(CurrencyMismatchError):
        engine.deposit(Money(Decimal("1000"), Currency.USD), t)
    with pytest.raises(ValueError):
        engine.deposit(Money(Decimal("-1000"), Currency.INR), t)

    with pytest.raises(TypeError):
        engine.withdraw("1000", t)
    with pytest.raises(CurrencyMismatchError):
        engine.withdraw(Money(Decimal("1000"), Currency.USD), t)
    with pytest.raises(ValueError):
        engine.withdraw(Money(Decimal("-1000"), Currency.INR), t)

    with pytest.raises(TypeError):
        engine.apply_fill(t, "NSE", "TCS", "BUY", 10, Money(Decimal("100"), Currency.INR))
    with pytest.raises(ValueError):
        engine.apply_fill(t, Exchange.NSE, "", "BUY", 10, Money(Decimal("100"), Currency.INR))
    with pytest.raises(TypeError):
        engine.apply_fill(t, Exchange.NSE, "TCS", "BUY", 10, "100")
    with pytest.raises(ValueError):
        engine.apply_fill(t, Exchange.NSE, "TCS", "BUY", 0, Money(Decimal("100"), Currency.INR))
    with pytest.raises(ValueError):
        engine.apply_fill(t, Exchange.NSE, "TCS", "HOLD", 10, Money(Decimal("100"), Currency.INR))

    engine.deposit(Money(Decimal("10000"), Currency.INR), t)
    with pytest.raises(ValueError):
        engine.apply_fill(t, Exchange.NSE, "TCS", "SELL", 5, Money(Decimal("100"), Currency.INR), allow_short=False)

    with pytest.raises(CurrencyMismatchError):
        engine.snapshot(Currency.USD, {}, t)

    engine.apply_fill(t, Exchange.NSE, "TCS", "BUY", 10, Money(Decimal("100"), Currency.INR))
    with pytest.raises(ValueError):
        engine.snapshot(Currency.INR, {}, t)
    with pytest.raises(CurrencyMismatchError):
        engine.snapshot(Currency.INR, {(Exchange.NSE, "TCS"): Money(Decimal("110"), Currency.USD)}, t)


def test_strategy_contracts_validation_branches() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="TCS", exchange=Exchange.NSE, currency=Currency.INR)

    with pytest.raises(TypeError):
        BarContext("TCS", t, ())
    with pytest.raises(TypeError):
        BarContext(inst, "2024-01-01", ())
    with pytest.raises(ValueError):
        BarContext(inst, datetime(2024, 1, 1, 10, 0), ())
    with pytest.raises(TypeError):
        BarContext(inst, t, ("candle",))

    candle_other = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("102"),
        volume=10,
        timestamp=t - timedelta(days=1),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError):
        BarContext(inst, t, (candle_other,))

    with pytest.raises(TypeError):
        Signal("NSE", "TCS", t, SignalDirection.LONG, Decimal("0.5"))
    with pytest.raises(ValueError):
        Signal(Exchange.NSE, "", t, SignalDirection.LONG, Decimal("0.5"))
    with pytest.raises(TypeError):
        Signal(Exchange.NSE, "TCS", "2024-01-01", SignalDirection.LONG, Decimal("0.5"))
    with pytest.raises(ValueError):
        Signal(Exchange.NSE, "TCS", datetime(2024, 1, 1), SignalDirection.LONG, Decimal("0.5"))
    with pytest.raises(TypeError):
        Signal(Exchange.NSE, "TCS", t, "LONG", Decimal("0.5"))
    with pytest.raises(ValueError):
        Signal(Exchange.NSE, "TCS", t, SignalDirection.LONG, Decimal("1.5"))
    with pytest.raises(TypeError):
        Signal(Exchange.NSE, "TCS", t, SignalDirection.LONG, Decimal("0.5"), stop_loss="90")
    with pytest.raises(TypeError):
        Signal(Exchange.NSE, "TCS", t, SignalDirection.LONG, Decimal("0.5"), take_profit="110")
    with pytest.raises(TypeError):
        Signal(Exchange.NSE, "TCS", t, SignalDirection.LONG, Decimal("0.5"), rationale=123)

    with pytest.raises(ValueError):
        TradeProposal("", "S1", inst, t, "BUY", 10)
    with pytest.raises(ValueError):
        TradeProposal("P1", "", inst, t, "BUY", 10)
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", "TCS", t, "BUY", 10)
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", inst, "2024-01-01", "BUY", 10)
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, datetime(2024, 1, 1), "BUY", 10)
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "HOLD", 10)
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 0)
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, order_type="STOP")
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, order_type="LIMIT", limit_price=None)
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, order_type="LIMIT", limit_price="100")
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, order_type="LIMIT", limit_price=Money(Decimal("100"), Currency.USD))
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, stop_loss="90")
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, stop_loss=Money(Decimal("90"), Currency.USD))
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, take_profit="110")
    with pytest.raises(ValueError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, take_profit=Money(Decimal("110"), Currency.USD))
    with pytest.raises(TypeError):
        TradeProposal("P1", "S1", inst, t, "BUY", 10, signal="SIG")


def test_risk_gate_policy_and_proposal_rejection_branches() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=5)

    with pytest.raises(ValueError):
        PortfolioRiskPolicy(max_position_pct=Decimal("0"))
    with pytest.raises(TypeError):
        PortfolioRiskPolicy(require_stop_loss="true")

    policy = PortfolioRiskPolicy(
        max_position_pct=Decimal("0.50"),
        max_total_exposure_pct=Decimal("0.60"),
        require_stop_loss=True,
    )

    port = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("50000"), Currency.INR),
        holdings_value=Money(Decimal("40000"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={},
    )

    with pytest.raises(TypeError):
        evaluate_trade_proposal("P1", port, Money(Decimal("100"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR))

    p_exposure = TradeProposal(
        proposal_id="P_EXP",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=30,
        stop_loss=Money(Decimal("990"), Currency.INR),
    )
    dec_exp = evaluate_trade_proposal(
        p_exposure, port, Money(Decimal("1000"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_exp.approved
    assert "TOTAL_EXPOSURE_LIMIT_EXCEEDED" in dec_exp.reasons

    p_cash = TradeProposal(
        proposal_id="P_CASH",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="BUY",
        quantity=60,
        stop_loss=Money(Decimal("990"), Currency.INR),
    )
    dec_cash = evaluate_trade_proposal(
        p_cash, port, Money(Decimal("1000"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_cash.approved
    assert "INSUFFICIENT_CASH" in dec_cash.reasons

    p_sell_bad_stop = TradeProposal(
        proposal_id="P_SELL",
        strategy_id="S1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=5,
        stop_loss=Money(Decimal("900"), Currency.INR),
    )
    dec_sell_stop = evaluate_trade_proposal(
        p_sell_bad_stop, port, Money(Decimal("1000"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR)
    )
    assert not dec_sell_stop.approved
    assert "INVALID_STOP_LOSS_DIRECTION" in dec_sell_stop.reasons


def test_realized_pnl_preserved_across_full_exits_and_reentries() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    engine = PortfolioEngine(currency=Currency.INR)
    engine.deposit(Money(Decimal("100000"), Currency.INR), t0)
    engine.apply_fill(t0, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("100"), Currency.INR))
    t1 = t0 + timedelta(minutes=1)
    engine.apply_fill(t1, Exchange.NSE, "INFY", "SELL", 10, Money(Decimal("120"), Currency.INR))
    snap1 = engine.snapshot(Currency.INR, {}, t1)
    assert snap1.realized_pnl == Money(Decimal("200"), Currency.INR)
    assert (Exchange.NSE, "INFY") not in snap1.positions
    t2 = t1 + timedelta(minutes=1)
    engine.apply_fill(t2, Exchange.NSE, "INFY", "BUY", 5, Money(Decimal("130"), Currency.INR))
    snap2 = engine.snapshot(Currency.INR, {(Exchange.NSE, "INFY"): Money(Decimal("130"), Currency.INR)}, t2)
    assert snap2.realized_pnl == Money(Decimal("200"), Currency.INR)
    assert snap2.positions[(Exchange.NSE, "INFY")].quantity == 5
    t3 = t2 + timedelta(minutes=1)
    engine.apply_fill(t3, Exchange.NSE, "INFY", "SELL", 5, Money(Decimal("110"), Currency.INR))
    snap3 = engine.snapshot(Currency.INR, {}, t3)
    assert snap3.realized_pnl == Money(Decimal("100"), Currency.INR)
    assert (Exchange.NSE, "INFY") not in snap3.positions


def test_prepopulated_ledger_replay_in_engine_init() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    ledger = AccountingLedger()
    ledger.append(t0, LedgerEventType.DEPOSIT, Currency.INR, Money(Decimal("50000"), Currency.INR))
    t1 = t0 + timedelta(minutes=5)
    ledger.append(t1, LedgerEventType.BUY_FILL, Currency.INR, Money(Decimal("-1000"), Currency.INR), exchange=Exchange.NSE, symbol="TCS", quantity_delta=10, execution_price=Money(Decimal("100"), Currency.INR))
    t2 = t1 + timedelta(minutes=5)
    ledger.append(t2, LedgerEventType.FEE_CHARGE, Currency.INR, Money(Decimal("-20"), Currency.INR), exchange=Exchange.NSE, symbol="TCS")
    t3 = t2 + timedelta(minutes=5)
    ledger.append(t3, LedgerEventType.SELL_FILL, Currency.INR, Money(Decimal("600"), Currency.INR), exchange=Exchange.NSE, symbol="TCS", quantity_delta=-5, execution_price=Money(Decimal("120"), Currency.INR))
    t4 = t3 + timedelta(minutes=5)
    ledger.append(t4, LedgerEventType.DIVIDEND_CREDIT, Currency.INR, Money(Decimal("50"), Currency.INR), exchange=Exchange.NSE, symbol="TCS")

    engine = PortfolioEngine(currency=Currency.INR, ledger=ledger)
    snap = engine.snapshot(Currency.INR, {(Exchange.NSE, "TCS"): Money(Decimal("120"), Currency.INR)}, t4)
    expected_cash = Decimal("50000") - Decimal("1000") - Decimal("20") + Decimal("600") + Decimal("50")
    assert snap.cash == Money(expected_cash, Currency.INR)
    assert snap.positions[(Exchange.NSE, "TCS")].quantity == 5
    assert snap.positions[(Exchange.NSE, "TCS")].average_cost == Money(Decimal("100"), Currency.INR)
    assert snap.realized_pnl == Money(Decimal("100"), Currency.INR)


def test_short_selling_boundary_and_signed_holdings() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    engine = PortfolioEngine(currency=Currency.INR)
    engine.deposit(Money(Decimal("20000"), Currency.INR), t0)
    with pytest.raises(InsufficientPositionError):
        engine.apply_fill(t0, Exchange.NSE, "INFY", "SELL", 10, Money(Decimal("100"), Currency.INR), allow_short=False)

    engine.apply_fill(t0, Exchange.NSE, "INFY", "SELL", 10, Money(Decimal("100"), Currency.INR), allow_short=True)
    snap1 = engine.snapshot(Currency.INR, {(Exchange.NSE, "INFY"): Money(Decimal("95"), Currency.INR)}, t0)
    assert snap1.positions[(Exchange.NSE, "INFY")].quantity == -10
    assert snap1.holdings_value == Money(Decimal("-950"), Currency.INR)
    assert snap1.unrealized_pnl == Money(Decimal("50"), Currency.INR)

    t1 = t0 + timedelta(minutes=1)
    engine.apply_fill(t1, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("90"), Currency.INR))
    snap2 = engine.snapshot(Currency.INR, {}, t1)
    assert (Exchange.NSE, "INFY") not in snap2.positions
    assert snap2.realized_pnl == Money(Decimal("100"), Currency.INR)
    assert snap2.holdings_value == Money(Decimal("0"), Currency.INR)


def test_sell_fee_overdraft_prevention() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)

    class OverdraftFeeModel(FeeModel):
        def calculate_fees(self, exchange: Exchange, symbol: str, side: str, quantity: int, price: Money) -> Money:
            return Money(Decimal("1500"), Currency.INR)

    engine = PortfolioEngine(currency=Currency.INR)
    engine.deposit(Money(Decimal("1000"), Currency.INR), t0)
    engine.apply_fill(t0, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("100"), Currency.INR))
    assert engine.snapshot(Currency.INR, {(Exchange.NSE, "INFY"): Money(Decimal("100"), Currency.INR)}, t0).cash == Money(Decimal("0"), Currency.INR)
    engine.fee_model = OverdraftFeeModel()

    with pytest.raises(InsufficientFundsError):
        engine.apply_fill(
            t0 + timedelta(minutes=1),
            Exchange.NSE,
            "INFY",
            "SELL",
            10,
            Money(Decimal("100"), Currency.INR),
        )


def test_dividend_api_and_accounting_conservation() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    engine = PortfolioEngine(currency=Currency.INR)
    engine.deposit(Money(Decimal("10000"), Currency.INR), t0)
    t1 = t0 + timedelta(hours=1)
    engine.apply_fill(t1, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("100"), Currency.INR))
    t2 = t1 + timedelta(hours=1)
    engine.apply_dividend(t2, Exchange.NSE, "INFY", Money(Decimal("50"), Currency.INR), reference_id="DIV-1")
    t3 = t2 + timedelta(hours=1)
    engine.apply_fill(t3, Exchange.NSE, "INFY", "SELL", 5, Money(Decimal("120"), Currency.INR))

    ledger = engine.ledger
    dep = ledger.get_total_deposits(Currency.INR).amount
    wdr = ledger.get_total_withdrawals(Currency.INR).amount
    fees = ledger.get_total_fees(Currency.INR).amount
    divs = ledger.get_total_dividends(Currency.INR).amount

    snap = engine.snapshot(Currency.INR, {(Exchange.NSE, "INFY"): Money(Decimal("110"), Currency.INR)}, t3)
    cash = snap.cash.amount
    realized = snap.realized_pnl.amount
    pos = snap.positions[(Exchange.NSE, "INFY")]
    open_cost = pos.average_cost.amount * Decimal(pos.quantity)

    assert dep - wdr + realized + divs - fees == cash + open_cost
    assert divs == Decimal("50")
    assert snap.cash.amount == Decimal("9650")


def test_true_tick_grid_rounding_and_slippage_direction() -> None:
    model = BasisPointsSlippageModel(basis_points=Decimal("0"))
    buy_price = model.calculate_slippage(Money(Decimal("100.02"), Currency.INR), "BUY", Decimal("0.05"))
    assert buy_price.amount == Decimal("100.05")
    sell_price = model.calculate_slippage(Money(Decimal("100.02"), Currency.INR), "SELL", Decimal("0.05"))
    assert sell_price.amount == Decimal("100.00")

    model_bps = BasisPointsSlippageModel(basis_points=Decimal("10"))
    buy_bps = model.calculate_slippage(Money(Decimal("100.00"), Currency.INR), "BUY", Decimal("0.05"))
    assert buy_bps.amount == Decimal("100.00")
    buy_bps_shifted = model_bps.calculate_slippage(Money(Decimal("100.00"), Currency.INR), "BUY", Decimal("0.05"))
    assert buy_bps_shifted.amount == Decimal("100.10")
    sell_bps_shifted = model_bps.calculate_slippage(Money(Decimal("100.00"), Currency.INR), "SELL", Decimal("0.05"))
    assert sell_bps_shifted.amount == Decimal("99.90")

    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    raw_candle = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.D1,
        open=Decimal("100.02"),
        high=Decimal("105.03"),
        low=Decimal("95.01"),
        close=Decimal("101.07"),
        volume=1000,
        timestamp=t,
        source="test",
        retrieval_timestamp=t,
    )
    action = CorporateAction(
        exchange=Exchange.NSE,
        symbol="INFY",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2024, 1, 2),
        adjustment_factor=Decimal("0.5"),
    )
    adjusted = adjust_candles_for_corporate_actions((raw_candle,), (action,), tick_size=Decimal("0.05"))
    assert adjusted[0].open == Decimal("50.00")
    assert adjusted[0].high == Decimal("52.50")
    assert adjusted[0].low == Decimal("47.50")
    assert adjusted[0].close == Decimal("50.55")


def test_cost_model_validation_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        BasisPointsSlippageModel(basis_points=Decimal("-5"))
    model = BasisPointsSlippageModel()
    with pytest.raises(ValueError):
        model.calculate_slippage(Money(Decimal("100"), Currency.INR), "BUY", Decimal("0"))
    with pytest.raises(ValueError):
        IndiaEquityFeeModel(brokerage_rate=Decimal("-0.01"))
    with pytest.raises(ValueError):
        IndiaEquityFeeModel(brokerage_cap=Money(Decimal("-10"), Currency.INR))
    with pytest.raises(CurrencyMismatchError):
        IndiaEquityFeeModel(brokerage_cap=Money(Decimal("20"), Currency.USD))

    fee_model = IndiaEquityFeeModel()
    with pytest.raises(ValueError):
        fee_model.calculate_fees(Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("0"), Currency.INR))
    with pytest.raises(ValueError):
        fee_model.calculate_fees(Exchange.NSE, "INFY", "BUY", 0, Money(Decimal("100"), Currency.INR))
    with pytest.raises(ValueError):
        fee_model.calculate_fees(Exchange.NSE, "INFY", "HOLD", 10, Money(Decimal("100"), Currency.INR))


def test_position_aware_sell_gate_and_stop_loss_waiver() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=5)
    policy = PortfolioRiskPolicy(require_stop_loss=True)
    port_empty = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("100000"), Currency.INR),
        holdings_value=Money(Decimal("0"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={},
    )
    p_short = TradeProposal("P1", "S1", inst, t, "SELL", 5)
    dec_short = evaluate_trade_proposal(p_short, port_empty, Money(Decimal("100"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR))
    assert not dec_short.approved
    assert "UNAUTHORIZED_SHORT" in dec_short.reasons

    pos = Position(exchange=Exchange.NSE, symbol="INFY", currency=Currency.INR, quantity=10, average_cost=Money(Decimal("100"), Currency.INR), realized_pnl=Money(Decimal("0"), Currency.INR))
    port_holding = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("99000"), Currency.INR),
        holdings_value=Money(Decimal("1000"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={(Exchange.NSE, "INFY"): pos},
    )
    p_oversell = TradeProposal("P2", "S1", inst, t, "SELL", 15)
    dec_oversell = evaluate_trade_proposal(p_oversell, port_holding, Money(Decimal("100"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR))
    assert not dec_oversell.approved
    assert "INSUFFICIENT_POSITION" in dec_oversell.reasons

    p_exit_no_stop = TradeProposal("P3", "S1", inst, t, "SELL", 10)
    dec_exit = evaluate_trade_proposal(p_exit_no_stop, port_holding, Money(Decimal("100"), Currency.INR), policy, Money(Decimal("0"), Currency.INR), Money(Decimal("100000"), Currency.INR))
    assert dec_exit.approved
    assert "MISSING_STOP_LOSS" not in dec_exit.reasons


def test_kill_switch_allows_risk_reducing_sell_exits() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=5)
    policy = PortfolioRiskPolicy(max_daily_loss_pct=Decimal("0.02"), max_drawdown_pct=Decimal("0.05"), require_stop_loss=False)
    pos = Position(exchange=Exchange.NSE, symbol="INFY", currency=Currency.INR, quantity=10, average_cost=Money(Decimal("100"), Currency.INR), realized_pnl=Money(Decimal("0"), Currency.INR))
    port = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("50000"), Currency.INR),
        holdings_value=Money(Decimal("1000"), Currency.INR),
        total_equity=Money(Decimal("80000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={(Exchange.NSE, "INFY"): pos},
    )
    daily_loss = Money(Decimal("-5000"), Currency.INR)
    peak = Money(Decimal("100000"), Currency.INR)

    p_buy = TradeProposal("P_BUY", "S1", inst, t, "BUY", 5)
    dec_buy = evaluate_trade_proposal(p_buy, port, Money(Decimal("100"), Currency.INR), policy, daily_loss, peak)
    assert not dec_buy.approved
    assert "DAILY_LOSS_LIMIT_REACHED" in dec_buy.reasons
    assert "DRAWDOWN_LIMIT_REACHED" in dec_buy.reasons

    p_sell = TradeProposal("P_SELL", "S1", inst, t, "SELL", 10)
    dec_sell = evaluate_trade_proposal(p_sell, port, Money(Decimal("100"), Currency.INR), policy, daily_loss, peak)
    assert dec_sell.approved
    assert "DAILY_LOSS_LIMIT_REACHED" not in dec_sell.reasons
    assert "DRAWDOWN_LIMIT_REACHED" not in dec_sell.reasons


def test_risk_gate_input_validations_and_inverted_directions() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=5)
    policy_no_sl = PortfolioRiskPolicy(require_stop_loss=False)
    port = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("50000"), Currency.INR),
        holdings_value=Money(Decimal("0"), Currency.INR),
        total_equity=Money(Decimal("50000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={},
    )
    zero_peak = Money(Decimal("0"), Currency.INR)
    valid_peak = Money(Decimal("50000"), Currency.INR)
    zero_pnl = Money(Decimal("0"), Currency.INR)

    p1 = TradeProposal("P1", "S1", inst, t, "BUY", 5)
    dec1 = evaluate_trade_proposal(p1, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, zero_peak)
    assert not dec1.approved
    assert "INVALID_PEAK_EQUITY" in dec1.reasons

    dec2 = evaluate_trade_proposal(p1, port, Money(Decimal("0"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec2.approved
    assert "INVALID_ENTRY_PRICE" in dec2.reasons

    p_inverted_sl = TradeProposal("P3", "S1", inst, t, "BUY", 5, stop_loss=Money(Decimal("110"), Currency.INR))
    dec3 = evaluate_trade_proposal(p_inverted_sl, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec3.approved
    assert "INVALID_STOP_LOSS_DIRECTION" in dec3.reasons

    p_zero_sl = TradeProposal("P4", "S1", inst, t, "BUY", 5, stop_loss=Money(Decimal("0"), Currency.INR))
    dec4 = evaluate_trade_proposal(p_zero_sl, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec4.approved
    assert "INVALID_STOP_LOSS" in dec4.reasons

    p_zero_tp = TradeProposal("P5", "S1", inst, t, "BUY", 5, take_profit=Money(Decimal("0"), Currency.INR))
    dec5 = evaluate_trade_proposal(p_zero_tp, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec5.approved
    assert "INVALID_TAKE_PROFIT" in dec5.reasons

    p_inverted_tp = TradeProposal("P6", "S1", inst, t, "BUY", 5, take_profit=Money(Decimal("90"), Currency.INR))
    dec6 = evaluate_trade_proposal(p_inverted_tp, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec6.approved
    assert "INVALID_TAKE_PROFIT_DIRECTION" in dec6.reasons

    p_zero_limit = TradeProposal("P7", "S1", inst, t, "BUY", 5, order_type="LIMIT", limit_price=Money(Decimal("0"), Currency.INR))
    dec7 = evaluate_trade_proposal(p_zero_limit, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec7.approved
    assert "INVALID_LIMIT_PRICE" in dec7.reasons

    p_inverted_limit = TradeProposal("P8", "S1", inst, t, "BUY", 5, order_type="LIMIT", limit_price=Money(Decimal("110"), Currency.INR))
    dec8 = evaluate_trade_proposal(p_inverted_limit, port, Money(Decimal("100"), Currency.INR), policy_no_sl, zero_pnl, valid_peak)
    assert not dec8.approved
    assert "INVALID_LIMIT_PRICE_DIRECTION" in dec8.reasons


def test_exact_max_allowed_quantity_computation() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=5)
    policy = PortfolioRiskPolicy(
        max_position_pct=Decimal("0.50"),
        max_total_exposure_pct=Decimal("0.80"),
        max_risk_per_trade_pct=Decimal("0.10"),
        require_stop_loss=True,
    )
    port = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("2500"), Currency.INR),
        holdings_value=Money(Decimal("0"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={},
    )
    p_buy_excess = TradeProposal(
        "P1",
        "S1",
        inst,
        t,
        "BUY",
        100,
        stop_loss=Money(Decimal("90"), Currency.INR),
    )
    dec_buy = evaluate_trade_proposal(
        p_buy_excess,
        port,
        Money(Decimal("100"), Currency.INR),
        policy,
        Money(Decimal("0"), Currency.INR),
        Money(Decimal("100000"), Currency.INR),
    )
    assert not dec_buy.approved
    assert "INSUFFICIENT_CASH" in dec_buy.reasons
    assert dec_buy.max_allowed_quantity == 25

    pos = Position(exchange=Exchange.NSE, symbol="INFY", currency=Currency.INR, quantity=35, average_cost=Money(Decimal("100"), Currency.INR), realized_pnl=Money(Decimal("0"), Currency.INR))
    port_pos = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("50000"), Currency.INR),
        holdings_value=Money(Decimal("3500"), Currency.INR),
        total_equity=Money(Decimal("100000"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={(Exchange.NSE, "INFY"): pos},
    )
    p_sell_excess = TradeProposal("P2", "S1", inst, t, "SELL", 100)
    dec_sell = evaluate_trade_proposal(
        p_sell_excess,
        port_pos,
        Money(Decimal("100"), Currency.INR),
        policy,
        Money(Decimal("0"), Currency.INR),
        Money(Decimal("100000"), Currency.INR),
    )
    assert not dec_sell.approved
    assert "INSUFFICIENT_POSITION" in dec_sell.reasons
    assert dec_sell.max_allowed_quantity == 35


def test_bar_context_m7_invariant_guards() -> None:
    t = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR)

    c1 = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("102"),
        volume=100,
        timestamp=t - timedelta(minutes=10),
        source="test",
        retrieval_timestamp=t,
    )
    c2_unsorted = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("102"),
        high=Decimal("106"),
        low=Decimal("101"),
        close=Decimal("104"),
        volume=150,
        timestamp=t - timedelta(minutes=15),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="strictly increasing timestamps"):
        BarContext(inst, t, (c1, c2_unsorted))

    c2_duplicate = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("102"),
        high=Decimal("106"),
        low=Decimal("101"),
        close=Decimal("104"),
        volume=150,
        timestamp=t - timedelta(minutes=10),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="strictly increasing timestamps"):
        BarContext(inst, t, (c1, c2_duplicate))

    c2_diff_interval = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M15,
        open=Decimal("102"),
        high=Decimal("106"),
        low=Decimal("101"),
        close=Decimal("104"),
        volume=150,
        timestamp=t - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="Inconsistent interval in bars"):
        BarContext(inst, t, (c1, c2_diff_interval))

    c_zero_open = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("0"),
        high=Decimal("105"),
        low=Decimal("0"),
        close=Decimal("102"),
        volume=100,
        timestamp=t - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="OHLC prices must be strictly positive"):
        BarContext(inst, t, (c_zero_open,))

    c_bad_high = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("100"),
        high=Decimal("95"),
        low=Decimal("90"),
        close=Decimal("98"),
        volume=100,
        timestamp=t - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="high must be >= max"):
        BarContext(inst, t, (c_bad_high,))

    c_bad_low = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("101"),
        close=Decimal("98"),
        volume=100,
        timestamp=t - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="low <= min"):
        BarContext(inst, t, (c_bad_low,))

    c_neg_vol = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("102"),
        volume=-10,
        timestamp=t - timedelta(minutes=5),
        source="test",
        retrieval_timestamp=t,
    )
    with pytest.raises(ValueError, match="volume must be non-negative"):
        BarContext(inst, t, (c_neg_vol,))


def test_rsi_m8_flat_prices_neutral_50() -> None:
    t0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    candles = [
        Candle(
            symbol="INFY",
            exchange=Exchange.NSE,
            interval=CandleInterval.M5,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=50,
            timestamp=t0 + timedelta(minutes=5 * i),
            source="test",
            retrieval_timestamp=t0 + timedelta(minutes=5 * i + 5),
        )
        for i in range(25)
    ]
    res = rsi(candles, 14)
    assert res is not None
    assert res == Decimal("50")


def test_r1_slippage_and_fill_price_positive_rejection() -> None:
    model = BasisPointsSlippageModel(Decimal("5"))
    with pytest.raises(ValueError, match="Price must be strictly positive"):
        model.calculate_slippage(Money(Decimal("0"), Currency.INR), "BUY", Decimal("0.05"))
    with pytest.raises(ValueError, match="Price must be strictly positive"):
        model.calculate_slippage(Money(Decimal("-10.00"), Currency.INR), "SELL", Decimal("0.05"))

    engine = PortfolioEngine(Currency.INR)
    t = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    engine.deposit(Money(Decimal("10000"), Currency.INR), t)
    with pytest.raises(ValueError, match="Fill price must be strictly positive"):
        engine.apply_fill(t, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("0"), Currency.INR))
    with pytest.raises(ValueError, match="Fill price must be strictly positive"):
        engine.apply_fill(t, Exchange.NSE, "INFY", "BUY", 10, Money(Decimal("-50"), Currency.INR))


def test_r2_exact_zero_drift_conservation_residual() -> None:
    engine = PortfolioEngine(Currency.INR)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=UTC)
    engine.deposit(Money(Decimal("1000000.00"), Currency.INR), t0)

    t1 = t0 + timedelta(minutes=5)
    engine.apply_fill(t1, Exchange.NSE, "INFY", "BUY", 100, Money(Decimal("1000.00"), Currency.INR))
    t2 = t1 + timedelta(minutes=5)
    engine.apply_fill(t2, Exchange.NSE, "INFY", "BUY", 50, Money(Decimal("1050.00"), Currency.INR))
    t3 = t2 + timedelta(minutes=5)
    engine.apply_fill(t3, Exchange.NSE, "INFY", "BUY", 75, Money(Decimal("980.00"), Currency.INR))

    t4 = t3 + timedelta(minutes=5)
    engine.apply_fill(t4, Exchange.NSE, "INFY", "SELL", 40, Money(Decimal("1020.00"), Currency.INR))
    t5 = t4 + timedelta(minutes=5)
    engine.apply_fill(t5, Exchange.NSE, "INFY", "SELL", 80, Money(Decimal("1040.00"), Currency.INR))
    t6 = t5 + timedelta(minutes=5)
    engine.apply_fill(t6, Exchange.NSE, "INFY", "SELL", 105, Money(Decimal("1010.00"), Currency.INR))

    assert (Exchange.NSE, "INFY") not in engine._total_cost_basis
    assert (Exchange.NSE, "INFY") not in engine._positions

    t7 = t6 + timedelta(minutes=5)
    engine.apply_fill(t7, Exchange.NSE, "TCS", "BUY", 200, Money(Decimal("500.00"), Currency.INR))
    t8 = t7 + timedelta(minutes=5)
    engine.apply_fill(t8, Exchange.NSE, "TCS", "SELL", 75, Money(Decimal("520.00"), Currency.INR))

    t9 = t8 + timedelta(minutes=5)
    engine.apply_dividend(t9, Exchange.NSE, "TCS", Money(Decimal("250.00"), Currency.INR))
    t10 = t9 + timedelta(minutes=5)
    engine.withdraw(Money(Decimal("50000.00"), Currency.INR), t10)

    cash = engine.ledger.get_cash_balance(Currency.INR).amount
    deposits = engine.ledger.get_total_deposits(Currency.INR).amount
    withdrawals = engine.ledger.get_total_withdrawals(Currency.INR).amount
    realized_pnl = sum(engine._realized_pnl_by_symbol.values(), Decimal("0"))
    dividends = engine.ledger.get_total_dividends(Currency.INR).amount
    fees = engine.ledger.get_total_fees(Currency.INR).amount
    open_basis = sum(engine._total_cost_basis.values(), Decimal("0"))

    residual = (deposits - withdrawals + realized_pnl + dividends - fees) - (cash + open_basis)
    assert residual == Decimal("0")


def test_r3_slippage_sell_below_tick_size_rejection() -> None:
    model = BasisPointsSlippageModel(Decimal("5000"))
    price = Money(Decimal("0.02"), Currency.INR)
    with pytest.raises(ValueError, match="falls below minimum tick size"):
        model.calculate_slippage(price, "SELL", Decimal("0.05"))


def test_r4_proposal_gate_long_exit_stop_loss_take_profit_direction() -> None:
    t = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=1)
    pos = Position(
        exchange=Exchange.NSE,
        symbol="INFY",
        currency=Currency.INR,
        quantity=100,
        average_cost=Money(Decimal("1500.00"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
    )
    portfolio = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("100000.00"), Currency.INR),
        holdings_value=Money(Decimal("150000.00"), Currency.INR),
        total_equity=Money(Decimal("250000.00"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={(Exchange.NSE, "INFY"): pos},
    )
    policy = PortfolioRiskPolicy()
    entry = Money(Decimal("1500.00"), Currency.INR)
    pnl = Money(Decimal("0"), Currency.INR)
    peak = Money(Decimal("250000.00"), Currency.INR)

    prop_valid = TradeProposal(
        proposal_id="p1",
        strategy_id="s1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=50,
        stop_loss=Money(Decimal("1400.00"), Currency.INR),
        take_profit=Money(Decimal("1600.00"), Currency.INR),
    )
    dec_valid = evaluate_trade_proposal(prop_valid, portfolio, entry, policy, pnl, peak)
    assert dec_valid.approved is True

    prop_bad_sl = TradeProposal(
        proposal_id="p2",
        strategy_id="s1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=50,
        stop_loss=Money(Decimal("1550.00"), Currency.INR),
    )
    dec_bad_sl = evaluate_trade_proposal(prop_bad_sl, portfolio, entry, policy, pnl, peak)
    assert dec_bad_sl.approved is False
    assert "INVALID_STOP_LOSS_DIRECTION" in dec_bad_sl.reasons

    prop_bad_tp = TradeProposal(
        proposal_id="p3",
        strategy_id="s1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=50,
        take_profit=Money(Decimal("1450.00"), Currency.INR),
    )
    dec_bad_tp = evaluate_trade_proposal(prop_bad_tp, portfolio, entry, policy, pnl, peak)
    assert dec_bad_tp.approved is False
    assert "INVALID_TAKE_PROFIT_DIRECTION" in dec_bad_tp.reasons


def test_r7_bar_context_overlapping_bars_rejection() -> None:
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR)
    t0 = datetime(2026, 11, 2, 9, 15, tzinfo=UTC)
    c1 = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("102"),
        volume=100,
        timestamp=t0,
        source="test",
        retrieval_timestamp=t0 + timedelta(minutes=5),
    )
    c2_overlap = Candle(
        symbol="INFY",
        exchange=Exchange.NSE,
        interval=CandleInterval.M5,
        open=Decimal("102"),
        high=Decimal("106"),
        low=Decimal("100"),
        close=Decimal("104"),
        volume=100,
        timestamp=t0 + timedelta(minutes=2),
        source="test",
        retrieval_timestamp=t0 + timedelta(minutes=7),
    )
    dec_time = t0 + timedelta(minutes=30)
    with pytest.raises(ValueError, match="Overlapping bars"):
        BarContext(inst, dec_time, (c1, c2_overlap))


def test_r8_proposal_gate_odd_lot_full_exit_allowed() -> None:
    t = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    inst = Instrument(symbol="INFY", exchange=Exchange.NSE, currency=Currency.INR, lot_size=100)
    pos = Position(
        exchange=Exchange.NSE,
        symbol="INFY",
        currency=Currency.INR,
        quantity=37,
        average_cost=Money(Decimal("1500.00"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
    )
    portfolio = PortfolioSnapshot(
        timestamp=t,
        currency=Currency.INR,
        cash=Money(Decimal("100000.00"), Currency.INR),
        holdings_value=Money(Decimal("55500.00"), Currency.INR),
        total_equity=Money(Decimal("155500.00"), Currency.INR),
        realized_pnl=Money(Decimal("0"), Currency.INR),
        unrealized_pnl=Money(Decimal("0"), Currency.INR),
        positions={(Exchange.NSE, "INFY"): pos},
    )
    policy = PortfolioRiskPolicy(require_stop_loss=False)
    entry = Money(Decimal("1500.00"), Currency.INR)
    pnl = Money(Decimal("0"), Currency.INR)
    peak = Money(Decimal("155500.00"), Currency.INR)

    prop_full = TradeProposal(
        proposal_id="p_full",
        strategy_id="s1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=37,
    )
    dec_full = evaluate_trade_proposal(prop_full, portfolio, entry, policy, pnl, peak)
    assert dec_full.approved is True
    assert dec_full.max_allowed_quantity == 37

    prop_partial = TradeProposal(
        proposal_id="p_part",
        strategy_id="s1",
        instrument=inst,
        timestamp=t,
        side="SELL",
        quantity=30,
    )
    dec_part = evaluate_trade_proposal(prop_partial, portfolio, entry, policy, pnl, peak)
    assert dec_part.approved is False
    assert "LOT_SIZE_MISMATCH" in dec_part.reasons


