from decimal import Decimal

from agentic_trading.risk_engine import OrderProposal, Side, evaluate_order


def proposal(**overrides):
    values = dict(
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=2,
        limit_price=Decimal("100"),
        available_cash=Decimal("10000"),
        portfolio_equity=Decimal("10000"),
        current_position_quantity=0,
    )
    values.update(overrides)
    return OrderProposal(**values)


def test_approves_order_within_all_limits():
    result = evaluate_order(proposal())
    assert result.approved is True
    assert result.reason_codes == ()
    assert result.order_notional == Decimal("200")


def test_rejects_sell_in_initial_policy():
    result = evaluate_order(proposal(side=Side.SELL))
    assert result.approved is False
    assert "SELL_DISABLED_IN_INITIAL_POLICY" in result.reason_codes


def test_rejects_order_above_position_limit():
    result = evaluate_order(proposal(quantity=6))
    assert result.approved is False
    assert "POSITION_NOTIONAL_LIMIT_EXCEEDED" in result.reason_codes


def test_rejects_insufficient_cash():
    result = evaluate_order(proposal(available_cash=Decimal("100")))
    assert result.approved is False
    assert "INSUFFICIENT_CASH" in result.reason_codes


def test_rejects_when_daily_loss_limit_reached():
    result = evaluate_order(proposal(daily_realized_pnl=Decimal("-200")))
    assert result.approved is False
    assert "DAILY_LOSS_LIMIT_REACHED" in result.reason_codes


def test_rejects_non_finite_price():
    result = evaluate_order(proposal(limit_price=Decimal("NaN")))
    assert result.approved is False
    assert result.reason_codes == ("INVALID_NUMERIC_INPUT",)


def test_rejects_zero_quantity():
    result = evaluate_order(proposal(quantity=0))
    assert result.approved is False
    assert "INVALID_QUANTITY" in result.reason_codes


def test_rejects_order_that_pushes_total_position_over_limit():
    result = evaluate_order(proposal(quantity=2, current_position_quantity=4))
    assert result.approved is False
    assert "POSITION_NOTIONAL_LIMIT_EXCEEDED" in result.reason_codes


def test_rejects_invalid_existing_position_type():
    result = evaluate_order(proposal(current_position_quantity=True))
    assert result.approved is False
    assert "INVALID_EXISTING_POSITION" in result.reason_codes
