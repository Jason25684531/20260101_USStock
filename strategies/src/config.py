"""
全系統共用常量 (Shared Constants)

統一管理股票池、閾值、評分邏輯等共用設定，避免散落在多個檔案中重複定義。
"""

# strategies/src/config.py
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# ==========================================
# 基礎設施連線配置 (Infrastructure)
# ==========================================
# 指向你的 OpenBB 數據販賣機 (Terminal A)
OPENBB_API_URL = os.getenv("OPENBB_API_URL", "http://127.0.0.1:6900")

# 指向你的 MySQL 資料庫中樞
DB_URI = os.getenv(
    "DATABASE_URL",
    "mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}".format(
        user=os.getenv("DB_USER", os.getenv("MYSQL_USER", "trader")),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "3308"),
        database=os.getenv("DB_NAME", os.getenv("MYSQL_DATABASE", "usstock")),
    ),
)

# ==========================================
# 策略配置 (Strategy)
# ==========================================
UNIVERSE_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMD", "META", "AMZN", "GOOGL", "NFLX", "BRK-B",
    "JPM", "V", "MA", "JNJ", "PG", "HD", "CVX", "MRK", "ABBV", "COST",
    "PEP", "WMT", "KO", "DIS", "MCD", "CSCO", "INTC", "CRM", "NKE", "BA",
    "BAC", "XOM", "WFC", "ORCL", "IBM", "QCOM", "TXN", "CAT", "UNH", "LLY",
    "ABT", "ACN", "ADBE", "AMGN", "AVGO", "CMCSA", "COP", "DHR", "GE", "GILD",
    "GS", "HON", "INTU", "ISRG", "LIN", "LOW", "MDT", "MMM", "MO", "MS",
    "NOW", "PANW", "PFE", "PLTR", "PM", "RTX", "SBUX", "SCHW", "SPGI", "T",
    "TMO", "TMUS", "UNP", "UPS", "USB", "VZ", "BLK", "C", "DE", "ELV",
    "ADP", "BKNG", "SYK", "TJX", "CHTR", "MDLZ", "AMAT", "MU", "LRCX", "KLAC",
    "SNPS", "CDNS", "PYPL", "SHOP", "UBER", "APH", "CRWD", "ARM", "MRVL", "ANET",
]  # 100 檔高流動性美股壓測股票池
NEWS_PROVIDER = os.getenv("NEWS_PROVIDER", "yfinance")
NEWS_LIMIT = int(os.getenv("NEWS_LIMIT", "5"))
NEWS_LOOKBACK_DAYS = int(os.getenv("NEWS_LOOKBACK_DAYS", "3"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ============================================================
# 股票池
# ============================================================

DEFAULT_SYMBOLS = [
    'SPY', 'QQQ', 'IWM',
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA',
    'BRK-B', 'LLY', 'AVGO', 'JPM', 'V', 'UNH', 'XOM', 'MA',
    'HD', 'PG', 'COST', 'JNJ', 'MRK', 'ABBV', 'CVX', 'BAC',
    'CRM', 'AMD', 'NFLX', 'PEP', 'KO', 'WMT', 'ADBE', 'TMO',
    'LIN', 'ACN', 'MCD', 'DIS', 'ABT', 'CSCO', 'WFC', 'INTC',
    'INTU', 'QCOM', 'CMCSA', 'VZ', 'IBM', 'AMGN', 'PFE', 'HON', 'TXN',
]

# 回測用的較小股票池 (排除 ETF)
BACKTEST_SYMBOLS = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA',
    'JPM', 'V', 'UNH', 'XOM', 'MA', 'HD', 'PG',
    'COST', 'JNJ', 'MRK', 'ABBV', 'CRM', 'AMD',
    'NFLX', 'PEP', 'KO', 'WMT', 'ADBE',
    'MCD', 'DIS', 'CSCO', 'INTC', 'QCOM',
]


# ============================================================
# 共用技術指標函式
# ============================================================

import pandas as pd
import numpy as np
from typing import Dict


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    計算 RSI (Relative Strength Index)

    統一實作，供 momentum 篩選、ML 特徵、回測等模組共用。

    Args:
        series: 價格序列 (通常為收盤價)
        period: 回看天數 (預設 14)

    Returns:
        RSI 序列 (0~100)
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 → 全為漲 → RSI = 100;  avg_gain == 0 → 全為跌 → RSI = 0
    rsi = rsi.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return rsi


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    計算 ATR (Average True Range)

    統一實作，供支撐壓力、回測止損等模組共用。

    Args:
        df: 含 High/Low/Close (或 high/low/close) 的 DataFrame
        period: 回看天數 (預設 14)

    Returns:
        ATR 序列
    """
    high = df['High'] if 'High' in df.columns else df['high']
    low = df['Low'] if 'Low' in df.columns else df['low']
    close = df['Close'] if 'Close' in df.columns else df['close']

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def calc_rule_score(r_breakout: Dict, r_accel: Dict, r_peg: Dict, r_dupont: Dict) -> float:
    """
    計算四策略綜合規則分 (0~4)

    統一實作，避免 engine.py 與 run_screener_backtest.py 分別定義。

    Args:
        r_breakout, r_accel, r_peg, r_dupont: 各策略結果 dict
            {"pass": bool, "score": float, ...}

    Returns:
        規則分 (0~4)
    """
    return sum([
        1.0 if r_breakout['pass'] else r_breakout['score'] * 0.5,
        1.0 if r_accel['pass'] else r_accel['score'] * 0.5,
        1.0 if r_peg['pass'] else r_peg['score'] * 0.5,
        1.0 if r_dupont['pass'] else r_dupont['score'] * 0.5,
    ])


def evaluate_stock_rules_v2(df: pd.DataFrame, info: dict, symbol: str = None) -> Dict:
    """
    v2 擴展版: 執行所有已註冊策略（含原始 4 策略 + 新增策略）。

    透過 Strategy Registry 自動發現所有策略，不需手動逐一呼叫。
    保持向後相容: 回傳中仍包含 breakout/acceleration/peg/dupont 的結構。

    Args:
        df: 含 OHLCV 的 DataFrame（至少 60 行）
        info: yfinance ticker.info dict
        symbol: 股票代碼（用於產業映射等）

    Returns:
        dict with keys:
            - 所有策略名稱的結果
            - rule_score: 綜合規則分
            - passes: 通過的策略數
            - all_results: {name: result} 完整結果
        若數據不足回傳 None
    """
    from strategies.registry import evaluate_all_strategies, calc_composite_score

    # 確保所有策略模組已被 import（觸發 Registry 註冊）
    _import_all_strategies()

    if df is None or len(df) < 60:
        return None

    all_results = evaluate_all_strategies(df, info)
    rule_score = calc_composite_score(all_results)
    passes = sum(1 for r in all_results.values() if r.get('pass'))

    result = {
        'rule_score': round(rule_score, 2),
        'passes': passes,
        'total_strategies': len(all_results),
        'all_results': all_results,
    }

    # 向後相容: 保留舊欄位名稱
    for name in ('breakout', 'acceleration', 'peg', 'dupont'):
        if name in all_results:
            result[name] = all_results[name]
        else:
            result[name] = {"pass": False, "score": 0.0, "details": "N/A"}

    return result


def _import_all_strategies():
    """
    匯入所有策略模組以觸發 Registry 自動註冊。
    使用 try/except 確保個別模組失敗不影響整體。
    """
    modules = [
        'strategies.momentum',
        'strategies.fundamental',
        'strategies.institutional',
        'strategies.volume_analysis',
        'strategies.enhanced_momentum',
        'strategies.earnings_quality',
        'strategies.sector',
    ]
    import importlib
    for mod in modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
