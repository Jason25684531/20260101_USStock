from __future__ import annotations

import importlib.util
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy import create_engine, text

if __package__ in (None, ""):
    REPO_ROOT = Path(__file__).resolve().parents[3]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from strategies.src.config import DB_URI, UNIVERSE_TICKERS, calc_rsi
from strategies.src.agents import SentimentAgent

MODEL_MODULE_PATH = Path(__file__).resolve().parents[1] / "ml" / "model.py"
MODEL_SPEC = importlib.util.spec_from_file_location("usstock_strategy_model", MODEL_MODULE_PATH)
if MODEL_SPEC is None or MODEL_SPEC.loader is None:
    raise ImportError(f"無法載入模型模組: {MODEL_MODULE_PATH}")

MODEL_MODULE = importlib.util.module_from_spec(MODEL_SPEC)
MODEL_SPEC.loader.exec_module(MODEL_MODULE)
StrategyModel = MODEL_MODULE.StrategyModel

warnings.filterwarnings("ignore", category=FutureWarning)

ENGINE = create_engine(DB_URI)
XGBOOST_RUNTIME = xgb.__version__
AI_REVIEW_LIMIT = 10
REQUIRED_PRICE_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
CRITICAL_FEATURES = [
    "close",
    "RSI_14",
    "MACD",
    "SMA_Diff",
    "Volatility_20",
    "Momentum_10",
]


def calculate_macd(
    prices: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    ema_fast = prices.ewm(span=fast_period, adjust=False).mean()
    ema_slow = prices.ewm(span=slow_period, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_period, adjust=False).mean()
    histogram = macd - signal
    return pd.DataFrame(
        {
            "MACD": macd,
            "MACD_Signal": signal,
            "MACD_Hist": histogram,
        }
    )


def calculate_sma_diff(
    prices: pd.Series,
    short_period: int = 20,
    long_period: int = 50,
) -> pd.Series:
    sma_short = prices.rolling(window=short_period).mean()
    sma_long = prices.rolling(window=long_period).mean()
    return ((sma_short - sma_long) / sma_long) * 100


def calculate_volatility(prices: pd.Series, period: int = 20) -> pd.Series:
    returns = prices.pct_change()
    return returns.rolling(window=period).std() * np.sqrt(252)


def calculate_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
    return ((prices - prices.shift(period)) / prices.shift(period)) * 100


def calculate_distance_from_ma(prices: pd.Series, period: int = 200) -> pd.Series:
    ma = prices.rolling(window=period).mean()
    return ((prices - ma) / ma) * 100


def calculate_52week_high_distance(prices: pd.Series) -> pd.Series:
    high_52w = prices.rolling(window=252).max()
    return ((prices - high_52w) / high_52w) * 100


def calculate_volume_volatility(volume: pd.Series, period: int = 20) -> pd.Series:
    volume_change = volume.pct_change()
    return volume_change.rolling(window=period).std() * np.sqrt(252)


def calculate_relative_strength_spy(
    prices: pd.Series,
    spy_close: pd.Series | None,
    period: int = 63,
) -> pd.Series:
    stock_ret = prices.pct_change(periods=period)
    if spy_close is None:
        return pd.Series(0.0, index=prices.index)
    spy_ret = spy_close.pct_change(periods=period)
    rs = stock_ret / spy_ret.replace(0, np.nan)
    return rs.fillna(0)


def calculate_volume_price_trend(
    prices: pd.Series,
    volume: pd.Series,
    period: int = 10,
) -> pd.Series:
    price_change = prices.pct_change()
    volume_change = volume.pct_change()
    return price_change.rolling(window=period).corr(volume_change).fillna(0)


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = np.sign(close.diff())
    return (sign * volume).fillna(0).cumsum()


def calc_mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    typical_price = (high + low + close) / 3
    raw_money_flow = typical_price * volume
    delta = typical_price.diff()

    positive_flow = raw_money_flow.where(delta > 0, 0.0)
    negative_flow = raw_money_flow.where(delta < 0, 0.0)

    positive_sum = positive_flow.rolling(window=period, min_periods=period).sum()
    negative_sum = negative_flow.rolling(window=period, min_periods=period).sum()

    money_ratio = positive_sum / negative_sum.replace(0, np.nan)
    mfi = 100 - 100 / (1 + money_ratio)
    return mfi.fillna(50)


def calc_cmf(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    hl_range = high - low
    close_location_value = ((close - low) - (high - close)) / hl_range.replace(0, np.nan)
    close_location_value = close_location_value.fillna(0)
    money_flow_volume = close_location_value * volume
    cmf = money_flow_volume.rolling(window=period).sum() / volume.rolling(window=period).sum()
    return cmf.fillna(0)


def _normalize_price_dataframe(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]

    missing_columns = sorted(REQUIRED_PRICE_COLUMNS - set(normalized.columns))
    if missing_columns:
        raise KeyError(f"{symbol} 缺少必要欄位: {', '.join(missing_columns)}")

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"]).sort_values("date")
    normalized = normalized.set_index("date")
    normalized.index.name = "date"

    for column in ["open", "high", "low", "close", "volume"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=["open", "high", "low", "close", "volume"])
    if normalized.empty:
        raise ValueError(f"{symbol} 的 OHLCV 數據在正規化後為空")

    return normalized


@lru_cache(maxsize=8)
def _load_benchmark_close(symbol: str, start_date: str, end_date: str) -> pd.Series | None:
    query = text(
        """
        SELECT date, close
        FROM price_data_v2
        WHERE symbol = :symbol
          AND date >= :start_date
          AND date <= :end_date
        ORDER BY date ASC
        """
    )
    benchmark = pd.read_sql(
        query,
        con=ENGINE,
        params={
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    if benchmark.empty:
        return None

    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark = benchmark.dropna(subset=["date", "close"]).sort_values("date")
    if benchmark.empty:
        return None

    return benchmark.set_index("date")["close"]


def _get_spy_close(index: pd.DatetimeIndex) -> pd.Series | None:
    clean_index = pd.DatetimeIndex(index)
    if getattr(clean_index, "tz", None) is not None:
        clean_index = clean_index.tz_localize(None)
    if clean_index.empty:
        return None

    spy_close = _load_benchmark_close(
        "SPY",
        (clean_index.min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        (clean_index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if spy_close is None:
        return None

    aligned = spy_close.copy()
    aligned.index = pd.to_datetime(aligned.index)
    if getattr(aligned.index, "tz", None) is not None:
        aligned.index = aligned.index.tz_localize(None)
    aligned.index = aligned.index.normalize()
    return aligned.reindex(clean_index.normalize(), method="ffill")


@lru_cache(maxsize=1)
def _get_model() -> StrategyModel:
    model = StrategyModel.load()
    if not model.feature_names:
        raise ValueError("模型缺少 feature_names，無法執行推論")
    return model


def load_data_from_db(symbol: str) -> pd.DataFrame:
    query = text(
        """
        SELECT *
        FROM price_data_v2
        WHERE symbol = :symbol
        ORDER BY date ASC
        """
    )

    try:
        df = pd.read_sql(query, con=ENGINE, params={"symbol": symbol.upper()})
        if df.empty:
            print(f"[WARN] [資料庫] 找不到 {symbol} 的數據，請確認 Feeder 是否已寫入 price_data_v2。")
            return df
        return _normalize_price_dataframe(df, symbol.upper())
    except Exception as error:
        print(f"[ERROR] [資料庫] 讀取 {symbol} 失敗: {error}")
        return pd.DataFrame()


def calculate_v30_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    features = df.copy()
    close = features["close"]
    high = features["high"]
    low = features["low"]
    volume = features["volume"]

    features["RSI_14"] = calc_rsi(close, period=14)

    macd = calculate_macd(close)
    features["MACD"] = macd["MACD"]
    features["MACD_Signal"] = macd["MACD_Signal"]
    features["MACD_Hist"] = macd["MACD_Hist"]

    features["SMA_Diff"] = calculate_sma_diff(close, short_period=20, long_period=50)
    features["Volatility_20"] = calculate_volatility(close, period=20)
    features["Momentum_10"] = calculate_momentum(close, period=10)
    features["Momentum_20"] = calculate_momentum(close, period=20)
    features["Distance_MA200"] = calculate_distance_from_ma(close, period=200)
    features["Distance_52W_High"] = calculate_52week_high_distance(close)
    features["Volume_Change"] = volume.pct_change() * 100
    features["Volume_SMA_Ratio"] = volume / volume.rolling(window=20).mean()
    features["Volume_Volatility"] = calculate_volume_volatility(volume, period=20)

    rolling_low = close.rolling(window=20).min()
    rolling_high = close.rolling(window=20).max()
    features["Price_Position"] = (close - rolling_low) / (rolling_high - rolling_low)

    spy_close = _get_spy_close(features.index)
    features["Rel_Strength_SPY"] = calculate_relative_strength_spy(close, spy_close, period=63)
    features["Rel_Strength_SPY"] = features["Rel_Strength_SPY"].ffill().fillna(0)

    features["Volume_Price_Trend"] = calculate_volume_price_trend(close, volume, period=10)
    features["Volume_Price_Trend"] = features["Volume_Price_Trend"].ffill().fillna(0)

    features["Momentum_5"] = calculate_momentum(close, period=5)
    features["Momentum_63"] = calculate_momentum(close, period=63)
    features["Momentum_252"] = calculate_momentum(close, period=252) if len(features) >= 253 else 0.0
    features["Momentum_Acceleration"] = features["Momentum_20"].diff(periods=20).fillna(0)

    rolling_high_20 = close.rolling(20).max()
    new_high_flag = (close >= rolling_high_20 * 0.99).astype(float)
    features["New_High_Freq_60"] = new_high_flag.rolling(60).mean().fillna(0)

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma120 = close.rolling(120).mean()
    sma200 = close.rolling(200).mean()
    features["MA_Alignment"] = (
        (sma20 > sma50).astype(float)
        + (sma50 > sma120).astype(float)
        + (sma120 > sma200).astype(float)
    ).fillna(0)

    features["MFI_14"] = calc_mfi(high, low, close, volume, period=14)
    features["CMF_20"] = calc_cmf(high, low, close, volume, period=20)

    obv = calc_obv(close, volume)
    features["OBV_Slope_10"] = obv.rolling(10).apply(
        lambda values: np.polyfit(np.arange(len(values)), values, 1)[0] if len(values) == 10 else 0,
        raw=True,
    ).fillna(0)

    features = features.dropna(subset=CRITICAL_FEATURES)

    derived_columns = [
        column
        for column in features.columns
        if column not in {"open", "high", "low", "close", "volume", "symbol"}
    ]
    for column in derived_columns:
        if features[column].isna().any():
            features[column] = features[column].fillna(0)

    return features


def run_xgboost_inference(features_df: pd.DataFrame, symbol: str) -> float:
    if features_df.empty:
        raise ValueError(f"{symbol} 無可用特徵資料，無法執行推論")

    model = _get_model()
    latest_data = features_df.iloc[[-1]].copy()

    missing_features = [
        feature_name
        for feature_name in model.feature_names
        if feature_name not in latest_data.columns
    ]
    for feature_name in missing_features:
        latest_data[feature_name] = 0.0

    prediction_frame = latest_data[model.feature_names].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    probability = float(model.predict_proba(prediction_frame)[0][1])

    if missing_features:
        display = ", ".join(missing_features[:8])
        suffix = " ..." if len(missing_features) > 8 else ""
        print(f"[WARN] [{symbol}] 以 0 補齊 {len(missing_features)} 個缺失特徵: {display}{suffix}")

    return round(probability, 4)


def evaluate_symbol(symbol: str) -> dict | None:
    df = load_data_from_db(symbol)
    if df.empty:
        return None

    features_df = calculate_v30_features(df)
    if features_df.empty:
        print(f"[WARN] [{symbol}] 特徵工程後無可用資料")
        return None

    score = run_xgboost_inference(features_df, symbol)
    latest_row = features_df.iloc[-1]
    return {
        "symbol": symbol,
        "latest_date": features_df.index[-1].strftime("%Y-%m-%d"),
        "latest_close": round(float(latest_row["close"]), 4),
        "xgboost_score": score,
        "xgboost_runtime": XGBOOST_RUNTIME,
    }


def run_daily_screener(symbols: list[str] | None = None) -> pd.DataFrame:
    print("啟動 XGBoost 策略初篩引擎 (V35-Local DaaS)...")
    results: list[dict] = []

    for symbol in symbols or UNIVERSE_TICKERS:
        try:
            result = evaluate_symbol(symbol)
            if result is None:
                continue

            results.append(result)
        except Exception as error:
            print(f"[ERROR] [{symbol}] 推論失敗: {error}")

    if not results:
        print("[WARN] 今日無可排序標的。")
        return pd.DataFrame()

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by="xgboost_score", ascending=False).reset_index(drop=True)
    results_df["ai_score"] = None
    results_df["ai_reason"] = "未審查"
    results_df["ai_reviewed"] = False

    review_indices = results_df.index[:AI_REVIEW_LIMIT]

    if len(review_indices) > 0:
        sentiment_agent = SentimentAgent()
        for index in review_indices:
            sentiment = sentiment_agent.analyze_sentiment(results_df.at[index, "symbol"])
            results_df.at[index, "ai_score"] = sentiment["score"]
            results_df.at[index, "ai_reason"] = sentiment["reason"]
            results_df.at[index, "ai_reviewed"] = True

    top_reviewed_df = results_df.head(AI_REVIEW_LIMIT).reset_index(drop=True)
    remaining_df = results_df.iloc[AI_REVIEW_LIMIT:].reset_index(drop=True)

    print(f"\n今日量化 Top {AI_REVIEW_LIMIT} + AI 新聞審查:")
    if top_reviewed_df.empty:
        print("無可審查標的。")
    else:
        print(
            top_reviewed_df[
                ["symbol", "latest_date", "latest_close", "xgboost_score", "ai_score", "ai_reason"]
            ].to_string(index=False)
        )

    if not remaining_df.empty:
        print(f"\n其餘標的量化排序 ({AI_REVIEW_LIMIT + 1}-{len(results_df)} 名):")
        print(
            remaining_df[
                ["symbol", "latest_date", "latest_close", "xgboost_score"]
            ].to_string(index=False)
        )

    return results_df


class MLStrategy:
    def __init__(self, buy_threshold: float = 0.55, sell_threshold: float = 0.30):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def generate_signal(self, symbol: str, lookback_days: int = 365):
        df = load_data_from_db(symbol)
        if df.empty:
            return "HOLD", 0.0, {"error": "無數據"}

        if lookback_days > 0:
            df = df.tail(lookback_days)

        features_df = calculate_v30_features(df)
        if features_df.empty:
            return "HOLD", 0.0, {"error": "特徵生成失敗"}

        score = run_xgboost_inference(features_df, symbol)
        if score >= self.buy_threshold:
            signal = "BUY"
        elif score <= self.sell_threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        details = {
            "symbol": symbol,
            "date": features_df.index[-1].strftime("%Y-%m-%d"),
            "price": float(features_df["close"].iloc[-1]),
            "up_probability": float(score),
            "signal": signal,
            "confidence": float(score if signal == "BUY" else 1 - score),
        }
        return signal, score, details

    def scan_multiple_symbols(self, symbols: list[str], min_adv_usd: float = 5_000_000) -> pd.DataFrame:
        results: list[dict] = []
        for symbol in symbols:
            df = load_data_from_db(symbol)
            if df.empty:
                continue

            average_daily_dollar_volume = (df["close"] * df["volume"]).tail(20).mean()
            if average_daily_dollar_volume < min_adv_usd:
                continue

            signal, score, details = self.generate_signal(symbol)
            if "error" in details:
                continue

            results.append(
                {
                    "symbol": symbol,
                    "signal": signal,
                    "up_probability": score,
                    "confidence": details["confidence"],
                    "price": details["price"],
                    "date": details["date"],
                }
            )

        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).sort_values("up_probability", ascending=False).reset_index(drop=True)

    def close(self):
        return None


def main() -> int:
    run_daily_screener()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())