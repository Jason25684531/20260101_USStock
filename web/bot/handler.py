"""
Line Bot Webhook 處理器

處理來自 Line Platform 的 Webhook 請求。
支援簽名驗證、互動命令（Top5 / ML）、Flex Message 回覆。

Author: Quant System
Created: 2026-01-31
Updated: 2026-02-12 - 新增 Top5、ML 命令；Flex Message 回覆；DB 查詢整合
"""

import os
import sys
import importlib
import hashlib
import hmac
import base64
import json
import logging
import math
import re
import threading
import requests as http_requests
from pathlib import Path
from typing import Optional, List, Callable
from datetime import datetime
from flask import Blueprint, request, abort, jsonify
from functools import wraps
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from security import get_secret
from db import get_engine, table_exists as _table_exists, column_exists as _column_exists

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STRATEGIES_SRC = _PROJECT_ROOT / 'strategies' / 'src'
_STRATEGIES_SRC_STR = str(_STRATEGIES_SRC)
if _STRATEGIES_SRC_STR not in sys.path:
    sys.path.insert(0, _STRATEGIES_SRC_STR)

from policies.valuation import GrowthAwarePolicy
from screener.market_data_resilience import (
    empty_provider_health as _empty_provider_health_contract,
    normalize_provider_health,
)
from screener.swing_calibration import build_calibration_status, load_active_calibration_profile
from screener.swing_calibration_drift import build_drift_report, read_recent_calibration_audit_events
from screener.swing_ranking import normalize_swing_ranking_metadata
from screener.swing_performance import build_performance_payload, load_swing_performance_rows
from screener.presentation_utils import safe_float as _shared_safe_float

try:
    from utils.line_flex import (
        build_decision_bubble as _build_decision_bubble,
        build_recommendation_flex_message as _build_recommendation_flex_message,
        sanitize_line_message as _sanitize_line_message,
    )  # type: ignore[reportMissingImports]
except ImportError:
    _line_flex_module = importlib.import_module('utils.line_flex')
    _build_decision_bubble = _line_flex_module.build_decision_bubble
    _build_recommendation_flex_message = _line_flex_module.build_recommendation_flex_message
    _sanitize_line_message = _line_flex_module.sanitize_line_message

from . import flex_messages

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)

CALIBRATION_FALLBACK_TEXT = "Calibration 狀態暫時無法取得，請稍後再試。"
CALIBRATION_COMMAND = "/calibration"

# ============================================
# Blueprint & Secrets
# ============================================
line_bot_bp = Blueprint('line_bot', __name__)

CHANNEL_SECRET = get_secret('line_channel_secret', '')
CHANNEL_TOKEN = get_secret('line_channel_token', '')

# Lazy DB Engine
_db_engine = None


def _get_db_engine():
    """延遲初始化 DB 引擎"""
    global _db_engine
    if _db_engine is None:
        _db_engine = get_engine()
    return _db_engine


def _is_stale_mysql_connection_error(error: Exception) -> bool:
    message = str(error).lower()
    stale_markers = (
        "mysql connection not available",
        "server has gone away",
        "lost connection",
        "connection was killed",
        "connection reset",
        "connection refused",
        "can't connect to mysql server",
    )
    return isinstance(error, (OperationalError, DBAPIError)) and any(marker in message for marker in stale_markers)


def _dispose_db_engine(engine) -> None:
    global _db_engine
    try:
        engine.dispose()
    except Exception:
        pass
    if engine is _db_engine:
        _db_engine = None


def _execute_linebot_read(command_name: str, reader: Callable) -> object:
    last_error: Exception | None = None
    for attempt in range(2):
        engine = _get_db_engine()
        try:
            with engine.connect() as conn:
                return reader(conn)
        except Exception as error:
            last_error = error
            if _is_stale_mysql_connection_error(error) and attempt == 0:
                _log_linebot(f"LineBot command={command_name} stale DB connection; retrying once")
                _dispose_db_engine(engine)
                continue
            raise
    raise last_error or RuntimeError("LineBot DB read failed")


def _linebot_db_unavailable_message(command_name: str) -> str:
    return (
        f"{command_name} 資料庫暫時無法連線，已避免使用失效連線重試。"
        "請稍後再試，或檢查 MySQL / Docker 服務與資料庫連線狀態。"
    )


def _is_database_unavailable_error(error: Exception) -> bool:
    return _is_stale_mysql_connection_error(error) or isinstance(error, (OperationalError, DBAPIError))


def _json_loads_safe(value, default=None):
    if value in (None, ''):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _empty_provider_health():
    return _empty_provider_health_contract()


def _load_latest_provider_health(conn):
    if not _table_exists(conn, "provider_health_log"):
        return _empty_provider_health()

    row = conn.execute(text("""
        SELECT *
        FROM provider_health_log
        ORDER BY run_at DESC, id DESC
        LIMIT 1
    """)).mappings().first()
    if not row:
        return _empty_provider_health()

    return normalize_provider_health(dict(row))


def _provider_health_is_degraded(provider_health: dict) -> bool:
    provider_health = normalize_provider_health(provider_health)
    status = provider_health.get("status")
    mode = provider_health.get("current_data_mode")
    coverage = provider_health.get("provider_coverage_ratio")
    minimum = provider_health.get("minimum_coverage_ratio")
    return (
        status in {"degraded", "stale", "failed", "critical"}
        or
        mode in {"fallback", "stale", "failed"}
        or bool(provider_health.get("stale_data_used"))
        or (coverage is not None and minimum is not None and coverage < minimum)
    )


def _provider_health_text(provider_health: dict) -> str:
    provider_health = normalize_provider_health(provider_health)
    if not provider_health or not provider_health.get("provider_health_available", True):
        return "data_provider_mode=unknown root_cause=provider_health_unavailable 修復方式=確認 provider_health_log 是否存在並可讀取"
    coverage = provider_health.get("provider_coverage_ratio")
    coverage_text = "unknown" if coverage is None else f"{coverage:.2f}"
    top_errors = provider_health.get("top_error_types") or {}
    top_error_text = ",".join(f"{key}:{value}" for key, value in top_errors.items()) or "none"
    diagnostics = provider_health.get("diagnostics") or {}
    actions = diagnostics.get("operator_actions") or []
    action_text = "；".join(actions[:2]) if actions else "目前無需人工處理"
    stale_text = (
        f" stale_age_days={provider_health.get('stale_age_days')}"
        if provider_health.get("is_stale") and provider_health.get("stale_age_days") is not None
        else ""
    )
    last_valid = provider_health.get("last_valid_recommendation_at") or provider_health.get("last_valid_recommendation_time")
    last_valid_text = f" last_valid_recommendation_at={last_valid}" if last_valid else ""
    return (
        f"data_health={provider_health.get('status', 'unknown')} "
        f"data_provider_mode={provider_health.get('current_data_mode', 'unknown')} "
        f"coverage={coverage_text} "
        f"effective_provider={provider_health.get('effective_provider') or 'N/A'} "
        f"live={provider_health.get('live_successes', 0)} "
        f"fallback={provider_health.get('fallback_successes', 0)} "
        f"failed={provider_health.get('failed_symbols', 0)} "
        f"skipped={provider_health.get('skipped_symbols', 0)} "
        f"recommendation_source={provider_health.get('recommendation_source', 'unknown')} "
        f"top_errors={top_error_text}"
        f"{stale_text}"
        f"{last_valid_text}"
        f" root_cause={diagnostics.get('root_cause', 'unknown')}"
        f" fallback_outcome={diagnostics.get('fallback_outcome', 'unknown')}"
        f" 診斷={diagnostics.get('display_message', '資料健康狀態待確認')}"
        f" 修復方式={action_text}"
    )


def _load_latest_provider_health_for_linebot() -> dict:
    try:
        engine = _get_db_engine()
        with engine.connect() as conn:
            return _load_latest_provider_health(conn)
    except Exception:
        return _empty_provider_health()


def _provider_incident_note_for_linebot() -> str | None:
    provider_health = normalize_provider_health(_load_latest_provider_health_for_linebot())
    if not _provider_health_is_degraded(provider_health):
        return None
    diagnostics = provider_health.get("diagnostics") or {}
    root_cause = diagnostics.get("root_cause") or "unknown"
    status = provider_health.get("status") or "unknown"
    message = diagnostics.get("display_message") or "provider health degraded"
    return (
        f"Provider incident: {status} "
        f"root_cause={root_cause} "
        f"recommendation_source={provider_health.get('recommendation_source', 'unknown')} "
        f"- provider health separate from calibration quality. {message}"
    )


def _load_performance_payload_for_linebot() -> dict:
    engine = _get_db_engine()
    with engine.connect() as conn:
        if not _table_exists(conn, "swing_ranking_performance"):
            payload = build_performance_payload([])
            payload["calibration"] = build_calibration_status(load_active_calibration_profile())
            return payload
        rows = load_swing_performance_rows(conn, limit=500)
    payload = build_performance_payload(rows, recent_limit=0)
    payload["calibration"] = build_calibration_status(load_active_calibration_profile())
    return payload


def _load_calibration_drift_for_linebot() -> dict:
    engine = _get_db_engine()
    with engine.connect() as conn:
        if not _table_exists(conn, "swing_ranking_performance"):
            report = build_drift_report([], active_profile=load_active_calibration_profile())
            report["recent_audit_events"] = read_recent_calibration_audit_events(conn, limit=5)
            return report
        rows = load_swing_performance_rows(conn, limit=500)
        report = build_drift_report(rows, active_profile=load_active_calibration_profile())
        report["recent_audit_events"] = read_recent_calibration_audit_events(conn, limit=5)
        return report


def _pct_text(value, signed: bool = True) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "N/A"
    return f"{numeric * 100:+.1f}%" if signed else f"{numeric * 100:.1f}%"


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        numeric = float(value)
        if not math.isfinite(numeric):
            return default
        return int(numeric)
    except (TypeError, ValueError):
        return default


def _best_group(rows: list, name_key: str) -> tuple[str, str] | None:
    candidates = [
        row for row in rows or []
        if _safe_float(row.get("avg_forward_return_20d")) is not None and int(row.get("sample_size") or 0) > 0
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: _safe_float(row.get("avg_forward_return_20d")) or -999)
    return str(best.get(name_key) or "unknown"), _pct_text(best.get("avg_forward_return_20d"))


def _calibration_line(calibration: dict | None) -> str:
    calibration = calibration or {}
    status = calibration.get("status") or "inactive"
    sample_size = int(calibration.get("source_sample_size") or 0)
    version = calibration.get("active_profile_version") or calibration.get("version")
    if status == "active" and version:
        return f"Calibration: active {version} n={sample_size}"
    if status == "insufficient_data":
        required = calibration.get("min_sample_size") or "N/A"
        return f"Calibration: insufficient data n={sample_size}/{required}"
    if status == "fallback_to_default":
        reason = calibration.get("fallback_reason") or "invalid profile"
        return f"Calibration: default profile fallback ({reason})"
    return "Calibration: inactive/default profile"


def _calibration_status_text(value) -> str:
    return str(value or "unknown").replace("_", " ")


def _calibration_fallback_messages() -> List[dict]:
    return [_text_msg(CALIBRATION_FALLBACK_TEXT)]


def _normalize_command_text(value: str) -> str:
    return (value or "").strip().lower()


def _canonical_command_name(command: str) -> Optional[str]:
    if command in (CALIBRATION_COMMAND, "calibration"):
        return CALIBRATION_COMMAND
    if command:
        return command
    return None


def _message_tree_has_invalid_value(value, *, depth: int = 0) -> bool:
    if depth > 20:
        return True
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        if len(value) > 50:
            return True
        return any(_message_tree_has_invalid_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return any(_message_tree_has_invalid_value(item, depth=depth + 1) for item in value.values())
    return False


def _validate_line_messages_for_reply(messages: List[dict]) -> bool:
    if not isinstance(messages, list) or not messages or len(messages) > 5:
        return False
    for message in messages:
        if not isinstance(message, dict) or _message_tree_has_invalid_value(message):
            return False
        message_type = message.get("type")
        if message_type == "text":
            text = str(message.get("text") or "").strip()
            if not text or len(text) > 5000:
                return False
        elif message_type == "flex":
            alt_text = str(message.get("altText") or "").strip()
            contents = message.get("contents")
            if not alt_text or not isinstance(contents, dict) or not contents:
                return False
        else:
            return False
    return True


def _build_calibration_reply_messages(report: dict, provider_note: str | None = None) -> List[dict]:
    if not isinstance(report, dict):
        raise ValueError("calibration report must be a dict")
    if not report.get("active"):
        sample = _safe_int(report.get("sample_size"))
        lines = [
            "Calibration Drift",
            "Active: inactive/default profile",
            f"Status: {_calibration_status_text(report.get('drift_status'))}",
            f"Sample: {sample}",
        ]
        if provider_note:
            lines.append(provider_note)
        messages = [_text_msg("\n".join(lines))]
        if not _validate_line_messages_for_reply(messages):
            raise ValueError("invalid calibration reply payload")
        return messages

    lines = [
        "Calibration Drift",
        f"Active: {report.get('active_profile_version') or report.get('profile_version') or 'unknown'}",
        f"Status: {_calibration_status_text(report.get('drift_status'))}",
        f"Score bucket: {_calibration_status_text(report.get('score_bucket_status'))}",
        f"Top5: {_calibration_status_text(report.get('top_rank_status'))}",
        f"Risk flags: {_calibration_status_text(report.get('risk_flag_status'))}",
        f"Impact: {_calibration_status_text(report.get('calibration_impact_status'))}",
    ]
    report_messages = report.get("messages") if isinstance(report.get("messages"), list) else []
    for message in report_messages[:2]:
        lines.append(f"Note: {message}")
    if provider_note:
        lines.append(provider_note)
    messages = [_text_msg("\n".join(lines))]
    if not _validate_line_messages_for_reply(messages):
        raise ValueError("invalid calibration reply payload")
    return messages


def _cmd_calibration() -> List[dict]:
    try:
        report = _load_calibration_drift_for_linebot()
        provider_note = _provider_incident_note_for_linebot()
        return _build_calibration_reply_messages(report, provider_note)
    except Exception as error:
        _log_linebot(f"LineBot command=/calibration failed with exception: {type(error).__name__}: {error}")
        return _calibration_fallback_messages()


def _status_calibration_note() -> str | None:
    try:
        calibration = build_calibration_status(load_active_calibration_profile())
    except Exception:
        return None
    if calibration.get("status") == "fallback_to_default":
        return _calibration_line(calibration)
    return None


def _cmd_performance() -> List[dict]:
    try:
        payload = _load_performance_payload_for_linebot()
        summary = payload.get("summary") or {}
        sample_size = int(summary.get("sample_size") or 0)
        if sample_size <= 0:
            return [_text_msg("Swing ranking performance data is not available yet.")]

        best_setup = _best_group(payload.get("setup_types") or [], "setup_type")
        best_bucket = _best_group(payload.get("score_buckets") or [], "bucket")
        risk_group = next(
            (row for row in payload.get("risk_flags") or [] if row.get("group") == "any_risk_flag"),
            None,
        )
        lines = [
            "Swing Ranking Performance",
            f"Sample: {sample_size} recommendations",
            f"20D avg return: {_pct_text(summary.get('avg_forward_return_20d'))}",
            f"20D hit rate: {_pct_text(summary.get('hit_rate_20d'), signed=False)}",
        ]
        if best_setup:
            lines.append(f"Best setup: {best_setup[0]} {best_setup[1]}")
        if best_bucket:
            lines.append(f"Best score bucket: {best_bucket[0]} {best_bucket[1]}")
        if risk_group:
            lines.append(f"Risk-flagged avg return: {_pct_text(risk_group.get('avg_forward_return_20d'))}")
        lines.append(_calibration_line(payload.get("calibration")))
        provider_note = _provider_incident_note_for_linebot()
        if provider_note:
            lines.append(provider_note)
        return [_text_msg("\n".join(lines))]
    except Exception as error:
        _log_linebot(f"Performance summary failed: {error}")
        return [_text_msg("Swing ranking performance data is not available yet.")]


def _critical_provider_failure_message(summary: dict) -> str:
    coverage = float(summary.get("coverage_ratio", 0.0) or 0.0)
    mode = summary.get("current_data_mode", "failed")
    return "\n".join([
        "資料供應異常，這次 Top5 掃描未寫入空推薦。",
        f"current_data_mode={mode}, coverage={coverage:.2f}",
        "已保留上一輪有效推薦，請先檢查 OpenBB / yfinance / DB fallback。",
    ])


def _log_linebot(message):
    """Write LINE Bot logs without crashing on non-UTF-8 Windows consoles."""
    text = str(message)
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
        print(safe_text)


_TICKER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_VALUATION_POLICY = GrowthAwarePolicy()


def _safe_float(value):
    return _shared_safe_float(value)


def _format_price(value):
    numeric = _safe_float(value)
    if numeric is None:
        return "N/A"
    return f"${numeric:.2f}"


def _format_percent(value):
    numeric = _safe_float(value)
    if numeric is None:
        return "N/A"
    if abs(numeric) <= 1:
        numeric *= 100
    return f"{numeric:.1f}%"


def _is_bare_ticker_command(text_value: str) -> bool:
    stripped = (text_value or "").strip()
    return bool(_TICKER_PATTERN.fullmatch(stripped))


def _nullable_bool(value):
    if value is None:
        return None
    return bool(value)


def _derive_eps_ttm(current_price, pe_ratio, forward_pe):
    price = _safe_float(current_price)
    pe = _safe_float(pe_ratio)
    if price and pe and pe > 0:
        return price / pe

    fpe = _safe_float(forward_pe)
    if price and fpe and fpe > 0:
        return price / fpe

    return None


def _coerce_strategy_lists(row_mapping):
    strategy_pairs = [
        ("Breakout", row_mapping.get("breakout_pass")),
        ("Acceleration", row_mapping.get("acceleration_pass")),
        ("PEG", row_mapping.get("peg_pass")),
        ("DuPont", row_mapping.get("dupont_pass")),
        ("Institutional", row_mapping.get("institutional_pass")),
        ("Volume", row_mapping.get("volume_structure_pass")),
        ("Money Flow", row_mapping.get("money_flow_pass")),
        ("Multi-TF", row_mapping.get("multi_tf_momentum_pass")),
        ("Relative Strength", row_mapping.get("relative_strength_pass")),
        ("Earnings Quality", row_mapping.get("earnings_quality_pass")),
        ("Sector Rotation", row_mapping.get("sector_rotation_pass")),
    ]
    passed = [name for name, flag in strategy_pairs if bool(flag)]
    failed = [name for name, flag in strategy_pairs if flag is not None and not bool(flag)]
    return passed, failed


def _load_stock_analysis_payload(conn, symbol: str) -> dict | None:
    recommendation = None
    if _table_exists(conn, "daily_recommendations"):
        recommendation = conn.execute(
            text(
                """
                SELECT symbol, scan_date, signal_type, total_score, current_price, ml_confidence,
                       support_1, resistance_1, macro_regime,
                       valuation_status, buy_price, sell_price,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                       institutional_pass, volume_structure_pass, money_flow_pass,
                       multi_tf_momentum_pass, relative_strength_pass,
                       earnings_quality_pass, sector_rotation_pass
                FROM daily_recommendations
                WHERE symbol = :sym
                ORDER BY scan_date DESC
                LIMIT 1
                """
            ),
            {"sym": symbol},
        ).mappings().first()

    registry = None
    if _table_exists(conn, "symbols_registry"):
        registry = conn.execute(
            text(
                """
                SELECT symbol, sector
                FROM symbols_registry
                WHERE symbol = :sym AND COALESCE(is_active, 0) = 1
                LIMIT 1
                """
            ),
            {"sym": symbol},
        ).mappings().first()

    fundamentals = None
    if _table_exists(conn, "stock_fundamentals"):
        fundamentals = conn.execute(
            text(
                """
                SELECT symbol, data_date, pe_ratio, forward_pe, peg_ratio, pb_ratio,
                       revenue_growth_yoy, earnings_growth_yoy, roe, profit_margin, sector
                FROM stock_fundamentals
                WHERE symbol = :sym
                ORDER BY data_date DESC
                LIMIT 1
                """
            ),
            {"sym": symbol},
        ).mappings().first()

    latest_price = None
    if _table_exists(conn, "price_data_v2"):
        latest_price = conn.execute(
            text(
                """
                SELECT close
                FROM price_data_v2
                WHERE symbol = :sym
                ORDER BY date DESC
                LIMIT 1
                """
            ),
            {"sym": symbol},
        ).scalar()

    if recommendation is None and registry is None and fundamentals is None and latest_price is None:
        return None

    current_price = (
        _safe_float(recommendation.get("current_price")) if recommendation is not None else None
    ) or _safe_float(latest_price)
    pe_ratio = _safe_float(fundamentals.get("pe_ratio")) if fundamentals is not None else None
    forward_pe = _safe_float(fundamentals.get("forward_pe")) if fundamentals is not None else None
    revenue_growth = _safe_float(fundamentals.get("revenue_growth_yoy")) if fundamentals is not None else None
    eps_ttm = _derive_eps_ttm(current_price, pe_ratio, forward_pe)
    valuation = _VALUATION_POLICY.evaluate(
        current_price=current_price,
        eps_ttm=eps_ttm,
        revenue_growth_yoy=revenue_growth,
    )

    passed = []
    failed = []
    if recommendation is not None:
        passed, failed = _coerce_strategy_lists(recommendation)

    return {
        "symbol": symbol,
        "scan_date": str(recommendation.get("scan_date")) if recommendation is not None and recommendation.get("scan_date") else None,
        "signal": recommendation.get("signal_type") if recommendation is not None else "WATCH",
        "total_score": _safe_float(recommendation.get("total_score")) if recommendation is not None else None,
        "current_price": current_price,
        "support_1": _safe_float(recommendation.get("support_1")) if recommendation is not None else None,
        "resistance_1": _safe_float(recommendation.get("resistance_1")) if recommendation is not None else None,
        "macro_regime": recommendation.get("macro_regime") if recommendation is not None else None,
        "ml_confidence": _safe_float(recommendation.get("ml_confidence")) if recommendation is not None else None,
        "fundamentals": {
            "eps_ttm": eps_ttm,
            "pe_ratio": pe_ratio,
            "forward_pe": forward_pe,
            "peg_ratio": _safe_float(fundamentals.get("peg_ratio")) if fundamentals is not None else None,
            "pb_ratio": _safe_float(fundamentals.get("pb_ratio")) if fundamentals is not None else None,
            "roe": _safe_float(fundamentals.get("roe")) if fundamentals is not None else None,
            "profit_margin": _safe_float(fundamentals.get("profit_margin")) if fundamentals is not None else None,
            "revenue_growth_yoy": revenue_growth,
            "sector": (fundamentals.get("sector") if fundamentals is not None else None)
            or (registry.get("sector") if registry is not None else None),
        },
        "valuation": valuation,
        "strategies_passed": passed,
        "strategies_failed": failed,
        "source": "daily_recommendations" if recommendation is not None else "registry_fallback",
    }


def _build_stock_analysis_message(payload: dict) -> str:
    fundamentals = payload.get("fundamentals") or {}
    valuation = payload.get("valuation") or _VALUATION_POLICY.evaluate(
        current_price=payload.get("current_price"),
        eps_ttm=fundamentals.get("eps_ttm") or _derive_eps_ttm(
            payload.get("current_price"),
            fundamentals.get("pe_ratio"),
            fundamentals.get("forward_pe"),
        ),
        revenue_growth_yoy=fundamentals.get("revenue_growth_yoy"),
    )
    passed = payload.get("strategies_passed") or []
    failed = payload.get("strategies_failed") or []
    total_strategies = len(passed) + len(failed)
    confidence = _safe_float(payload.get("ml_confidence"))
    confidence_text = f"{confidence:.0%}" if confidence is not None else "N/A"

    lines = [
        f"🔎 {payload.get('symbol', 'N/A')} Stock Check",
        f"Date: {payload.get('scan_date') or 'N/A'} | Signal: {payload.get('signal') or 'WATCH'} | Score: {payload.get('total_score') or 0:.1f}" if payload.get("total_score") is not None else f"Date: {payload.get('scan_date') or 'N/A'} | Signal: {payload.get('signal') or 'WATCH'}",
        f"Current: {_format_price(payload.get('current_price'))} | Support: {_format_price(payload.get('support_1'))} | Resistance: {_format_price(payload.get('resistance_1'))}",
        f"Regime: {payload.get('macro_regime') or 'N/A'} | ML Confidence: {confidence_text}",
        "",
        f"Valuation: {valuation.get('valuation_status', 'FAIR')}",
        f"Buy Below: {_format_price(valuation.get('buy_price'))}",
        f"Fair Price: {_format_price(valuation.get('fair_price'))}",
        f"Sell Above: {_format_price(valuation.get('sell_price'))}",
        "",
        "Fundamentals:",
        f"PE {fundamentals.get('pe_ratio') if fundamentals.get('pe_ratio') is not None else 'N/A'} | PEG {fundamentals.get('peg_ratio') if fundamentals.get('peg_ratio') is not None else 'N/A'} | PB {fundamentals.get('pb_ratio') if fundamentals.get('pb_ratio') is not None else 'N/A'}",
        f"Revenue Growth: {_format_percent(fundamentals.get('revenue_growth_yoy'))} | ROE: {_format_percent(fundamentals.get('roe'))} | Margin: {_format_percent(fundamentals.get('profit_margin'))}",
        f"Sector: {fundamentals.get('sector') or 'N/A'}",
    ]

    if total_strategies:
        lines.extend(
            [
                "",
                f"Strategies Passed ({len(passed)}/{total_strategies}): {', '.join(passed) if passed else 'None'}",
                f"Strategies Failed: {', '.join(failed) if failed else 'None'}",
            ]
        )

    return "\n".join(lines)


INSTITUTIONAL_FLOW_TABLE_CANDIDATES = (
    {
        'table': 'institutional_trading_daily',
        'date': ['date', 'trade_date', 'data_date'],
        'foreign_net': ['foreign_net', 'foreign_net_shares', 'foreign_net_volume'],
        'foreign_buy': ['foreign_buy', 'foreign_buy_shares'],
        'foreign_sell': ['foreign_sell', 'foreign_sell_shares'],
        'trust_net': ['investment_trust_net', 'trust_net', 'institutional_trust_net'],
        'trust_buy': ['investment_trust_buy', 'trust_buy'],
        'trust_sell': ['investment_trust_sell', 'trust_sell'],
        'dealer_net': ['dealer_net', 'self_dealer_net', 'proprietary_trader_net'],
        'dealer_buy': ['dealer_buy', 'self_dealer_buy'],
        'dealer_sell': ['dealer_sell', 'self_dealer_sell'],
    },
    {
        'table': 'institutional_flows',
        'date': ['date', 'trade_date', 'data_date'],
        'foreign_net': ['foreign_net'],
        'foreign_buy': ['foreign_buy'],
        'foreign_sell': ['foreign_sell'],
        'trust_net': ['trust_net', 'investment_trust_net'],
        'trust_buy': ['trust_buy', 'investment_trust_buy'],
        'trust_sell': ['trust_sell', 'investment_trust_sell'],
        'dealer_net': ['dealer_net'],
        'dealer_buy': ['dealer_buy'],
        'dealer_sell': ['dealer_sell'],
    },
)


def _resolve_existing_column(conn, table_name, column_candidates):
    for column_name in column_candidates:
        if _column_exists(conn, table_name, column_name):
            return column_name
    return None


def _select_optional_column(conn, table_name, column_candidates, alias, default_sql='NULL'):
    column_name = _resolve_existing_column(conn, table_name, column_candidates)
    if column_name:
        return f'{column_name} AS {alias}'
    return f'{default_sql} AS {alias}'


def _format_trade_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    if hasattr(value, 'strftime'):
        try:
            return value.strftime('%Y-%m-%d')
        except Exception:
            pass
    return str(value)[:10]


def _format_signed_number(value):
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return 'N/A'

    sign = '+' if numeric > 0 else ''
    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f'{numeric / 1_000_000_000:.2f}B'
    elif abs_value >= 1_000_000:
        formatted = f'{numeric / 1_000_000:.2f}M'
    elif abs_value >= 1_000:
        formatted = f'{numeric:,.0f}'
    else:
        formatted = f'{numeric:.0f}'
    return f'{sign}{formatted}'


def _format_compact_number(value, suffix=''):
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        formatted = f'{numeric / 1_000_000_000:.2f}B'
    elif abs_value >= 1_000_000:
        formatted = f'{numeric / 1_000_000:.2f}M'
    elif abs_value >= 1_000:
        formatted = f'{numeric / 1_000:.2f}K'
    else:
        formatted = f'{numeric:.0f}'
    return f'{formatted}{suffix}'


def _format_money_compact(value):
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    abs_value = abs(numeric)
    if abs_value >= 1_000_000_000:
        return f'${numeric / 1_000_000_000:.2f}B'
    if abs_value >= 1_000_000:
        return f'${numeric / 1_000_000:.2f}M'
    if abs_value >= 1_000:
        return f'${numeric / 1_000:.2f}K'
    return f'${numeric:.2f}'


def _derive_flow_value(row, net_key, buy_key, sell_key):
    try:
        net_value = float(row.get(net_key)) if net_key and row.get(net_key) is not None else None
    except (TypeError, ValueError):
        net_value = None
    if net_value is not None:
        return net_value

    try:
        buy_value = float(row.get(buy_key)) if buy_key and row.get(buy_key) is not None else None
        sell_value = float(row.get(sell_key)) if sell_key and row.get(sell_key) is not None else None
    except (TypeError, ValueError):
        return None

    if buy_value is not None and sell_value is not None:
        return buy_value - sell_value
    return None


def _load_actual_institutional_flow_snapshot(conn, symbol: str) -> dict | None:
    if _table_exists(conn, 'us_institutional_activity'):
        row = conn.execute(text("""
            SELECT snapshot_date,
                   institution_report_date,
                   mutualfund_report_date,
                   institution_total_shares,
                   institution_total_value,
                   mutualfund_total_shares,
                   mutualfund_total_value,
                   insider_buys_6m,
                   insider_sells_6m,
                   insider_net_shares_6m
            FROM us_institutional_activity
            WHERE symbol = :sym
            ORDER BY snapshot_date DESC, updated_at DESC, id DESC
            LIMIT 1
        """), {'sym': symbol}).mappings().first()

        if row:
            institution_parts = []
            mutualfund_parts = []
            insider_parts = []

            institution_shares = _format_compact_number(row.get('institution_total_shares'), '股')
            institution_value = _format_money_compact(row.get('institution_total_value'))
            if institution_shares:
                institution_parts.append(institution_shares)
            if institution_value:
                institution_parts.append(institution_value)

            mutualfund_shares = _format_compact_number(row.get('mutualfund_total_shares'), '股')
            mutualfund_value = _format_money_compact(row.get('mutualfund_total_value'))
            if mutualfund_shares:
                mutualfund_parts.append(mutualfund_shares)
            if mutualfund_value:
                mutualfund_parts.append(mutualfund_value)

            insider_net = _format_signed_number(row.get('insider_net_shares_6m'))
            insider_buys = _format_compact_number(row.get('insider_buys_6m'), '股')
            insider_sells = _format_compact_number(row.get('insider_sells_6m'), '股')
            if insider_net and insider_net != 'N/A':
                insider_parts.append(f'{insider_net}股')
            if insider_buys or insider_sells:
                insider_parts.append(f'買 {insider_buys or "N/A"} / 賣 {insider_sells or "N/A"}')

            rows = [
                {'label': '機構持股', 'value': ' / '.join(institution_parts) or 'N/A'},
                {'label': '共同基金', 'value': ' / '.join(mutualfund_parts) or 'N/A'},
                {'label': '內部人近6M', 'value': ' | '.join(insider_parts) or 'N/A'},
            ]
            if any(item['value'] != 'N/A' for item in rows):
                snapshot_date = _format_trade_date(row.get('snapshot_date'))
                report_notes = []
                institution_report = _format_trade_date(row.get('institution_report_date'))
                mutualfund_report = _format_trade_date(row.get('mutualfund_report_date'))
                if institution_report:
                    report_notes.append(f'機構揭露 {institution_report}')
                if mutualfund_report:
                    report_notes.append(f'基金揭露 {mutualfund_report}')

                note = '資料來源: Yahoo Finance institutional_holders / mutualfund_holders / insider_purchases'
                if report_notes:
                    note = f"{note}；{'，'.join(report_notes)}"

                summary = ' / '.join(f"{item['label']} {item['value']}" for item in rows if item['value'] != 'N/A')
                return {
                    'trade_date': snapshot_date,
                    'date_label': '快照日期',
                    'headline_label': '法人 / 內部人快照',
                    'rows': rows,
                    'source': 'us_holder_activity',
                    'summary': f'{snapshot_date} 主力快照: {summary}' if snapshot_date else f'主力快照: {summary}',
                    'note': note,
                    'is_fallback': False,
                }

    from sqlalchemy import text as sql_text

    for candidate in INSTITUTIONAL_FLOW_TABLE_CANDIDATES:
        table_name = candidate['table']
        if not _table_exists(conn, table_name) or not _column_exists(conn, table_name, 'symbol'):
            continue

        date_column = _resolve_existing_column(conn, table_name, candidate['date'])
        if not date_column:
            continue

        resolved_columns = {
            'foreign_net': _resolve_existing_column(conn, table_name, candidate['foreign_net']),
            'foreign_buy': _resolve_existing_column(conn, table_name, candidate['foreign_buy']),
            'foreign_sell': _resolve_existing_column(conn, table_name, candidate['foreign_sell']),
            'trust_net': _resolve_existing_column(conn, table_name, candidate['trust_net']),
            'trust_buy': _resolve_existing_column(conn, table_name, candidate['trust_buy']),
            'trust_sell': _resolve_existing_column(conn, table_name, candidate['trust_sell']),
            'dealer_net': _resolve_existing_column(conn, table_name, candidate['dealer_net']),
            'dealer_buy': _resolve_existing_column(conn, table_name, candidate['dealer_buy']),
            'dealer_sell': _resolve_existing_column(conn, table_name, candidate['dealer_sell']),
        }

        if not any(resolved_columns.values()):
            continue

        select_columns = [f'{date_column} AS trade_date']
        for alias, column_name in resolved_columns.items():
            if column_name:
                select_columns.append(f'{column_name} AS {alias}')

        row = conn.execute(sql_text(f"""
            SELECT {', '.join(select_columns)}
            FROM {table_name}
            WHERE symbol = :sym
            ORDER BY {date_column} DESC
            LIMIT 1
        """), {'sym': symbol}).mappings().first()

        if not row:
            continue

        foreign_value = _derive_flow_value(row, 'foreign_net', 'foreign_buy', 'foreign_sell')
        trust_value = _derive_flow_value(row, 'trust_net', 'trust_buy', 'trust_sell')
        dealer_value = _derive_flow_value(row, 'dealer_net', 'dealer_buy', 'dealer_sell')
        if all(value is None for value in (foreign_value, trust_value, dealer_value)):
            continue

        trade_date = _format_trade_date(row.get('trade_date'))
        rows = [
            {'label': '外資', 'value': _format_signed_number(foreign_value)},
            {'label': '投信', 'value': _format_signed_number(trust_value)},
            {'label': '自營商', 'value': _format_signed_number(dealer_value)},
        ]
        summary = ' / '.join(f"{item['label']} {item['value']}" for item in rows)
        return {
            'trade_date': trade_date,
            'rows': rows,
            'source': 'actual',
            'summary': f'{trade_date} 三大法人買賣超: {summary}' if trade_date else f'三大法人買賣超: {summary}',
            'note': f'資料來源: {table_name} 原始買賣超欄位',
            'is_fallback': False,
        }

    return None


def _build_smart_money_trend(institutional_pass, money_flow_pass, insider_sentiment='NEUTRAL'):
    sentiment = str(insider_sentiment or 'NEUTRAL').upper()

    if institutional_pass is True and money_flow_pass is True:
        return '法人大戶偏多，疑似持續吸籌'
    if institutional_pass is True:
        return '法人偏多，短線流向待確認'
    if money_flow_pass is True:
        return '短線回流，法人態度觀察中'
    if sentiment == 'BUYING':
        return '內部人偏買方，先續看量價'
    if institutional_pass is False or sentiment == 'SELLING':
        return '大戶偏保守，暫未見明確加碼'
    return '資料有限，待主力快照更新'


def _build_today_flow_snapshot(conn, symbol: str, money_flow_pass=None) -> dict:
    actual_snapshot = _load_actual_institutional_flow_snapshot(conn, symbol)
    if actual_snapshot:
        return actual_snapshot

    return {
        'trade_date': None,
        'date_label': '快照日期',
        'headline_label': '法人 / 內部人快照',
        'rows': [
            {'label': '機構持股', 'value': '待更新'},
            {'label': '共同基金', 'value': '待更新'},
            {'label': '內部人近6M', 'value': '待更新'},
        ],
        'source': 'unavailable',
        'summary': '尚未建立美股機構 / 共同基金 / 內部人快照資料',
        'note': '請先更新 us_institutional_activity 快照，LINE 才會顯示真實數值。',
        'is_fallback': True,
    }


def _get_daily_screener_class():
    """延遲匯入 DailyScreener，避免 web 啟動時路徑問題。"""
    project_root = Path(__file__).resolve().parents[2]
    strategies_src = project_root / 'strategies' / 'src'

    for path in (project_root, strategies_src):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    screener_engine = importlib.import_module('screener.engine')
    return screener_engine.DailyScreener


# ============================================
# 簽名驗證
# ============================================
def verify_signature(func):
    """驗證 Line Webhook 簽名的裝飾器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        signature = request.headers.get('X-Line-Signature', '')
        
        # 如果未配置 Channel Secret，允許請求通過（僅供開發環境）
        if not CHANNEL_SECRET:
            _log_linebot("⚠️  Channel Secret 未配置，跳過簽名驗證（僅限開發環境）")
            return func(*args, **kwargs)
        
        if not signature:
            _log_linebot("❌ 缺少 X-Line-Signature 標頭")
            abort(400, description="Missing X-Line-Signature header")

        try:
            body = request.get_data(as_text=True)
            hash_value = hmac.new(
                CHANNEL_SECRET.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(hash_value).decode('utf-8')

            if not hmac.compare_digest(signature, expected):
                _log_linebot("❌ 簽名驗證失敗")
                _log_linebot(f"   收到: {signature[:20]}...")
                _log_linebot(f"   預期: {expected[:20]}...")
                abort(403, description="Invalid signature")
            
            _log_linebot("✅ 簽名驗證成功")
        except Exception as e:
            _log_linebot(f"❌ 簽名驗證異常: {e}")
            abort(403, description=f"Signature verification error: {str(e)}")

        return func(*args, **kwargs)
    return wrapper


# ============================================
# Webhook 路由
# ============================================
@line_bot_bp.route('/callback', methods=['GET'])
def callback_health():
    """LINE Webhook 健康檢查端點（GET 請求）"""
    return jsonify({
        'status': 'ok',
        'message': 'LINE Bot Webhook is running',
        'endpoint': '/callback',
        'methods': ['GET', 'POST']
    }), 200


@line_bot_bp.route('/callback', methods=['POST'])
@verify_signature
def callback():
    """LINE Webhook 回調端點（POST 請求）- 已啟用簽名驗證"""
    try:
        body = request.get_json()
        if not body:
            _log_linebot("⚠️  收到空的請求 body")
            return jsonify({'status': 'error', 'message': 'Empty body'}), 400

        events = body.get('events', [])
        _log_linebot(f"📨 收到 {len(events)} 個事件")

        for event in events:
            event_type = event.get('type')
            _log_linebot(f"🔔 處理事件類型: {event_type}")
            
            if event_type == 'message':
                handle_message_event(event)
            elif event_type == 'follow':
                handle_follow_event(event)
            elif event_type == 'unfollow':
                user_id = event.get('source', {}).get('userId', 'unknown')
                _log_linebot(f"👋 用戶取消關注: {user_id}")
            else:
                _log_linebot(f"📨 未處理事件: {event_type}")

        return jsonify({'status': 'ok'}), 200

    except Exception as error:
        logger.exception("Webhook callback failed")
        _log_linebot(f"Webhook callback failed: {type(error).__name__}: {error}")
        return jsonify({'status': 'error', 'message': str(error)}), 500


# ============================================
# 事件處理
# ============================================
def handle_message_event(event: dict):
    """處理文字消息事件"""
    message = event.get('message', {})
    if message.get('type') != 'text':
        return

    text = message.get('text', '')
    user_id = event.get('source', {}).get('userId', 'unknown')
    reply_token = event.get('replyToken')

    _log_linebot(f"📩 收到文字消息: '{text}' from {user_id}")

    messages = process_command(text, user_id=user_id)
    if messages and reply_token:
        reply_messages(reply_token, messages, command=_canonical_command_name(_normalize_command_text(text)))


def handle_follow_event(event: dict):
    """處理新用戶關注事件"""
    user_id = event.get('source', {}).get('userId', 'unknown')
    reply_token = event.get('replyToken')
    _log_linebot(f"👋 新用戶關注: {user_id}")

    welcome = (
        "🎉 歡迎使用美股量化交易系統！\n\n"
        "可用命令：\n"
        "🏆 Top5 — 選股推薦（含 ML 加權）\n"
        "📊 Top5基礎 — 純規則推薦\n"
        "🔍 /stock AAPL — 個股分析\n"
        "🌍 /market — 宏觀環境\n"
        "📅 /history — 歷史推薦\n"
        "🏭 /sector — 產業動能\n"
        "🤖 ML AAPL — ML 預測\n"
        "❓ /help — 完整幫助\n\n"
        "系統每日自動推送選股報告。"
    )

    if reply_token:
        reply_messages(reply_token, [_text_msg(welcome)])


# ============================================
# 命令解析
# ============================================
def _cmd_recommendation_strategy_help() -> List[dict]:
    return [_text_msg(
        "我目前支援這些推薦指令：\n\n"
        "推薦：XGBoost 綜合大腦 Top 5\n"
        "推薦 動量：技術面動量策略\n"
        "推薦 機構：機構跟單策略\n"
        "推薦 籌碼：籌碼暴風眼策略"
    )]


def _route_recommendation_command(text_value: str) -> Optional[List[dict]]:
    if (text_value or '').strip().lower() in {"/recommendations", "recommendations"}:
        return _cmd_default_recommendations()
    stripped = (text_value or '').strip()
    if '推薦' not in stripped:
        return None

    compact = ''.join(stripped.split())
    if compact == '推薦':
        return _cmd_default_recommendations()
    if '動量' in stripped:
        return _cmd_momentum_recommendations()
    if '機構' in stripped or '籌碼' in stripped:
        return _cmd_institutional_recommendations()
    return _cmd_recommendation_strategy_help()


def process_command(text: str, user_id: Optional[str] = None) -> Optional[List[dict]]:
    """
    處理用戶命令

    Returns:
        LINE message object 列表，或 None (非命令)
    """
    cmd = _normalize_command_text(text)

    # --- Web URL 查詢 ---
    if cmd in ('web', '/web', '網址'):
        return _cmd_web()

    recommendation_messages = _route_recommendation_command(text)
    if recommendation_messages is not None:
        return recommendation_messages

    # --- Top5 / scan 命令 ---
    if cmd in ('top5', 'top 5', '/top5'):
        return _cmd_top5()

    if cmd == '/scan':
        if user_id and user_id != 'unknown':
            return _cmd_top5_realtime(user_id)
        return _cmd_top5()

    # --- Top5 基礎版（純規則，無 ML）---
    if cmd in ('top5基礎', 'top5-basic', '/top5basic', '/basic', '基礎'):
        return _cmd_top5_basic()

    # --- ML 命令 ---
    if cmd in ('/performance', 'performance'):
        return _cmd_performance()

    if cmd in (CALIBRATION_COMMAND, 'calibration'):
        _log_linebot("LineBot command=/calibration started")
        try:
            messages = _cmd_calibration()
            _log_linebot("LineBot command=/calibration build succeeded")
            return messages
        except Exception as error:
            _log_linebot(f"LineBot command=/calibration failed with exception: {type(error).__name__}: {error}")
            return _calibration_fallback_messages()

    if cmd.startswith(('ml ', '/ml ')) or cmd in ('ml', '/ml'):
        parts = text.strip().split()
        if len(parts) >= 2:
            return _cmd_ml(parts[1].upper())
        return [_text_msg("請指定股票代碼，例如: ML AAPL")]

    # --- /stock SYMBOL: 個股 11 策略詳細分析 ---
    if cmd.startswith(('/stock ', '個股 ', '查股 ')):
        parts = text.strip().split()
        if len(parts) >= 2:
            return _cmd_stock(parts[1].upper())
        return [_text_msg("請指定股票代碼，例如: /stock AAPL")]

    if _is_bare_ticker_command(text):
        return _cmd_stock(text.strip().upper())

    # --- /market: 宏觀環境 ---
    if cmd in ('/market', '市場', '宏觀', '/macro'):
        return _cmd_market()

    # --- /history MMDD: 歷史推薦 ---
    if cmd.startswith(('/history', '歷史')):
        parts = text.strip().split()
        date_str = parts[1] if len(parts) >= 2 else None
        return _cmd_history(date_str)

    # --- /sector: 產業動能 ---
    if cmd in ('/sector', '產業', '板塊', '/sectors'):
        return _cmd_sector()

    # --- Status (real health check) ---
    if cmd in ('/status', '狀態'):
        return _cmd_status()

    # --- Help ---
    if cmd in ('/help', '幫助'):
        return [_text_msg(
            "📚 可用命令：\n\n"
            "🏆 Top5 — 今日選股推薦（含 ML）\n"
            "📊 Top5基礎 — 純規則推薦\n"
            "🔍 /stock AAPL — 個股詳細分析\n"
            "🌍 /market — 宏觀環境\n"
            "📅 /history 0214 — 歷史推薦\n"
            "🏭 /sector — 產業動能排行\n"
            "🤖 ML AAPL — ML 預測\n"
            "📈 /status — 即時系統狀態\n"
            "🎯 /strategies — 策略說明\n"
            "❓ /help — 顯示此幫助\n\n"
            "💡 點擊 Top5 推薦下方按鈕快速查股"
        )]

    # --- Strategies ---
    if cmd in ('/strategies', '策略'):
        return [_text_msg(
            "📈 選股策略 v2（11 策略 + ML）：\n\n"
            "📋 規則策略（11 項）:\n"
            "  1️⃣ Breakout — 200日新高突破\n"
            "  2️⃣ Acceleration — 均速曲率加速\n"
            "  3️⃣ PEG — PEG<1.5 + ROE>10%\n"
            "  4️⃣ DuPont — 杜邦分解品質\n"
            "  5️⃣ Institutional — 機構籌碼\n"
            "  6️⃣ Volume Structure — 量價結構\n"
            "  7️⃣ Money Flow — 資金流向\n"
            "  8️⃣ Multi-TF Momentum — 多週期動能\n"
            "  9️⃣ Relative Strength — 相對強度\n"
            "  🔟 Earnings Quality — 盈餘品質\n"
            "  1️⃣1️⃣ Sector Rotation — 產業輪動\n\n"
            "🤖 ML (XGBoost) — 信心度加權\n"
            "📊 評分 = 規則通過數 × ML加權"
        )]

    # 非命令消息
    return None


def _cmd_web() -> List[dict]:
    """回傳目前 Web 戰情室對外網址。"""
    url = (os.getenv('NGROK_URL') or '').strip()
    if not url:
        return [_text_msg("🌐 目前尚未設定 Web 戰情室網址，請先設定 NGROK_URL。")]

    return [_text_msg(
        f"🌐 目前的 Web 戰情室網址是：\n{url}\n\n預設帳號：admin / 密碼：admin123"
    )]


def _cmd_top5_realtime(user_id: str) -> List[dict]:
    """立即回覆受理訊息，背景執行最新 Top5 掃描並主動推播。"""
    worker = threading.Thread(
        target=_run_screener_and_push,
        args=(user_id,),
        daemon=True,
    )
    worker.start()
    return [_text_msg(
        "⏳ 正在為您啟動最新的全市場掃描與 AI 運算，大約需要 1-2 分鐘，請稍候..."
    )]


# ============================================
# /stock SYMBOL: 個股 11 策略分析
# ============================================
def _cmd_stock(symbol: str) -> List[dict]:
    """Return DB-backed stock analysis with growth-aware valuation output."""
    try:
        engine = _get_db_engine()
        with engine.connect() as conn:
            payload = _load_stock_analysis_payload(conn, symbol)

        if not payload:
            return [_text_msg(f"??? {symbol} ?????????????")]

        text_fallback = _build_stock_analysis_message(payload)
        try:
            return [flex_messages.build_stock_check_message(payload)]
        except Exception as flex_error:
            _log_linebot(f"/stock flex build failed for {symbol}: {flex_error}")
            return [_text_msg(text_fallback)]
    except Exception as error:
        logger.exception("Stock lookup failed for %s", symbol)
        _log_linebot(f"/stock lookup failed for {symbol}: {error}")
        return [_text_msg(f"?? {symbol} ??: {error}")]


# ============================================
# /market: 宏觀環境
# ============================================
def _cmd_market() -> List[dict]:
    """查詢宏觀環境 (Regime + FRED 指標)"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # Regime
            reg = None
            if _table_exists(conn, 'macro_regime_log'):
                reg = conn.execute(sql_text("""
                    SELECT regime, description, report_date
                    FROM macro_regime_log
                    ORDER BY report_date DESC LIMIT 1
                """)).first()

            regime_str = "UNKNOWN"
            regime_emoji = "⚪"
            regime_desc = ""
            regime_date = ""
            if reg:
                regime_str = reg[0] or "UNKNOWN"
                regime_desc = reg[1] or ""
                regime_date = str(reg[2]) if reg[2] else ""
                regime_emoji = {"RISK_ON": "🟢", "NEUTRAL": "🟡", "RISK_OFF": "🔴"}.get(regime_str, "⚪")

            # FRED indicators
            indicators = {}
            if _table_exists(conn, 'macro_data'):
                if _column_exists(conn, 'macro_data', 'indicator'):
                    code_col = 'indicator'
                elif _column_exists(conn, 'macro_data', 'ticker'):
                    code_col = 'ticker'
                else:
                    code_col = None

                code_alias_map = {
                    'VIX': ['VIX', 'VIXCLS'],
                    'T10Y2Y': ['T10Y2Y'],
                    'UNRATE': ['UNRATE'],
                    'DFF': ['DFF'],
                    'CPIAUCSL': ['CPIAUCSL', 'CPI'],
                }

                if code_col:
                    for indicator in ['VIX', 'T10Y2Y', 'UNRATE', 'DFF', 'CPIAUCSL']:
                        r = None
                        for alias in code_alias_map.get(indicator, [indicator]):
                            r = conn.execute(sql_text(f"""
                                SELECT value FROM macro_data
                                WHERE {code_col} = :ind
                                ORDER BY date DESC LIMIT 1
                            """), {'ind': alias}).first()
                            if r:
                                break
                        if r:
                            indicators[indicator] = float(r[0])

            vix = indicators.get('VIX')
            vix_str = f"{vix:.1f}" if vix else "-"
            vix_emoji = "🟢" if vix and vix < 20 else "🟡" if vix and vix < 30 else "🔴"

            yield_curve = indicators.get('T10Y2Y')
            yc_str = f"{yield_curve:.2f}" if yield_curve is not None else "-"

            unrate = indicators.get('UNRATE')
            ur_str = f"{unrate:.1f}%" if unrate else "-"

            fed = indicators.get('DFF')
            fed_str = f"{fed:.2f}%" if fed else "-"

            if regime_str == "UNKNOWN" and indicators:
                if yield_curve is not None and yield_curve < 0:
                    regime_str = "RISK_OFF"
                    regime_emoji = "🔴"
                    regime_desc = "Fallback: 殖利率倒掛，偏防禦"
                elif yield_curve is not None and yield_curve > 0.3 and (fed is None or fed < 5.0):
                    regime_str = "RISK_ON"
                    regime_emoji = "🟢"
                    regime_desc = "Fallback: 曲線正向且利率中性，偏風險資產"
                else:
                    regime_str = "NEUTRAL"
                    regime_emoji = "🟡"
                    regime_desc = "Fallback: 宏觀信號中性"

            msg = (
                f"🌍 宏觀環境報告\n"
                f"{'='*24}\n\n"
                f"{regime_emoji} Regime: {regime_str}\n"
                f"  {regime_desc}\n"
                f"  📅 {regime_date}\n\n"
                f"📊 關鍵指標:\n"
                f"  {vix_emoji} VIX: {vix_str}\n"
                f"  📈 殖利率曲線: {yc_str}\n"
                f"  👷 失業率: {ur_str}\n"
                f"  🏦 Fed 利率: {fed_str}\n\n"
                f"💡 Regime 影響選股加權:\n"
                f"  🟢 RISK_ON = 積極進場\n"
                f"  🟡 NEUTRAL = 正常配置\n"
                f"  🔴 RISK_OFF = 保守防禦"
            )
            try:
                return [flex_messages.build_market_regime_message({
                    "regime": regime_str,
                    "vix": vix_str,
                    "yield_curve": yc_str,
                    "unemployment": ur_str,
                    "fed_rate": fed_str,
                    "description": regime_desc,
                    "date": regime_date,
                })]
            except Exception as flex_error:
                _log_linebot(f"/market flex build failed: {flex_error}")
                try:
                    return [flex_messages.build_ml_prediction_message({
                        "symbol": row[0],
                        "date": row[1],
                        "price": float(row[2]) if row[2] is not None else None,
                        "ml_confidence": conf,
                        "signal": "ML",
                    })]
                except Exception as flex_error:
                    _log_linebot(f"ML flex build failed for {symbol}: {flex_error}")
                    return [_text_msg(msg)]

    except Exception as e:
        _log_linebot(f"❌ /market 查詢失敗: {e}")
        return [_text_msg(f"❌ 宏觀資料查詢失敗: {e}")]


# ============================================
# /history MMDD: 歷史推薦
# ============================================
def _cmd_history(date_str: Optional[str] = None) -> List[dict]:
    """Query persisted historical recommendations with stale-connection retry."""
    try:
        from sqlalchemy import text as sql_text

        def read_history(conn):
            if date_str:
                now = datetime.now()
                if len(date_str) == 4:
                    target = f"{now.year}-{date_str[:2]}-{date_str[2:]}"
                elif len(date_str) == 8:
                    target = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                else:
                    target = date_str

                rows = conn.execute(sql_text("""
                    SELECT symbol, rank_position, signal_type, total_score, ml_confidence
                    FROM daily_recommendations
                    WHERE scan_date = :d
                    ORDER BY rank_position ASC LIMIT 10
                """), {"d": target})
                return "rows", target, [r for r in rows]

            dates = conn.execute(sql_text("""
                SELECT DISTINCT scan_date FROM daily_recommendations
                ORDER BY scan_date DESC LIMIT 10
            """))
            return "dates", None, [str(r[0]) for r in dates]

        result_type, target, values = _execute_linebot_read("/history", read_history)

        if result_type == "rows":
            recs = values
            if not recs:
                return [_text_msg(f"{target} 沒有歷史推薦資料。")]

            lines = [f"{target} 歷史推薦:", ""]
            for r in recs:
                ml = f"{float(r[4]) * 100:.0f}%" if r[4] else "N/A"
                lines.append(f"#{r[1]} {r[0]} | {r[2]} | Score {float(r[3]):.1f} | ML:{ml}")
            text_fallback = "\n".join(lines)
            try:
                return [flex_messages.build_history_recommendation_message(target, [
                    {
                        "symbol": r[0],
                        "rank": r[1],
                        "signal": r[2],
                        "total_score": float(r[3]) if r[3] is not None else None,
                        "ml_confidence": float(r[4]) if r[4] is not None else None,
                    }
                    for r in recs
                ])]
            except Exception as flex_error:
                _log_linebot(f"/history flex build failed for {target}: {flex_error}")
                return [_text_msg(text_fallback)]

        date_list = values
        if not date_list:
            return [_text_msg("目前沒有歷史推薦資料。")]

        msg = "可查詢的歷史推薦日期:\n\n"
        for d in date_list:
            msg += f"  {d}\n"
        msg += "\n輸入 /history 0214 查看特定日期"
        return [_text_msg(msg)]

    except Exception as e:
        _log_linebot(f"/history lookup failed: {type(e).__name__}: {e}")
        if _is_database_unavailable_error(e):
            return [_text_msg(_linebot_db_unavailable_message("歷史推薦"))]
        return [_text_msg("歷史推薦查詢失敗，請稍後再試。")]


# ============================================
# /sector: 產業動能排行
# ============================================
def _cmd_sector() -> List[dict]:
    """查詢產業動能排行"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            sectors = []

            if _table_exists(conn, 'sector_momentum'):
                etf_col = 'etf' if _column_exists(conn, 'sector_momentum', 'etf') else 'etf_symbol'
                rows = conn.execute(sql_text(f"""
                    SELECT sector, {etf_col}, rank_position, return_20d, return_63d
                    FROM sector_momentum
                    WHERE report_date = (SELECT MAX(report_date) FROM sector_momentum)
                    ORDER BY rank_position ASC
                """))
                sectors = [r for r in rows]

            # fallback: 若無 sector_momentum，用 daily_recommendations 聚合
            if not sectors and _table_exists(conn, 'daily_recommendations'):
                if _column_exists(conn, 'daily_recommendations', 'sector'):
                    rows = conn.execute(sql_text("""
                        SELECT COALESCE(sector, 'Unknown') AS sector_name,
                               COUNT(*) AS stock_count,
                               AVG(total_score) AS avg_score
                        FROM daily_recommendations
                        WHERE scan_date = (SELECT MAX(scan_date) FROM daily_recommendations)
                        GROUP BY COALESCE(sector, 'Unknown')
                        ORDER BY avg_score DESC, stock_count DESC
                    """))
                    rank = 1
                    for row in rows:
                        sectors.append((row[0], 'N/A', rank, None, None))
                        rank += 1
                else:
                    rows = conn.execute(sql_text("""
                        SELECT symbol, total_score
                        FROM daily_recommendations
                        WHERE scan_date = (SELECT MAX(scan_date) FROM daily_recommendations)
                    """))
                    from constants import SECTOR_MAP_FALLBACK
                    sector_map = SECTOR_MAP_FALLBACK
                    agg = {}
                    for row in rows:
                        sector_name = sector_map.get(row[0], 'Other')
                        agg[sector_name] = agg.get(sector_name, 0) + 1
                    sorted_items = sorted(agg.items(), key=lambda item: item[1], reverse=True)
                    rank = 1
                    for sector_name, _count in sorted_items:
                        sectors.append((sector_name, 'N/A', rank, None, None))
                        rank += 1

            if not sectors:
                return [_text_msg("🏭 尚無產業動能資料")]

            lines = ["🏭 產業動能排行", "=" * 24, ""]
            for s in sectors:
                r20 = f"{float(s[3])*100:.1f}%" if s[3] else "-"
                r63 = f"{float(s[4])*100:.1f}%" if s[4] else "-"
                arrow = "📈" if s[3] and float(s[3]) > 0 else "📉"
                lines.append(f"  #{s[2]} {arrow} {s[0]} ({s[1]})")
                lines.append(f"     20日: {r20} | 63日: {r63}")

            lines.append("\n💡 輸入 /stock SYMBOL 查看個股")
            text_fallback = "\n".join(lines)
            try:
                return [flex_messages.build_sector_ranking_message([
                    {
                        "sector": s[0],
                        "etf": s[1],
                        "rank": s[2],
                        "return_20d": s[3],
                        "return_63d": s[4],
                    }
                    for s in sectors
                ])]
            except Exception as flex_error:
                _log_linebot(f"/sector flex build failed: {flex_error}")
                return [_text_msg(text_fallback)]

    except Exception as e:
        _log_linebot(f"❌ /sector 查詢失敗: {e}")
        return [_text_msg(f"❌ 產業動能查詢失敗: {e}")]


# ============================================
# /status: 即時系統健康檢查
# ============================================
def _cmd_status() -> List[dict]:
    """即時健康檢查，回報 DB、API、ML"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        db_ok = False
        latest_rec = "N/A"
        rec_count = 0
        provider_health = _empty_provider_health()
        try:
            with engine.connect() as conn:
                conn.execute(sql_text("SELECT 1"))
                db_ok = True
                r = conn.execute(sql_text(
                    "SELECT MAX(scan_date), COUNT(*) FROM daily_recommendations"
                )).first()
                if r:
                    latest_rec = str(r[0]) if r[0] else "N/A"
                    rec_count = r[1] or 0
                provider_health = _load_latest_provider_health(conn)
        except Exception:
            pass

        db_emoji = "🟢" if db_ok else "🔴"
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        provider_line = _provider_health_text(provider_health)
        calibration_note = _status_calibration_note()
        provider_warning = ""
        if _provider_health_is_degraded(provider_health):
            provider_warning = "\n資料供應異常：目前不是完整 live data，請勿視為系統完全正常。"
        status_msg = "\n".join([
            "系統狀態",
            "=" * 24,
            f"{db_emoji} DB: {'connected' if db_ok else 'disconnected'}",
            f"latest_recommendation={latest_rec}",
            f"recommendation_rows={rec_count:,}",
            provider_line,
            f"last_successful_run_at={provider_health.get('last_successful_run_at') or 'N/A'}",
            "strategy_engine=v2 (11 strategies + ML)",
            f"checked_at={now}",
        ]) + provider_warning
        if calibration_note:
            status_msg = status_msg.replace(f"checked_at={now}", f"{calibration_note}\nchecked_at={now}")
        return [_text_msg(status_msg)]

        msg = (
            f"📊 系統狀態報告\n"
            f"{'='*24}\n\n"
            f"{db_emoji} 資料庫: {'已連接' if db_ok else '斷線'}\n"
            f"📈 最新推薦: {latest_rec}\n"
            f"📋 總推薦數: {rec_count:,}\n"
            f"🤖 策略引擎: v2 (11策略+ML)\n"
            f"⏰ 查詢時間: {now}"
        )
        return [_text_msg(msg)]

    except Exception as e:
        return [_text_msg(f"❌ 狀態查詢失敗: {e}")]


# ============================================
# Top5 命令：查詢最新選股推薦
# ============================================
_DAILY_RECOMMENDATION_COLUMNS = (
    ('rank_position', 'rank_position', '0'),
    ('signal_type', 'signal_type', "'BUY'"),
    ('total_score', 'total_score', '0'),
    ('current_price', 'current_price', '0'),
    ('target_price', 'target_price', 'NULL'),
    ('ml_confidence', 'ml_confidence', '0'),
    ('institutional_ownership', 'institutional_ownership', 'NULL'),
    ('insider_sentiment', 'insider_sentiment', "'NEUTRAL'"),
    ('institutional_pass', 'institutional_pass', 'NULL'),
    ('money_flow_pass', 'money_flow_pass', 'NULL'),
    ('valuation_status', 'valuation_status', "'FAIR'"),
    ('buy_price', 'buy_price', 'NULL'),
    ('sell_price', 'sell_price', 'NULL'),
    ('reason_summary', 'reason_summary', 'NULL'),
    ('support_1', 'support_1', 'NULL'),
    ('resistance_1', 'resistance_1', 'NULL'),
    ('breakout_pass', 'breakout_pass', '0'),
    ('acceleration_pass', 'acceleration_pass', '0'),
    ('peg_pass', 'peg_pass', '0'),
    ('dupont_pass', 'dupont_pass', '0'),
    ('multi_tf_momentum_pass', 'multi_tf_momentum_pass', '0'),
    ('relative_strength_pass', 'relative_strength_pass', '0'),
    ('volume_structure_pass', 'volume_structure_pass', '0'),
    ('whale_held_pct', 'whale_held_pct', 'NULL'),
    ('inst_count', 'inst_count', 'NULL'),
    ('institutional_net_buy', 'institutional_net_buy', 'NULL'),
    ('strategy_details', 'strategy_details', 'NULL'),
)


def _daily_recommendation_select_columns(conn) -> str:
    parts = ['symbol']
    for column_name, alias, default_sql in _DAILY_RECOMMENDATION_COLUMNS:
        parts.append(_select_optional_column(conn, 'daily_recommendations', [column_name], alias, default_sql))
    parts.append(
        _select_optional_column(
            conn,
            'daily_recommendations',
            ['news_sentiment', 'sentiment_score'],
            'news_sentiment',
            'NULL',
        )
    )
    return ',\n                       '.join(parts)


def _row_to_recommendation(conn, row_mapping, rank=None, reason_prefix: str | None = None) -> dict:
    institutional_pass = _nullable_bool(row_mapping.get('institutional_pass'))
    money_flow_pass = _nullable_bool(row_mapping.get('money_flow_pass'))
    reason = row_mapping.get('reason_summary') or '綜合訊號中性，待更多確認'
    if reason_prefix:
        reason = f'{reason_prefix}：{reason}'

    result = {
        'symbol': row_mapping.get('symbol'),
        'rank': rank if rank is not None else int(row_mapping.get('rank_position') or 0),
        'signal': row_mapping.get('signal_type') or 'BUY',
        'total_score': _safe_float(row_mapping.get('total_score')) or 0,
        'current_price': _safe_float(row_mapping.get('current_price')) or 0,
        'target_price': _safe_float(row_mapping.get('target_price')),
        'ml_confidence': _safe_float(row_mapping.get('ml_confidence')) or 0,
        'institutional_ownership': _safe_float(row_mapping.get('institutional_ownership')),
        'insider_sentiment': row_mapping.get('insider_sentiment') or 'NEUTRAL',
        'institutional_pass': institutional_pass,
        'money_flow_pass': money_flow_pass,
        'smart_money_trend': _build_smart_money_trend(
            institutional_pass,
            money_flow_pass,
            row_mapping.get('insider_sentiment'),
        ),
        'today_flow': _build_today_flow_snapshot(
            conn,
            row_mapping.get('symbol'),
            money_flow_pass=money_flow_pass,
        ) if row_mapping.get('symbol') else None,
        'valuation_status': row_mapping.get('valuation_status') or 'FAIR',
        'buy_price': _safe_float(row_mapping.get('buy_price')),
        'sell_price': _safe_float(row_mapping.get('sell_price')),
        'reason_summary': reason,
        'support_1': _safe_float(row_mapping.get('support_1')),
        'resistance_1': _safe_float(row_mapping.get('resistance_1')),
        'breakout_pass': bool(row_mapping.get('breakout_pass')),
        'acceleration_pass': bool(row_mapping.get('acceleration_pass')),
        'peg_pass': bool(row_mapping.get('peg_pass')),
        'dupont_pass': bool(row_mapping.get('dupont_pass')),
        'whale_held_pct': _safe_float(row_mapping.get('whale_held_pct')),
        'inst_count': _safe_float(row_mapping.get('inst_count')),
        'institutional_net_buy': _safe_float(row_mapping.get('institutional_net_buy')),
        'news_sentiment': _safe_float(row_mapping.get('news_sentiment')),
    }
    result.update(normalize_swing_ranking_metadata(
        row_mapping.get('strategy_details'),
        fallback_score=result['total_score'],
        rank=result['rank'],
    ))
    return result


def _latest_recommendation_date(conn):
    from sqlalchemy import text as sql_text

    if not _table_exists(conn, 'daily_recommendations'):
        return None
    return conn.execute(sql_text("SELECT MAX(scan_date) FROM daily_recommendations")).scalar()


def _recommendation_quick_reply(recs: list) -> dict:
    quick_items = [
        {"type": "action", "action": {"type": "message", "label": f"📌{r['symbol']}", "text": f"/stock {r['symbol']}"}}
        for r in recs[:5]
    ]
    quick_items.append({"type": "action", "action": {"type": "message", "label": "📈 市場", "text": "/market"}})
    return {"items": quick_items}


def _cmd_default_recommendations() -> List[dict]:
    """Default XGBoost route with final smart-money quality filters."""
    try:
        from sqlalchemy import text as sql_text

        def read_recommendations(conn):
            latest = _latest_recommendation_date(conn)
            if not latest:
                return latest, [], _empty_provider_health()

            select_columns = _daily_recommendation_select_columns(conn)
            rows = conn.execute(sql_text(f"""
                SELECT {select_columns}
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY ml_confidence DESC, total_score DESC, rank_position ASC
                LIMIT 30
            """), {"d": str(latest)}).mappings()

            recs = []
            for row in rows:
                news_sentiment = _safe_float(row.get("news_sentiment"))
                whale_held_pct = _safe_float(row.get("whale_held_pct"))
                if news_sentiment is not None and news_sentiment < 0:
                    continue
                if whale_held_pct is not None and whale_held_pct == 0:
                    continue
                recs.append(_row_to_recommendation(conn, row, rank=len(recs) + 1, reason_prefix="XGBoost"))
                if len(recs) >= 5:
                    break
            provider_health = _load_latest_provider_health(conn)
            return latest, recs, provider_health

        latest, recs, provider_health = _execute_linebot_read("recommendations", read_recommendations)
        if not latest:
            return [_text_msg("目前沒有推薦資料，請先執行每日選股流程。")]
        if not recs:
            return [_text_msg("目前沒有符合條件的推薦標的。")]

        flex = _build_top5_flex(recs, f"{str(latest)} XGBoost recommendations")
        flex["quickReply"] = _recommendation_quick_reply(recs)
        if _provider_health_is_degraded(provider_health):
            return [_text_msg(_provider_health_text(provider_health)), flex]
        return [flex]

    except Exception as e:
        _log_linebot(f"Default recommendation lookup failed: {type(e).__name__}: {e}")
        if _is_database_unavailable_error(e):
            return [_text_msg(_linebot_db_unavailable_message("推薦查詢"))]
        return [_text_msg("推薦查詢失敗，請稍後再試。")]


def _cmd_momentum_recommendations() -> List[dict]:
    """Technical momentum route using existing recommendation pass flags."""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            latest = _latest_recommendation_date(conn)
            if not latest:
                return [_text_msg("📊 尚無動量策略資料，請先執行每日推薦流程。")]

            select_columns = _daily_recommendation_select_columns(conn)
            rows = list(conn.execute(sql_text(f"""
                SELECT {select_columns}
                FROM daily_recommendations
                WHERE scan_date = :d
                LIMIT 100
            """), {'d': str(latest)}).mappings())

            def momentum_score(row):
                flags = (
                    row.get('breakout_pass'),
                    row.get('acceleration_pass'),
                    row.get('multi_tf_momentum_pass'),
                    row.get('relative_strength_pass'),
                    row.get('volume_structure_pass'),
                )
                return (
                    sum(1 for flag in flags if bool(flag)),
                    _safe_float(row.get('total_score')) or 0,
                    _safe_float(row.get('ml_confidence')) or 0,
                )

            ranked_rows = sorted(rows, key=momentum_score, reverse=True)[:5]
            recs = [
                _row_to_recommendation(conn, row, rank=index + 1, reason_prefix='技術面動量策略')
                for index, row in enumerate(ranked_rows)
            ]

            if not recs:
                return [_text_msg("📊 目前沒有可用的動量策略標的。")]

            flex = _build_top5_flex(recs, f"{str(latest)} 動量策略")
            flex["quickReply"] = _recommendation_quick_reply(recs)
            return [flex]

    except Exception as e:
        _log_linebot(f"Momentum recommendation lookup failed: {e}")
        return [_text_msg(f"❌ 動量策略查詢失敗: {e}")]


def _cmd_institutional_recommendations() -> List[dict]:
    """Institutional-following route from symbols_registry concentration data."""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            if not _table_exists(conn, 'symbols_registry'):
                return [_text_msg("📊 尚無 symbols_registry 籌碼資料。")]

            whale_column = _resolve_existing_column(conn, 'symbols_registry', ['whale_held_pct'])
            inst_column = _resolve_existing_column(conn, 'symbols_registry', ['inst_count'])
            if not whale_column and not inst_column:
                return [_text_msg("📊 尚無機構籌碼欄位資料，暫時無法產生機構跟單推薦。")]

            select_parts = [
                'symbol',
                _select_optional_column(conn, 'symbols_registry', ['sector'], 'sector', 'NULL'),
                _select_optional_column(conn, 'symbols_registry', ['whale_held_pct'], 'whale_held_pct', 'NULL'),
                _select_optional_column(conn, 'symbols_registry', ['inst_count'], 'inst_count', 'NULL'),
                _select_optional_column(conn, 'symbols_registry', ['institutional_net_buy'], 'institutional_net_buy', 'NULL'),
                _select_optional_column(conn, 'symbols_registry', ['sentiment_score', 'news_sentiment'], 'news_sentiment', 'NULL'),
            ]
            where_parts = []
            if _column_exists(conn, 'symbols_registry', 'is_active'):
                where_parts.append('COALESCE(is_active, 0) = 1')
            whale_rank_expr = 'COALESCE(whale_held_pct, 0)' if whale_column else '0'
            inst_rank_expr = 'COALESCE(inst_count, 0)' if inst_column else '0'
            if whale_column or inst_column:
                where_parts.append(f'({whale_rank_expr} > 0 OR {inst_rank_expr} > 0)')
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ''

            rows = conn.execute(sql_text(f"""
                SELECT {', '.join(select_parts)}
                FROM symbols_registry
                {where_sql}
                ORDER BY {whale_rank_expr} DESC, {inst_rank_expr} DESC
                LIMIT 5
            """)).mappings()

            recs = []
            for index, row in enumerate(rows):
                whale_held_pct = _safe_float(row.get('whale_held_pct'))
                inst_count = _safe_float(row.get('inst_count'))
                score = min(5.0, ((whale_held_pct or 0) / 20.0) + ((inst_count or 0) / 1000.0))
                recs.append({
                    'symbol': row.get('symbol'),
                    'rank': index + 1,
                    'signal': 'WATCH',
                    'total_score': round(score, 2),
                    'current_price': 0,
                    'target_price': None,
                    'ml_confidence': 0,
                    'institutional_ownership': whale_held_pct,
                    'insider_sentiment': 'NEUTRAL',
                    'institutional_pass': True,
                    'money_flow_pass': None,
                    'smart_money_trend': '機構集中',
                    'today_flow': None,
                    'valuation_status': 'FAIR',
                    'buy_price': None,
                    'sell_price': None,
                    'reason_summary': f"機構跟單策略：Whale {whale_held_pct if whale_held_pct is not None else 'N/A'} / Holders {int(inst_count) if inst_count is not None else 'N/A'}",
                    'support_1': None,
                    'resistance_1': None,
                    'breakout_pass': False,
                    'acceleration_pass': False,
                    'peg_pass': False,
                    'dupont_pass': False,
                    'whale_held_pct': whale_held_pct,
                    'inst_count': inst_count,
                    'institutional_net_buy': _safe_float(row.get('institutional_net_buy')),
                    'news_sentiment': _safe_float(row.get('news_sentiment')),
                })

            if not recs:
                return [_text_msg("📊 目前沒有可用的機構籌碼推薦標的。")]

            flex = _build_top5_flex(recs, "機構籌碼策略")
            flex["quickReply"] = _recommendation_quick_reply(recs)
            return [flex]

    except Exception as e:
        _log_linebot(f"Institutional recommendation lookup failed: {e}")
        return [_text_msg(f"❌ 機構策略查詢失敗: {e}")]


def _cmd_top5() -> List[dict]:
    """Query persisted Top 5 recommendations with stale-connection retry."""
    try:
        from sqlalchemy import text as sql_text

        def read_top5(conn):
            latest = conn.execute(sql_text(
                "SELECT MAX(scan_date) FROM daily_recommendations"
            )).scalar()
            if not latest:
                return latest, []

            select_columns = _daily_recommendation_select_columns(conn)
            rows = conn.execute(sql_text(f"""
                SELECT {select_columns}
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {"d": str(latest)}).mappings()
            recs = [_row_to_recommendation(conn, row) for row in rows]
            return latest, recs

        latest, recs = _execute_linebot_read("top5", read_top5)

        if not latest:
            return [_text_msg(
                "目前沒有推薦資料。\n\n"
                "請先執行: python strategies/scripts/run_daily_screener.py --save-db"
            )]
        if not recs:
            return [_text_msg("最新日期沒有可用推薦資料。")]

        flex = _build_top5_flex(recs, str(latest))
        flex["quickReply"] = _recommendation_quick_reply(recs)
        return [flex]

    except Exception as e:
        _log_linebot(f"Top5 lookup failed: {type(e).__name__}: {e}")
        if _is_database_unavailable_error(e):
            return [_text_msg(_linebot_db_unavailable_message("Top5"))]
        return [_text_msg("Top5 查詢失敗，請稍後再試。")]


# ============================================
# Top5 基礎版命令：純規則推薦（無 ML 加權）
# ============================================
def _cmd_top5_basic() -> List[dict]:
    """查詢 DB 最新 Top 5 推薦（純規則版，顯示原始規則評分）"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # 查詢與 _cmd_top5() 相同的資料，但呈現時顯示純規則邏輯
            latest = conn.execute(sql_text(
                "SELECT MAX(scan_date) FROM daily_recommendations"
            )).scalar()

            if not latest:
                return [_text_msg(
                    "📊 尚無選股推薦資料\n\n"
                    "請先執行:\n"
                    "python strategies/scripts/run_daily_screener.py --save-db"
                )]

            rows = conn.execute(sql_text("""
                SELECT symbol, rank_position, signal_type, total_score,
                       current_price, target_price, ml_confidence,
                       institutional_ownership, insider_sentiment,
                      institutional_pass, money_flow_pass,
                       valuation_status, buy_price, sell_price, reason_summary,
                       support_1, resistance_1,
                       breakout_pass, acceleration_pass, peg_pass, dupont_pass,
                       strategy_details
                FROM daily_recommendations
                WHERE scan_date = :d
                ORDER BY rank_position ASC
                LIMIT 5
            """), {'d': str(latest)}).mappings()

            recs = []
            for row in rows:
                # 計算純規則評分（不考慮 ML 加權）
                ml_conf = float(row['ml_confidence']) if row['ml_confidence'] else 0
                total_score = float(row['total_score']) if row['total_score'] else 0
                
                # 反推原始規則分：如果有 ML 加權，除回去
                if ml_conf > 0:
                    rule_score = total_score / (ml_conf / 0.5)
                else:
                    rule_score = total_score
                
                institutional_pass = bool(row['institutional_pass']) if row['institutional_pass'] is not None else None
                money_flow_pass = bool(row['money_flow_pass']) if row['money_flow_pass'] is not None else None
                today_flow = _build_today_flow_snapshot(conn, row['symbol'], money_flow_pass=money_flow_pass)
                rec = {
                    'symbol': row['symbol'],
                    'rank': row['rank_position'],
                    'signal': row['signal_type'],
                    'total_score': round(rule_score, 2),  # 使用純規則分
                    'current_price': float(row['current_price']) if row['current_price'] else 0,
                    'target_price': float(row['target_price']) if row['target_price'] is not None else None,
                    'ml_confidence': 0,  # 強制顯示 0（無 ML）
                    'institutional_ownership': float(row['institutional_ownership']) if row['institutional_ownership'] is not None else None,
                    'insider_sentiment': row['insider_sentiment'] or 'NEUTRAL',
                    'institutional_pass': institutional_pass,
                    'money_flow_pass': money_flow_pass,
                    'smart_money_trend': _build_smart_money_trend(institutional_pass, money_flow_pass, row['insider_sentiment']),
                    'today_flow': today_flow,
                    'valuation_status': row['valuation_status'] or 'FAIR',
                    'buy_price': float(row['buy_price']) if row['buy_price'] is not None else None,
                    'sell_price': float(row['sell_price']) if row['sell_price'] is not None else None,
                    'reason_summary': row['reason_summary'] or '綜合訊號中性，待更多確認',
                    'support_1': float(row['support_1']) if row['support_1'] else None,
                    'resistance_1': float(row['resistance_1']) if row['resistance_1'] else None,
                    'breakout_pass': bool(row['breakout_pass']),
                    'acceleration_pass': bool(row['acceleration_pass']),
                    'peg_pass': bool(row['peg_pass']),
                    'dupont_pass': bool(row['dupont_pass']),
                }
                rec.update(normalize_swing_ranking_metadata(
                    row.get('strategy_details'),
                    fallback_score=rec['total_score'],
                    rank=rec['rank'],
                ))
                recs.append(rec)

            if not recs:
                return [_text_msg("📊 該日期無推薦資料")]

            # 使用相同 Flex 格式，但評分已改為純規則分（ML 顯示為 —）
            return [_build_top5_flex(recs, f"{str(latest)} (純規則)")]

    except Exception as e:
        _log_linebot(f"❌ Top5 基礎版查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢失敗: {e}")]


# ============================================
# ML 命令：查詢單支股票 ML 預測
# ============================================
def _cmd_ml(symbol: str) -> List[dict]:
    """查詢 DB 中指定股票的最新 ML 預測"""
    try:
        from sqlalchemy import text as sql_text
        engine = _get_db_engine()

        with engine.connect() as conn:
            # 優先查 trade_logs（含 confidence + top_features）
            row = None
            if _table_exists(conn, 'trade_logs') and _column_exists(conn, 'trade_logs', 'confidence'):
                top_col = 'top_features' if _column_exists(conn, 'trade_logs', 'top_features') else 'NULL AS top_features'
                row = conn.execute(sql_text(f"""
                    SELECT symbol, entry_date, entry_price, confidence, {top_col}
                    FROM trade_logs
                    WHERE symbol = :sym AND confidence IS NOT NULL
                    ORDER BY entry_date DESC, id DESC
                    LIMIT 1
                """), {'sym': symbol}).first()

            if row:
                conf = float(row[3]) if row[3] else 0
                conf_str = f"{conf:.0%}" if conf > 0 else "—"
                features = json.loads(row[4]) if row[4] else None

                msg = (
                    f"🤖 {row[0]} ML 預測\n\n"
                    f"📅 日期: {row[1]}\n"
                    f"💰 價格: ${float(row[2]):.2f}\n"
                    f"🎯 信心度: {conf_str}"
                )
                if features:
                    msg += "\n\n📋 重要特徵:"
                    for f in features[:5]:
                        if isinstance(f, dict):
                            msg += f"\n  • {f.get('feature', 'N/A')}: {f.get('importance', 0):.4f}"
                        else:
                            msg += f"\n  • {f}"

                return [_text_msg(msg)]

            # 備選：查 daily_recommendations
            row2 = conn.execute(sql_text("""
                SELECT symbol, scan_date, current_price, ml_confidence,
                       total_score, signal_type, support_1, resistance_1
                FROM daily_recommendations
                WHERE symbol = :sym
                ORDER BY scan_date DESC
                LIMIT 1
            """), {'sym': symbol}).first()

            if not row2:
                if symbol == "NVDI":
                    return [_text_msg("找不到 NVDI 的 ML 預測資料。是否想查 NVDA?")]
                return [_text_msg(f"❌ 找不到 {symbol} 的 ML 預測資料")]

            conf = float(row2[3]) if row2[3] else 0
            conf_str = f"{conf:.0%}" if conf > 0 else "—"
            s1 = f"${float(row2[6]):.2f}" if row2[6] else "N/A"
            r1 = f"${float(row2[7]):.2f}" if row2[7] else "N/A"

            text_fallback = (
                f"🤖 {row2[0]} ML 預測\n\n"
                f"📅 日期: {row2[1]}\n"
                f"💰 價格: ${float(row2[2]):.2f}\n"
                f"📊 評分: {float(row2[4]):.1f}/5\n"
                f"🎯 信號: {row2[5]}\n"
                f"🤖 ML 信心度: {conf_str}\n"
                f"📉 支撐: {s1}\n"
                f"📈 壓力: {r1}"
            )
            try:
                return [flex_messages.build_ml_prediction_message({
                    "symbol": row2[0],
                    "date": row2[1],
                    "price": float(row2[2]) if row2[2] is not None else None,
                    "score": float(row2[4]) if row2[4] is not None else None,
                    "signal": row2[5],
                    "ml_confidence": conf,
                    "support": float(row2[6]) if row2[6] is not None else None,
                    "resistance": float(row2[7]) if row2[7] is not None else None,
                })]
            except Exception as flex_error:
                _log_linebot(f"ML flex build failed for {symbol}: {flex_error}")
                return [_text_msg(text_fallback)]

    except Exception as e:
        _log_linebot(f"❌ ML 查詢失敗: {e}")
        return [_text_msg(f"❌ 查詢 {symbol} 失敗: {e}")]


# ============================================
# Flex Message 建構
# ============================================
def _build_top5_flex(recs: list, scan_date: str) -> dict:
    """Build Top recommendation Flex Carousel."""
    return _build_recommendation_flex_message(
        recs,
        title=f"Top {len(recs)} recommendations {scan_date}",
        limit=10,
    )


def _build_bubble(rec: dict) -> dict:
    """建構單支股票的三層決策 Flex Bubble。"""
    return _build_decision_bubble(rec)


# ============================================
# LINE Reply 共用
# ============================================
def _text_msg(s: str) -> dict:
    """建構 LINE Text Message 物件"""
    return {"type": "text", "text": s.strip()}


def reply_messages(reply_token: str, messages: List[dict], command: Optional[str] = None, fallback_messages: Optional[List[dict]] = None):
    """Reply to LINE messages with sanitized payloads."""
    if not CHANNEL_TOKEN:
        if command == CALIBRATION_COMMAND:
            _log_linebot("LineBot command=/calibration failed with exception: channel token not configured")
        else:
            _log_linebot("Channel token not configured; cannot reply.")
        return False

    try:
        safe_messages = [_sanitize_line_message(message) for message in messages[:5]]
        if not _validate_line_messages_for_reply(safe_messages):
            raise ValueError("invalid LINE reply payload")
    except Exception as error:
        if command != CALIBRATION_COMMAND:
            _log_linebot(f"Reply payload validation failed: {type(error).__name__}: {error}")
            if not fallback_messages:
                return False
            safe_messages = [_sanitize_line_message(message) for message in fallback_messages[:5]]
            if not _validate_line_messages_for_reply(safe_messages):
                return False
        _log_linebot(f"LineBot command=/calibration failed with exception: {type(error).__name__}: {error}")
        safe_messages = _calibration_fallback_messages()

    for message in safe_messages:
        if message.get("type") == "flex":
            logger.debug(json.dumps(message.get("contents", {}), ensure_ascii=False))

    payload = {
        "replyToken": reply_token,
        "messages": safe_messages,
    }

    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CHANNEL_TOKEN}",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            if command == CALIBRATION_COMMAND:
                _log_linebot("LineBot command=/calibration reply sent successfully")
            else:
                _log_linebot("Reply sent successfully")
            return True

        logger.error("LINE reply failed payload=%s", json.dumps(payload, ensure_ascii=False))
        if command == CALIBRATION_COMMAND:
            _log_linebot(f"LineBot command=/calibration failed with exception: reply failed {resp.status_code} - {resp.text}")
        else:
            _log_linebot(f"Reply failed: {resp.status_code} - {resp.text}")
    except Exception as error:
        logger.exception("LINE reply request failed payload=%s", json.dumps(payload, ensure_ascii=False))
        if command == CALIBRATION_COMMAND:
            _log_linebot(f"LineBot command=/calibration failed with exception: {type(error).__name__}: {error}")
        else:
            _log_linebot(f"Reply request failed: {error}")
    if fallback_messages and messages != fallback_messages:
        _log_linebot("Retrying reply with text fallback")
        return reply_messages(reply_token, fallback_messages, command=command)
    return False


def push_message(user_id: str, messages: List[dict]) -> bool:
    """Push sanitized LINE messages to a user."""
    if not CHANNEL_TOKEN:
        _log_linebot("Channel token not configured; cannot push.")
        return False

    safe_messages = [_sanitize_line_message(message) for message in messages[:5]]
    for message in safe_messages:
        if message.get("type") == "flex":
            logger.debug(json.dumps(message.get("contents", {}), ensure_ascii=False))

    payload = {
        "to": user_id,
        "messages": safe_messages,
    }

    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CHANNEL_TOKEN}",
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            _log_linebot(f"Push sent successfully: {user_id}")
            return True

        logger.error("LINE push failed payload=%s", json.dumps(payload, ensure_ascii=False))
        _log_linebot(f"Push failed: {resp.status_code} - {resp.text}")
    except Exception as error:
        logger.exception("LINE push request failed payload=%s", json.dumps(payload, ensure_ascii=False))
        _log_linebot(f"Push request failed: {error}")

    return False


def _run_screener_and_push(user_id: str):
    """背景執行最新全市場掃描，完成後主動推播 Top5。"""
    try:
        DailyScreener = _get_daily_screener_class()
        screener = DailyScreener(use_ml=True)
        df_all = screener.scan_all()
        recommendations = screener.get_top_recommendations(df_all, n=5)
        summary = getattr(screener, "last_run_summary", {}) or {}

        if not recommendations:
            if summary.get("current_data_mode") == "failed" or float(summary.get("coverage_ratio", 0.0) or 0.0) < 0.2:
                push_message(user_id, [_text_msg(_critical_provider_failure_message(summary))])
                return
            push_message(user_id, [_text_msg("📊 最新掃描未產生可用推薦結果。")])
            return

        wrote = screener.save_to_db(recommendations)
        summary["recommendations_written"] = bool(wrote)
        if not wrote and (summary.get("current_data_mode") == "failed" or float(summary.get("coverage_ratio", 0.0) or 0.0) < 0.2):
            push_message(user_id, [_text_msg(_critical_provider_failure_message(summary))])
            return
        flex = _build_top5_flex(recommendations, datetime.now().strftime('%Y-%m-%d'))
        if summary.get("current_data_mode") in {"fallback", "stale"} or summary.get("degraded"):
            push_message(user_id, [_text_msg(_provider_health_text(normalize_provider_health({
                **summary,
                "provider_health_available": True,
            }))), flex])
        else:
            push_message(user_id, [flex])
    except Exception as error:
        logger.exception("Background Top5 scan failed for user %s", user_id)
        _log_linebot(f"Background Top5 scan failed: {type(error).__name__}: {error}")
        push_message(user_id, [_text_msg(f"❌ 最新掃描失敗: {error}")])


# ============================================
# Debug 路由
# ============================================
@line_bot_bp.route('/webhook/info', methods=['GET'])
def webhook_info():
    """返回 Webhook 配置信息（用於調試）"""
    return jsonify({
        'status': 'active',
        'endpoint': '/callback',
        'channel_secret_configured': bool(CHANNEL_SECRET),
        'channel_token_configured': bool(CHANNEL_TOKEN),
    })
