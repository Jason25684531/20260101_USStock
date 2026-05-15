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


def test_calculate_valuation_targets_keeps_classic_policy_defaults():
    result = calculate_valuation_targets(current_price=150.0, eps_ttm=10.0)
    assert result["fair_pe"] == 15.0
    assert result["safety_margin"] == 0.2
    assert result["premium"] == 0.2
    assert result["valuation_status"] == "FAIR"


def test_growth_aware_policy_marks_premium_growth_for_high_growth_symbols():
    from policies.valuation import GrowthAwarePolicy

    policy = GrowthAwarePolicy()
    result = policy.evaluate(
        current_price=115.0,
        eps_ttm=5.0,
        revenue_growth_yoy=0.6,
    )

    assert result["valuation_supported"] is True
    assert result["valuation_status"] == "PREMIUM_GROWTH"
    assert result["fair_pe"] > 15.0
    assert result["buy_price"] is not None
