"""
支撐壓力計算模組

計算方式:
1. 均線支撐壓力: SMA(60), SMA(120), SMA(200) — 價格下方為支撐、上方為壓力
2. ATR 動態帶: current_price ± 1.5 * ATR(14)
3. 近期高低點: 20 日高點 = 壓力、20 日低點 = 支撐
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
from config import calc_atr


def calc_support_resistance(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    計算支撐與壓力價位

    Args:
        df: 含 OHLCV 的 DataFrame（至少 200 行）

    Returns:
        dict with keys:
          support_1, support_2, resistance_1, resistance_2,
          atr_band_low, atr_band_high, sma_60, sma_120, sma_200
    """
    close_col = 'Close' if 'Close' in df.columns else 'close'
    high_col = 'High' if 'High' in df.columns else 'high'
    low_col = 'Low' if 'Low' in df.columns else 'low'

    close = df[close_col]
    current_price = float(close.iloc[-1])

    # --- 均線 ---
    sma_60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else None
    sma_120 = float(close.rolling(120).mean().iloc[-1]) if len(close) >= 120 else None
    sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

    # --- ATR 動態帶 ---
    atr = calc_atr(df, 14)
    atr_val = float(atr.iloc[-1]) if not atr.empty and not pd.isna(atr.iloc[-1]) else 0
    atr_band_low = current_price - 1.5 * atr_val
    atr_band_high = current_price + 1.5 * atr_val

    # --- 近期高低點 ---
    recent_high = float(df[high_col].tail(20).max()) if len(df) >= 20 else None
    recent_low = float(df[low_col].tail(20).min()) if len(df) >= 20 else None

    # --- 組合支撐壓力 ---
    supports = []
    resistances = []

    for level in [sma_60, sma_120, sma_200, recent_low]:
        if level is not None and level < current_price:
            supports.append(level)
    for level in [sma_60, sma_120, sma_200, recent_high]:
        if level is not None and level > current_price:
            resistances.append(level)

    # 支撐：取最接近現價的（降序排列取第一）
    supports.sort(reverse=True)
    resistances.sort()

    return {
        'support_1': supports[0] if len(supports) >= 1 else atr_band_low,
        'support_2': supports[1] if len(supports) >= 2 else atr_band_low,
        'resistance_1': resistances[0] if len(resistances) >= 1 else atr_band_high,
        'resistance_2': resistances[1] if len(resistances) >= 2 else atr_band_high,
        'atr_band_low': round(atr_band_low, 2),
        'atr_band_high': round(atr_band_high, 2),
        'sma_60': round(sma_60, 2) if sma_60 else None,
        'sma_120': round(sma_120, 2) if sma_120 else None,
        'sma_200': round(sma_200, 2) if sma_200 else None,
    }
