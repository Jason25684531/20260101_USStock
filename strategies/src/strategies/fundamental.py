"""Fundamental screening strategies and valuation helpers."""

from typing import Dict

from policies.valuation import ClassicPEPolicy

try:
    from strategies.registry import BaseScreenStrategy
except ImportError:
    class BaseScreenStrategy:  # type: ignore[override]
        name = "base"
        description = "base"
        category = "base"

        def screen(self, df, info: dict) -> Dict:
            raise NotImplementedError


def calculate_valuation_targets(
    current_price: float,
    eps_ttm: float | None,
    fair_pe: float = 15,
    safety_margin: float = 0.2,
    premium: float = 0.2,
) -> Dict:
    """Classic P/E valuation wrapper kept for backward compatibility."""
    return ClassicPEPolicy(
        fair_pe=float(fair_pe),
        safety_margin=float(safety_margin),
        premium=float(premium),
    ).evaluate(current_price=current_price, eps_ttm=eps_ttm)


def screen_peg(info: dict) -> Dict:
    """PEG + ROE + operating cash flow based screen."""
    peg = info.get("pegRatio") or info.get("peg_ratio") or info.get("trailingPegRatio")
    roe = info.get("returnOnEquity") or info.get("roe")
    ocf = info.get("operatingCashflow") or info.get("operating_cashflow")
    pe = info.get("trailingPE") or info.get("pe_ratio")

    if peg is None or roe is None:
        return {"pass": False, "score": 0.0, "details": "PEG 或 ROE 數據缺失"}

    roe_pct = roe * 100
    peg_ok = 0 < peg < 1.5
    roe_ok = roe_pct > 10
    ocf_ok = (ocf is not None and ocf > 0) if ocf is not None else True
    passed = peg_ok and roe_ok and ocf_ok

    score = sum(
        [
            0.4 if peg_ok else 0.0,
            0.35 if roe_ok else 0.0,
            0.25 if ocf_ok else 0.0,
        ]
    )

    parts = [
        f"PEG:{peg:.2f}{'✓' if peg_ok else '✗'}",
        f"ROE:{roe_pct:.1f}%{'✓' if roe_ok else '✗'}",
    ]
    if ocf is not None:
        parts.append(f"OCF:{'正向' if ocf > 0 else '負向'}{'✓' if ocf_ok else '✗'}")
    else:
        parts.append("OCF:N/A")
    if pe is not None:
        parts.append(f"PE:{pe:.1f}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class PEGStrategy(BaseScreenStrategy):
    """Registry PEG strategy."""

    name = "peg"
    description = "PEG + ROE + 營運現金流"
    category = "fundamental"

    def screen(self, df, info: dict) -> Dict:
        return screen_peg(info)


def screen_dupont(info: dict) -> Dict:
    """ROE + PB + asset turnover based screen."""
    roe = info.get("returnOnEquity") or info.get("roe")
    pb = info.get("priceToBook") or info.get("pb_ratio")
    total_revenue = info.get("totalRevenue") or info.get("total_revenue")
    total_assets = info.get("totalAssets") or info.get("total_assets")

    if roe is None or pb is None:
        return {"pass": False, "score": 0.0, "details": "ROE 或 PB 數據缺失"}

    roe_pct = roe * 100
    asset_turnover = None
    if total_revenue and total_assets and total_assets > 0:
        asset_turnover = total_revenue / total_assets

    roe_ok = roe_pct > 5
    pb_ok = 0 < pb < 8
    turnover_ok = asset_turnover is not None and asset_turnover > 0.3
    passed = (roe_ok and pb_ok) if asset_turnover is None else (roe_ok and pb_ok and turnover_ok)

    score = sum(
        [
            0.35 if roe_ok else 0.0,
            0.35 if pb_ok else 0.0,
            0.30 if turnover_ok else (0.15 if asset_turnover is None else 0.0),
        ]
    )

    parts = [
        f"ROE:{roe_pct:.1f}%{'✓' if roe_ok else '✗'}",
        f"PB:{pb:.2f}{'✓' if pb_ok else '✗'}",
    ]
    if asset_turnover is not None:
        parts.append(f"資產週轉:{asset_turnover:.2f}{'✓' if turnover_ok else '✗'}")
    else:
        parts.append("資產週轉:N/A")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class DuPontStrategy(BaseScreenStrategy):
    """Registry DuPont-style quality strategy."""

    name = "dupont"
    description = "ROE + PB + 資產週轉"
    category = "fundamental"

    def screen(self, df, info: dict) -> Dict:
        return screen_dupont(info)
