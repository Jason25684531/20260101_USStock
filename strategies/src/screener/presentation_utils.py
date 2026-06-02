from __future__ import annotations

import math
import json
import re
from typing import Any


NEUTRAL_COLOR = "#555555"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def safe_text(value: Any, fallback: str = "N/A", *, max_length: int = 240) -> str:
    if value is None:
        return fallback
    if isinstance(value, float) and not math.isfinite(value):
        return fallback
    text = str(value).strip()
    if text.lower() in {"nan", "inf", "-inf", "infinity", "-infinity"}:
        return fallback
    if not text:
        return fallback
    if len(text) > max_length:
        return text[: max(max_length - 3, 0)] + "..."
    return text


def safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def bounded_list(value: Any, *, limit: int = 3) -> list[Any]:
    return safe_list(value)[: max(int(limit or 0), 0)]


def safe_pct_return(current: Any, past: Any, *, max_abs_return: float = 3.0) -> float | None:
    current_value = safe_float(current)
    past_value = safe_float(past)
    if current_value is None or past_value is None:
        return None
    if past_value <= 0:
        return None
    result = (current_value - past_value) / past_value
    if not math.isfinite(result):
        return None
    if abs(result) > max_abs_return:
        return None
    return round(result, 10)


def format_metric_or_na(value: Any, *, suffix: str = "", scale: float = 1.0, decimals: int = 2) -> str:
    number = safe_float(value)
    if number is None:
        return "N/A"
    return f"{number * scale:.{decimals}f}{suffix}"


def format_status_label(value: Any) -> str:
    return safe_text(value, "Unknown").replace("_", " ").title()


def format_recommendation_source(value: Any) -> str:
    mapping = {
        "current_run": "Current run",
        "last_valid_snapshot": "Last valid snapshot",
        "unknown": "Unknown",
    }
    key = str(value or "unknown")
    return mapping.get(key, format_status_label(key))


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _safe_color(value: Any, fallback: str = NEUTRAL_COLOR) -> str:
    text = str(value or "").strip()
    return text if HEX_COLOR_RE.match(text) else fallback


def sanitize_for_line_flex(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_for_line_flex(item) for item in value[:50]]
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key in {"text", "altText"}:
                sanitized[key] = safe_text(item, "Stock update" if key == "altText" else "N/A")
            elif key in {"color", "backgroundColor"}:
                sanitized[key] = _safe_color(item)
            else:
                sanitized[key] = sanitize_for_line_flex(item)
        return sanitized
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
