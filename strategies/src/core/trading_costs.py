from __future__ import annotations

COMMISSION_RATE = 0.0008
SLIPPAGE_RATE = 0.0015
FRICTION_COST = COMMISSION_RATE + SLIPPAGE_RATE


def calculate_friction_cost(notional: float, rate: float = FRICTION_COST) -> float:
    if notional <= 0:
        return 0.0
    return float(notional) * float(rate)