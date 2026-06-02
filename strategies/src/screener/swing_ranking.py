"""Deterministic daily-bar swing ranking helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Mapping

import pandas as pd


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
MIN_HISTORY_ROWS = 60


@dataclass
class SwingIndicatorResult:
    is_valid: bool
    values: dict[str, float | None] = field(default_factory=dict)
    skip_reason: str | None = None


@dataclass
class SwingRankingResult:
    symbol: str
    is_valid: bool
    total_score: float = 0.0
    setup_type: str | None = None
    trend_score: float = 0.0
    momentum_score: float = 0.0
    setup_score: float = 0.0
    volatility_score: float = 0.0
    risk_score: float = 0.0
    liquidity_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    stop_loss_price: float | None = None
    risk_percent: float | None = None
    skip_reason: str | None = None
    calibration_profile_version: str | None = None
    calibration_status: str | None = None
    calibration_active: bool = False
    calibration_adjustments: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self, rank: int | None = None) -> dict[str, Any]:
        payload = {
            "score": self.total_score,
            "setup_type": self.setup_type,
            "trend_score": self.trend_score,
            "momentum_score": self.momentum_score,
            "setup_score": self.setup_score,
            "volatility_score": self.volatility_score,
            "risk_score": self.risk_score,
            "liquidity_score": self.liquidity_score,
            "reasons": list(self.reasons),
            "risk_flags": list(self.risk_flags),
            "stop_loss_price": self.stop_loss_price,
            "risk_percent": self.risk_percent,
            "calibration_profile_version": self.calibration_profile_version,
            "calibration_status": self.calibration_status,
            "calibration_active": self.calibration_active,
            "calibration_adjustments": dict(self.calibration_adjustments or {}),
        }
        if rank is not None:
            payload["rank"] = rank
        return payload


def _normalize_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    normalized = df.copy()
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    for source, target in rename_map.items():
        if source in normalized.columns and target not in normalized.columns:
            normalized[target] = normalized[source]
    return normalized


def _round(value: Any, digits: int = 4) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def calculate_swing_indicators(df: pd.DataFrame | None) -> SwingIndicatorResult:
    normalized = _normalize_ohlcv(df)
    if normalized is None:
        return SwingIndicatorResult(False, skip_reason="missing_ohlcv")
    if any(column not in normalized.columns for column in REQUIRED_COLUMNS):
        return SwingIndicatorResult(False, skip_reason="missing_ohlcv")

    price = normalized.loc[:, REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce").dropna()
    if len(price) < MIN_HISTORY_ROWS:
        return SwingIndicatorResult(False, skip_reason="insufficient_history")

    close = price["Close"]
    high = price["High"]
    low = price["Low"]
    volume = price["Volume"]

    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(100).where(gain > 0, 50)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.rolling(14).mean()

    donchian_high_20 = high.shift(1).rolling(20).max()
    donchian_low_10 = low.shift(1).rolling(10).min()
    bb_mid = ma20
    bb_std = close.rolling(20).std()
    bb_width = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid.replace(0, pd.NA)
    avg_volume_20 = volume.rolling(20).mean()
    avg_dollar_volume_20 = (close * volume).rolling(20).mean()
    roc_10 = (close / close.shift(10) - 1) * 100

    values = {
        "close": _round(close.iloc[-1]),
        "ma20": _round(ma20.iloc[-1]),
        "ma60": _round(ma60.iloc[-1]),
        "ema20": _round(ema20.iloc[-1]),
        "ema50": _round(ema50.iloc[-1]),
        "ma20_slope": _round(ma20.iloc[-1] - ma20.iloc[-6] if len(ma20.dropna()) >= 6 else None),
        "rsi14": _round(rsi.iloc[-1]),
        "macd": _round(macd.iloc[-1]),
        "macd_signal": _round(macd_signal.iloc[-1]),
        "macd_histogram": _round(macd_hist.iloc[-1]),
        "macd_histogram_prev": _round(macd_hist.iloc[-2] if len(macd_hist) >= 2 else None),
        "atr14": _round(atr14.iloc[-1]),
        "atr_percent": _round(atr14.iloc[-1] / close.iloc[-1] if close.iloc[-1] else None),
        "donchian_high_20": _round(donchian_high_20.iloc[-1]),
        "donchian_low_10": _round(donchian_low_10.iloc[-1]),
        "bollinger_width_20": _round(bb_width.iloc[-1]),
        "bollinger_width_20_prev_mean": _round(bb_width.shift(1).rolling(10).mean().iloc[-1]),
        "avg_volume_20": _round(avg_volume_20.iloc[-1]),
        "avg_dollar_volume_20": _round(avg_dollar_volume_20.iloc[-1]),
        "roc_10": _round(roc_10.iloc[-1]),
    }
    return SwingIndicatorResult(True, values=values)


def _score_trend(values: Mapping[str, float | None], reasons: list[str]) -> float:
    score = 0.0
    close = values.get("close")
    ma20 = values.get("ma20")
    ma60 = values.get("ma60")
    ema20 = values.get("ema20")
    ema50 = values.get("ema50")
    if close is not None and ma20 is not None and close > ma20:
        score += 5
        reasons.append("Close is above MA20")
    if close is not None and ma60 is not None and close > ma60:
        score += 5
    if ma20 is not None and ma60 is not None and ma20 > ma60:
        score += 5
        reasons.append("MA20 > MA60")
    if ema20 is not None and ema50 is not None and ema20 > ema50:
        score += 5
    if (values.get("ma20_slope") or 0) > 0:
        score += 5
    return min(score, 25.0)


def _score_momentum(values: Mapping[str, float | None], reasons: list[str]) -> float:
    score = 0.0
    rsi = values.get("rsi14")
    hist = values.get("macd_histogram")
    hist_prev = values.get("macd_histogram_prev")
    roc_10 = values.get("roc_10")
    if rsi is not None and rsi > 50:
        score += 5
        reasons.append("RSI14 is above 50")
    if rsi is not None:
        if 55 <= rsi <= 70:
            score += 7
            reasons.append("RSI14 is in the 55-70 momentum zone")
        elif rsi > 70:
            score += 4
    if hist is not None and hist > 0:
        score += 5
        reasons.append("MACD histogram is positive")
    if hist is not None and hist_prev is not None and hist > hist_prev:
        score += 5
        reasons.append("MACD histogram is improving")
    if roc_10 is not None and roc_10 > 0:
        score += 3
    return min(score, 25.0)


def _classify_setup(df: pd.DataFrame, values: Mapping[str, float | None], reasons: list[str]) -> tuple[str, float]:
    close = values.get("close")
    ma20 = values.get("ma20")
    ema20 = values.get("ema20")
    donchian_high = values.get("donchian_high_20")
    bb_width = values.get("bollinger_width_20")
    bb_prev = values.get("bollinger_width_20_prev_mean")

    if close is not None and donchian_high is not None and close > donchian_high:
        reasons.append("Close broke above the 20-day high")
        return "breakout", 20.0

    normalized = _normalize_ohlcv(df)
    if normalized is not None and len(normalized) >= 25 and close is not None:
        close_series = pd.to_numeric(normalized["Close"], errors="coerce")
        ma20_series = close_series.rolling(20).mean()
        ema20_series = close_series.ewm(span=20, adjust=False).mean()
        recent_close = close_series.iloc[-8:]
        recent_ma20 = ma20_series.iloc[-8:]
        recent_ema20 = ema20_series.iloc[-8:]
        touched_ma = (
            ((recent_close - recent_ma20).abs() / recent_ma20).min() <= 0.035
            or ((recent_close - recent_ema20).abs() / recent_ema20).min() <= 0.035
        )
        reclaimed = (
            (ma20 is not None and close > ma20)
            or (ema20 is not None and close > ema20)
        ) and close > close_series.iloc[-2]
        if bool(touched_ma) and bool(reclaimed):
            reasons.append("Pullback reclaimed MA20/EMA20")
            return "pullback_reclaim", 18.0

    if bb_width is not None and bb_prev is not None and bb_width > bb_prev * 1.2:
        reasons.append("Bollinger Band Width is expanding")
        return "volatility_expansion", 14.0

    reasons.append("Trend continuation above short-term support")
    return "trend_continuation", 14.0


def _score_volatility(values: Mapping[str, float | None], risk_flags: list[str]) -> float:
    atr_percent = values.get("atr_percent")
    bb_width = values.get("bollinger_width_20")
    score = 0.0
    if atr_percent is None:
        return 0.0
    if 0.01 <= atr_percent <= 0.06:
        score += 6
    elif 0.006 <= atr_percent <= 0.10:
        score += 4
    elif atr_percent < 0.006:
        score += 2
        risk_flags.append("ATR% is very low; movement may be too quiet")
    else:
        score += 1
        risk_flags.append("ATR% is elevated; position risk is high")
    if bb_width is not None and 0.03 <= bb_width <= 0.25:
        score += 4
    else:
        score += 2
    return min(score, 10.0)


def _score_risk(values: Mapping[str, float | None], risk_flags: list[str]) -> tuple[float, float | None, float | None]:
    close = values.get("close")
    ma20 = values.get("ma20")
    atr = values.get("atr14")
    atr_percent = values.get("atr_percent")
    donchian_low = values.get("donchian_low_10")
    score = 10.0
    stop_loss = None
    risk_percent = None

    if close is not None and atr is not None:
        atr_stop = close - 2 * atr
        stop_loss = max([value for value in (donchian_low, atr_stop) if value is not None])
        if stop_loss < close:
            risk_percent = ((close - stop_loss) / close) * 100
            if risk_percent > 10:
                score -= 3
                risk_flags.append("Stop distance is wide")

    if close is not None and ma20:
        distance = (close - ma20) / ma20
        if distance > 0.12:
            score -= 5
            risk_flags.append("Close is extended above MA20")
        elif distance > 0.08:
            score -= 2
            risk_flags.append("Close is moderately extended above MA20")

    if atr_percent is not None and atr_percent > 0.10:
        score -= 4
    elif atr_percent is not None and atr_percent > 0.07:
        score -= 2

    return max(0.0, min(score, 10.0)), _round(stop_loss), _round(risk_percent, 2)


def _score_liquidity(values: Mapping[str, float | None], risk_flags: list[str]) -> float:
    avg_volume = values.get("avg_volume_20") or 0
    avg_dollar_volume = values.get("avg_dollar_volume_20") or 0
    score = 0.0
    if avg_volume >= 1_000_000:
        score += 5
    elif avg_volume >= 200_000:
        score += 3
    else:
        score += 1
        risk_flags.append("Average volume indicates low liquidity")

    if avg_dollar_volume >= 20_000_000:
        score += 5
    elif avg_dollar_volume >= 5_000_000:
        score += 3
    else:
        score += 1
        risk_flags.append("Average dollar volume indicates low liquidity")
    return min(score, 10.0)


def _empty_calibration_adjustments() -> dict[str, Any]:
    return {
        "setup_adjustment": None,
        "risk_penalty_total": None,
        "applied_risk_penalties": [],
        "threshold_penalties": [],
    }


def score_swing_candidate(
    symbol: str,
    df: pd.DataFrame | None,
    *,
    calibration_profile: Mapping[str, Any] | None = None,
) -> SwingRankingResult:
    indicators = calculate_swing_indicators(df)
    if not indicators.is_valid:
        return SwingRankingResult(symbol=symbol, is_valid=False, skip_reason=indicators.skip_reason)

    reasons: list[str] = []
    risk_flags: list[str] = []
    values = indicators.values
    trend_score = _score_trend(values, reasons)
    momentum_score = _score_momentum(values, reasons)
    setup_type, setup_score = _classify_setup(df, values, reasons)
    volatility_score = _score_volatility(values, risk_flags)
    risk_score, stop_loss_price, risk_percent = _score_risk(values, risk_flags)
    liquidity_score = _score_liquidity(values, risk_flags)

    if risk_score <= 3 and setup_type != "breakout":
        setup_type = "avoid_overextended"

    component_scores = {
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "setup_score": setup_score,
        "volatility_score": volatility_score,
        "risk_score": risk_score,
        "liquidity_score": liquidity_score,
    }
    try:
        from screener.swing_calibration import apply_calibration_to_score, load_active_calibration_profile

        active_profile = calibration_profile if calibration_profile is not None else load_active_calibration_profile()
        total, calibration_context = apply_calibration_to_score(
            component_scores,
            setup_type=setup_type,
            risk_flags=risk_flags,
            profile=active_profile,
        )
    except Exception:
        total = round(
            min(
                99.99,
                max(0.0, trend_score + momentum_score + setup_score + volatility_score + risk_score + liquidity_score),
            ),
            2,
        )
        calibration_context = {
            "calibration_profile_version": None,
            "calibration_status": "fallback_to_default",
            "calibration_active": False,
            **_empty_calibration_adjustments(),
        }

    setup_adjustment = calibration_context.get("setup_adjustment")
    risk_penalty_total = calibration_context.get("risk_penalty_total")
    if setup_adjustment not in (None, 0, 0.0):
        reasons.append(f"Calibration setup adjustment {setup_adjustment:+.1f}")
    if risk_penalty_total not in (None, 0, 0.0):
        risk_flags.append(f"Calibration risk penalty {risk_penalty_total:+.1f}")

    return SwingRankingResult(
        symbol=symbol,
        is_valid=True,
        total_score=total,
        setup_type=setup_type,
        trend_score=round(trend_score, 2),
        momentum_score=round(momentum_score, 2),
        setup_score=round(setup_score, 2),
        volatility_score=round(volatility_score, 2),
        risk_score=round(risk_score, 2),
        liquidity_score=round(liquidity_score, 2),
        reasons=reasons[:8],
        risk_flags=risk_flags[:5],
        stop_loss_price=stop_loss_price,
        risk_percent=risk_percent,
        calibration_profile_version=calibration_context.get("calibration_profile_version"),
        calibration_status=calibration_context.get("calibration_status"),
        calibration_active=bool(calibration_context.get("calibration_active")),
        calibration_adjustments={
            "setup_adjustment": calibration_context.get("setup_adjustment"),
            "risk_penalty_total": calibration_context.get("risk_penalty_total"),
            "applied_risk_penalties": list(calibration_context.get("applied_risk_penalties") or []),
            "threshold_penalties": list(calibration_context.get("threshold_penalties") or []),
        },
    )


SWING_METADATA_FIELDS = (
    "score",
    "setup_type",
    "trend_score",
    "momentum_score",
    "setup_score",
    "volatility_score",
    "risk_score",
    "liquidity_score",
    "reasons",
    "risk_flags",
    "stop_loss_price",
    "risk_percent",
    "calibration_profile_version",
    "calibration_status",
    "calibration_active",
    "calibration_adjustments",
)


def _safe_json(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def normalize_swing_ranking_metadata(
    strategy_details: Any = None,
    *,
    fallback_score: float | None = None,
    rank: int | None = None,
) -> dict[str, Any]:
    details = _safe_json(strategy_details)
    source = details.get("swing_ranking") if isinstance(details, Mapping) else {}
    if not isinstance(source, Mapping):
        source = {}

    metadata = {field: source.get(field) for field in SWING_METADATA_FIELDS}
    if metadata["score"] is None:
        metadata["score"] = fallback_score
    if rank is not None:
        metadata["rank"] = rank

    for field in (
        "score",
        "trend_score",
        "momentum_score",
        "setup_score",
        "volatility_score",
        "risk_score",
        "liquidity_score",
        "stop_loss_price",
        "risk_percent",
    ):
        metadata[field] = _round(metadata.get(field), 2)

    metadata["reasons"] = list(metadata.get("reasons") or [])
    metadata["risk_flags"] = list(metadata.get("risk_flags") or [])
    metadata["setup_type"] = metadata.get("setup_type")
    metadata["calibration_profile_version"] = metadata.get("calibration_profile_version")
    metadata["calibration_status"] = metadata.get("calibration_status")
    metadata["calibration_active"] = bool(metadata.get("calibration_active"))
    adjustments = metadata.get("calibration_adjustments")
    if not isinstance(adjustments, Mapping):
        adjustments = {}
    metadata["calibration_adjustments"] = {
        "setup_adjustment": _round(adjustments.get("setup_adjustment"), 2),
        "risk_penalty_total": _round(adjustments.get("risk_penalty_total"), 2),
        "applied_risk_penalties": list(adjustments.get("applied_risk_penalties") or []),
        "threshold_penalties": list(adjustments.get("threshold_penalties") or []),
    }
    return metadata
