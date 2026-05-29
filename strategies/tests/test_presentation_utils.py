import math

from screener.presentation_utils import (
    bounded_list,
    format_metric_or_na,
    format_recommendation_source,
    format_status_label,
    safe_list,
    safe_pct_return,
    safe_text,
    sanitize_for_json,
    sanitize_for_line_flex,
)


def test_safe_pct_return_rejects_missing_and_invalid_base():
    assert safe_pct_return(None, 100) is None
    assert safe_pct_return(100, None) is None
    assert safe_pct_return(100, 0) is None
    assert safe_pct_return(100, -5) is None


def test_safe_pct_return_rejects_non_finite_and_outliers():
    assert safe_pct_return(math.nan, 100) is None
    assert safe_pct_return(math.inf, 100) is None
    assert safe_pct_return(500, 100, max_abs_return=3.0) is None


def test_safe_pct_return_keeps_normal_returns():
    assert safe_pct_return(112, 100) == 0.12
    assert safe_pct_return(88, 100) == -0.12


def test_format_metric_or_na_handles_none_and_numbers():
    assert format_metric_or_na(None) == "N/A"
    assert format_metric_or_na(0.1234, suffix="%", scale=100, decimals=1) == "12.3%"


def test_shared_helpers_sanitize_text_lists_and_status():
    assert safe_text(None) == "N/A"
    assert safe_text("x" * 300, max_length=12).endswith("...")
    assert safe_list('["a", "b"]') == ["a", "b"]
    assert bounded_list(["a", "b", "c"], limit=2) == ["a", "b"]
    assert format_status_label("fallback_to_default") == "Fallback To Default"
    assert format_recommendation_source("last_valid_snapshot") == "Last valid snapshot"


def test_sanitize_for_json_and_line_flex_remove_non_finite_values():
    payload = {"value": math.inf, "items": [1, math.nan], "text": "hello"}

    assert sanitize_for_json(payload) == {"value": None, "items": [1, None], "text": "hello"}
    flex = sanitize_for_line_flex({"type": "text", "text": math.nan, "color": "not-a-color"})
    assert flex["text"] == "N/A"
    assert flex["color"] == "#555555"
