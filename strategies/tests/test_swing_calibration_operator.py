from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.calibrate_swing_ranking import run_calibration
from scripts.monitor_swing_calibration import run_monitor


class FakeConn:
    pass


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


def test_calibration_dry_run_does_not_persist(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.calibrate_swing_ranking.load_swing_performance_rows",
        lambda conn, limit=500: [_row(), _row(setup_type="pullback_reclaim", forward_return_20d=-0.02, hit_20d=False)],
    )
    profile_path = tmp_path / "profile.json"

    result = run_calibration(FakeConn(), min_sample_size=2, profile_path=profile_path)

    assert result["status"] == "ready"
    assert result["activated"] is False
    assert not profile_path.exists()


def test_calibration_activation_refuses_insufficient_sample(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("scripts.calibrate_swing_ranking.load_swing_performance_rows", lambda conn, limit=500: [_row()])
    profile_path = tmp_path / "profile.json"

    result = run_calibration(FakeConn(), min_sample_size=3, activate=True, profile_path=profile_path)

    assert result["status"] == "insufficient_data"
    assert result["activated"] is False
    assert result["activation_error"] == "insufficient_data"
    assert not profile_path.exists()


def test_calibration_activation_and_deactivation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.calibrate_swing_ranking.load_swing_performance_rows",
        lambda conn, limit=500: [_row(), _row(setup_type="pullback_reclaim", forward_return_20d=-0.02, hit_20d=False)],
    )
    profile_path = tmp_path / "profile.json"

    activated = run_calibration(FakeConn(), min_sample_size=2, activate=True, profile_path=profile_path)
    deactivated = run_calibration(FakeConn(), deactivate=True, profile_path=profile_path)

    assert activated["activated"] is True
    assert activated["profile_version"].startswith("cal-")
    assert profile_path.exists() is False
    assert deactivated["deactivated"] is True


def test_calibration_activation_backs_up_previous_profile(monkeypatch, tmp_path: Path):
    from screener.swing_calibration import default_calibration_profile, persist_calibration_profile

    monkeypatch.setattr(
        "scripts.calibrate_swing_ranking.load_swing_performance_rows",
        lambda conn, limit=500: [_row(), _row(setup_type="pullback_reclaim", forward_return_20d=-0.02, hit_20d=False)],
    )
    profile_path = tmp_path / "profile.json"
    previous = default_calibration_profile(status="active")
    previous.update({"version": "cal-previous", "active": True, "source_sample_size": 50})
    persist_calibration_profile(previous, profile_path)

    activated = run_calibration(FakeConn(), min_sample_size=2, activate=True, profile_path=profile_path)

    assert activated["activated"] is True
    assert activated["backup_path"]
    assert Path(activated["backup_path"]).exists()
    assert Path(activated["backup_path"]).name.endswith("cal-previous.json")


def test_monitor_script_builds_json_ready_report(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.monitor_swing_calibration.load_swing_performance_rows",
        lambda conn, limit=500: [_row(), _row(rank=6, score=65, forward_return_20d=0.01, hit_20d=True)],
    )
    profile_path = tmp_path / "profile.json"

    result = run_monitor(FakeConn(), report=True, profile_path=profile_path, min_sample_size=1)

    assert result["mode"] == "report"
    assert result["report"]["sample_size"] == 2
    assert "drift_status" in result["report"]


def test_monitor_script_rolls_back_profile(monkeypatch, tmp_path: Path):
    from screener.swing_calibration import default_calibration_profile, persist_calibration_profile

    profile_path = tmp_path / "profile.json"
    current = default_calibration_profile(status="active")
    current.update({"version": "cal-current", "active": True, "source_sample_size": 40})
    previous = default_calibration_profile(status="active")
    previous.update({"version": "cal-previous", "active": True, "source_sample_size": 40})
    persist_calibration_profile(current, profile_path)
    backup_dir = tmp_path / "calibration_profiles"
    backup_dir.mkdir()
    (backup_dir / "swing_calibration_profile_cal-previous.json").write_text(
        __import__("json").dumps(previous),
        encoding="utf-8",
    )

    result = run_monitor(FakeConn(), rollback="cal-previous", profile_path=profile_path, backup_dir=backup_dir)

    assert result["mode"] == "rollback"
    assert result["rollback"]["rolled_back"] is True
    assert result["rollback"]["profile_version"] == "cal-previous"
