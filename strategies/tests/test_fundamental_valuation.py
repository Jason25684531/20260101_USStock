from strategies.fundamental import calculate_valuation_targets


def test_calculate_valuation_targets_for_undervalued_stock():
    result = calculate_valuation_targets(current_price=80.0, eps_ttm=10.0)
    assert result["current_pe"] == 8.0
    assert result["fair_price"] == 150.0
    assert result["buy_price"] == 120.0
    assert result["sell_price"] == 180.0
    assert result["valuation_status"] == "UNDERVALUED"
    assert result["valuation_supported"] is True


def test_calculate_valuation_targets_handles_missing_eps():
    result = calculate_valuation_targets(current_price=100.0, eps_ttm=None)
    assert result["valuation_status"] == "FAIR"
    assert result["valuation_supported"] is False
    assert result["buy_price"] is None