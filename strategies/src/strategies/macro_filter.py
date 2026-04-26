"""
宏觀環境濾網 (Macro Regime Filter)

不是篩選個股的策略，而是一個 meta-filter，
根據宏觀經濟環境動態調整整體風險暴露。

三種市場狀態:
  - RISK_ON  (0): 進攻模式 — 開放高 Beta、成長股策略
  - NEUTRAL  (1): 標準模式 — 維持平衡配置
  - RISK_OFF (2): 防禦模式 — 僅保守型策略 (高 FCF、低 Beta、穩定股息)
"""

import os
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from enum import IntEnum


class MacroRegime(IntEnum):
    RISK_ON = 0
    NEUTRAL = 1
    RISK_OFF = 2


BULL_MARKET = "BULL_MARKET"
BEAR_MARKET = "BEAR_MARKET"


def get_market_regime(spy_df: pd.DataFrame) -> str:
    """以 SPY 收盤價相對 200 日均線判斷多空 regime。"""
    if spy_df is None or spy_df.empty:
        return BULL_MARKET

    close_column = "close" if "close" in spy_df.columns else "Close" if "Close" in spy_df.columns else None
    if close_column is None:
        raise KeyError("spy_df 必須包含 close 或 Close 欄位")

    close = pd.to_numeric(spy_df[close_column], errors="coerce").dropna()
    if close.empty:
        return BULL_MARKET

    sma_200 = close.rolling(window=200, min_periods=1).mean()
    latest_close = float(close.iloc[-1])
    latest_sma_200 = float(sma_200.iloc[-1])
    if latest_close < latest_sma_200:
        return BEAR_MARKET
    return BULL_MARKET


def classify_macro_regime(
    vix: Optional[float] = None,
    yield_curve: Optional[float] = None,  # T10Y2Y
    unemployment_rate: Optional[float] = None,
    fed_rate: Optional[float] = None,
) -> Tuple[MacroRegime, str]:
    """
    根據宏觀指標分類市場環境。

    Args:
        vix: CBOE 波動率指數
        yield_curve: 10Y-2Y 殖利率差 （正=正常，負=倒掛）
        unemployment_rate: 失業率 (%)
        fed_rate: 聯邦基金利率 (%)

    Returns:
        (regime, description)
    """
    risk_off_signals = 0
    risk_on_signals = 0
    details = []

    # VIX
    if vix is not None:
        if vix > 30:
            risk_off_signals += 2
            details.append(f"VIX={vix:.1f}(高恐慌)")
        elif vix > 20:
            risk_off_signals += 1
            details.append(f"VIX={vix:.1f}(偏高)")
        else:
            risk_on_signals += 1
            details.append(f"VIX={vix:.1f}(低)")

    # 殖利率曲線
    if yield_curve is not None:
        if yield_curve < -0.2:
            risk_off_signals += 2
            details.append(f"殖利率曲線={yield_curve:.2f}(深度倒掛)")
        elif yield_curve < 0:
            risk_off_signals += 1
            details.append(f"殖利率曲線={yield_curve:.2f}(淺倒掛)")
        else:
            risk_on_signals += 1
            details.append(f"殖利率曲線={yield_curve:.2f}(正常)")

    # 失業率
    if unemployment_rate is not None:
        if unemployment_rate > 6:
            risk_off_signals += 1
            details.append(f"失業率={unemployment_rate:.1f}%(高)")
        elif unemployment_rate < 4.5:
            risk_on_signals += 1
            details.append(f"失業率={unemployment_rate:.1f}%(低)")
        else:
            details.append(f"失業率={unemployment_rate:.1f}%")

    # 判定
    if risk_off_signals >= 3:
        regime = MacroRegime.RISK_OFF
    elif risk_on_signals >= 2 and risk_off_signals == 0:
        regime = MacroRegime.RISK_ON
    else:
        regime = MacroRegime.NEUTRAL

    desc = f"{regime.name}: {', '.join(details)}" if details else regime.name
    return regime, desc


def get_regime_strategy_filter(regime: MacroRegime) -> Dict:
    """
    根據市場環境回傳策略權重調整建議。

    Returns:
        {
            "enabled_categories": [...],  # 允許啟用的策略分類
            "score_multiplier": float,     # 綜合分數乘數
            "max_positions": int,          # 最大持倉數
            "description": str,
        }
    """
    if regime == MacroRegime.RISK_ON:
        return {
            "enabled_categories": ["momentum", "fundamental", "chips", "volume", "macro", "custom"],
            "score_multiplier": 1.2,
            "max_positions": 7,
            "description": "進攻模式: 全策略啟用，加權成長與動能",
        }
    elif regime == MacroRegime.RISK_OFF:
        return {
            "enabled_categories": ["fundamental", "chips"],
            "score_multiplier": 0.8,
            "max_positions": 3,
            "description": "防禦模式: 僅基本面+籌碼面，減少倉位",
        }
    else:
        return {
            "enabled_categories": ["momentum", "fundamental", "chips", "volume", "macro", "custom"],
            "score_multiplier": 1.0,
            "max_positions": 5,
            "description": "標準模式: 均衡配置",
        }


def fetch_macro_indicators_from_db() -> Dict[str, Optional[float]]:
    """
    從資料庫取得最新宏觀指標（若可用）。

    Returns:
        {"vix": float|None, "yield_curve": float|None, "unemployment": float|None, "fed_rate": float|None}
    """
    result = {"vix": None, "yield_curve": None, "unemployment": None, "fed_rate": None}
    try:
        from adapters.database import DatabaseAdapter
        from sqlalchemy import text

        db = DatabaseAdapter()
        with db.engine.connect() as conn:
            # 嘗試從 macro_data 表取最新值
            for ticker, key in [
                ("VIXCLS", "vix"), ("T10Y2Y", "yield_curve"),
                ("UNRATE", "unemployment"), ("DFF", "fed_rate"),
            ]:
                row = conn.execute(
                    text("SELECT value FROM macro_data WHERE ticker = :t ORDER BY report_date DESC LIMIT 1"),
                    {"t": ticker},
                ).fetchone()
                if row:
                    result[key] = float(row[0])
        db.close()
    except Exception:
        pass
    return result
