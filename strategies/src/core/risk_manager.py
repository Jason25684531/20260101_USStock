"""
風控模組 — 動態停損機制 (Risk Manager)

三種停損:
  1. Initial Stop:  進場價 - 2 × ATR(14)
  2. Trailing Stop:  max(最高價 - 2 × ATR, initial_stop)
  3. Time Stop:     持有 > 30 交易日且 return < 0% → 強制出場
"""

import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import date

SELL = "SELL"
HOLD = "HOLD"


def check_stop_loss_and_take_profit(
    entry_price: float,
    current_price: float,
    highest_price: float,
) -> str:
    """以固定 8% 硬停損與條件式移動停利判斷是否賣出。"""
    if min(entry_price, current_price, highest_price) <= 0:
        return HOLD

    hard_stop_price = entry_price * 0.92
    if current_price <= hard_stop_price:
        return SELL

    trailing_activation_price = entry_price * 1.15
    trailing_stop_price = highest_price * 0.95
    if highest_price >= trailing_activation_price and current_price <= trailing_stop_price:
        return SELL

    return HOLD


@dataclass
class PositionRisk:
    """單一持倉的風控狀態"""
    symbol: str
    entry_price: float
    entry_date: date
    initial_stop: float
    trailing_stop: float
    highest_since_entry: float
    atr_at_entry: float

    def update(self, current_price: float, current_atr: float) -> None:
        """更新最高價與 trailing stop"""
        if current_price > self.highest_since_entry:
            self.highest_since_entry = current_price
        new_trail = self.highest_since_entry - 2 * current_atr
        self.trailing_stop = max(self.trailing_stop, new_trail)

    def should_stop(
        self, current_price: float, current_date: date, max_hold_days: int = 30
    ) -> Tuple[bool, str]:
        """
        檢查是否觸發停損。

        Returns:
            (should_exit, reason)
        """
        stop_action = check_stop_loss_and_take_profit(
            entry_price=self.entry_price,
            current_price=current_price,
            highest_price=self.highest_since_entry,
        )
        if stop_action == SELL:
            if current_price <= self.entry_price * 0.92:
                return True, "Hard Stop (-8.0%)"
            return True, f"Trailing Take Profit ({self.highest_since_entry:.2f})"

        # Trailing Stop
        if current_price <= self.trailing_stop:
            return True, f"Trailing Stop ({self.trailing_stop:.2f})"

        # Time Stop
        hold_days = (current_date - self.entry_date).days
        ret = (current_price / self.entry_price - 1)
        if hold_days > max_hold_days and ret < 0:
            return True, f"Time Stop ({hold_days}d, {ret*100:.1f}%)"

        return False, ""


class RiskManager:
    """
    投資組合風控管理器

    追蹤所有持倉的停損狀態，每日更新。
    """

    def __init__(self, max_hold_days: int = 30, atr_multiplier: float = 2.0):
        self.positions: Dict[str, PositionRisk] = {}
        self.max_hold_days = max_hold_days
        self.atr_multiplier = atr_multiplier

    def add_position(
        self, symbol: str, entry_price: float, entry_date: date, atr: float
    ) -> PositionRisk:
        """新增持倉並設定初始停損"""
        initial_stop = entry_price - self.atr_multiplier * atr
        pos = PositionRisk(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            initial_stop=initial_stop,
            trailing_stop=initial_stop,
            highest_since_entry=entry_price,
            atr_at_entry=atr,
        )
        self.positions[symbol] = pos
        return pos

    def remove_position(self, symbol: str) -> None:
        """移除持倉"""
        self.positions.pop(symbol, None)

    def check_all(
        self,
        current_prices: Dict[str, float],
        current_atrs: Dict[str, float],
        current_date: date,
    ) -> Dict[str, Tuple[bool, str]]:
        """
        檢查所有持倉的停損狀態。

        Returns:
            {symbol: (should_exit, reason)}
        """
        results = {}
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol)
            atr = current_atrs.get(symbol, pos.atr_at_entry)

            if price is None:
                continue

            pos.update(price, atr)
            should_exit, reason = pos.should_stop(
                price, current_date, self.max_hold_days
            )
            results[symbol] = (should_exit, reason)

        return results

    def get_status(self) -> Dict[str, Dict]:
        """取得所有持倉的風控狀態摘要"""
        return {
            sym: {
                "entry": pos.entry_price,
                "initial_stop": pos.initial_stop,
                "trailing_stop": pos.trailing_stop,
                "highest": pos.highest_since_entry,
            }
            for sym, pos in self.positions.items()
        }
