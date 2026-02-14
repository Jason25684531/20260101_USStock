"""
策略註冊表 (Strategy Registry)

提供 BaseScreenStrategy 抽象基底類別與自動註冊機制。
新增策略只需繼承 BaseScreenStrategy 並實作 screen() 方法，
系統會自動發現並納入選股管線。

Usage:
    from strategies.registry import BaseScreenStrategy, get_all_strategies

    class MyNewStrategy(BaseScreenStrategy):
        name = "my_strategy"
        description = "自訂策略"
        category = "momentum"        # momentum / fundamental / chips / custom

        def screen(self, df, info):
            ...
            return {"pass": True, "score": 0.8, "details": "..."}

    # 取得所有已註冊策略
    strategies = get_all_strategies()
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type

import pandas as pd


# 全域策略登錄表
_REGISTRY: Dict[str, Type["BaseScreenStrategy"]] = {}


class BaseScreenStrategy(ABC):
    """
    篩選策略的抽象基底類別。

    子類別必須定義:
        name (str):        策略唯一識別碼（英文小寫，如 'breakout'）
        description (str): 一句話說明
        category (str):    分類 — momentum / fundamental / chips / volume / macro / custom

    子類別必須實作:
        screen(df, info) -> Dict
    """

    name: str = ""
    description: str = ""
    category: str = "custom"

    def __init_subclass__(cls, **kwargs):
        """自動註冊所有具備 name 屬性的子類別"""
        super().__init_subclass__(**kwargs)
        if cls.name:
            _REGISTRY[cls.name] = cls

    @abstractmethod
    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        """
        對單支股票執行篩選。

        Args:
            df:   含 OHLCV 欄位的 DataFrame（至少 60 行）
            info: yfinance ticker.info dict（或從 DB 取得的基本面 dict）

        Returns:
            {"pass": bool, "score": float (0~1), "details": str}
        """
        ...

    @classmethod
    def create(cls) -> "BaseScreenStrategy":
        """Factory method — 直接實例化策略"""
        return cls()


# ============================================================
# Public API
# ============================================================


def get_all_strategies() -> Dict[str, Type[BaseScreenStrategy]]:
    """取得所有已註冊的篩選策略（name → class）"""
    return dict(_REGISTRY)


def get_strategies_by_category(category: str) -> Dict[str, Type[BaseScreenStrategy]]:
    """依分類篩選策略"""
    return {k: v for k, v in _REGISTRY.items() if v.category == category}


def evaluate_all_strategies(
    df: pd.DataFrame,
    info: dict,
    enabled: Optional[List[str]] = None,
) -> Dict[str, Dict]:
    """
    對單支股票執行所有已註冊策略並回傳結果。

    Args:
        df:       OHLCV DataFrame
        info:     基本面 dict
        enabled:  白名單（若指定，僅執行清單中的策略）

    Returns:
        {strategy_name: {"pass": bool, "score": float, "details": str}, ...}
    """
    results: Dict[str, Dict] = {}
    for name, strategy_cls in _REGISTRY.items():
        if enabled and name not in enabled:
            continue
        try:
            strategy = strategy_cls.create()
            results[name] = strategy.screen(df, info)
        except Exception as e:
            results[name] = {"pass": False, "score": 0.0, "details": f"Error: {e}"}
    return results


def calc_composite_score(results: Dict[str, Dict]) -> float:
    """
    計算所有策略的綜合規則分。

    公式: 每個策略通過 → 1.0 分，未通過 → score * 0.5
    總分範圍: 0 ~ len(strategies)

    Args:
        results: evaluate_all_strategies() 的輸出

    Returns:
        綜合分數
    """
    total = 0.0
    for r in results.values():
        if r.get("pass"):
            total += 1.0
        else:
            total += r.get("score", 0.0) * 0.5
    return round(total, 2)
