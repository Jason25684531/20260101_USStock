"""
測試: Strategy Registry 核心機制
"""
import pytest
import pandas as pd
import numpy as np


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_df():
    """產生 300 天的模擬 OHLCV 資料"""
    np.random.seed(42)
    dates = pd.bdate_range("2024-01-01", periods=300)
    close = 100 + np.cumsum(np.random.randn(300) * 0.5)
    close = np.maximum(close, 10)  # 防止負價格
    return pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.02,
        "Low": close * 0.98,
        "Close": close,
        "Volume": np.random.randint(1_000_000, 10_000_000, 300),
    }, index=dates)


@pytest.fixture
def sample_info():
    """模擬 yfinance ticker.info"""
    return {
        "pegRatio": 1.2,
        "returnOnEquity": 0.18,
        "priceToBook": 5.5,
        "trailingPE": 25.0,
        "operatingCashflow": 5_000_000_000,
        "totalRevenue": 80_000_000_000,
        "totalAssets": 120_000_000_000,
        "heldPercentInstitutions": 0.72,
        "heldPercentInsiders": 0.08,
        "shortRatio": 2.5,
        "shortPercentOfFloat": 0.02,
        "earningsGrowth": 0.15,
        "revenueGrowth": 0.10,
        "freeCashflow": 10_000_000_000,
        "marketCap": 200_000_000_000,
        "grossMargins": 0.45,
        "profitMargins": 0.25,
        "sector": "Technology",
    }


# ============================================================
# Registry Tests
# ============================================================

class TestRegistry:
    def test_all_strategies_registered(self):
        """確認所有策略均已註冊到 Registry"""
        from strategies.registry import get_all_strategies

        # 觸發所有模組匯入
        import strategies.momentum
        import strategies.fundamental
        import strategies.institutional
        import strategies.volume_analysis
        import strategies.enhanced_momentum
        import strategies.earnings_quality
        import strategies.sector

        strategies_map = get_all_strategies()
        expected = {
            "breakout", "acceleration", "peg", "dupont",
            "institutional", "volume_structure", "money_flow",
            "multi_tf_momentum", "relative_strength",
            "earnings_quality", "sector_rotation",
        }
        assert expected.issubset(set(strategies_map.keys())), \
            f"缺少策略: {expected - set(strategies_map.keys())}"

    def test_evaluate_all_strategies(self, sample_df, sample_info):
        """確認 evaluate_all_strategies 正常回傳所有策略結果"""
        from strategies.registry import evaluate_all_strategies
        import strategies  # 觸發全部匯入

        results = evaluate_all_strategies(sample_df, sample_info)
        assert len(results) >= 4, f"應至少有 4 個策略結果，得到 {len(results)}"
        for name, r in results.items():
            assert "pass" in r, f"{name} 缺少 'pass' 欄位"
            assert "score" in r, f"{name} 缺少 'score' 欄位"
            assert 0 <= r["score"] <= 1.0, f"{name} score 超出範圍: {r['score']}"

    def test_composite_score(self, sample_df, sample_info):
        """確認綜合分數計算合理"""
        from strategies.registry import evaluate_all_strategies, calc_composite_score
        import strategies

        results = evaluate_all_strategies(sample_df, sample_info)
        score = calc_composite_score(results)
        assert score >= 0, "分數不應為負"
        assert score <= len(results), f"分數不應超過策略總數 ({len(results)})"


# ============================================================
# Individual Strategy Tests
# ============================================================

class TestMomentumStrategies:
    def test_breakout_returns_valid(self, sample_df):
        from strategies.momentum import screen_breakout
        result = screen_breakout(sample_df)
        assert isinstance(result, dict)
        assert "pass" in result
        assert "score" in result
        assert "details" in result

    def test_breakout_insufficient_data(self):
        """數據不足時應回傳 pass=False"""
        from strategies.momentum import screen_breakout
        df = pd.DataFrame({"Close": [100, 101, 102]})
        result = screen_breakout(df)
        assert result["pass"] is False
        assert "數據不足" in result["details"]

    def test_acceleration_returns_valid(self, sample_df):
        from strategies.momentum import screen_acceleration
        result = screen_acceleration(sample_df, n=20)
        assert isinstance(result, dict)
        assert 0 <= result["score"] <= 1.0

    def test_multi_tf_momentum(self, sample_df):
        from strategies.enhanced_momentum import screen_multi_tf_momentum
        result = screen_multi_tf_momentum(sample_df)
        assert isinstance(result, dict)
        assert "pass" in result
        assert "加速度" in result["details"]

    def test_relative_strength(self, sample_df):
        from strategies.enhanced_momentum import screen_relative_strength
        result = screen_relative_strength(sample_df)
        assert isinstance(result, dict)
        assert "新高次數" in result["details"]


class TestFundamentalStrategies:
    def test_peg_returns_valid(self, sample_info):
        from strategies.fundamental import screen_peg
        result = screen_peg(sample_info)
        assert isinstance(result, dict)
        assert "PEG" in result["details"]

    def test_peg_missing_data(self):
        from strategies.fundamental import screen_peg
        result = screen_peg({})
        assert result["pass"] is False

    def test_dupont_returns_valid(self, sample_info):
        from strategies.fundamental import screen_dupont
        result = screen_dupont(sample_info)
        assert isinstance(result, dict)
        assert "ROE" in result["details"]

    def test_earnings_quality(self, sample_info):
        from strategies.earnings_quality import screen_earnings_quality
        result = screen_earnings_quality(sample_info)
        assert isinstance(result, dict)
        assert "EPS" in result["details"] or "EPS成長" in result["details"]


class TestChipsStrategies:
    def test_institutional(self, sample_info):
        from strategies.institutional import screen_institutional
        result = screen_institutional(sample_info)
        assert isinstance(result, dict)
        assert "機構" in result["details"]

    def test_institutional_missing(self):
        from strategies.institutional import screen_institutional
        result = screen_institutional({})
        assert result["pass"] is False


class TestVolumeStrategies:
    def test_volume_structure(self, sample_df):
        from strategies.volume_analysis import screen_volume_structure
        result = screen_volume_structure(sample_df)
        assert isinstance(result, dict)
        assert "量比" in result["details"]

    def test_money_flow(self, sample_df):
        from strategies.volume_analysis import screen_money_flow
        result = screen_money_flow(sample_df)
        assert isinstance(result, dict)
        assert "MFI" in result["details"]


class TestSectorStrategies:
    def test_sector_rotation(self, sample_df, sample_info):
        from strategies.sector import screen_sector_rotation
        result = screen_sector_rotation(sample_df, sample_info)
        assert isinstance(result, dict)
        assert "產業" in result["details"]

    def test_sector_constraint(self):
        from strategies.sector import apply_sector_constraint
        recommendations = [
            {"symbol": "AAPL", "total_score": 5},
            {"symbol": "MSFT", "total_score": 4.5},
            {"symbol": "NVDA", "total_score": 4.2},
            {"symbol": "JPM", "total_score": 3.8},
            {"symbol": "JNJ", "total_score": 3.6},
            {"symbol": "AMZN", "total_score": 3.5},
            {"symbol": "V", "total_score": 3.2},
            {"symbol": "KO", "total_score": 3.0},
        ]
        result = apply_sector_constraint(recommendations, max_per_sector=2, total_n=5)
        assert len(result) == 5
        # 最多 2 支同產業
        from strategies.sector import get_sector
        sectors = [get_sector(r["symbol"]) for r in result]
        from collections import Counter
        for sec, cnt in Counter(sectors).items():
            if sec != "ETF":
                assert cnt <= 2, f"{sec} 超出限制: {cnt}"


class TestMacroFilter:
    def test_risk_on(self):
        from strategies.macro_filter import classify_macro_regime, MacroRegime
        regime, desc = classify_macro_regime(vix=15, yield_curve=0.5, unemployment_rate=3.5)
        assert regime == MacroRegime.RISK_ON

    def test_risk_off(self):
        from strategies.macro_filter import classify_macro_regime, MacroRegime
        regime, desc = classify_macro_regime(vix=35, yield_curve=-0.5, unemployment_rate=7.0)
        assert regime == MacroRegime.RISK_OFF

    def test_neutral(self):
        from strategies.macro_filter import classify_macro_regime, MacroRegime
        regime, desc = classify_macro_regime(vix=22, yield_curve=0.1)
        assert regime == MacroRegime.NEUTRAL


# ============================================================
# Config & Shared Functions
# ============================================================

class TestConfig:
    def test_calc_rsi(self):
        from config import calc_rsi
        prices = pd.Series([10, 11, 12, 11, 10, 11, 12, 13, 14, 15,
                           14, 13, 14, 15, 16, 17, 18, 17, 16, 17])
        rsi = calc_rsi(prices, period=14)
        assert rsi.iloc[-1] >= 0
        assert rsi.iloc[-1] <= 100

    def test_calc_atr(self):
        from config import calc_atr
        np.random.seed(42)
        df = pd.DataFrame({
            "High": np.random.uniform(101, 110, 30),
            "Low": np.random.uniform(90, 100, 30),
            "Close": np.random.uniform(95, 105, 30),
        })
        atr = calc_atr(df, period=14)
        assert atr.iloc[-1] > 0

    def test_calc_rule_score(self):
        from config import calc_rule_score
        score = calc_rule_score(
            {"pass": True, "score": 1.0},
            {"pass": False, "score": 0.5},
            {"pass": True, "score": 0.8},
            {"pass": False, "score": 0.0},
        )
        assert score == 1.0 + 0.25 + 1.0 + 0.0  # 2.25

    def test_evaluate_stock_rules_v2(self, sample_df, sample_info):
        from config import evaluate_stock_rules_v2
        result = evaluate_stock_rules_v2(sample_df, sample_info)
        assert result is not None
        assert "rule_score" in result
        assert "passes" in result
        assert "all_results" in result
        assert result["total_strategies"] >= 4


# ============================================================
# Core Modules
# ============================================================

class TestPositionSizing:
    def test_atr_sizing(self):
        from core.position_sizing import calc_atr_position_size
        shares = calc_atr_position_size(
            atr=2.5, current_price=150.0,
            total_equity=100_000, risk_per_trade=0.02,
        )
        assert shares > 0
        assert shares * 150 <= 100_000 * 0.20  # 不超過 20% 權重

    def test_atr_sizing_zero(self):
        from core.position_sizing import calc_atr_position_size
        assert calc_atr_position_size(0, 100, 100000) == 0

    def test_equal_risk_weights(self):
        from core.position_sizing import calc_equal_risk_weights
        result = calc_equal_risk_weights(
            symbols=["AAPL", "MSFT"],
            atr_values={"AAPL": 3.0, "MSFT": 2.0},
            prices={"AAPL": 180, "MSFT": 400},
            total_equity=100_000,
        )
        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"] > 0
        assert result["MSFT"] > 0


class TestRiskManager:
    def test_trailing_stop(self):
        from core.risk_manager import RiskManager
        from datetime import date
        rm = RiskManager()
        rm.add_position("AAPL", entry_price=150, entry_date=date(2025, 1, 1), atr=3.0)

        # 價格上漲
        results = rm.check_all(
            {"AAPL": 160}, {"AAPL": 3.0}, date(2025, 1, 10)
        )
        should_exit, _ = results["AAPL"]
        assert should_exit is False

        # 價格暴跌至 stop 以下
        results = rm.check_all(
            {"AAPL": 140}, {"AAPL": 3.0}, date(2025, 1, 15)
        )
        should_exit, reason = results["AAPL"]
        assert should_exit is True
        assert "Trailing Stop" in reason

    def test_time_stop(self):
        from core.risk_manager import RiskManager
        from datetime import date
        rm = RiskManager(max_hold_days=30)
        rm.add_position("TSLA", entry_price=200, entry_date=date(2025, 1, 1), atr=5.0)

        # 持有 35 天且虧損
        results = rm.check_all(
            {"TSLA": 195}, {"TSLA": 5.0}, date(2025, 2, 5)
        )
        should_exit, reason = results["TSLA"]
        assert should_exit is True
        assert "Time Stop" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
