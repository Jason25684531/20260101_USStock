"""
基本面策略 (Fundamental Strategy)

包含兩個篩選函式（用於每日選股）:
  1. screen_peg    — 本益成長比選股（0 < PEG < 1.5 + ROE > 10% + OCF > 0）
  2. screen_dupont — 杜邦分析優質股（ROE > 5% + 資產周轉率 > 0.3 + PB < 8）

取代原 growth_peg.py 和 chips_momentum.py 中的篩選邏輯。
"""
from typing import Dict

from strategies.registry import BaseScreenStrategy


def screen_peg(info: dict) -> Dict:
    """
    本益成長比 (PEG) 選股法

    條件:
      1. 0 < PEG < 1.5（成長速度快於估值擴張）
      2. ROE > 10%
      3. 營業活動現金流量 > 0

    Args:
        info: yfinance ticker.info dict

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    peg = info.get('pegRatio') or info.get('peg_ratio') or info.get('trailingPegRatio')
    roe = info.get('returnOnEquity') or info.get('roe')
    ocf = info.get('operatingCashflow') or info.get('operating_cashflow')
    pe = info.get('trailingPE') or info.get('pe_ratio')

    # 缺值處理
    if peg is None or roe is None:
        return {"pass": False, "score": 0.0, "details": "PEG或ROE數據缺失"}

    # 轉換：yfinance ROE 為分數 (如 0.25 = 25%, 1.52 = 152%)
    roe_pct = roe * 100

    peg_ok = 0 < peg < 1.5  # PEG 須為正數且 < 1.5
    roe_ok = roe_pct > 10
    ocf_ok = (ocf is not None and ocf > 0) if ocf is not None else True  # 缺值時不懲罰

    passed = peg_ok and roe_ok and ocf_ok

    # 評分
    score = sum([
        0.4 if peg_ok else 0.0,
        0.35 if roe_ok else 0.0,
        0.25 if ocf_ok else 0.0,
    ])

    parts = []
    parts.append(f"PEG:{peg:.2f}{'✓' if peg_ok else '✗'}")
    parts.append(f"ROE:{roe_pct:.1f}%{'✓' if roe_ok else '✗'}")
    if ocf is not None:
        parts.append(f"OCF:{'正' if ocf > 0 else '負'}{'✓' if ocf_ok else '✗'}")
    else:
        parts.append("OCF:N/A")
    if pe is not None:
        parts.append(f"PE:{pe:.1f}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class PEGStrategy(BaseScreenStrategy):
    """Registry 版: PEG 選股策略"""
    name = "peg"
    description = "本益成長比 + ROE + 現金流"
    category = "fundamental"

    def screen(self, df, info: dict) -> Dict:
        return screen_peg(info)


def screen_dupont(info: dict) -> Dict:
    """
    杜邦分析優質股篩選

    條件:
      1. ROE > 5%
      2. 總資產周轉率 > 0.3（revenue / totalAssets）
      3. PB < 8（放寬以涵蓋高成長科技股）

    Args:
        info: yfinance ticker.info dict

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    roe = info.get('returnOnEquity') or info.get('roe')
    pb = info.get('priceToBook') or info.get('pb_ratio')
    total_revenue = info.get('totalRevenue') or info.get('total_revenue')
    total_assets = info.get('totalAssets') or info.get('total_assets')

    if roe is None or pb is None:
        return {"pass": False, "score": 0.0, "details": "ROE或PB數據缺失"}

    # ROE 轉換：yfinance 為分數 (如 0.25 = 25%, 1.52 = 152%)
    roe_pct = roe * 100

    # 資產周轉率
    if total_revenue and total_assets and total_assets > 0:
        asset_turnover = total_revenue / total_assets
    else:
        asset_turnover = None

    roe_ok = roe_pct > 5
    pb_ok = 0 < pb < 8  # 放寬至 8 以涵蓋高成長科技股
    turnover_ok = (asset_turnover is not None and asset_turnover > 0.3)

    # 若缺少資產周轉率, 放寬為只看 ROE + PB
    if asset_turnover is None:
        passed = roe_ok and pb_ok
    else:
        passed = roe_ok and pb_ok and turnover_ok

    score = sum([
        0.35 if roe_ok else 0.0,
        0.35 if pb_ok else 0.0,
        0.30 if turnover_ok else (0.15 if asset_turnover is None else 0.0),
    ])

    parts = []
    parts.append(f"ROE:{roe_pct:.1f}%{'✓' if roe_ok else '✗'}")
    parts.append(f"PB:{pb:.2f}{'✓' if pb_ok else '✗'}")
    if asset_turnover is not None:
        parts.append(f"資產周轉率:{asset_turnover:.2f}{'✓' if turnover_ok else '✗'}")
    else:
        parts.append("資產周轉率:N/A")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class DuPontStrategy(BaseScreenStrategy):
    """Registry 版: 杜邦分析優質股策略"""
    name = "dupont"
    description = "ROE分解 + PB合理 + 資產周轉率"
    category = "fundamental"

    def screen(self, df, info: dict) -> Dict:
        return screen_dupont(info)
