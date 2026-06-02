from __future__ import annotations

import importlib.util
import json
import math
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


def test_decision_bubble_renders_enriched_institutional_and_sentiment_rows():
    from utils.line_flex import build_decision_bubble

    bubble = build_decision_bubble(
        {
            "symbol": "NVDA",
            "valuation_status": "FAIR",
            "current_price": 120.0,
            "target_price": 140.0,
            "whale_held_pct": 72.5,
            "inst_count": 1500,
            "institutional_net_buy": 12.5,
            "sentiment_score": 0.35,
        }
    )

    text_values = [
        node["text"]
        for node in _iter_dict_nodes(bubble)
        if "text" in node
    ]

    assert "Whale / Holders" in text_values
    assert "72.5% / 1500" in text_values
    assert "Net Buy / Sentiment" in text_values
    assert "12.50 / +0.35" in text_values


def test_decision_bubble_sanitizes_invalid_enrichment_values_for_json():
    from utils.line_flex import build_decision_bubble

    bubble = build_decision_bubble(
        {
            "symbol": "NVDA",
            "valuation_status": "FAIR",
            "current_price": 120.0,
            "target_price": 140.0,
            "whale_held_pct": math.nan,
            "inst_count": float("inf"),
            "institutional_net_buy": "not-a-number",
            "sentiment_score": float("-inf"),
        }
    )

    payload = json.dumps(bubble, ensure_ascii=False)
    assert "NaN" not in payload
    assert "Infinity" not in payload
    assert "Whale / Holders" in payload
    assert "Net Buy / Sentiment" in payload


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

    assert bubble["header"]["backgroundColor"] == "#FFA000"
    assert "FAIR" in bubble["header"]["contents"][1]["text"]
    assert any(value == "N/A" for value in text_values)
    assert all(isinstance(value, str) and value.strip() for value in text_values)
    assert all(isinstance(color, str) and HEX_COLOR_RE.match(color) for color in color_values)


def test_canonical_recommendation_flex_accepts_daily_and_command_shapes():
    from utils.line_flex import build_recommendation_flex_message

    daily_message = build_recommendation_flex_message(
        [
            {
                "symbol": "NVDA",
                "latest_date": "2026-05-15",
                "xgboost_score": 0.72,
                "valuation_status": "PREMIUM_GROWTH",
                "buy_price": 118.0,
                "suggested_allocation_pct": 7.5,
                "ai_reason": "Daily morning setup",
            }
        ],
        title="Daily Screener",
    )
    command_message = build_recommendation_flex_message(
        [
            {
                "symbol": "NVDA",
                "rank": 1,
                "total_score": 86.4,
                "score": 86.4,
                "setup_type": "breakout",
                "reasons": ["Close broke above the 20-day high"],
                "risk_flags": ["Close is extended above MA20"],
                "valuation_status": "PREMIUM_GROWTH",
                "buy_price": 118.0,
                "suggested_allocation_pct": 7.5,
                "reason_summary": "Daily morning setup",
            }
        ],
        title="Command Top5",
    )

    for message in (daily_message, command_message):
        payload = json.dumps(message, ensure_ascii=False)
        assert "Decision" in payload
        assert "Price / Target" in payload
        assert "Buy Below" in payload
        assert "Smart Money / AI" in payload
        assert "Reason" in payload
        assert "FAIR" in payload

    assert "breakout" in json.dumps(command_message, ensure_ascii=False)
    assert "AI Score" not in json.dumps(command_message, ensure_ascii=False)


def test_canonical_recommendation_flex_sanitizes_invalid_values():
    from utils.line_flex import build_recommendation_flex_message

    message = build_recommendation_flex_message(
        [
            {
                "symbol": "NVDA",
                "xgboost_score": math.nan,
                "total_score": float("inf"),
                "valuation_status": "EXPERIMENTAL_STATUS",
                "buy_price": float("-inf"),
                "suggested_allocation_pct": math.nan,
                "ai_reason": "x" * 500,
            }
        ],
        title="Invalid Samples",
    )

    payload = json.dumps(message, ensure_ascii=False)
    assert "NaN" not in payload
    assert "Infinity" not in payload
    assert "Decision" in payload
    assert "N/A" in payload
