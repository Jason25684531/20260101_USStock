"""
多時間框架動能 + 相對強度策略 (Multi-Timeframe Momentum & Relative Strength)

策略:
  1. screen_multi_tf_momentum — 短/中/長期動能一致性 + 加速度
  2. screen_relative_strength — RS Rating (IBD 風格) + 新高頻率
  3. MultiTFMomentumStrategy  — Registry 版
  4. RelativeStrengthStrategy  — Registry 版
"""

import numpy as np
import pandas as pd
from typing import Dict

from strategies.registry import BaseScreenStrategy


def screen_multi_tf_momentum(df: pd.DataFrame) -> Dict:
    """
    多時間框架動能策略

    條件:
      1. 至少 2/3 個時間框架動能為正 (5d, 20d, 63d)
      2. 動能加速度 > 0 (20d 動能比 20 天前更強)
      3. 年化動能 (252d) 為正（長線方向正確）

    Args:
        df: 含 Close 欄位, 至少 260 行

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    close_col = "Close" if "Close" in df.columns else "close"
    c = df[close_col]

    if len(c) < 260:
        return {"pass": False, "score": 0.0, "details": "數據不足260日"}

    current = float(c.iloc[-1])

    # 短期 (5d)
    mom_5 = (current / float(c.iloc[-6]) - 1) * 100 if len(c) >= 6 else 0
    # 中期 (20d)
    mom_20 = (current / float(c.iloc[-21]) - 1) * 100 if len(c) >= 21 else 0
    # 中長期 (63d ≈ 3 個月)
    mom_63 = (current / float(c.iloc[-64]) - 1) * 100 if len(c) >= 64 else 0
    # 長期 (252d ≈ 1 年)
    mom_252 = (current / float(c.iloc[-253]) - 1) * 100 if len(c) >= 253 else 0

    # 動能加速度: 目前 20 日動能 vs 20 天前的 20 日動能
    if len(c) >= 41:
        prev_20 = float(c.iloc[-21])
        prev_40 = float(c.iloc[-41])
        mom_20_prev = (prev_20 / prev_40 - 1) * 100
        acceleration = mom_20 - mom_20_prev
    else:
        acceleration = 0

    # 判定
    positive_count = sum([mom_5 > 0, mom_20 > 0, mom_63 > 0])
    multi_tf_ok = positive_count >= 2
    accel_ok = acceleration > 0
    long_term_ok = mom_252 > 0

    passed = multi_tf_ok and accel_ok and long_term_ok

    score = sum([
        0.35 * min(positive_count / 3, 1.0),  # 最多 0.35
        0.35 if accel_ok else 0.0,
        0.30 if long_term_ok else 0.0,
    ])

    parts = []
    parts.append(f"5d:{mom_5:+.1f}% 20d:{mom_20:+.1f}% 63d:{mom_63:+.1f}%")
    parts.append(f"加速度:{acceleration:+.1f}{'✓' if accel_ok else '✗'}")
    parts.append(f"252d:{mom_252:+.1f}%{'✓' if long_term_ok else '✗'}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


def screen_relative_strength(df: pd.DataFrame, all_returns: dict = None) -> Dict:
    """
    相對強度策略 (IBD RS Rating 風格)

    條件:
      1. 近 252 日收益率排名在前 30%（RS Rating ≥ 70）
      2. 近 60 日內創 20 日新高的次數 ≥ 3（持續突破能力）
      3. 近 63 日收益率 > 0（中短期趨勢正向）

    Args:
        df: 含 Close 欄位, 至少 260 行
        all_returns: {symbol: 252d_return} 用於排名（可選）
                     若不提供，僅檢查新高頻率與中期趨勢

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    close_col = "Close" if "Close" in df.columns else "close"
    c = df[close_col]

    if len(c) < 260:
        return {"pass": False, "score": 0.0, "details": "數據不足260日"}

    current = float(c.iloc[-1])
    ret_252 = (current / float(c.iloc[-253]) - 1) * 100 if len(c) >= 253 else 0
    ret_63 = (current / float(c.iloc[-64]) - 1) * 100 if len(c) >= 64 else 0

    # 新高頻率: 過去 60 日中，有多少日收盤為近 20 日新高
    recent_60 = c.iloc[-60:]
    rolling_high_20 = c.rolling(20).max().iloc[-60:]
    new_high_count = int((recent_60 >= rolling_high_20 * 0.99).sum())
    new_high_ok = new_high_count >= 3

    # RS 排名（若有全域資料）
    rs_rating = None
    rs_ok = True  # 無全域數據時不作為篩選條件
    if all_returns:
        sorted_rets = sorted(all_returns.values(), reverse=True)
        n = len(sorted_rets)
        if n > 0:
            rank = sum(1 for r in sorted_rets if r >= ret_252)
            rs_rating = int((1 - rank / n) * 100)
            rs_ok = rs_rating >= 70

    mid_term_ok = ret_63 > 0
    passed = new_high_ok and mid_term_ok and rs_ok

    score = sum([
        0.35 if new_high_ok else min(new_high_count / 3, 1.0) * 0.15,
        0.35 if mid_term_ok else 0.0,
        0.30 if rs_ok else 0.0,
    ])

    parts = []
    parts.append(f"新高次數:{new_high_count}{'✓' if new_high_ok else '✗'}")
    parts.append(f"63d:{ret_63:+.1f}%{'✓' if mid_term_ok else '✗'}")
    if rs_rating is not None:
        parts.append(f"RS:{rs_rating}{'✓' if rs_ok else '✗'}")
    parts.append(f"252d:{ret_252:+.1f}%")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


# ============================================================
# Registry 整合
# ============================================================

class MultiTFMomentumStrategy(BaseScreenStrategy):
    """Registry 版: 多時間框架動能策略"""
    name = "multi_tf_momentum"
    description = "短中長期動能一致 + 加速度"
    category = "momentum"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_multi_tf_momentum(df)


class RelativeStrengthStrategy(BaseScreenStrategy):
    """Registry 版: 相對強度策略"""
    name = "relative_strength"
    description = "RS Rating + 新高頻率 + 中期趨勢"
    category = "momentum"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_relative_strength(df)
