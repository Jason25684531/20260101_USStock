"""Shared LINE Flex formatting helpers."""

from typing import Mapping

import pandas as pd


def flex_kv(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#555555", "flex": 0},
            {"type": "text", "text": value, "size": "sm", "color": "#111111", "align": "end", "wrap": True},
        ],
    }


def flex_section_title(title: str) -> dict:
    return {
        "type": "text",
        "text": title,
        "size": "xs",
        "weight": "bold",
        "color": "#333333",
        "margin": "sm",
    }


def get_valuation_style(rec: Mapping) -> tuple[str, str]:
    valuation_status = str(rec.get('valuation_status') or 'FAIR').upper()
    style_map = {
        'UNDERVALUED': ('UNDERVALUED', '#00C853'),
        'FAIR': ('FAIR', '#FFA000'),
        'OVERVALUED': ('OVERVALUED', '#FF1744'),
    }
    return style_map.get(valuation_status, (valuation_status, '#555555'))


def format_currency(value, prefix: str = '$') -> str:
    try:
        if value is None or pd.isna(value):
            return 'N/A'
        return f"{prefix}{float(value):.2f}"
    except (TypeError, ValueError):
        return 'N/A'


def format_price_pair(rec: Mapping) -> str:
    return f"{format_currency(rec.get('current_price'))} / {format_currency(rec.get('target_price'))}"


def format_support_resistance_pair(rec: Mapping) -> str:
    return f"{format_currency(rec.get('support_1'))} / {format_currency(rec.get('resistance_1'))}"


def format_price_bound(value, operator: str) -> str:
    formatted = format_currency(value)
    return f"{operator} {formatted}" if formatted != 'N/A' else 'N/A'


def format_institutional_ownership(value) -> str:
    try:
        if value is None or pd.isna(value):
            return 'N/A'
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return f"{numeric:.1f}%"
    except (TypeError, ValueError):
        return 'N/A'


def format_insider_sentiment(value) -> str:
    sentiment = str(value or 'NEUTRAL').upper()
    label_map = {
        'BUYING': '🔥 BUYING',
        'SELLING': '❄️ SELLING',
        'NEUTRAL': '-',
    }
    return label_map.get(sentiment, sentiment)


def format_smart_money_pair(rec: Mapping) -> str:
    institutional = format_institutional_ownership(rec.get('institutional_ownership'))
    insider = format_insider_sentiment(rec.get('insider_sentiment'))
    return f"{institutional} / {insider}"


def format_ml_confidence(value) -> str:
    try:
        if value is None or pd.isna(value):
            return 'N/A'
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return f"{numeric:.0f}%"
    except (TypeError, ValueError):
        return 'N/A'


def build_decision_bubble(rec: Mapping) -> dict:
    valuation_text, header_color = get_valuation_style(rec)

    body_contents = [
        flex_section_title("📊 決策定錨"),
        flex_kv("現價 / 目標", format_price_pair(rec)),
        flex_kv("支撐 / 壓力", format_support_resistance_pair(rec)),
        flex_kv("建議買入", format_price_bound(rec.get('buy_price'), '<')),
        flex_kv("預期賣出", format_price_bound(rec.get('sell_price'), '>')),
        flex_section_title("🏦 籌碼與 AI"),
        flex_kv("法人 / 內部人", format_smart_money_pair(rec)),
        flex_kv("🤖 AI 勝率", format_ml_confidence(rec.get('ml_confidence'))),
    ]

    return {
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
                    "text": str(rec.get('symbol') or 'N/A'),
                    "weight": "bold",
                    "size": "xl",
                    "color": "#FFFFFF",
                },
                {
                    "type": "text",
                    "text": f"估值：{valuation_text}",
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
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "14px",
            "contents": [
                {"type": "separator", "margin": "sm"},
                {
                    "type": "text",
                    "text": "💡 推薦理由",
                    "size": "sm",
                    "color": "#333333",
                    "weight": "bold",
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": str(rec.get('reason_summary') or '策略指標符合預期'),
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                    "margin": "sm",
                },
            ],
        },
    }