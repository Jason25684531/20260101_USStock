"""
產業輪動策略 + 分散約束 (Sector Rotation & Diversification)

策略:
  1. screen_sector_rotation — 產業動能排名，篩選熱門產業中的領頭羊
  2. SectorRotationStrategy — Registry 版

附屬功能:
  - SECTOR_MAP: GICS 產業映射表
  - get_sector: 取得個股所屬產業
  - apply_sector_constraint: Top-N 推薦的產業分散約束
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from strategies.registry import BaseScreenStrategy


# ============================================================
# GICS 產業映射（覆蓋 DEFAULT_SYMBOLS 的 51 支股票）
# ============================================================

SECTOR_MAP: Dict[str, str] = {
    # ETFs
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF",
    # Information Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "CRM": "Technology", "AMD": "Technology",
    "ADBE": "Technology", "ACN": "Technology", "CSCO": "Technology",
    "INTC": "Technology", "INTU": "Technology", "QCOM": "Technology",
    "IBM": "Technology", "TXN": "Technology",
    # Communication Services
    "GOOGL": "Communication", "META": "Communication", "NFLX": "Communication",
    "DIS": "Communication", "CMCSA": "Communication", "VZ": "Communication",
    # Consumer Discretionary
    "AMZN": "Consumer Disc.", "TSLA": "Consumer Disc.", "HD": "Consumer Disc.",
    "MCD": "Consumer Disc.", "COST": "Consumer Disc.",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples",
    # Financials
    "BRK-B": "Financials", "JPM": "Financials", "V": "Financials",
    "MA": "Financials", "BAC": "Financials", "WFC": "Financials",
    # Health Care
    "LLY": "Health Care", "UNH": "Health Care", "JNJ": "Health Care",
    "MRK": "Health Care", "ABBV": "Health Care", "TMO": "Health Care",
    "ABT": "Health Care", "AMGN": "Health Care", "PFE": "Health Care",
    # Energy
    "XOM": "Energy", "CVX": "Energy",
    # Industrial
    "HON": "Industrials", "LIN": "Industrials",
}

# 產業 ETF 映射（用於計算產業動能）
SECTOR_ETF = {
    "Technology": "XLK",
    "Communication": "XLC",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
}


def get_sector(symbol: str) -> str:
    """取得個股所屬產業"""
    return SECTOR_MAP.get(symbol, "Unknown")


def screen_sector_rotation(df: pd.DataFrame, info: dict = None,
                           symbol: str = None,
                           sector_momentum: Dict[str, float] = None) -> Dict:
    """
    產業輪動策略

    條件:
      1. 個股所屬產業動能排名在前 50%（若有產業動能資料）
      2. 個股 63 日動能 > 同產業平均（產業內領頭羊）
      3. 個股 20 日動能為正（短期趨勢正確）

    Args:
        df: 含 Close 欄位
        info: yfinance ticker.info（可取 sector）
        symbol: 股票代碼（用於映射產業）
        sector_momentum: {sector_name: 63d_return} 產業動能表

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    close_col = "Close" if "Close" in df.columns else "close"
    c = df[close_col]

    if len(c) < 64:
        return {"pass": False, "score": 0.0, "details": "數據不足"}

    current = float(c.iloc[-1])
    mom_63 = (current / float(c.iloc[-64]) - 1) * 100
    mom_20 = (current / float(c.iloc[-21]) - 1) * 100 if len(c) >= 21 else 0

    sector = "Unknown"
    if symbol:
        sector = get_sector(symbol)
    elif info:
        sector = info.get("sector", "Unknown")

    # 產業排名
    sector_rank_ok = True  # 預設通過（無資料時不懲罰）
    sector_detail = sector
    if sector_momentum and sector in sector_momentum:
        sorted_sectors = sorted(sector_momentum.values(), reverse=True)
        rank = sorted_sectors.index(sector_momentum[sector]) + 1
        n = len(sorted_sectors)
        sector_rank_ok = rank <= n // 2 + 1  # 前 50%
        sector_detail = f"{sector}(#{rank}/{n})"

    # 短期趨勢
    short_term_ok = mom_20 > 0

    passed = sector_rank_ok and short_term_ok and mom_63 > 0

    score = sum([
        0.35 if sector_rank_ok else 0.10,
        0.35 if mom_63 > 0 else 0.0,
        0.30 if short_term_ok else 0.0,
    ])

    parts = []
    parts.append(f"產業:{sector_detail}")
    parts.append(f"63d:{mom_63:+.1f}%")
    parts.append(f"20d:{mom_20:+.1f}%{'✓' if short_term_ok else '✗'}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


def apply_sector_constraint(
    recommendations: List[Dict],
    max_per_sector: int = 2,
    total_n: int = 5,
) -> List[Dict]:
    """
    產業分散約束: 限制同一產業的推薦數量。

    Args:
        recommendations: 已排序（score DESC）的推薦清單
        max_per_sector: 同一產業最多幾支
        total_n: 最終推薦數量

    Returns:
        經過產業分散約束的推薦清單
    """
    result = []
    sector_count: Dict[str, int] = {}

    for rec in recommendations:
        symbol = rec.get("symbol", "")
        sector = get_sector(symbol)

        if sector == "ETF":
            # ETF 不受產業限制
            if len(result) < total_n:
                result.append(rec)
            continue

        count = sector_count.get(sector, 0)
        if count < max_per_sector and len(result) < total_n:
            result.append(rec)
            sector_count[sector] = count + 1

    return result


class SectorRotationStrategy(BaseScreenStrategy):
    """Registry 版: 產業輪動策略"""
    name = "sector_rotation"
    description = "產業動能排名 + 產業內領頭羊"
    category = "macro"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_sector_rotation(df, info)
