"""
Tests for macro regime classification and sector constraints.
"""

import pandas as pd

from strategies.macro_filter import BEAR_MARKET, BULL_MARKET, MacroRegime, classify_macro_regime, get_market_regime, get_regime_strategy_filter
from strategies.sector import apply_sector_constraint, get_sector


def test_classify_macro_regime_risk_on():
    regime, desc = classify_macro_regime(vix=15, yield_curve=0.5, unemployment_rate=3.5)
    assert regime == MacroRegime.RISK_ON
    assert regime.name in desc


def test_classify_macro_regime_risk_off():
    regime, desc = classify_macro_regime(vix=35, yield_curve=-0.5, unemployment_rate=7.0)
    assert regime == MacroRegime.RISK_OFF
    assert regime.name in desc


def test_classify_macro_regime_neutral():
    regime, desc = classify_macro_regime(vix=25, yield_curve=0.1, unemployment_rate=5.0)
    assert regime == MacroRegime.NEUTRAL
    assert regime.name in desc


def test_get_regime_strategy_filter_keys():
    info = get_regime_strategy_filter(MacroRegime.RISK_OFF)
    assert set(info.keys()) == {
        "enabled_categories",
        "score_multiplier",
        "max_positions",
        "description",
    }
    assert info["max_positions"] == 3


def test_get_market_regime_uses_spy_200sma_filter():
    bear_df = pd.DataFrame({"close": [100.0] * 199 + [90.0]})
    bull_df = pd.DataFrame({"close": [100.0] * 199 + [110.0]})

    assert get_market_regime(bear_df) == BEAR_MARKET
    assert get_market_regime(bull_df) == BULL_MARKET


def test_apply_sector_constraint_limits_per_sector():
    recommendations = [
        {"symbol": "AAPL", "total_score": 5.0},
        {"symbol": "MSFT", "total_score": 4.8},
        {"symbol": "JPM", "total_score": 4.5},
        {"symbol": "XOM", "total_score": 4.2},
    ]

    result = apply_sector_constraint(recommendations, max_per_sector=1, total_n=3)
    sectors = [get_sector(item["symbol"]) for item in result]

    assert len(result) == 3
    for sector in set(sectors):
        assert sectors.count(sector) <= 1


def test_get_sector_unknown():
    assert get_sector("UNKNOWN") == "Unknown"
