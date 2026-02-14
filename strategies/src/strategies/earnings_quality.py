"""
盈餘品質策略 (Earnings Quality)

策略:
  1. screen_earnings_quality — EPS 成長 + 營收成長 + FCF 收益率 + 毛利率
  2. EarningsQualityStrategy — Registry 版

專注於盈餘品質與成長持續性，篩選出真正高品質的成長股。
"""

import pandas as pd
from typing import Dict

from strategies.registry import BaseScreenStrategy


def screen_earnings_quality(info: dict) -> Dict:
    """
    盈餘品質篩選

    條件:
      1. EPS 正向成長（earningsGrowth > 0）
      2. 營收成長 > 5%（revenueGrowth > 0.05）
      3. 自由現金流正向（freeCashflow > 0）
      4. 毛利率 > 30%（grossMargins > 0.30）

    Args:
        info: yfinance ticker.info dict

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    eps_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    rev_growth = info.get("revenueGrowth")
    fcf = info.get("freeCashflow")
    market_cap = info.get("marketCap")
    gross_margin = info.get("grossMargins")
    profit_margin = info.get("profitMargins")

    # EPS 成長
    eps_ok = eps_growth is not None and eps_growth > 0
    eps_strong = eps_growth is not None and eps_growth > 0.15  # > 15% 額外加分

    # 營收成長
    rev_ok = rev_growth is not None and rev_growth > 0.05

    # FCF 收益率 (FCF / Market Cap)
    fcf_yield = None
    fcf_ok = False
    if fcf is not None and market_cap is not None and market_cap > 0:
        fcf_yield = fcf / market_cap
        fcf_ok = fcf_yield > 0.03  # > 3%

    # 毛利率
    margin_ok = gross_margin is not None and gross_margin > 0.30

    passed = eps_ok and rev_ok and (fcf_ok or fcf is None) and margin_ok

    score = sum([
        0.30 if eps_ok else 0.0,
        0.05 if eps_strong else 0.0,
        0.25 if rev_ok else 0.0,
        0.20 if fcf_ok else (0.10 if fcf is None else 0.0),
        0.20 if margin_ok else 0.0,
    ])

    parts = []
    if eps_growth is not None:
        parts.append(f"EPS成長:{eps_growth*100:.1f}%{'✓' if eps_ok else '✗'}")
    else:
        parts.append("EPS:N/A")
    if rev_growth is not None:
        parts.append(f"營收:{rev_growth*100:.1f}%{'✓' if rev_ok else '✗'}")
    else:
        parts.append("營收:N/A")
    if fcf_yield is not None:
        parts.append(f"FCF率:{fcf_yield*100:.1f}%{'✓' if fcf_ok else '✗'}")
    else:
        parts.append("FCF:N/A")
    if gross_margin is not None:
        parts.append(f"毛利率:{gross_margin*100:.1f}%{'✓' if margin_ok else '✗'}")
    else:
        parts.append("毛利率:N/A")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class EarningsQualityStrategy(BaseScreenStrategy):
    """Registry 版: 盈餘品質策略"""
    name = "earnings_quality"
    description = "EPS成長 + 營收 + FCF + 毛利率"
    category = "fundamental"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_earnings_quality(info)
