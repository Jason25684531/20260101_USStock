"""Deterministic swing ranking calibration helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from screener.presentation_utils import safe_float as _shared_safe_float
from screener.swing_performance import SCORE_BUCKETS, score_bucket, summarize_rows


DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_MAX_ADJUSTMENT = 5.0
DEFAULT_PROFILE_VERSION = "default"
DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[3] / "data" / "swing_calibration_profile.json"
INVALID_DEFAULT_PROVIDER_STATUSES = {"failed", "critical", "stale", "degraded"}
SNAPSHOT_SOURCES = {"last_valid_snapshot"}
COMPONENT_SCORE_FIELDS = (
    "trend_score",
    "momentum_score",
    "setup_score",
    "volatility_score",
    "risk_score",
    "liquidity_score",
)
DEFAULT_SETUP_TYPES = (
    "breakout",
    "pullback_reclaim",
    "trend_continuation",
    "volatility_expansion",
    "avoid_overextended",
)


def _safe_float(value: Any) -> float | None:
    return _shared_safe_float(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 4) -> float | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_baseline() -> dict[str, Any]:
    return summarize_rows([])


def _empty_adjustments() -> dict[str, list[dict[str, Any]]]:
    return {
        "setup_adjustments": [],
        "risk_penalties": [],
        "component_weight_nudges": [],
        "eligibility_thresholds": [],
    }


def default_component_weights() -> dict[str, float]:
    return {field: 1.0 for field in COMPONENT_SCORE_FIELDS}


def default_setup_adjustments() -> dict[str, float]:
    return {setup: 0.0 for setup in DEFAULT_SETUP_TYPES}


def default_calibration_profile(
    *,
    status: str = "inactive",
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    profile = {
        "version": DEFAULT_PROFILE_VERSION,
        "status": status,
        "active": False,
        "created_at": None,
        "activated_at": None,
        "deactivated_at": None,
        "source": "unknown",
        "created_from_sample_size": 0,
        "description": "",
        "source_sample_size": 0,
        "min_sample_size": DEFAULT_MIN_SAMPLE_SIZE,
        "max_adjustment": DEFAULT_MAX_ADJUSTMENT,
        "component_weights": default_component_weights(),
        "setup_adjustments": default_setup_adjustments(),
        "risk_penalties": {},
        "eligibility_thresholds": {
            "min_total_score": None,
            "min_risk_score": None,
            "min_liquidity_score": None,
        },
        "baseline_metrics": _empty_baseline(),
        "recommended_adjustments": _empty_adjustments(),
        "fallback_reason": fallback_reason,
    }
    return profile


def _profile_path(path: str | Path | None = None) -> Path:
    configured = path or os.getenv("SWING_CALIBRATION_PROFILE_PATH")
    return Path(configured) if configured else DEFAULT_PROFILE_PATH


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def validate_calibration_profile(profile: Mapping[str, Any] | None) -> tuple[bool, str | None]:
    if not isinstance(profile, Mapping):
        return False, "profile_not_mapping"
    for field in (
        "version",
        "source_sample_size",
        "min_sample_size",
        "component_weights",
        "setup_adjustments",
        "risk_penalties",
        "eligibility_thresholds",
    ):
        if field not in profile:
            return False, f"missing_{field}"
    if not str(profile.get("version") or "").strip():
        return False, "invalid_version"
    if _safe_int(profile.get("min_sample_size"), -1) < 0:
        return False, "invalid_min_sample_size"
    if _safe_int(profile.get("source_sample_size"), -1) < 0:
        return False, "invalid_source_sample_size"

    weights = _mapping(profile.get("component_weights"))
    for field in COMPONENT_SCORE_FIELDS:
        weight = _safe_float(weights.get(field))
        if weight is None or weight < 0 or weight > 3:
            return False, f"invalid_component_weight:{field}"

    for name, value in _mapping(profile.get("setup_adjustments")).items():
        adjustment = _safe_float(value)
        if adjustment is None or adjustment < -25 or adjustment > 25:
            return False, f"invalid_setup_adjustment:{name}"

    for name, value in _mapping(profile.get("risk_penalties")).items():
        penalty = _safe_float(value)
        if penalty is None or penalty < -25 or penalty > 0:
            return False, f"invalid_risk_penalty:{name}"

    thresholds = _mapping(profile.get("eligibility_thresholds"))
    for name, value in thresholds.items():
        numeric = _safe_float(value)
        if value is not None and (numeric is None or numeric < 0 or numeric > 100):
            return False, f"invalid_threshold:{name}"
    return True, None


def normalize_calibration_profile(profile: Mapping[str, Any], *, active: bool = True, status: str = "active") -> dict[str, Any]:
    default = default_calibration_profile(status=status)
    merged = dict(default)
    merged.update(dict(profile))
    merged["status"] = status
    merged["active"] = bool(active)
    merged["source_sample_size"] = _safe_int(merged.get("source_sample_size"), 0)
    merged["created_from_sample_size"] = _safe_int(
        merged.get("created_from_sample_size"),
        merged["source_sample_size"],
    )
    merged["min_sample_size"] = _safe_int(merged.get("min_sample_size"), DEFAULT_MIN_SAMPLE_SIZE)
    merged["max_adjustment"] = _safe_float(merged.get("max_adjustment")) or DEFAULT_MAX_ADJUSTMENT
    merged["activated_at"] = merged.get("activated_at")
    merged["deactivated_at"] = merged.get("deactivated_at")
    merged["source"] = str(merged.get("source") or "unknown")
    merged["description"] = str(merged.get("description") or "")
    merged["component_weights"] = {
        field: float(_mapping(merged.get("component_weights")).get(field, 1.0))
        for field in COMPONENT_SCORE_FIELDS
    }
    setup_adjustments = default_setup_adjustments()
    for setup, value in _mapping(merged.get("setup_adjustments")).items():
        numeric = _safe_float(value)
        if numeric is not None:
            setup_adjustments[str(setup)] = float(numeric)
    merged["setup_adjustments"] = setup_adjustments
    merged["risk_penalties"] = {
        str(name): float(value)
        for name, value in _mapping(merged.get("risk_penalties")).items()
        if _safe_float(value) is not None
    }
    thresholds = dict(default["eligibility_thresholds"])
    for name, value in _mapping(merged.get("eligibility_thresholds")).items():
        thresholds[str(name)] = _safe_float(value)
    merged["eligibility_thresholds"] = thresholds
    merged["baseline_metrics"] = dict(merged.get("baseline_metrics") or _empty_baseline())
    merged["recommended_adjustments"] = dict(merged.get("recommended_adjustments") or _empty_adjustments())
    return merged


def load_active_calibration_profile(path: str | Path | None = None) -> dict[str, Any]:
    profile_path = _profile_path(path)
    if not profile_path.exists():
        profile = default_calibration_profile(status="inactive")
        profile["profile_path"] = str(profile_path)
        return profile
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as error:
        profile = default_calibration_profile(status="fallback_to_default", fallback_reason=f"load_error:{error}")
        profile["profile_path"] = str(profile_path)
        return profile

    valid, reason = validate_calibration_profile(raw)
    if not valid:
        profile = default_calibration_profile(status="fallback_to_default", fallback_reason=reason)
        profile["profile_path"] = str(profile_path)
        return profile
    profile = normalize_calibration_profile(raw, active=True, status="active")
    profile["profile_path"] = str(profile_path)
    return profile


def persist_calibration_profile(profile: Mapping[str, Any], path: str | Path | None = None) -> Path:
    valid, reason = validate_calibration_profile(profile)
    if not valid:
        raise ValueError(f"Invalid calibration profile: {reason}")
    profile_path = _profile_path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(dict(profile), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return profile_path


def deactivate_calibration_profile(path: str | Path | None = None) -> bool:
    profile_path = _profile_path(path)
    if profile_path.exists():
        profile_path.unlink()
        return True
    return False


def _is_eligible_fresh_row(
    row: Mapping[str, Any],
    *,
    include_provider_statuses: set[str] | None = None,
) -> tuple[bool, str | None]:
    source = str(_row_get(row, "recommendation_source") or "unknown")
    provider_status = str(_row_get(row, "provider_health_status") or "unknown")
    if source in SNAPSHOT_SOURCES:
        return False, source
    if source != "current_run":
        return False, f"recommendation_source:{source}"
    allowed = include_provider_statuses or set()
    if provider_status in INVALID_DEFAULT_PROVIDER_STATUSES and provider_status not in allowed:
        return False, f"provider_status:{provider_status}"
    return True, None


def filter_calibration_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    include_provider_statuses: Iterable[str] | None = None,
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    allowed = {str(value) for value in include_provider_statuses or []}
    eligible: list[Mapping[str, Any]] = []
    excluded: Counter[str] = Counter()
    for row in rows or []:
        row_dict = dict(row)
        is_eligible, reason = _is_eligible_fresh_row(row_dict, include_provider_statuses=allowed)
        if is_eligible:
            eligible.append(row_dict)
        else:
            excluded[reason or "unknown"] += 1
    return eligible, dict(sorted(excluded.items()))


def _group_rows(rows: list[Mapping[str, Any]], key: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(_row_get(row, key) or "unknown")].append(row)
    return grouped


def _risk_groups(rows: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        flags = _json_list(_row_get(row, "risk_flags"))
        if not flags:
            grouped["no_risk_flag"].append(row)
            continue
        grouped["any_risk_flag"].append(row)
        for flag in flags:
            grouped[str(flag)].append(row)
    return grouped


def _segment_rows(rows: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    score_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        score_groups[score_bucket(_row_get(row, "score"))].append(row)

    return {
        "score_buckets": [
            {"bucket": bucket, **summarize_rows(score_groups.get(bucket, []))}
            for bucket in SCORE_BUCKETS
        ],
        "setup_types": [
            {"setup_type": setup, **summarize_rows(grouped)}
            for setup, grouped in sorted(_group_rows(rows, "setup_type").items())
        ],
        "risk_flags": [
            {"group": flag, **summarize_rows(grouped)}
            for flag, grouped in sorted(_risk_groups(rows).items())
        ],
        "provider_health_segments": [
            {"provider_health_status": status, **summarize_rows(grouped)}
            for status, grouped in sorted(_group_rows(rows, "provider_health_status").items())
        ],
        "recommendation_source_segments": [
            {"recommendation_source": source, **summarize_rows(grouped)}
            for source, grouped in sorted(_group_rows(rows, "recommendation_source").items())
        ],
    }


def _adjustment_from_delta(delta_return: float | None, delta_hit: float | None, max_adjustment: float) -> float:
    if delta_return is None and delta_hit is None:
        return 0.0
    return_part = abs(delta_return or 0.0) * 100
    hit_part = abs(delta_hit or 0.0) * 4
    magnitude = min(max_adjustment, max(1.0, round(return_part + hit_part, 2)))
    sign = -1.0 if (delta_return or 0.0) < 0 or (delta_hit or 0.0) < 0 else 1.0
    return round(sign * magnitude, 2)


def _metric_delta(segment: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> float | None:
    left = _safe_float(segment.get(key))
    right = _safe_float(baseline.get(key))
    if left is None or right is None:
        return None
    return left - right


def recommend_adjustments(
    rows: Iterable[Mapping[str, Any]],
    baseline: Mapping[str, Any],
    *,
    min_segment_sample_size: int,
    max_adjustment: float,
) -> dict[str, list[dict[str, Any]]]:
    row_list = list(rows or [])
    adjustments = _empty_adjustments()

    for setup, grouped in sorted(_group_rows(row_list, "setup_type").items()):
        summary = summarize_rows(grouped)
        if summary["sample_size"] < min_segment_sample_size:
            continue
        delta_return = _metric_delta(summary, baseline, "avg_forward_return_20d")
        delta_hit = _metric_delta(summary, baseline, "hit_rate_20d")
        adjustment = _adjustment_from_delta(delta_return, delta_hit, max_adjustment)
        if adjustment:
            adjustments["setup_adjustments"].append({
                "setup_type": setup,
                "adjustment": adjustment,
                "sample_size": summary["sample_size"],
                "avg_forward_return_20d": summary["avg_forward_return_20d"],
                "hit_rate_20d": summary["hit_rate_20d"],
                "reason": "outperformed_fresh_baseline" if adjustment > 0 else "underperformed_fresh_baseline",
            })

    risk_groups = _risk_groups(row_list)
    no_risk_summary = summarize_rows(risk_groups.get("no_risk_flag", []))
    for flag, grouped in sorted(risk_groups.items()):
        if flag in {"no_risk_flag", "any_risk_flag"}:
            continue
        summary = summarize_rows(grouped)
        if summary["sample_size"] < min_segment_sample_size:
            continue
        delta_return = _metric_delta(summary, no_risk_summary, "avg_forward_return_20d")
        delta_hit = _metric_delta(summary, no_risk_summary, "hit_rate_20d")
        penalty = _adjustment_from_delta(delta_return, delta_hit, max_adjustment)
        if penalty > 0:
            continue
        adjustments["risk_penalties"].append({
            "risk_flag": flag,
            "penalty": penalty,
            "sample_size": summary["sample_size"],
            "avg_forward_return_20d": summary["avg_forward_return_20d"],
            "hit_rate_20d": summary["hit_rate_20d"],
            "reason": "risk_flag_underperformed_no_risk_rows",
        })

    by_bucket: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in row_list:
        by_bucket[score_bucket(_row_get(row, "score"))].append(row)
    for bucket in SCORE_BUCKETS:
        summary = summarize_rows(by_bucket.get(bucket, []))
        if summary["sample_size"] < min_segment_sample_size:
            continue
        delta_return = _metric_delta(summary, baseline, "avg_forward_return_20d")
        if delta_return is not None and delta_return < 0:
            adjustments["eligibility_thresholds"].append({
                "bucket": bucket,
                "suggestion": "tighten_min_score",
                "sample_size": summary["sample_size"],
                "avg_forward_return_20d": summary["avg_forward_return_20d"],
            })

    for field in COMPONENT_SCORE_FIELDS:
        valued_rows = [row for row in row_list if _safe_float(_row_get(row, field)) is not None]
        if len(valued_rows) < min_segment_sample_size * 2:
            continue
        ordered = sorted(valued_rows, key=lambda row: _safe_float(_row_get(row, field)) or 0.0)
        median_value = _safe_float(_row_get(ordered[len(ordered) // 2], field))
        if median_value is None:
            continue
        high_rows = [row for row in valued_rows if (_safe_float(_row_get(row, field)) or 0.0) >= median_value]
        low_rows = [row for row in valued_rows if (_safe_float(_row_get(row, field)) or 0.0) < median_value]
        if len(high_rows) < min_segment_sample_size or len(low_rows) < min_segment_sample_size:
            continue
        high_summary = summarize_rows(high_rows)
        low_summary = summarize_rows(low_rows)
        delta_return = _metric_delta(high_summary, low_summary, "avg_forward_return_20d")
        delta_hit = _metric_delta(high_summary, low_summary, "hit_rate_20d")
        if delta_return is None and delta_hit is None:
            continue
        nudge = _adjustment_from_delta(delta_return, delta_hit, 0.2)
        if nudge:
            adjustments["component_weight_nudges"].append({
                "component": field,
                "weight_delta": nudge,
                "split_value": _round(median_value, 2),
                "high_sample_size": high_summary["sample_size"],
                "low_sample_size": low_summary["sample_size"],
                "reason": "high_component_outperformed" if nudge > 0 else "high_component_underperformed",
            })

    return adjustments


def build_calibration_payload(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    min_segment_sample_size: int | None = None,
    max_adjustment: float = DEFAULT_MAX_ADJUSTMENT,
    include_provider_statuses: Iterable[str] | None = None,
) -> dict[str, Any]:
    eligible, excluded = filter_calibration_rows(rows, include_provider_statuses=include_provider_statuses)
    baseline = summarize_rows(eligible)
    required = max(0, int(min_sample_size or 0))
    available = int(baseline.get("sample_size") or 0)
    status = "ready" if available >= required and available > 0 else "insufficient_data"
    segments = _segment_rows(eligible)
    segment_min = int(min_segment_sample_size if min_segment_sample_size is not None else max(1, min_sample_size))
    adjustments = (
        recommend_adjustments(
            eligible,
            baseline,
            min_segment_sample_size=segment_min,
            max_adjustment=float(max_adjustment or DEFAULT_MAX_ADJUSTMENT),
        )
        if status == "ready"
        else _empty_adjustments()
    )
    return {
        "status": status,
        "baseline": baseline,
        "segments": segments,
        "excluded_rows": excluded,
        "available_sample_size": available,
        "required_sample_size": required,
        "min_segment_sample_size": segment_min,
        "max_adjustment": float(max_adjustment or DEFAULT_MAX_ADJUSTMENT),
        "recommended_adjustments": adjustments,
        "fresh_filter": {
            "recommendation_source": "current_run",
            "excluded_provider_statuses": sorted(INVALID_DEFAULT_PROVIDER_STATUSES),
        },
    }


def create_profile_from_calibration(
    payload: Mapping[str, Any],
    *,
    base_profile: Mapping[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    if payload.get("status") != "ready":
        raise ValueError("Cannot create active calibration profile from insufficient data")
    base = normalize_calibration_profile(base_profile or default_calibration_profile(), active=False, status="inactive")
    adjustments = dict(payload.get("recommended_adjustments") or _empty_adjustments())
    setup_adjustments = dict(base["setup_adjustments"])
    for item in adjustments.get("setup_adjustments") or []:
        setup = str(item.get("setup_type") or "")
        if setup:
            setup_adjustments[setup] = _round(item.get("adjustment"), 2) or 0.0
    risk_penalties = dict(base["risk_penalties"])
    for item in adjustments.get("risk_penalties") or []:
        flag = str(item.get("risk_flag") or "")
        if flag:
            risk_penalties[flag] = _round(item.get("penalty"), 2) or 0.0
    component_weights = dict(base["component_weights"])
    for item in adjustments.get("component_weight_nudges") or []:
        component = str(item.get("component") or "")
        if component in component_weights:
            component_weights[component] = round(
                min(3.0, max(0.0, component_weights[component] + (_safe_float(item.get("weight_delta")) or 0.0))),
                4,
            )

    profile = {
        "version": version or f"cal-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "status": "active",
        "active": True,
        "created_at": _utc_now(),
        "activated_at": _utc_now(),
        "deactivated_at": None,
        "source": "calibrate_swing_ranking.py",
        "source_sample_size": int((payload.get("baseline") or {}).get("sample_size") or 0),
        "created_from_sample_size": int((payload.get("baseline") or {}).get("sample_size") or 0),
        "description": "Conservative bounded calibration generated from fresh current_run rows.",
        "min_sample_size": int(payload.get("required_sample_size") or DEFAULT_MIN_SAMPLE_SIZE),
        "max_adjustment": float(payload.get("max_adjustment") or DEFAULT_MAX_ADJUSTMENT),
        "component_weights": component_weights,
        "setup_adjustments": setup_adjustments,
        "risk_penalties": risk_penalties,
        "eligibility_thresholds": dict(base["eligibility_thresholds"]),
        "baseline_metrics": dict(payload.get("baseline") or _empty_baseline()),
        "recommended_adjustments": adjustments,
    }
    valid, reason = validate_calibration_profile(profile)
    if not valid:
        raise ValueError(f"Generated invalid calibration profile: {reason}")
    return profile


def apply_calibration_to_score(
    component_scores: Mapping[str, Any],
    *,
    setup_type: str | None = None,
    risk_flags: Iterable[str] | None = None,
    profile: Mapping[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    normalized = normalize_calibration_profile(profile or default_calibration_profile(), active=bool(profile and profile.get("active")), status=str((profile or {}).get("status") or "inactive"))
    weights = normalized["component_weights"]
    weighted_components = {
        field: (_safe_float(component_scores.get(field)) or 0.0) * weights.get(field, 1.0)
        for field in COMPONENT_SCORE_FIELDS
    }
    base_score = sum(weighted_components.values())
    setup_adjustment = float(normalized["setup_adjustments"].get(str(setup_type), 0.0) or 0.0)
    applied_risk_penalties = []
    risk_penalty_total = 0.0
    for flag in risk_flags or []:
        penalty = _safe_float(normalized["risk_penalties"].get(str(flag)))
        if penalty is not None:
            risk_penalty_total += penalty
            applied_risk_penalties.append({"risk_flag": str(flag), "penalty": penalty})
    raw_score = base_score + setup_adjustment + risk_penalty_total

    thresholds = normalized["eligibility_thresholds"]
    min_risk = _safe_float(thresholds.get("min_risk_score"))
    min_liquidity = _safe_float(thresholds.get("min_liquidity_score"))
    threshold_penalties: list[dict[str, Any]] = []
    if min_risk is not None and (_safe_float(component_scores.get("risk_score")) or 0.0) < min_risk:
        raw_score = min(raw_score, 59.99)
        threshold_penalties.append({"threshold": "min_risk_score", "value": min_risk})
    if min_liquidity is not None and (_safe_float(component_scores.get("liquidity_score")) or 0.0) < min_liquidity:
        raw_score = min(raw_score, 59.99)
        threshold_penalties.append({"threshold": "min_liquidity_score", "value": min_liquidity})

    bounded = round(min(99.99, max(0.0, raw_score)), 2)
    context = {
        "calibration_profile_version": normalized.get("version"),
        "calibration_status": normalized.get("status"),
        "calibration_active": bool(normalized.get("active")),
        "setup_adjustment": _round(setup_adjustment, 2),
        "risk_penalty_total": _round(risk_penalty_total, 2),
        "applied_risk_penalties": applied_risk_penalties,
        "threshold_penalties": threshold_penalties,
        "weighted_components": {key: _round(value, 2) for key, value in weighted_components.items()},
    }
    return bounded, context


def build_calibration_status(profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = dict(profile or load_active_calibration_profile())
    active = bool(profile.get("active"))
    version = profile.get("version")
    status = profile.get("status") or ("active" if active else "inactive")
    baseline = dict(profile.get("baseline_metrics") or _empty_baseline())
    adjustments = dict(profile.get("recommended_adjustments") or _empty_adjustments())
    return {
        "status": status,
        "active": active,
        "active_profile_version": version if active else None,
        "version": version,
        "created_at": profile.get("created_at"),
        "activated_at": profile.get("activated_at"),
        "deactivated_at": profile.get("deactivated_at"),
        "source": profile.get("source") or "unknown",
        "source_sample_size": int(profile.get("source_sample_size") or 0),
        "created_from_sample_size": int(profile.get("created_from_sample_size") or profile.get("source_sample_size") or 0),
        "description": profile.get("description") or "",
        "min_sample_size": int(profile.get("min_sample_size") or DEFAULT_MIN_SAMPLE_SIZE),
        "baseline_metrics": baseline,
        "adjustments": {
            "setup_adjustments": list(adjustments.get("setup_adjustments") or []),
            "risk_penalties": list(adjustments.get("risk_penalties") or []),
            "component_weight_nudges": list(adjustments.get("component_weight_nudges") or []),
            "eligibility_thresholds": list(adjustments.get("eligibility_thresholds") or []),
        },
        "fallback_reason": profile.get("fallback_reason"),
        "profile_path": profile.get("profile_path"),
    }
