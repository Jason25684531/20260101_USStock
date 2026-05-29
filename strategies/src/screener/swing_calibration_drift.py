"""Calibration drift monitoring and governance helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from screener.presentation_utils import safe_float as _shared_safe_float
from screener.swing_calibration import (
    DEFAULT_PROFILE_PATH,
    default_calibration_profile,
    load_active_calibration_profile,
    normalize_calibration_profile,
    persist_calibration_profile,
    validate_calibration_profile,
)
from screener.swing_performance import INVALID_FRESH_PROVIDER_STATUSES, score_bucket, summarize_rows


DEFAULT_DRIFT_MIN_SAMPLE_SIZE = 30
DEFAULT_DRIFT_RETURN_MARGIN = 0.01
DEFAULT_DRIFT_HIT_RATE_MARGIN = 0.05
DEFAULT_DRIFT_LOOKBACK_DAYS = 90
SNAPSHOT_SOURCES = {"last_valid_snapshot"}


@dataclass(frozen=True)
class DriftThresholds:
    min_sample_size: int = DEFAULT_DRIFT_MIN_SAMPLE_SIZE
    return_margin: float = DEFAULT_DRIFT_RETURN_MARGIN
    hit_rate_margin: float = DEFAULT_DRIFT_HIT_RATE_MARGIN
    lookback_days: int = DEFAULT_DRIFT_LOOKBACK_DAYS
    enable_audit_log: bool = True


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = None) -> float | None:
    return _shared_safe_float(value, default)


def _safe_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def drift_thresholds_from_env(**overrides: Any) -> DriftThresholds:
    min_sample_size = _safe_int(
        overrides.get("min_sample_size", os.getenv("SWING_DRIFT_MIN_SAMPLE_SIZE")),
        DEFAULT_DRIFT_MIN_SAMPLE_SIZE,
    )
    return_margin = _safe_float(
        overrides.get("return_margin", os.getenv("SWING_DRIFT_RETURN_MARGIN")),
        DEFAULT_DRIFT_RETURN_MARGIN,
    )
    hit_rate_margin = _safe_float(
        overrides.get("hit_rate_margin", os.getenv("SWING_DRIFT_HIT_RATE_MARGIN")),
        DEFAULT_DRIFT_HIT_RATE_MARGIN,
    )
    lookback_days = _safe_int(
        overrides.get("lookback_days", os.getenv("SWING_DRIFT_LOOKBACK_DAYS")),
        DEFAULT_DRIFT_LOOKBACK_DAYS,
    )
    enable_audit_log = _safe_bool(
        overrides.get("enable_audit_log", os.getenv("SWING_DRIFT_ENABLE_AUDIT_LOG")),
        True,
    )
    return DriftThresholds(
        min_sample_size=min_sample_size,
        return_margin=float(return_margin if return_margin is not None and return_margin > 0 else DEFAULT_DRIFT_RETURN_MARGIN),
        hit_rate_margin=float(hit_rate_margin if hit_rate_margin is not None and hit_rate_margin > 0 else DEFAULT_DRIFT_HIT_RATE_MARGIN),
        lookback_days=lookback_days,
        enable_audit_log=enable_audit_log,
    )


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value).split(" ")[0], "%Y-%m-%d").date()
        except ValueError:
            return None


def _datetime_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed_date = _date_value(value)
    if parsed_date:
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    return None


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, list) else []
        except Exception:
            return []
    return []


def _filter_fresh_rows(rows: Iterable[Mapping[str, Any]], *, lookback_days: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    row_list = [dict(row) for row in rows or []]
    dates = [_date_value(_row_get(row, "recommendation_date")) for row in row_list]
    max_date = max([value for value in dates if value is not None], default=None)
    cutoff = max_date - timedelta(days=max(1, int(lookback_days))) if max_date else None
    eligible: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for row in row_list:
        source = str(_row_get(row, "recommendation_source") or "unknown")
        provider_status = str(_row_get(row, "provider_health_status") or "unknown")
        row_date = _date_value(_row_get(row, "recommendation_date"))
        if cutoff and row_date and row_date < cutoff:
            excluded["outside_lookback"] += 1
            continue
        if source in SNAPSHOT_SOURCES:
            excluded[source] += 1
            continue
        if source != "current_run":
            excluded[f"recommendation_source:{source}"] += 1
            continue
        if provider_status in INVALID_FRESH_PROVIDER_STATUSES:
            excluded[f"provider_status:{provider_status}"] += 1
            continue
        eligible.append(row)
    return eligible, dict(sorted(excluded.items()))


def _metric_delta(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> float | None:
    left_value = _safe_float(left.get(key))
    right_value = _safe_float(right.get(key))
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 6)


def _status_from_deltas(
    return_delta: float | None,
    hit_delta: float | None,
    *,
    return_margin: float,
    hit_rate_margin: float,
) -> str:
    if (return_delta is not None and return_delta <= -return_margin) or (
        hit_delta is not None and hit_delta <= -hit_rate_margin
    ):
        return "drifted"
    if (return_delta is not None and return_delta < 0) or (hit_delta is not None and hit_delta < 0):
        return "warning"
    return "healthy"


def _score_bucket_status(rows: list[dict[str, Any]], thresholds: DriftThresholds, messages: list[str]) -> tuple[str, dict[str, Any]]:
    high = [row for row in rows if score_bucket(_row_get(row, "score")) == ">=80"]
    lower = [row for row in rows if score_bucket(_row_get(row, "score")) not in {">=80", "unknown"}]
    high_summary = summarize_rows(high)
    lower_summary = summarize_rows(lower)
    detail = {"high": high_summary, "lower": lower_summary}
    if high_summary["sample_size"] < thresholds.min_sample_size or lower_summary["sample_size"] < thresholds.min_sample_size:
        return "insufficient_data", detail
    return_delta = _metric_delta(high_summary, lower_summary, "avg_forward_return_20d")
    hit_delta = _metric_delta(high_summary, lower_summary, "hit_rate_20d")
    status = _status_from_deltas(return_delta, hit_delta, return_margin=thresholds.return_margin, hit_rate_margin=thresholds.hit_rate_margin)
    if status in {"warning", "drifted"}:
        messages.append(f"High score bucket underperformed lower buckets by {abs(return_delta or 0) * 100:.1f}%.")
    detail.update({"return_delta": return_delta, "hit_rate_delta": hit_delta})
    return status, detail


def _top_rank_status(rows: list[dict[str, Any]], thresholds: DriftThresholds, messages: list[str]) -> tuple[str, dict[str, Any]]:
    top5 = [row for row in rows if int(_row_get(row, "rank") or 999) <= 5]
    others = [row for row in rows if int(_row_get(row, "rank") or 999) > 5]
    top5_summary = summarize_rows(top5)
    others_summary = summarize_rows(others)
    detail = {"top5": top5_summary, "others": others_summary}
    if top5_summary["sample_size"] < thresholds.min_sample_size or others_summary["sample_size"] < thresholds.min_sample_size:
        return "insufficient_data", detail
    return_delta = _metric_delta(top5_summary, others_summary, "avg_forward_return_20d")
    hit_delta = _metric_delta(top5_summary, others_summary, "hit_rate_20d")
    status = _status_from_deltas(return_delta, hit_delta, return_margin=thresholds.return_margin, hit_rate_margin=thresholds.hit_rate_margin)
    if status in {"warning", "drifted"}:
        messages.append(f"Top5 underperformed broader recommendations by {abs(return_delta or 0) * 100:.1f}%.")
    detail.update({"return_delta": return_delta, "hit_rate_delta": hit_delta})
    return status, detail


def _risk_flag_status(rows: list[dict[str, Any]], thresholds: DriftThresholds, messages: list[str]) -> tuple[str, dict[str, Any]]:
    no_risk = [row for row in rows if not _json_list(_row_get(row, "risk_flags"))]
    any_risk = [row for row in rows if _json_list(_row_get(row, "risk_flags"))]
    no_risk_summary = summarize_rows(no_risk)
    any_risk_summary = summarize_rows(any_risk)
    detail = {"no_risk": no_risk_summary, "any_risk": any_risk_summary}
    if no_risk_summary["sample_size"] < thresholds.min_sample_size or any_risk_summary["sample_size"] < thresholds.min_sample_size:
        return "insufficient_data", detail
    return_delta = _metric_delta(any_risk_summary, no_risk_summary, "avg_forward_return_20d")
    drawdown_delta = _metric_delta(any_risk_summary, no_risk_summary, "avg_max_drawdown_20d")
    status = "healthy"
    if return_delta is not None and drawdown_delta is not None:
        if return_delta >= thresholds.return_margin and drawdown_delta >= thresholds.return_margin:
            status = "drifted"
        elif return_delta > 0 and drawdown_delta > 0:
            status = "warning"
    if status in {"warning", "drifted"}:
        messages.append("Risk flag behavior may be noisy or inverted.")
    detail.update({"return_delta": return_delta, "drawdown_delta": drawdown_delta})
    return status, detail


def _calibration_impact_status(
    rows: list[dict[str, Any]],
    active_profile: Mapping[str, Any],
    thresholds: DriftThresholds,
) -> tuple[str, dict[str, Any]]:
    activated_at = _datetime_value(active_profile.get("activated_at"))
    if not activated_at:
        return "insufficient_data", {"before": summarize_rows([]), "after": summarize_rows([])}
    before = []
    after = []
    for row in rows:
        row_date = _date_value(_row_get(row, "recommendation_date"))
        if not row_date:
            continue
        row_dt = datetime(row_date.year, row_date.month, row_date.day, tzinfo=timezone.utc)
        if row_dt < activated_at:
            before.append(row)
        else:
            after.append(row)
    before_summary = summarize_rows(before)
    after_summary = summarize_rows(after)
    detail = {"before": before_summary, "after": after_summary}
    if before_summary["sample_size"] < thresholds.min_sample_size or after_summary["sample_size"] < thresholds.min_sample_size:
        return "insufficient_data", detail
    return_delta = _metric_delta(after_summary, before_summary, "avg_forward_return_20d")
    hit_delta = _metric_delta(after_summary, before_summary, "hit_rate_20d")
    detail.update({"return_delta": return_delta, "hit_rate_delta": hit_delta})
    if (return_delta is not None and return_delta >= thresholds.return_margin) or (
        hit_delta is not None and hit_delta >= thresholds.hit_rate_margin
    ):
        return "improved", detail
    if (return_delta is not None and return_delta <= -thresholds.return_margin) or (
        hit_delta is not None and hit_delta <= -thresholds.hit_rate_margin
    ):
        return "worsened", detail
    return "neutral", detail


def _overall_status(statuses: Iterable[str]) -> str:
    status_list = [status for status in statuses if status]
    if any(status == "drifted" for status in status_list):
        return "drifted"
    if any(status == "warning" for status in status_list):
        return "warning"
    if status_list and all(status == "insufficient_data" for status in status_list):
        return "insufficient_data"
    return "healthy"


def build_drift_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    active_profile: Mapping[str, Any] | None = None,
    lookback_days: int | None = None,
    min_sample_size: int | None = None,
    return_margin: float | None = None,
    hit_rate_margin: float | None = None,
) -> dict[str, Any]:
    thresholds = drift_thresholds_from_env(
        lookback_days=lookback_days,
        min_sample_size=min_sample_size,
        return_margin=return_margin,
        hit_rate_margin=hit_rate_margin,
    )
    profile = dict(active_profile or load_active_calibration_profile())
    eligible, excluded = _filter_fresh_rows(rows, lookback_days=thresholds.lookback_days)
    messages: list[str] = []
    score_status, score_detail = _score_bucket_status(eligible, thresholds, messages)
    top_status, top_detail = _top_rank_status(eligible, thresholds, messages)
    risk_status, risk_detail = _risk_flag_status(eligible, thresholds, messages)
    impact_status, impact_detail = _calibration_impact_status(eligible, profile, thresholds)
    drift_status = _overall_status([score_status, top_status, risk_status])
    if drift_status == "insufficient_data" and eligible:
        messages.append("Eligible sample size is below the configured drift threshold.")
    active = bool(profile.get("active"))
    version = profile.get("version")
    return {
        "active": active,
        "active_profile_version": version if active else None,
        "profile_version": version,
        "activation_time": profile.get("activated_at"),
        "lookback_days": thresholds.lookback_days,
        "sample_size": len(eligible),
        "required_sample_size": thresholds.min_sample_size,
        "drift_status": drift_status,
        "score_bucket_status": score_status,
        "top_rank_status": top_status,
        "risk_flag_status": risk_status,
        "calibration_impact_status": impact_status,
        "score_bucket": score_detail,
        "top_rank": top_detail,
        "risk_flag": risk_detail,
        "calibration_impact": impact_detail,
        "excluded_rows": excluded,
        "messages": messages,
        "recent_audit_events": [],
        "rollback_available": False,
    }


def _profile_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else DEFAULT_PROFILE_PATH


def _backup_dir(profile_path: str | Path | None = None, backup_dir: str | Path | None = None) -> Path:
    if backup_dir:
        return Path(backup_dir)
    return _profile_path(profile_path).parent / "calibration_profiles"


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "unknown")


def backup_active_profile(profile_path: str | Path | None = None, backup_dir: str | Path | None = None) -> Path | None:
    source_path = _profile_path(profile_path)
    if not source_path.exists():
        return None
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    valid, _ = validate_calibration_profile(raw)
    if not valid:
        return None
    version = _safe_filename(str(raw.get("version") or f"unknown-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"))
    target_dir = _backup_dir(source_path, backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"swing_calibration_profile_{version}.json"
    shutil.copy2(source_path, target)
    return target


def list_calibration_profile_backups(profile_path: str | Path | None = None, backup_dir: str | Path | None = None) -> list[dict[str, Any]]:
    target_dir = _backup_dir(profile_path, backup_dir)
    if not target_dir.exists():
        return []
    backups = []
    for path in sorted(target_dir.glob("swing_calibration_profile_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        version = raw.get("version")
        if version:
            backups.append({"version": version, "path": str(path), "created_at": raw.get("created_at")})
    return backups


def rollback_calibration_profile(
    profile_version: str,
    *,
    profile_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    current = load_active_calibration_profile(profile_path)
    target = None
    for backup in list_calibration_profile_backups(profile_path, backup_dir):
        if backup["version"] == profile_version:
            target = Path(backup["path"])
            break
    if target is None:
        return {"rolled_back": False, "error": "profile_not_found", "profile_version": profile_version}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as error:
        return {"rolled_back": False, "error": f"load_error:{error}", "profile_version": profile_version}
    valid, reason = validate_calibration_profile(raw)
    if not valid:
        return {"rolled_back": False, "error": reason, "profile_version": profile_version}
    restored = normalize_calibration_profile(raw, active=True, status="active")
    restored["activated_at"] = _utc_now()
    restored["deactivated_at"] = None
    restored["source"] = restored.get("source") or "rollback"
    saved_path = persist_calibration_profile(restored, profile_path)
    result = {
        "rolled_back": True,
        "profile_version": restored.get("version"),
        "previous_profile_version": current.get("version"),
        "profile_path": str(saved_path),
        "backup_path": str(target),
    }
    if conn is not None:
        log_calibration_audit_event(
            conn,
            "rollback",
            profile_version=restored.get("version"),
            previous_profile_version=current.get("version"),
            profile_path=str(saved_path),
            created_from_sample_size=restored.get("created_from_sample_size") or restored.get("source_sample_size"),
            event_payload=result,
        )
    return result


def ensure_swing_calibration_audit_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS swing_calibration_audit_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            event_type VARCHAR(32) NOT NULL,
            profile_version VARCHAR(128) NULL,
            previous_profile_version VARCHAR(128) NULL,
            profile_path TEXT NULL,
            created_from_sample_size INT NULL,
            score_bucket_status VARCHAR(32) NULL,
            top_rank_status VARCHAR(32) NULL,
            risk_flag_status VARCHAR(32) NULL,
            drift_status VARCHAR(32) NULL,
            event_payload_json JSON NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_swing_calib_audit_created_at (created_at),
            INDEX idx_swing_calib_audit_event_type (event_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))


def log_calibration_audit_event(
    conn,
    event_type: str,
    *,
    profile_version: str | None = None,
    previous_profile_version: str | None = None,
    profile_path: str | None = None,
    created_from_sample_size: int | None = None,
    score_bucket_status: str | None = None,
    top_rank_status: str | None = None,
    risk_flag_status: str | None = None,
    drift_status: str | None = None,
    event_payload: Mapping[str, Any] | None = None,
) -> bool:
    try:
        ensure_swing_calibration_audit_table(conn)
        conn.execute(text("""
            INSERT INTO swing_calibration_audit_log (
                event_type, profile_version, previous_profile_version, profile_path,
                created_from_sample_size, score_bucket_status, top_rank_status,
                risk_flag_status, drift_status, event_payload_json
            ) VALUES (
                :event_type, :profile_version, :previous_profile_version, :profile_path,
                :created_from_sample_size, :score_bucket_status, :top_rank_status,
                :risk_flag_status, :drift_status, :event_payload_json
            )
        """), {
            "event_type": event_type,
            "profile_version": profile_version,
            "previous_profile_version": previous_profile_version,
            "profile_path": profile_path,
            "created_from_sample_size": created_from_sample_size,
            "score_bucket_status": score_bucket_status,
            "top_rank_status": top_rank_status,
            "risk_flag_status": risk_flag_status,
            "drift_status": drift_status,
            "event_payload_json": json.dumps(dict(event_payload or {}), ensure_ascii=False, default=str),
        })
        return True
    except Exception:
        return False


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def read_recent_calibration_audit_events(conn, limit: int = 10) -> list[dict[str, Any]]:
    try:
        safe_limit = min(max(int(limit or 10), 1), 50)
        rows = conn.execute(text(f"""
            SELECT event_type, profile_version, previous_profile_version, created_from_sample_size,
                   score_bucket_status, top_rank_status, risk_flag_status, drift_status,
                   event_payload_json, created_at
            FROM swing_calibration_audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT {safe_limit}
        """)).mappings().fetchall()
    except Exception:
        return []
    events = []
    for row in rows:
        events.append({
            "event_type": row.get("event_type"),
            "profile_version": row.get("profile_version"),
            "previous_profile_version": row.get("previous_profile_version"),
            "created_from_sample_size": row.get("created_from_sample_size"),
            "score_bucket_status": row.get("score_bucket_status"),
            "top_rank_status": row.get("top_rank_status"),
            "risk_flag_status": row.get("risk_flag_status"),
            "drift_status": row.get("drift_status"),
            "event_payload": _decode_payload(row.get("event_payload_json")),
            "created_at": str(row.get("created_at")) if row.get("created_at") is not None else None,
        })
    return events
