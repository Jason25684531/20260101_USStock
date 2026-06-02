from __future__ import annotations

from datetime import date

from screener.swing_calibration import default_calibration_profile
from screener.swing_calibration_drift import build_drift_report, drift_thresholds_from_env


def _row(**overrides):
    base = {
        "recommendation_date": date(2026, 5, 20),
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


def test_drift_report_returns_insufficient_data_for_low_sample_size():
    report = build_drift_report([_row()], active_profile=default_calibration_profile(), min_sample_size=3)

    assert report["drift_status"] == "insufficient_data"
    assert report["score_bucket_status"] == "insufficient_data"
    assert report["top_rank_status"] == "insufficient_data"
    assert report["risk_flag_status"] == "insufficient_data"
    assert report["sample_size"] == 1


def test_score_bucket_drift_detects_high_score_underperformance():
    rows = []
    for idx in range(5):
        rows.append(_row(symbol=f"H{idx}", rank=idx + 1, score=84, forward_return_20d=-0.03, hit_20d=False))
        rows.append(_row(symbol=f"L{idx}", rank=idx + 11, score=64, forward_return_20d=0.04, hit_20d=True))

    report = build_drift_report(rows, active_profile=default_calibration_profile(status="active"), min_sample_size=5, return_margin=0.01)

    assert report["score_bucket_status"] == "drifted"
    assert report["drift_status"] == "drifted"
    assert any("High score bucket" in message for message in report["messages"])


def test_top_rank_drift_detects_top5_underperformance():
    rows = []
    for idx in range(5):
        rows.append(_row(symbol=f"T{idx}", rank=idx + 1, score=82, forward_return_20d=-0.02, hit_20d=False))
        rows.append(_row(symbol=f"O{idx}", rank=idx + 6, score=72, forward_return_20d=0.04, hit_20d=True))

    report = build_drift_report(rows, active_profile=default_calibration_profile(status="active"), min_sample_size=5, return_margin=0.01)

    assert report["top_rank_status"] == "drifted"
    assert any("Top5" in message for message in report["messages"])


def test_risk_flag_drift_detects_inverted_flags():
    rows = []
    for idx in range(5):
        rows.append(_row(symbol=f"R{idx}", risk_flags=["wide stop"], forward_return_20d=0.05, hit_20d=True, max_drawdown_20d=-0.01))
        rows.append(_row(symbol=f"N{idx}", risk_flags=[], forward_return_20d=0.00, hit_20d=False, max_drawdown_20d=-0.06))

    report = build_drift_report(rows, active_profile=default_calibration_profile(status="active"), min_sample_size=5, return_margin=0.01)

    assert report["risk_flag_status"] in {"warning", "drifted"}
    assert any("risk flag" in message.lower() for message in report["messages"])


def test_drift_report_filters_failed_and_snapshot_rows():
    rows = [
        _row(symbol="GOOD", provider_health_status="healthy", recommendation_source="current_run"),
        _row(symbol="BAD1", provider_health_status="failed", recommendation_source="current_run"),
        _row(symbol="BAD2", provider_health_status="healthy", recommendation_source="last_valid_snapshot"),
    ]

    report = build_drift_report(rows, active_profile=default_calibration_profile(), min_sample_size=1)

    assert report["sample_size"] == 1
    assert report["excluded_rows"]["provider_status:failed"] == 1
    assert report["excluded_rows"]["last_valid_snapshot"] == 1


def test_calibration_impact_ignores_invalid_provider_and_snapshot_rows():
    profile = default_calibration_profile(status="active")
    profile.update({"version": "cal-test", "active": True, "activated_at": "2026-05-15T00:00:00Z"})
    rows = [
        _row(symbol=f"B{idx}", recommendation_date=date(2026, 5, 10), forward_return_20d=0.01, hit_20d=True)
        for idx in range(5)
    ]
    rows.extend(
        _row(symbol=f"A{idx}", recommendation_date=date(2026, 5, 20), forward_return_20d=0.04, hit_20d=True)
        for idx in range(5)
    )
    rows.append(_row(symbol="BAD", recommendation_date=date(2026, 5, 20), provider_health_status="critical", forward_return_20d=-0.5))

    report = build_drift_report(rows, active_profile=profile, min_sample_size=5, return_margin=0.01)

    assert report["calibration_impact_status"] == "improved"
    assert report["calibration_impact"]["before"]["sample_size"] == 5
    assert report["calibration_impact"]["after"]["sample_size"] == 5


def test_invalid_env_thresholds_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("SWING_DRIFT_MIN_SAMPLE_SIZE", "bad")
    monkeypatch.setenv("SWING_DRIFT_RETURN_MARGIN", "-1")
    monkeypatch.setenv("SWING_DRIFT_HIT_RATE_MARGIN", "bad")
    monkeypatch.setenv("SWING_DRIFT_LOOKBACK_DAYS", "0")
    monkeypatch.setenv("SWING_DRIFT_ENABLE_AUDIT_LOG", "false")

    thresholds = drift_thresholds_from_env()

    assert thresholds.min_sample_size == 30
    assert thresholds.return_margin == 0.01
    assert thresholds.hit_rate_margin == 0.05
    assert thresholds.lookback_days == 90
    assert thresholds.enable_audit_log is False
