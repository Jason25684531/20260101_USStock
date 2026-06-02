from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "strategies" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from screener.swing_calibration import default_calibration_profile
from screener.swing_ranking import calculate_swing_indicators, normalize_swing_ranking_metadata, score_swing_candidate


def _ohlcv(closes, *, volume=1_000_000, high_spread=0.02, low_spread=0.02):
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series([float(v) for v in closes], index=dates)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]) * 0.995,
            "High": close * (1 + high_spread),
            "Low": close * (1 - low_spread),
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def test_indicator_helpers_return_latest_daily_values():
    df = _ohlcv([100 + i * 0.5 for i in range(80)])

    indicators = calculate_swing_indicators(df)

    assert indicators.is_valid
    assert indicators.values["ma20"] > indicators.values["ma60"]
    assert indicators.values["ema20"] > indicators.values["ema50"]
    assert indicators.values["rsi14"] > 50
    assert indicators.values["atr14"] > 0
    assert indicators.values["donchian_high_20"] >= df["High"].iloc[-21:-1].max()
    assert indicators.values["avg_volume_20"] == 1_000_000
    assert indicators.values["avg_dollar_volume_20"] > 0


def test_indicator_helpers_skip_short_or_incomplete_history_safely():
    short_df = _ohlcv([100, 101, 102])
    missing_volume = short_df.drop(columns=["Volume"])

    short_result = calculate_swing_indicators(short_df)
    missing_result = calculate_swing_indicators(missing_volume)

    assert not short_result.is_valid
    assert short_result.skip_reason == "insufficient_history"
    assert not missing_result.is_valid
    assert missing_result.skip_reason == "missing_ohlcv"


def test_clear_uptrend_scores_high_trend_and_stays_bounded():
    df = _ohlcv([80 + i * 0.8 for i in range(90)])

    result = score_swing_candidate("TREND", df)

    assert result.is_valid
    assert result.trend_score >= 20
    assert 0 <= result.total_score <= 100
    assert result.setup_type in {"trend_continuation", "breakout", "volatility_expansion"}
    assert any("MA20" in reason for reason in result.reasons)


def test_breakout_and_pullback_reclaim_are_classified():
    breakout = _ohlcv([100 + i * 0.15 for i in range(60)] + [112])
    pullback_closes = [80 + i * 0.8 for i in range(65)]
    pullback_closes.extend([126, 124, 123, 122, 124, 126])
    pullback = _ohlcv(pullback_closes)

    breakout_result = score_swing_candidate("BO", breakout)
    pullback_result = score_swing_candidate("PB", pullback)

    assert breakout_result.setup_type == "breakout"
    assert breakout_result.setup_score >= 15
    assert any("20-day high" in reason for reason in breakout_result.reasons)
    assert pullback_result.setup_type == "pullback_reclaim"
    assert any("reclaim" in reason.lower() for reason in pullback_result.reasons)


def test_overextension_atr_and_liquidity_penalties_are_explainable():
    normal = [100 + i * 0.2 for i in range(70)]
    overextended = _ohlcv(normal + [150], volume=20_000, high_spread=0.08, low_spread=0.08)

    result = score_swing_candidate("RISKY", overextended)

    assert result.is_valid
    assert result.risk_score <= 5
    assert result.liquidity_score <= 3
    assert any("MA20" in flag for flag in result.risk_flags)
    assert any("liquidity" in flag.lower() for flag in result.risk_flags)
    assert result.stop_loss_price is not None
    assert result.risk_percent is not None


def test_calibration_profile_adjusts_score_and_metadata_safely():
    df = _ohlcv([80 + i * 0.8 for i in range(90)])
    default_result = score_swing_candidate("TREND", df, calibration_profile=default_calibration_profile())
    profile = default_calibration_profile(status="active")
    profile.update({
        "version": "cal-test",
        "active": True,
        "source_sample_size": 120,
        "setup_adjustments": {default_result.setup_type: -4.0},
        "risk_penalties": {},
    })

    calibrated = score_swing_candidate("TREND", df, calibration_profile=profile)
    metadata = calibrated.to_metadata()

    assert calibrated.total_score == max(0, round(default_result.total_score - 4.0, 2))
    assert metadata["calibration_profile_version"] == "cal-test"
    assert metadata["calibration_status"] == "active"
    assert metadata["calibration_active"] is True
    assert metadata["calibration_adjustments"]["setup_adjustment"] == -4.0


def test_normalize_swing_ranking_metadata_defaults_missing_calibration_fields():
    metadata = normalize_swing_ranking_metadata(
        '{"swing_ranking":{"score":86.4,"setup_type":"breakout"}}',
        fallback_score=80.0,
        rank=1,
    )

    assert metadata["calibration_profile_version"] is None
    assert metadata["calibration_status"] is None
    assert metadata["calibration_active"] is False
    assert metadata["calibration_adjustments"]["setup_adjustment"] is None
