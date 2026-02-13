"""
全系統共用常量 (Shared Constants)

統一管理股票池、閾值、評分邏輯等共用設定，避免散落在多個檔案中重複定義。
"""

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


def evaluate_stock_rules(df: pd.DataFrame, info: dict) -> Dict:
    """
    對單支股票執行四策略評估（共用邏輯）。

    回傳結果包含 r_breakout / r_accel / r_peg / r_dupont + rule_score + passes。
    供 engine.py 與 run_screener_backtest.py 共用，避免重複。

    Args:
        df: 含 OHLCV 的 DataFrame（至少 60 行）
        info: yfinance ticker.info dict

    Returns:
        dict with keys: breakout, acceleration, peg, dupont, rule_score, passes
        若數據不足回傳 None
    """
    from strategies.momentum import screen_breakout, screen_acceleration
    from strategies.fundamental import screen_peg, screen_dupont

    if df is None or len(df) < 60:
        return None

    r_breakout = screen_breakout(df)
    r_accel = screen_acceleration(df, n=20)
    r_peg = screen_peg(info)
    r_dupont = screen_dupont(info)

    rule_score = calc_rule_score(r_breakout, r_accel, r_peg, r_dupont)
    passes = sum([r_breakout['pass'], r_accel['pass'], r_peg['pass'], r_dupont['pass']])

    return {
        'breakout': r_breakout,
        'acceleration': r_accel,
        'peg': r_peg,
        'dupont': r_dupont,
        'rule_score': round(rule_score, 2),
        'passes': passes,
    }
