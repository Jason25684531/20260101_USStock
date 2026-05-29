from __future__ import annotations

import json
from pathlib import Path

from screener.swing_calibration import (
    DEFAULT_MIN_SAMPLE_SIZE,
    build_calibration_payload,
    build_calibration_status,
    default_calibration_profile,
    load_active_calibration_profile,
    persist_calibration_profile,
    validate_calibration_profile,
)


def _row(**overrides):
    base = {
        "rank": 1,
        "score": 82.0,
        "setup_type": "breakout",
        "risk_flags": [],
        "provider_health_status": "healthy",
        "recommendation_source": "current_run",
        "forward_return_5d": 0.01,
        "forward_return_10d": 0.02,
        "forward_return_20d": 0.04,
        "hit_5d": True,
        "hit_10d": True,
        "hit_20d": True,
        "max_drawdown_20d": -0.03,
        "max_favorable_excursion_20d": 0.08,
    }
    base.update(overrides)
    return base


def test_calibration_payload_summarizes_fresh_rows_and_exclusions():
    rows = [
        _row(setup_type="breakout", forward_return_20d=0.06, hit_20d=True),
        _row(setup_type="breakout", forward_return_20d=0.04, hit_20d=True),
        _row(setup_type="pullback_reclaim", risk_flags=["wide stop"], forward_return_20d=-0.04, hit_20d=False),
        _row(setup_type="pullback_reclaim", risk_flags=["wide stop"], forward_return_20d=-0.02, hit_20d=False),
        _row(recommendation_source="last_valid_snapshot", provider_health_status="critical"),
        _row(provider_health_status="stale"),
    ]

    payload = build_calibration_payload(rows, min_sample_size=2, max_adjustment=4)

    assert payload["status"] == "ready"
    assert payload["baseline"]["sample_size"] == 4
    assert payload["excluded_rows"]["last_valid_snapshot"] == 1
    assert payload["excluded_rows"]["provider_status:stale"] == 1
    assert any(item["setup_type"] == "pullback_reclaim" for item in payload["segments"]["setup_types"])
    penalties = [item for item in payload["recommended_adjustments"]["setup_adjustments"] if item["setup_type"] == "pullback_reclaim"]
    assert penalties
    assert penalties[0]["adjustment"] < 0
    assert abs(penalties[0]["adjustment"]) <= 4
    risk_penalties = payload["recommended_adjustments"]["risk_penalties"]
    assert risk_penalties[0]["risk_flag"] == "wide stop"
    assert risk_penalties[0]["penalty"] < 0


def test_calibration_payload_refuses_insufficient_data():
    payload = build_calibration_payload([_row()], min_sample_size=3)

    assert payload["status"] == "insufficient_data"
    assert payload["baseline"]["sample_size"] == 1
    assert payload["available_sample_size"] == 1
    assert payload["required_sample_size"] == 3
    assert payload["recommended_adjustments"]["setup_adjustments"] == []


def test_profile_validation_and_default_fallback(tmp_path: Path):
    default_profile = default_calibration_profile()
    assert default_profile["version"] == "default"
    assert default_profile["component_weights"]["trend_score"] == 1.0

    valid_profile = {
        "version": "cal-20260528-000001",
        "created_at": "2026-05-28T00:00:00Z",
        "source_sample_size": 120,
        "min_sample_size": DEFAULT_MIN_SAMPLE_SIZE,
        "component_weights": default_profile["component_weights"],
        "setup_adjustments": {"breakout": 2.0},
        "risk_penalties": {"wide stop": -3.0},
        "eligibility_thresholds": default_profile["eligibility_thresholds"],
        "baseline_metrics": {"avg_forward_return_20d": 0.01},
        "recommended_adjustments": {"setup_adjustments": [], "risk_penalties": [], "component_weight_nudges": []},
    }
    assert validate_calibration_profile(valid_profile)[0] is True

    profile_path = tmp_path / "profile.json"
    persist_calibration_profile(valid_profile, profile_path)
    loaded = load_active_calibration_profile(profile_path)
    assert loaded["status"] == "active"
    assert loaded["version"] == "cal-20260528-000001"
    assert loaded["active"] is True

    profile_path.write_text(json.dumps({"version": "bad"}), encoding="utf-8")
    fallback = load_active_calibration_profile(profile_path)
    assert fallback["status"] == "fallback_to_default"
    assert fallback["version"] == "default"
    assert fallback["active"] is False
    assert "fallback_reason" in fallback


def test_calibration_status_has_safe_defaults():
    status = build_calibration_status(default_calibration_profile(status="inactive"))

    assert status["status"] == "inactive"
    assert status["active"] is False
    assert status["active_profile_version"] is None
    assert status["source_sample_size"] == 0
    assert status["min_sample_size"] == DEFAULT_MIN_SAMPLE_SIZE
    assert status["baseline_metrics"]["avg_forward_return_20d"] is None
    assert status["adjustments"]["setup_adjustments"] == []


def test_calibration_status_exposes_governance_metadata_safely(tmp_path: Path):
    legacy_profile = default_calibration_profile(status="active")
    legacy_profile.update({
        "version": "cal-legacy",
        "active": True,
        "source_sample_size": 42,
    })
    profile_path = tmp_path / "profile.json"
    persist_calibration_profile(legacy_profile, profile_path)

    loaded = load_active_calibration_profile(profile_path)
    status = build_calibration_status(loaded)

    assert status["status"] == "active"
    assert status["active_profile_version"] == "cal-legacy"
    assert status["activated_at"] is None
    assert status["deactivated_at"] is None
    assert status["source"] == "unknown"
    assert status["created_from_sample_size"] == 42
    assert status["description"] == ""
