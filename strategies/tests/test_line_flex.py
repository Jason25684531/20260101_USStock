from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pandas as pd


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _iter_dict_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dict_nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dict_nodes(item)


def test_premium_growth_uses_fair_style_in_line_flex():
    from utils.line_flex import build_decision_bubble, get_valuation_style

    label, color = get_valuation_style({"valuation_status": "PREMIUM_GROWTH"})
    bubble = build_decision_bubble(
        {
            "symbol": "NVDA",
            "valuation_status": "PREMIUM_GROWTH",
            "current_price": 120.0,
            "target_price": 135.0,
        }
    )

    assert label == "FAIR"
    assert color == "#FFA000"
    assert bubble["header"]["backgroundColor"] == "#FFA000"
    assert "FAIR" in bubble["header"]["contents"][1]["text"]


def test_unknown_status_falls_back_to_fair_style():
    from utils.line_flex import get_valuation_style

    label, color = get_valuation_style({"valuation_status": "EXPERIMENTAL_STATUS"})

    assert label == "FAIR"
    assert color == "#FFA000"


def test_decision_bubble_has_no_null_text_and_uses_hex_colors():
    from utils.line_flex import build_decision_bubble

    bubble = build_decision_bubble(
        {
            "symbol": None,
            "valuation_status": "EXPERIMENTAL_STATUS",
            "current_price": None,
            "target_price": None,
            "support_1": None,
            "resistance_1": None,
            "buy_price": None,
            "sell_price": None,
            "institutional_ownership": None,
            "insider_sentiment": None,
            "ml_confidence": None,
            "reason_summary": None,
        }
    )

    text_values = []
    color_values = []
    for node in _iter_dict_nodes(bubble):
        if "text" in node:
            text_values.append(node["text"])
        for color_key in ("color", "backgroundColor"):
            if color_key in node:
                color_values.append(node[color_key])

    assert text_values
    assert all(isinstance(value, str) and value.strip() for value in text_values)
    assert color_values
    assert all(isinstance(color, str) and HEX_COLOR_RE.match(color) for color in color_values)


def test_daily_screener_flex_is_null_safe_for_premium_growth():
    notifier_path = Path(__file__).resolve().parents[1] / "src" / "adapters" / "notifier.py"
    spec = importlib.util.spec_from_file_location("line_notifier_under_test", notifier_path)
    assert spec and spec.loader
    notifier_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier_module)
    LineNotifier = notifier_module.LineNotifier

    notifier = LineNotifier()
    payload = notifier.build_daily_screener_flex(
        pd.DataFrame(
            [
                {
                    "symbol": "NVDA",
                    "latest_date": "2026-05-15",
                    "xgboost_score": 0.72,
                    "valuation_status": "PREMIUM_GROWTH",
                    "buy_price": None,
                    "sell_price": None,
                    "suggested_allocation_pct": None,
                    "ai_reason": None,
                }
            ]
        )
    )

    bubble = payload["contents"]["contents"][0]
    text_values = []
    color_values = []
    for node in _iter_dict_nodes(payload):
        if "text" in node:
            text_values.append(node["text"])
        for color_key in ("color", "backgroundColor"):
            if color_key in node:
                color_values.append(node[color_key])

    assert bubble["header"]["backgroundColor"] == "#A16207"
    assert "FAIR" in bubble["header"]["contents"][1]["text"]
    assert any(value == "N/A" for value in text_values)
    assert all(isinstance(value, str) and value.strip() for value in text_values)
    assert all(isinstance(color, str) and HEX_COLOR_RE.match(color) for color in color_values)
