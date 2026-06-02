from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def _safe_result(
    eps_ttm: float | None,
    fair_pe: float,
    safety_margin: float,
    premium: float,
) -> dict:
    return {
        "current_pe": None,
        "fair_price": None,
        "buy_price": None,
        "sell_price": None,
        "valuation_status": "FAIR",
        "valuation_supported": False,
        "eps_ttm": float(eps_ttm) if eps_ttm is not None and pd.notna(eps_ttm) else None,
        "fair_pe": float(fair_pe),
        "safety_margin": float(safety_margin),
        "premium": float(premium),
    }


def _evaluate_classic(
    current_price: float,
    eps_ttm: float,
    fair_pe: float,
    safety_margin: float,
    premium: float,
) -> dict:
    fair_price = float(eps_ttm) * float(fair_pe)
    buy_price = fair_price * (1 - float(safety_margin))
    sell_price = fair_price * (1 + float(premium))

    if current_price < buy_price:
        valuation_status = "UNDERVALUED"
    elif current_price > sell_price:
        valuation_status = "OVERVALUED"
    else:
        valuation_status = "FAIR"

    return {
        "current_pe": round(current_price / float(eps_ttm), 4),
        "fair_price": round(fair_price, 4),
        "buy_price": round(buy_price, 4),
        "sell_price": round(sell_price, 4),
        "valuation_status": valuation_status,
        "valuation_supported": True,
        "eps_ttm": round(float(eps_ttm), 4),
        "fair_pe": float(fair_pe),
        "safety_margin": float(safety_margin),
        "premium": float(premium),
    }


@dataclass(slots=True)
class ClassicPEPolicy:
    fair_pe: float = 15.0
    safety_margin: float = 0.20
    premium: float = 0.20

    def evaluate(
        self,
        current_price: float | None,
        eps_ttm: float | None,
        revenue_growth_yoy: float | None = None,
    ) -> dict:
        result = _safe_result(
            eps_ttm=eps_ttm,
            fair_pe=self.fair_pe,
            safety_margin=self.safety_margin,
            premium=self.premium,
        )

        if current_price is None or pd.isna(current_price) or float(current_price) <= 0:
            return result
        if eps_ttm is None or pd.isna(eps_ttm) or float(eps_ttm) <= 0:
            return result

        return _evaluate_classic(
            current_price=float(current_price),
            eps_ttm=float(eps_ttm),
            fair_pe=self.fair_pe,
            safety_margin=self.safety_margin,
            premium=self.premium,
        )


@dataclass(slots=True)
class GrowthAwarePolicy:
    base_fair_pe: float = 15.0
    base_safety_margin: float = 0.20
    base_premium: float = 0.20

    def evaluate(
        self,
        current_price: float | None,
        eps_ttm: float | None,
        revenue_growth_yoy: float | None = None,
    ) -> dict:
        classic = ClassicPEPolicy(
            fair_pe=self.base_fair_pe,
            safety_margin=self.base_safety_margin,
            premium=self.base_premium,
        ).evaluate(current_price=current_price, eps_ttm=eps_ttm)

        if revenue_growth_yoy is None or pd.isna(revenue_growth_yoy):
            return classic

        growth = float(revenue_growth_yoy)
        if growth <= 0.30:
            return classic

        fair_pe = self.base_fair_pe * 1.20
        safety_margin = 0.15
        if growth > 0.50:
            fair_pe = self.base_fair_pe * 1.35
            safety_margin = 0.10

        growth_aware = ClassicPEPolicy(
            fair_pe=fair_pe,
            safety_margin=safety_margin,
            premium=self.base_premium,
        ).evaluate(current_price=current_price, eps_ttm=eps_ttm)

        if (
            growth_aware["valuation_supported"]
            and classic["valuation_status"] == "OVERVALUED"
            and growth_aware["valuation_status"] == "FAIR"
        ):
            growth_aware["valuation_status"] = "PREMIUM_GROWTH"

        return growth_aware
