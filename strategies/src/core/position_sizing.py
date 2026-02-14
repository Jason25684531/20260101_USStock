"""
Position Sizing 模組 (倉位管理)

基於風險的倉位計算，取代固定股數交易。

三種方式:
  1. ATR-Based Sizing  — 依波動率決定倉位
  2. Equal Risk        — 等風險配置
  3. Max Weight Limit  — 單一持股上限
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple


def calc_atr_position_size(
    atr: float,
    current_price: float,
    total_equity: float,
    risk_per_trade: float = 0.02,
    atr_multiplier: float = 2.0,
) -> int:
    """
    ATR-Based Position Sizing

    公式: shares = (equity × risk_per_trade) / (ATR × multiplier)
    含義: 每筆交易最多虧損帳戶淨值的 risk_per_trade%

    Args:
        atr: 14 日 ATR 值
        current_price: 當前股價
        total_equity: 帳戶總淨值
        risk_per_trade: 單筆交易風險百分比 (預設 2%)
        atr_multiplier: ATR 倍數 (預設 2x)

    Returns:
        建議買入股數 (整數)
    """
    if atr <= 0 or current_price <= 0 or total_equity <= 0:
        return 0

    risk_amount = total_equity * risk_per_trade
    stop_distance = atr * atr_multiplier
    shares = risk_amount / stop_distance

    # 確保不超過單一持股上限 (20% of equity)
    max_shares_by_weight = (total_equity * 0.20) / current_price
    shares = min(shares, max_shares_by_weight)

    return max(int(shares), 0)


def calc_equal_risk_weights(
    symbols: list,
    atr_values: Dict[str, float],
    prices: Dict[str, float],
    total_equity: float,
    max_weight: float = 0.20,
) -> Dict[str, int]:
    """
    等風險配置 — 每支股票承擔相同的風險預算

    Args:
        symbols: 要配置的股票清單
        atr_values: {symbol: atr}
        prices: {symbol: current_price}
        total_equity: 帳戶總淨值
        max_weight: 單一持股最大權重

    Returns:
        {symbol: shares}
    """
    if not symbols or total_equity <= 0:
        return {}

    risk_per_stock = total_equity / len(symbols)
    result = {}

    for sym in symbols:
        atr = atr_values.get(sym, 0)
        price = prices.get(sym, 0)

        if atr > 0 and price > 0:
            shares = risk_per_stock / (atr * 2)
            max_shares = (total_equity * max_weight) / price
            shares = min(shares, max_shares)
            result[sym] = max(int(shares), 0)
        else:
            result[sym] = 0

    return result


def calc_atr_from_df(df: pd.DataFrame, period: int = 14) -> float:
    """從 OHLCV DataFrame 計算 ATR 最新值"""
    from config import calc_atr
    atr_series = calc_atr(df, period)
    if atr_series is not None and not atr_series.empty:
        val = atr_series.iloc[-1]
        return float(val) if pd.notna(val) else 0.0
    return 0.0
