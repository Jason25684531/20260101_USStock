"""Shared presentation helpers for Dashboard and LineBot read paths."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any


def json_loads_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            pass
    return str(value)[:10]


def format_signed_number(value: Any) -> str:
    numeric = to_float(value)
    if numeric is None:
        return "N/A"

    sign = "+" if numeric > 0 else ""
    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f"{numeric / 1_000_000_000:.2f}B"
    elif abs_value >= 1_000_000:
        formatted = f"{numeric / 1_000_000:.2f}M"
    elif abs_value >= 1_000:
        formatted = f"{numeric:,.0f}"
    else:
        formatted = f"{numeric:.0f}"
    return f"{sign}{formatted}"


def format_compact_number(value: Any, suffix: str = "") -> str | None:
    numeric = to_float(value)
    if numeric is None:
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f"{numeric / 1_000_000_000:.2f}B"
    elif abs_value >= 1_000_000:
        formatted = f"{numeric / 1_000_000:.2f}M"
    elif abs_value >= 1_000:
        formatted = f"{numeric / 1_000:.2f}K"
    else:
        formatted = f"{numeric:.0f}"
    return f"{formatted}{suffix}"


def format_money_compact(value: Any) -> str | None:
    numeric = to_float(value)
    if numeric is None:
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        return f"${numeric / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"${numeric / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"${numeric / 1_000:.2f}K"
    return f"${numeric:.2f}"


def derive_flow_value(row, net_key, buy_key, sell_key) -> float | None:
    net_value = to_float(row.get(net_key)) if net_key else None
    if net_value is not None:
        return net_value

    buy_value = to_float(row.get(buy_key)) if buy_key else None
    sell_value = to_float(row.get(sell_key)) if sell_key else None
    if buy_value is not None and sell_value is not None:
        return buy_value - sell_value
    return None
