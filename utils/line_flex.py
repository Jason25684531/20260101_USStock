"""Shared LINE Flex formatting helpers for web and strategy runtimes."""

from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


FAIR_LABEL = "FAIR"
FAIR_COLOR = "#FFA000"
NEUTRAL_COLOR = "#555555"
WHITE_COLOR = "#FFFFFF"
BODY_TEXT_COLOR = "#111111"
MUTED_TEXT_COLOR = "#666666"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
STATUS_STYLE_MAP = {
    "UNDERVALUED": ("UNDERVALUED", "#00C853"),
    "FAIR": (FAIR_LABEL, FAIR_COLOR),
    "PREMIUM_GROWTH": (FAIR_LABEL, FAIR_COLOR),
    "OVERVALUED": ("OVERVALUED", "#FF1744"),
}


def _safe_text(value: Any, fallback: str = "N/A") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)) and not pd.notna(value):
        return fallback
    text = str(value).strip()
    if text.lower() in {"nan", "inf", "-inf", "infinity", "-infinity"}:
        return fallback
    return (text[:237] + "...") if len(text) > 240 else (text or fallback)


def _safe_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if HEX_COLOR_RE.match(text) else fallback


def sanitize_flex_component(component: Any) -> Any:
    if isinstance(component, list):
        return [sanitize_flex_component(item) for item in component]

    if isinstance(component, dict):
        sanitized = {}
        for key, value in component.items():
            if key == "text":
                sanitized[key] = _safe_text(value)
            elif key == "altText":
                sanitized[key] = _safe_text(value, "Stock update")
            elif key == "color":
                sanitized[key] = _safe_color(value, NEUTRAL_COLOR)
            elif key == "backgroundColor":
                sanitized[key] = _safe_color(value, FAIR_COLOR)
            else:
                sanitized[key] = sanitize_flex_component(value)
        return sanitized

    return component


def sanitize_line_message(message: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_flex_component(dict(message))


def flex_kv(label: str, value: str) -> dict:
    return sanitize_flex_component(
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": _safe_text(label), "size": "sm", "color": NEUTRAL_COLOR, "flex": 0},
                {
                    "type": "text",
                    "text": _safe_text(value),
                    "size": "sm",
                    "color": BODY_TEXT_COLOR,
                    "align": "end",
                    "wrap": True,
                },
            ],
        }
    )


def flex_section_title(title: str) -> dict:
    return sanitize_flex_component(
        {
            "type": "text",
            "text": _safe_text(title),
            "size": "xs",
            "weight": "bold",
            "color": "#333333",
            "margin": "sm",
        }
    )


def get_valuation_style(rec: Mapping) -> tuple[str, str]:
    valuation_status = _safe_text(rec.get("valuation_status"), "FAIR").upper()
    label, color = STATUS_STYLE_MAP.get(valuation_status, STATUS_STYLE_MAP["FAIR"])
    return label, _safe_color(color, FAIR_COLOR)


def format_currency(value, prefix: str = "$") -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{prefix}{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def format_price_pair(rec: Mapping) -> str:
    return f"{format_currency(rec.get('current_price'))} / {format_currency(rec.get('target_price'))}"


def format_support_resistance_pair(rec: Mapping) -> str:
    return f"{format_currency(rec.get('support_1'))} / {format_currency(rec.get('resistance_1'))}"


def format_price_bound(value, operator: str) -> str:
    formatted = format_currency(value)
    return f"{operator} {formatted}" if formatted != "N/A" else "N/A"


def format_institutional_ownership(value) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return f"{numeric:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _safe_number(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def format_holder_count(value) -> str:
    numeric = _safe_number(value)
    if numeric is None or numeric < 0:
        return "N/A"
    return str(int(round(numeric)))


def format_signed_score(value) -> str:
    numeric = _safe_number(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:.2f}"


def format_sentiment_score(value) -> str:
    numeric = _safe_number(value)
    if numeric is None:
        return "N/A"
    numeric = max(-1.0, min(1.0, numeric))
    return f"{numeric:+.2f}"


def format_whale_holder_pair(rec: Mapping) -> str:
    return f"{format_institutional_ownership(rec.get('whale_held_pct'))} / {format_holder_count(rec.get('inst_count'))}"


def format_net_sentiment_pair(rec: Mapping) -> str:
    return f"{format_signed_score(rec.get('institutional_net_buy'))} / {format_sentiment_score(rec.get('sentiment_score'))}"


def format_insider_sentiment(value) -> str:
    sentiment = _safe_text(value, "NEUTRAL").upper()
    label_map = {
        "BUYING": "BUYING",
        "SELLING": "SELLING",
        "NEUTRAL": "-",
    }
    return label_map.get(sentiment, "NEUTRAL")


def format_smart_money_pair(rec: Mapping) -> str:
    institutional = format_institutional_ownership(rec.get("institutional_ownership"))
    insider = format_insider_sentiment(rec.get("insider_sentiment"))
    return f"{institutional} / {insider}"


def format_smart_money_trend(rec: Mapping) -> str:
    explicit = rec.get("smart_money_trend")
    if explicit:
        return _safe_text(explicit)

    institutional_pass = rec.get("institutional_pass")
    money_flow_pass = rec.get("money_flow_pass")
    insider_sentiment = _safe_text(rec.get("insider_sentiment"), "NEUTRAL").upper()

    if institutional_pass is True and money_flow_pass is True:
        return "Strong"
    if institutional_pass is True:
        return "Institutional"
    if money_flow_pass is True:
        return "Money Flow"
    if insider_sentiment == "BUYING":
        return "Insider Buying"
    if institutional_pass is False or insider_sentiment == "SELLING":
        return "Cautious"
    return "Neutral"


def format_today_flow(rec: Mapping) -> str:
    flow = rec.get("today_flow") if isinstance(rec.get("today_flow"), Mapping) else None
    if flow:
        rows = flow.get("rows") or []
        if flow.get("is_fallback"):
            return "Fallback"

        parts: list[str] = []
        trade_date = _safe_text(flow.get("trade_date"), "")
        if trade_date:
            parts.append(trade_date[5:] if len(trade_date) >= 10 else trade_date)
        row_parts = []
        for row in rows:
            label = _safe_text(row.get("label"), "")
            value = _safe_text(row.get("value"), "")
            if not label or not value:
                continue
            row_parts.append(f"{label} {value}")
        if row_parts:
            parts.append(" / ".join(row_parts))
        return " ".join(part for part in parts if part).strip() or "N/A"

    summary = rec.get("today_flow_summary")
    if summary:
        return _safe_text(summary)
    return "Fallback"


def format_ml_confidence(value) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return f"{numeric:.0f}%"
    except (TypeError, ValueError):
        return "N/A"


def build_decision_bubble(rec: Mapping) -> dict:
    valuation_text, header_color = get_valuation_style(rec)

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": header_color,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": _safe_text(rec.get("symbol")),
                    "weight": "bold",
                    "size": "xl",
                    "color": WHITE_COLOR,
                },
                {
                    "type": "text",
                    "text": f"Valuation {valuation_text}",
                    "size": "sm",
                    "color": "#F9FAFB",
                    "wrap": True,
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "14px",
            "contents": [
                flex_section_title("Decision"),
                flex_kv("Price / Target", format_price_pair(rec)),
                flex_kv("Support / Resistance", format_support_resistance_pair(rec)),
                flex_kv("Buy Below", format_price_bound(rec.get("buy_price"), "<")),
                flex_kv("Sell Above", format_price_bound(rec.get("sell_price"), ">")),
                flex_section_title("Smart Money / AI"),
                flex_kv("Institutional / Insider", format_smart_money_pair(rec)),
                flex_kv("Whale / Holders", format_whale_holder_pair(rec)),
                flex_kv("Net Buy / Sentiment", format_net_sentiment_pair(rec)),
                flex_kv("Trend", format_smart_money_trend(rec)),
                flex_kv("Today Flow", format_today_flow(rec)),
                flex_kv("ML Confidence", format_ml_confidence(rec.get("ml_confidence"))),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "14px",
            "contents": [
                {"type": "separator", "margin": "sm"},
                {
                    "type": "text",
                    "text": "Reason",
                    "size": "sm",
                    "color": "#333333",
                    "weight": "bold",
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": _safe_text(rec.get("reason_summary"), "No summary"),
                    "size": "xs",
                    "color": MUTED_TEXT_COLOR,
                    "wrap": True,
                    "margin": "sm",
                },
            ],
        },
    }
    return sanitize_flex_component(bubble)
