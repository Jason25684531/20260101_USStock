"""LINE Flex builders for read-only LineBot query commands."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

try:
    from utils.line_flex import sanitize_line_message
except ImportError:  # pragma: no cover - fallback for alternate runtime path
    from strategies.src.utils.line_flex import sanitize_line_message  # type: ignore


GREEN = "#00C853"
AMBER = "#FFA000"
RED = "#FF1744"
BLUE = "#1565C0"
GRAY = "#555555"
LIGHT_GRAY = "#F5F5F5"
WHITE = "#FFFFFF"
BLACK = "#111111"
MUTED = "#666666"
LOW_ML_CONFIDENCE = 0.40


def _safe_text(value: Any, fallback: str = "N/A", limit: int = 160) -> str:
    if value is None:
        return fallback
    if isinstance(value, float) and not math.isfinite(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "inf", "-inf", "infinity", "-infinity", "none"}:
        return fallback
    return text[: limit - 3] + "..." if len(text) > limit else text


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value: Any) -> str:
    number = _safe_float(value)
    return "N/A" if number is None else f"${number:.2f}"


def _score(value: Any) -> str:
    number = _safe_float(value)
    return "N/A" if number is None else f"{number:.1f}"


def _percent(value: Any, *, anomaly_check: bool = False) -> tuple[str, bool]:
    number = _safe_float(value)
    if number is None:
        return "N/A", anomaly_check
    percent = number * 100 if abs(number) <= 20 else number
    anomalous = anomaly_check and abs(percent) > 1000
    return f"{percent:+.1f}%", anomalous


def _confidence(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "N/A"
    percent = number * 100 if number <= 1 else number
    return f"{percent:.0f}%"


def _status_color(status: Any) -> str:
    text = _safe_text(status, "WATCH").upper()
    if text in {"BUY", "RISK_ON", "UNDERVALUED", "HEALTHY"}:
        return GREEN
    if text in {"SELL", "RISK_OFF", "OVERVALUED", "FAILED", "CRITICAL"}:
        return RED
    return AMBER


def _regime_color(regime: Any) -> str:
    return {
        "RISK_ON": GREEN,
        "NEUTRAL": AMBER,
        "RISK_OFF": RED,
    }.get(_safe_text(regime, "NEUTRAL").upper(), GRAY)


def _kv(label: str, value: Any) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": _safe_text(label), "size": "sm", "color": MUTED, "flex": 4},
            {"type": "text", "text": _safe_text(value), "size": "sm", "color": BLACK, "align": "end", "wrap": True, "flex": 5},
        ],
    }


def _badge(text: str, color: str) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": color,
        "cornerRadius": "md",
        "paddingAll": "4px",
        "contents": [
            {"type": "text", "text": _safe_text(text, limit=40), "size": "xs", "color": WHITE, "weight": "bold", "align": "center"}
        ],
    }


def _warning(text: str) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#FFF3CD",
        "cornerRadius": "md",
        "paddingAll": "6px",
        "contents": [
            {"type": "text", "text": _safe_text(text, limit=120), "size": "xs", "color": "#7A4D00", "wrap": True}
        ],
    }


def _bubble(title: str, subtitle: str, color: str, body_contents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": _safe_text(title, limit=60), "color": WHITE, "weight": "bold", "size": "lg"},
                {"type": "text", "text": _safe_text(subtitle, limit=90), "color": WHITE, "size": "xs", "wrap": True},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "backgroundColor": WHITE,
            "contents": body_contents or [_kv("Status", "N/A")],
        },
    }


def _message(alt_text: str, contents: dict[str, Any]) -> dict[str, Any]:
    return sanitize_line_message({"type": "flex", "altText": _safe_text(alt_text, "Stock update", 380), "contents": contents})


def _valuation(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    valuation = payload.get("valuation")
    return valuation if isinstance(valuation, Mapping) else payload


def build_stock_check_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    valuation = _valuation(payload)
    signal = _safe_text(payload.get("signal"), "WATCH").upper()
    valuation_status = _safe_text(valuation.get("valuation_status") or payload.get("valuation_status"), "FAIR").upper()
    confidence = _safe_float(payload.get("ml_confidence"))
    warnings: list[dict[str, Any]] = []
    if signal == "BUY" and valuation_status == "OVERVALUED":
        warnings.append(_warning("BUY signal has valuation risk: valuation is OVERVALUED"))
    if confidence is None:
        warnings.append(_warning("ML confidence is unavailable"))
    elif confidence < LOW_ML_CONFIDENCE:
        warnings.append(_warning("ML confidence is low"))

    body = [
        _kv("Signal", signal),
        _kv("Score", _score(payload.get("total_score"))),
        _kv("Current Price", _money(payload.get("current_price"))),
        _kv("Support", _money(payload.get("support_1") or payload.get("support"))),
        _kv("Resistance", _money(payload.get("resistance_1") or payload.get("resistance"))),
        _kv("Regime", payload.get("macro_regime") or payload.get("regime")),
        _kv("ML Confidence", _confidence(payload.get("ml_confidence"))),
        _kv("Valuation", valuation_status),
        _kv("Buy Below", _money(valuation.get("buy_price") or valuation.get("buy_below"))),
        _kv("Fair Price", _money(valuation.get("fair_price") or valuation.get("target_price"))),
        _kv("Sell Above", _money(valuation.get("sell_price") or valuation.get("sell_above"))),
        _kv("Data Source", payload.get("data_quality") or payload.get("provider") or payload.get("source")),
    ]
    body.extend(warnings)
    bubble = _bubble(
        f"{_safe_text(payload.get('symbol'), 'UNKNOWN')} Stock Check",
        f"{signal} | {valuation_status}",
        _status_color(valuation_status if valuation_status != "FAIR" else signal),
        body,
    )
    return _message(f"{_safe_text(payload.get('symbol'), 'Stock')} stock check", bubble)


def _recommendation_bubble(rec: Mapping[str, Any], degraded: bool = False) -> dict[str, Any]:
    signal = _safe_text(rec.get("signal") or rec.get("signal_type"), "WATCH").upper()
    valuation = _safe_text(rec.get("valuation_status"), "FAIR").upper()
    header = "DATA DEGRADED" if degraded else signal
    body = [
        _kv("Signal", signal),
        _kv("Score", _score(rec.get("total_score") or rec.get("score"))),
        _kv("Current Price", _money(rec.get("current_price"))),
        _kv("Valuation", valuation),
        _kv("ML Confidence", _confidence(rec.get("ml_confidence"))),
        _kv("Reason", rec.get("reason_summary") or rec.get("reason") or "N/A"),
    ]
    setup = rec.get("setup_type")
    if setup:
        body.append(_kv("Setup", setup))
    reasons = rec.get("reasons") or []
    if reasons:
        body.append(_kv("Top Reason", reasons[0]))
    risk_flags = rec.get("risk_flags") or []
    if risk_flags:
        body.append(_warning(_safe_text(risk_flags[0], limit=120)))
    return _bubble(
        f"#{_safe_text(rec.get('rank'), '-')} {_safe_text(rec.get('symbol'), 'UNKNOWN')}",
        f"{header} | Score {_score(rec.get('total_score') or rec.get('score'))}",
        RED if degraded else _status_color(signal),
        body,
    )


def build_recommendations_carousel(
    recommendations: Iterable[Mapping[str, Any]],
    title: str = "Recommendations",
    degraded: bool = False,
) -> dict[str, Any]:
    bubbles = [_recommendation_bubble(rec, degraded=degraded) for rec in list(recommendations)[:10]]
    if not bubbles:
        bubbles = [_recommendation_bubble({"symbol": "N/A", "reason_summary": "No recommendations"}, degraded=degraded)]
    return _message(
        _safe_text(title, "Recommendations"),
        {"type": "carousel", "contents": bubbles},
    )


def build_market_regime_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    regime = _safe_text(payload.get("regime") or payload.get("macro_regime"), "UNKNOWN").upper()
    body = [
        _kv("Regime", regime),
        _kv("VIX", _safe_text(payload.get("vix"), "N/A")),
        _kv("Yield Curve", _safe_text(payload.get("yield_curve"), "N/A")),
        _kv("Unemployment", _safe_text(payload.get("unemployment"), "N/A")),
        _kv("Fed Rate", _safe_text(payload.get("fed_rate"), "N/A")),
        _kv("Explanation", payload.get("description") or payload.get("explanation")),
    ]
    return _message("Macro regime", _bubble("Macro Regime", regime, _regime_color(regime), body))


def build_sector_ranking_message(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in list(rows)[:10]:
        r20, anomaly_20 = _percent(row.get("return_20d"), anomaly_check=True)
        r63, anomaly_63 = _percent(row.get("return_63d"), anomaly_check=True)
        body.extend(
            [
                _kv(
                    f"#{_safe_text(row.get('rank') or row.get('rank_position'), '-')} {_safe_text(row.get('sector') or row.get('sector_name'), 'Unknown')}",
                    _safe_text(row.get("etf") or row.get("etf_symbol"), "N/A"),
                ),
                _kv("20D / 63D", f"{r20} / {r63}"),
            ]
        )
        if anomaly_20 or anomaly_63:
            body.append(_warning("DATA ANOMALY: momentum value is missing, invalid, or extreme"))
    return _message("Sector ranking", _bubble("Sector Ranking", "Momentum overview", BLUE, body or [_kv("Sector", "N/A")]))


def build_history_recommendation_message(date_text: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = [_kv("Date", date_text)]
    for row in list(rows)[:10]:
        body.append(
            _kv(
                f"#{_safe_text(row.get('rank') or row.get('rank_position'), '-')} {_safe_text(row.get('symbol'), 'UNKNOWN')}",
                f"{_safe_text(row.get('signal') or row.get('signal_type'), 'WATCH')} | Score {_score(row.get('total_score') or row.get('score'))} | ML {_confidence(row.get('ml_confidence'))}",
            )
        )
    return _message("History recommendations", _bubble("History Recommendations", date_text, BLUE, body))


def build_ml_prediction_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = [
        _kv("Date", payload.get("date") or payload.get("entry_date") or payload.get("scan_date")),
        _kv("Price", _money(payload.get("price") or payload.get("entry_price") or payload.get("current_price"))),
        _kv("Score", _score(payload.get("score") or payload.get("total_score"))),
        _kv("Signal", payload.get("signal") or payload.get("signal_type")),
        _kv("ML Confidence", _confidence(payload.get("ml_confidence") or payload.get("confidence"))),
        _kv("Support", _money(payload.get("support") or payload.get("support_1"))),
        _kv("Resistance", _money(payload.get("resistance") or payload.get("resistance_1"))),
    ]
    symbol = _safe_text(payload.get("symbol"), "UNKNOWN")
    return _message(f"{symbol} ML prediction", _bubble(f"{symbol} ML Prediction", "Model signal", BLUE, body))


def build_strategies_summary_message() -> dict[str, Any]:
    body = [
        _kv("Rules", "11 rule strategies"),
        _kv("ML", "XGBoost confidence weighting"),
        _kv("Scope", "Summary only"),
    ]
    return _message("Strategy summary", _bubble("Strategy Summary", "11 rules + ML", GRAY, body))
