"""
成交量結構策略 + 資金流向策略 (Volume Structure & Money Flow)

策略:
  1. screen_volume_structure  — 量價突破 + 縮量回撤 + OBV 趨勢
  2. screen_money_flow        — MFI + CMF 資金流指標
  3. VolumeStructureStrategy  — Registry 版
  4. MoneyFlowStrategy        — Registry 版

這些策略專注於成交量和資金流的微觀結構分析。
"""

import numpy as np
import pandas as pd
from typing import Dict

from strategies.registry import BaseScreenStrategy


# ============================================================
# 成交量工具函式
# ============================================================

def _get_ohlcv(df: pd.DataFrame):
    """統一取得 OHLCV 欄位"""
    o = df["Open"] if "Open" in df.columns else df.get("open")
    h = df["High"] if "High" in df.columns else df.get("high")
    l = df["Low"] if "Low" in df.columns else df.get("low")
    c = df["Close"] if "Close" in df.columns else df.get("close")
    v = df["Volume"] if "Volume" in df.columns else df.get("volume")
    return o, h, l, c, v


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """計算 On-Balance Volume"""
    sign = np.sign(close.diff())
    return (sign * volume).fillna(0).cumsum()


def calc_mfi(high: pd.Series, low: pd.Series, close: pd.Series,
             volume: pd.Series, period: int = 14) -> pd.Series:
    """
    計算 Money Flow Index (MFI)

    類似 RSI 但加入成交量加權，範圍 0-100。
    MFI > 50 且上升 → 資金流入。
    """
    tp = (high + low + close) / 3
    raw_mf = tp * volume
    delta = tp.diff()

    pos_mf = raw_mf.where(delta > 0, 0.0)
    neg_mf = raw_mf.where(delta < 0, 0.0)

    pos_sum = pos_mf.rolling(window=period, min_periods=period).sum()
    neg_sum = neg_mf.rolling(window=period, min_periods=period).sum()

    mfi = 100 - 100 / (1 + pos_sum / neg_sum.replace(0, np.nan))
    return mfi.fillna(50)


def calc_cmf(high: pd.Series, low: pd.Series, close: pd.Series,
             volume: pd.Series, period: int = 20) -> pd.Series:
    """
    計算 Chaikin Money Flow (CMF)

    範圍 -1 ~ 1。CMF > 0.05 → 機構持續買進。
    """
    hl_range = high - low
    clv = ((close - low) - (high - close)) / hl_range.replace(0, np.nan)
    clv = clv.fillna(0)
    mfv = clv * volume

    cmf = mfv.rolling(window=period).sum() / volume.rolling(window=period).sum()
    return cmf.fillna(0)


# ============================================================
# 篩選函式
# ============================================================

def screen_volume_structure(df: pd.DataFrame) -> Dict:
    """
    成交量結構篩選

    條件:
      1. 量價突破: 最近 5 日均量 > 20 日均量 × 1.5（放量）
      2. OBV 趨勢: OBV 10 日斜率 > 0（資金持續流入）
      3. 近 5 日 VWAP 偏離: 收盤價 > VWAP（買方主導）

    Args:
        df: 含 OHLCV 的 DataFrame（至少 60 行）

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    _, h, l, c, v = _get_ohlcv(df)
    if c is None or v is None or len(df) < 60:
        return {"pass": False, "score": 0.0, "details": "數據不足"}

    # 1. 量價突破 — 近 5 日均量 vs 20 日均量
    vol_5 = v.iloc[-5:].mean()
    vol_20 = v.iloc[-20:].mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
    vol_breakout = vol_ratio > 1.5

    # 2. OBV 趨勢 — 10 日線性回歸斜率
    obv = calc_obv(c, v)
    obv_recent = obv.iloc[-10:].values
    if len(obv_recent) >= 10:
        x = np.arange(10)
        obv_slope = np.polyfit(x, obv_recent, 1)[0]
        obv_trend = obv_slope > 0
    else:
        obv_slope = 0
        obv_trend = False

    # 3. VWAP — 近 5 日量加權平均價
    if h is not None and l is not None:
        tp = (h + l + c) / 3
        vwap_5 = (tp.iloc[-5:] * v.iloc[-5:]).sum() / v.iloc[-5:].sum()
        current_price = float(c.iloc[-1])
        above_vwap = current_price > vwap_5
    else:
        vwap_5 = 0
        above_vwap = False

    passed = vol_breakout and obv_trend and above_vwap

    score = sum([
        0.40 if vol_breakout else min(vol_ratio / 1.5, 1.0) * 0.20,
        0.35 if obv_trend else 0.0,
        0.25 if above_vwap else 0.0,
    ])

    parts = []
    parts.append(f"量比:{vol_ratio:.2f}{'✓' if vol_breakout else '✗'}")
    parts.append(f"OBV趨勢:{'↑' if obv_trend else '↓'}")
    parts.append(f"VWAP:{'上方' if above_vwap else '下方'}{'✓' if above_vwap else '✗'}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


def screen_money_flow(df: pd.DataFrame) -> Dict:
    """
    資金流向篩選

    條件:
      1. MFI(14) > 50 且近 5 日上升（資金正流入）
      2. CMF(20) > 0.05（機構持續買進）

    Args:
        df: 含 OHLCV 的 DataFrame（至少 60 行）

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    _, h, l, c, v = _get_ohlcv(df)
    if c is None or v is None or h is None or l is None or len(df) < 60:
        return {"pass": False, "score": 0.0, "details": "數據不足"}

    mfi = calc_mfi(h, l, c, v, period=14)
    cmf = calc_cmf(h, l, c, v, period=20)

    mfi_current = float(mfi.iloc[-1])
    mfi_5ago = float(mfi.iloc[-5]) if len(mfi) >= 5 else mfi_current
    mfi_rising = mfi_current > mfi_5ago
    mfi_ok = mfi_current > 50 and mfi_rising

    cmf_current = float(cmf.iloc[-1])
    cmf_ok = cmf_current > 0.05

    passed = mfi_ok and cmf_ok

    score = sum([
        0.55 if mfi_ok else (0.25 if mfi_current > 50 else 0.0),
        0.45 if cmf_ok else (0.20 if cmf_current > 0 else 0.0),
    ])

    parts = []
    parts.append(f"MFI:{mfi_current:.1f}{'↑' if mfi_rising else '↓'}{'✓' if mfi_ok else '✗'}")
    parts.append(f"CMF:{cmf_current:.3f}{'✓' if cmf_ok else '✗'}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


# ============================================================
# Registry 整合
# ============================================================

class VolumeStructureStrategy(BaseScreenStrategy):
    """Registry 版: 成交量結構策略"""
    name = "volume_structure"
    description = "量價突破 + OBV趨勢 + VWAP"
    category = "volume"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_volume_structure(df)


class MoneyFlowStrategy(BaseScreenStrategy):
    """Registry 版: 資金流向策略"""
    name = "money_flow"
    description = "MFI資金流入 + CMF機構買進"
    category = "volume"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_money_flow(df)
