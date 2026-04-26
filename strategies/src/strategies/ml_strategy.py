from __future__ import annotations

import importlib.util
import json
import sys
import time
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
from strategies.src.core.position_sizing import calculate_position_size

MODEL_MODULE_PATH = Path(__file__).resolve().parents[1] / "ml" / "model.py"
MODEL_SPEC = importlib.util.spec_from_file_location("usstock_strategy_model", MODEL_MODULE_PATH)
if MODEL_SPEC is None or MODEL_SPEC.loader is None:
    raise ImportError(f"無法載入模型模組: {MODEL_MODULE_PATH}")

MODEL_MODULE = importlib.util.module_from_spec(MODEL_SPEC)
MODEL_SPEC.loader.exec_module(MODEL_MODULE)
StrategyModel = MODEL_MODULE.StrategyModel

FUNDAMENTAL_MODULE_PATH = Path(__file__).resolve().parent / "fundamental.py"
FUNDAMENTAL_SPEC = importlib.util.spec_from_file_location("usstock_strategy_fundamental", FUNDAMENTAL_MODULE_PATH)
if FUNDAMENTAL_SPEC is None or FUNDAMENTAL_SPEC.loader is None:
    raise ImportError(f"無法載入基本面模組: {FUNDAMENTAL_MODULE_PATH}")

FUNDAMENTAL_MODULE = importlib.util.module_from_spec(FUNDAMENTAL_SPEC)
FUNDAMENTAL_SPEC.loader.exec_module(FUNDAMENTAL_MODULE)
calculate_valuation_targets = FUNDAMENTAL_MODULE.calculate_valuation_targets

MACRO_FILTER_MODULE_PATH = Path(__file__).resolve().parent / "macro_filter.py"
MACRO_FILTER_SPEC = importlib.util.spec_from_file_location("usstock_strategy_macro_filter", MACRO_FILTER_MODULE_PATH)
if MACRO_FILTER_SPEC is None or MACRO_FILTER_SPEC.loader is None:
    raise ImportError(f"無法載入宏觀濾網模組: {MACRO_FILTER_MODULE_PATH}")

MACRO_FILTER_MODULE = importlib.util.module_from_spec(MACRO_FILTER_SPEC)
MACRO_FILTER_SPEC.loader.exec_module(MACRO_FILTER_MODULE)
BEAR_MARKET = MACRO_FILTER_MODULE.BEAR_MARKET
get_market_regime = MACRO_FILTER_MODULE.get_market_regime

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
SCREENING_EQUITY_BASE = 100_000.0


def _format_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2f}"


def _format_percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.1f}%"


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


def _load_latest_fundamentals(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}

    symbol_list = [symbol.upper() for symbol in symbols]
    placeholders = ", ".join(f":s{i}" for i in range(len(symbol_list)))
    params = {f"s{i}": symbol for i, symbol in enumerate(symbol_list)}

    query = text(
        f"""
        SELECT sf.symbol, sf.data_date, sf.pe_ratio, sf.forward_pe, sf.peg_ratio, sf.pb_ratio,
               sf.market_cap, sf.revenue_growth_yoy, sf.earnings_growth_yoy
        FROM stock_fundamentals sf
        INNER JOIN (
            SELECT symbol, MAX(data_date) AS max_data_date
            FROM stock_fundamentals
            WHERE symbol IN ({placeholders})
            GROUP BY symbol
        ) latest
            ON sf.symbol = latest.symbol
           AND sf.data_date = latest.max_data_date
        WHERE sf.symbol IN ({placeholders})
        ORDER BY sf.symbol ASC
        """
    )

    try:
        fundamentals_df = pd.read_sql(query, con=ENGINE, params=params)
    except Exception as error:
        print(f"[WARN] [基本面] 讀取 stock_fundamentals 失敗: {error}")
        return {}

    if fundamentals_df.empty:
        return {}

    records: dict[str, dict] = {}
    for row in fundamentals_df.to_dict(orient="records"):
        symbol = str(row.pop("symbol", "")).upper()
        if symbol:
            records[symbol] = row
    return records


def _derive_eps_ttm(current_price: float, fundamentals: dict | None) -> float | None:
    if not fundamentals or current_price <= 0:
        return None

    direct_eps = fundamentals.get("eps_ttm")
    if direct_eps is not None and pd.notna(direct_eps) and float(direct_eps) > 0:
        return float(direct_eps)

    for pe_key in ("pe_ratio", "forward_pe"):
        pe_value = fundamentals.get(pe_key)
        if pe_value is not None and pd.notna(pe_value) and float(pe_value) > 0:
            return float(current_price) / float(pe_value)

    return None


def _build_display_frame(results_df: pd.DataFrame, include_ai: bool) -> pd.DataFrame:
    display_df = results_df.copy()
    display_df["target_buy_price"] = display_df["buy_price"].apply(_format_price)
    display_df["target_sell_price"] = display_df["sell_price"].apply(_format_price)
    display_df["suggested_allocation"] = display_df["suggested_allocation_pct"].apply(_format_percent)

    columns = [
        "symbol",
        "latest_date",
        "latest_close",
        "xgboost_score",
        "valuation_status",
        "target_buy_price",
        "target_sell_price",
        "suggested_allocation",
    ]
    if include_ai:
        columns.extend(["ai_score", "ai_reason"])
    return display_df[columns]


def _to_sql_nullable(value):
    if value is None or pd.isna(value):
        return None
    return value


def save_daily_screener_results(results_df: pd.DataFrame, top_n: int = 5) -> int:
    if results_df is None or results_df.empty:
        return 0

    top_df = results_df.head(top_n).copy()
    scan_date = pd.to_datetime(top_df["latest_date"].iloc[0]).date()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS daily_recommendations (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            scan_date DATE NOT NULL,
            symbol VARCHAR(10) NOT NULL,
            rank_position INT NOT NULL,
            signal_type VARCHAR(4) NOT NULL DEFAULT 'BUY',
            total_score DECIMAL(4,2) NOT NULL,
            breakout_pass TINYINT(1) DEFAULT 0,
            acceleration_pass TINYINT(1) DEFAULT 0,
            peg_pass TINYINT(1) DEFAULT 0,
            dupont_pass TINYINT(1) DEFAULT 0,
            ml_confidence DECIMAL(4,3) DEFAULT NULL,
            current_price DECIMAL(12,4) NOT NULL,
            support_1 DECIMAL(12,4),
            support_2 DECIMAL(12,4),
            resistance_1 DECIMAL(12,4),
            resistance_2 DECIMAL(12,4),
            pe_ratio DECIMAL(10,2),
            peg_ratio DECIMAL(10,4),
            pb_ratio DECIMAL(10,2),
            roe DECIMAL(10,4),
            strategy_details JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_date_symbol (scan_date, symbol),
            INDEX idx_scan_date (scan_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    insert_sql = text(
        """
        INSERT INTO daily_recommendations (
            scan_date, symbol, rank_position, signal_type, total_score,
            breakout_pass, acceleration_pass, peg_pass, dupont_pass,
            ml_confidence, current_price,
            support_1, support_2, resistance_1, resistance_2,
            pe_ratio, peg_ratio, pb_ratio, roe, strategy_details
        ) VALUES (
            :scan_date, :symbol, :rank_position, :signal_type, :total_score,
            :breakout_pass, :acceleration_pass, :peg_pass, :dupont_pass,
            :ml_confidence, :current_price,
            :support_1, :support_2, :resistance_1, :resistance_2,
            :pe_ratio, :peg_ratio, :pb_ratio, :roe, :strategy_details
        )
        ON DUPLICATE KEY UPDATE
            rank_position = VALUES(rank_position),
            signal_type = VALUES(signal_type),
            total_score = VALUES(total_score),
            breakout_pass = VALUES(breakout_pass),
            acceleration_pass = VALUES(acceleration_pass),
            peg_pass = VALUES(peg_pass),
            dupont_pass = VALUES(dupont_pass),
            ml_confidence = VALUES(ml_confidence),
            current_price = VALUES(current_price),
            pe_ratio = VALUES(pe_ratio),
            peg_ratio = VALUES(peg_ratio),
            strategy_details = VALUES(strategy_details)
        """
    )

    with ENGINE.begin() as conn:
        conn.execute(create_table_sql)
        for rank, (_, row) in enumerate(top_df.iterrows(), start=1):
            strategy_details = {
                "engine": "ml_strategy",
                "xgboost_score": _to_sql_nullable(row["xgboost_score"]),
                "ai_score": _to_sql_nullable(row.get("ai_score")),
                "ai_reason": _to_sql_nullable(row.get("ai_reason")),
                "valuation_status": _to_sql_nullable(row.get("valuation_status")),
                "buy_price": _to_sql_nullable(row.get("buy_price")),
                "sell_price": _to_sql_nullable(row.get("sell_price")),
                "suggested_allocation_pct": _to_sql_nullable(row.get("suggested_allocation_pct")),
                "market_regime": _to_sql_nullable(row.get("market_regime")),
            }
            conn.execute(
                insert_sql,
                {
                    "scan_date": str(scan_date),
                    "symbol": row["symbol"],
                    "rank_position": rank,
                    "signal_type": "BUY",
                    "total_score": round(float(row["xgboost_score"]) * 5, 2),
                    "breakout_pass": 0,
                    "acceleration_pass": 0,
                    "peg_pass": 1 if row.get("valuation_status") == "UNDERVALUED" else 0,
                    "dupont_pass": 0,
                    "ml_confidence": round(float(row["xgboost_score"]), 3),
                    "current_price": float(row["latest_close"]),
                    "support_1": _to_sql_nullable(row.get("buy_price")),
                    "support_2": None,
                    "resistance_1": _to_sql_nullable(row.get("sell_price")),
                    "resistance_2": None,
                    "pe_ratio": _to_sql_nullable(row.get("pe_ratio")),
                    "peg_ratio": None,
                    "pb_ratio": None,
                    "roe": None,
                    "strategy_details": json.dumps(strategy_details, ensure_ascii=False, default=str),
                },
            )

    print(f"✅ 已將 ml_strategy Top {len(top_df)} 存入 daily_recommendations (scan_date={scan_date})")
    return len(top_df)


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


def run_xgboost_inference(features_df: pd.DataFrame, symbol: str, log_missing_features: bool = True) -> float:
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

    if missing_features and log_missing_features:
        display = ", ".join(missing_features[:8])
        suffix = " ..." if len(missing_features) > 8 else ""
        print(f"[WARN] [{symbol}] 以 0 補齊 {len(missing_features)} 個缺失特徵: {display}{suffix}")

    return round(probability, 4)


def evaluate_symbol(
    symbol: str,
    fundamentals_lookup: dict[str, dict] | None = None,
    market_regime: str = "BULL_MARKET",
) -> dict | None:
    df = load_data_from_db(symbol)
    if df.empty:
        return None

    features_df = calculate_v30_features(df)
    if features_df.empty:
        print(f"[WARN] [{symbol}] 特徵工程後無可用資料")
        return None

    score = run_xgboost_inference(features_df, symbol)
    latest_row = features_df.iloc[-1]
    latest_close = round(float(latest_row["close"]), 4)
    fundamentals = (fundamentals_lookup or {}).get(symbol.upper(), {})
    eps_ttm = _derive_eps_ttm(latest_close, fundamentals)
    valuation = calculate_valuation_targets(current_price=latest_close, eps_ttm=eps_ttm)
    sizing = calculate_position_size(
        total_equity=SCREENING_EQUITY_BASE,
        is_bear_market=market_regime == BEAR_MARKET,
    )

    return {
        "symbol": symbol,
        "latest_date": features_df.index[-1].strftime("%Y-%m-%d"),
        "latest_close": latest_close,
        "xgboost_score": score,
        "xgboost_runtime": XGBOOST_RUNTIME,
        "market_regime": market_regime,
        "eps_ttm": round(float(eps_ttm), 4) if eps_ttm is not None else None,
        "pe_ratio": fundamentals.get("pe_ratio"),
        "forward_pe": fundamentals.get("forward_pe"),
        "valuation_status": valuation["valuation_status"],
        "valuation_supported": valuation["valuation_supported"],
        "current_pe": valuation["current_pe"],
        "fair_price": valuation["fair_price"],
        "buy_price": valuation["buy_price"],
        "sell_price": valuation["sell_price"],
        "suggested_position_value": sizing["max_position_value"],
        "suggested_allocation_pct": round(float(sizing["allocation_pct"]) * 100, 2),
    }


def run_daily_screener(symbols: list[str] | None = None) -> pd.DataFrame:
    print("啟動 XGBoost 策略初篩引擎 (V35-Local DaaS)...")
    results: list[dict] = []
    symbol_list = [symbol.upper() for symbol in (symbols or UNIVERSE_TICKERS)]
    spy_df = load_data_from_db("SPY")
    market_regime = get_market_regime(spy_df) if not spy_df.empty else "BULL_MARKET"
    fundamentals_lookup = _load_latest_fundamentals(symbol_list)

    print(f"[INFO] 市場 regime: {market_regime}")

    for symbol in symbol_list:
        try:
            result = evaluate_symbol(
                symbol,
                fundamentals_lookup=fundamentals_lookup,
                market_regime=market_regime,
            )
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
        for position, index in enumerate(review_indices):
            symbol = results_df.at[index, "symbol"]
            try:
                sentiment = sentiment_agent.analyze_sentiment(symbol)
                results_df.at[index, "ai_score"] = sentiment["score"]
                results_df.at[index, "ai_reason"] = sentiment["reason"]
                results_df.at[index, "ai_reviewed"] = True
            except Exception as error:
                print(f"[WARN] [{symbol}] AI 審查失敗: {error}")
                results_df.at[index, "ai_score"] = 0.5
                results_df.at[index, "ai_reason"] = f"AI 審查失敗: {error}"
                results_df.at[index, "ai_reviewed"] = True
            finally:
                if position < len(review_indices) - 1:
                    print("  [Rate Limit] 等待 4.5 秒後進行下一檔審查...")
                    time.sleep(4.5)

    top_reviewed_df = results_df.head(AI_REVIEW_LIMIT).reset_index(drop=True)
    remaining_df = results_df.iloc[AI_REVIEW_LIMIT:].reset_index(drop=True)

    print(f"\n今日量化 Top {AI_REVIEW_LIMIT} + AI 新聞審查:")
    if top_reviewed_df.empty:
        print("無可審查標的。")
    else:
        print(_build_display_frame(top_reviewed_df, include_ai=True).to_string(index=False))

    if not remaining_df.empty:
        print(f"\n其餘標的量化排序 ({AI_REVIEW_LIMIT + 1}-{len(results_df)} 名):")
        print(_build_display_frame(remaining_df, include_ai=False).to_string(index=False))

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
    results_df = run_daily_screener()
    if results_df.empty:
        return 0

    top_n_df = results_df.head(5).copy()
    save_daily_screener_results(results_df, top_n=5)

    try:
        from strategies.src.adapters.notifier import get_notifier

        notifier = get_notifier()
        if notifier.send_daily_screener_flex(top_n_df):
            print("✅ 每日情報 Flex Message 已處理完成")
    except Exception as error:
        print(f"⚠️ Line Flex 推播失敗: {error}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())