"""
Tests for position sizing and risk management utilities.
"""

from datetime import date, timedelta

from core.position_sizing import calc_atr_position_size, calc_equal_risk_weights, calculate_position_size
from core.risk_manager import HOLD, SELL, RiskManager, check_stop_loss_and_take_profit


def test_calc_atr_position_size_guardrails():
    assert calc_atr_position_size(atr=0, current_price=100, total_equity=100_000) == 0
    assert calc_atr_position_size(atr=2, current_price=0, total_equity=100_000) == 0
    assert calc_atr_position_size(atr=2, current_price=100, total_equity=0) == 0


def test_calc_atr_position_size_weight_cap():
    shares = calc_atr_position_size(
        atr=2.5,
        current_price=150.0,
        total_equity=100_000,
        risk_per_trade=0.02,
        atr_multiplier=2.0,
    )
    assert shares == 133


def test_calc_equal_risk_weights_caps_max_weight():
    weights = calc_equal_risk_weights(
        symbols=["AAPL", "MSFT"],
        atr_values={"AAPL": 2.0, "MSFT": 4.0},
        prices={"AAPL": 100.0, "MSFT": 200.0},
        total_equity=100_000,
        max_weight=0.20,
    )
    assert weights["AAPL"] == 200
    assert weights["MSFT"] == 100


def test_calculate_position_size_caps_and_halves_in_bear_market():
    result = calculate_position_size(total_equity=100_000, is_bear_market=True)
    assert result["max_position_value"] == 12_500.0
    assert result["allocation_pct"] == 0.125
    assert result["capped_by_max_weight"] is False


def test_check_stop_loss_and_take_profit_returns_sell():
    assert check_stop_loss_and_take_profit(100.0, 92.0, 100.0) == SELL
    assert check_stop_loss_and_take_profit(100.0, 109.25, 115.0) == SELL
    assert check_stop_loss_and_take_profit(100.0, 103.0, 110.0) == HOLD


def test_risk_manager_trailing_stop():
    rm = RiskManager(max_hold_days=30, atr_multiplier=2.0)
    rm.add_position("AAPL", entry_price=150.0, entry_date=date(2026, 1, 1), atr=3.0)

    # Price rises -> trailing stop moves up
    rm.check_all({"AAPL": 160.0}, {"AAPL": 3.0}, date(2026, 1, 5))

    # Price dips below trailing stop -> should exit
    results = rm.check_all({"AAPL": 153.0}, {"AAPL": 3.0}, date(2026, 1, 6))
    should_exit, reason = results["AAPL"]
    assert should_exit is True
    assert "Trailing Stop" in reason


def test_risk_manager_time_stop():
    rm = RiskManager(max_hold_days=30, atr_multiplier=2.0)
    entry_date = date(2026, 1, 1)
    rm.add_position("AAPL", entry_price=150.0, entry_date=entry_date, atr=3.0)

    late_date = entry_date + timedelta(days=31)
    results = rm.check_all({"AAPL": 146.0}, {"AAPL": 3.0}, late_date)
    should_exit, reason = results["AAPL"]
    assert should_exit is True
    assert "Time Stop" in reason
