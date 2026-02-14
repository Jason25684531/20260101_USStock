"""
籌碼面策略 — 機構持股與內部人動向 (Institutional & Smart Money)

策略:
  1. screen_institutional — 機構持股 + 內部人持有 + 空頭壓力分析
  2. InstitutionalStrategy — Registry 版本

數據源: yfinance ticker.info (heldPercentInstitutions, heldPercentInsiders, shortRatio)
"""

import pandas as pd
from typing import Dict

from strategies.registry import BaseScreenStrategy


def screen_institutional(info: dict) -> Dict:
    """
    機構籌碼面篩選

    條件:
      1. 機構持股 > 50%（機構認可度高）
      2. 內部人持股在合理範圍 5-30%（管理層有動機但非壟斷）
      3. 空頭比率 < 5（低空頭壓力）

    Args:
        info: yfinance ticker.info dict

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    inst = info.get("heldPercentInstitutions")
    insider = info.get("heldPercentInsiders")
    short_ratio = info.get("shortRatio")  # days-to-cover
    short_pct = info.get("shortPercentOfFloat")

    if inst is None:
        return {"pass": False, "score": 0.0, "details": "機構持股數據缺失"}

    # 轉換百分比（yfinance 回傳小數，如 0.75 = 75%）
    inst_pct = inst * 100 if inst and inst <= 1 else (inst or 0)
    insider_pct = insider * 100 if insider and insider <= 1 else (insider or 0)

    # 條件判定
    inst_ok = inst_pct > 50
    insider_ok = 1 <= insider_pct <= 35 if insider is not None else True  # 缺值不懲罰
    short_ok = (short_ratio is not None and short_ratio < 5) if short_ratio is not None else True

    # 額外加分: 極低空頭
    low_short_bonus = (
        short_pct is not None and short_pct < 0.03  # < 3%
    )

    passed = inst_ok and insider_ok and short_ok

    score = sum([
        0.40 if inst_ok else min(inst_pct / 50, 1.0) * 0.20,
        0.30 if insider_ok else 0.10,
        0.20 if short_ok else 0.0,
        0.10 if low_short_bonus else 0.0,
    ])

    parts = []
    parts.append(f"機構:{inst_pct:.1f}%{'✓' if inst_ok else '✗'}")
    if insider is not None:
        parts.append(f"內部人:{insider_pct:.1f}%{'✓' if insider_ok else '✗'}")
    else:
        parts.append("內部人:N/A")
    if short_ratio is not None:
        parts.append(f"空頭比率:{short_ratio:.1f}{'✓' if short_ok else '✗'}")
    else:
        parts.append("空頭比率:N/A")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class InstitutionalStrategy(BaseScreenStrategy):
    """Registry 版: 籌碼面策略"""
    name = "institutional"
    description = "機構持股 + 內部人 + 空頭壓力"
    category = "chips"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_institutional(info)
