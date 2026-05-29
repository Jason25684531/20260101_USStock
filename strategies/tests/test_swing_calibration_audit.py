from __future__ import annotations

import json
from pathlib import Path

from screener.swing_calibration import default_calibration_profile, persist_calibration_profile
from screener.swing_calibration_drift import (
    backup_active_profile,
    ensure_swing_calibration_audit_table,
    log_calibration_audit_event,
    read_recent_calibration_audit_events,
    rollback_calibration_profile,
)


class RecordingConn:
    def __init__(self, *, fail_select: bool = False):
        self.statements = []
        self.fail_select = fail_select

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if self.fail_select and "SELECT" in sql.upper():
            raise RuntimeError("missing table")
        return self

    def mappings(self):
        return self

    def fetchall(self):
        return []


def _active_profile(version: str):
    profile = default_calibration_profile(status="active")
    profile.update({"version": version, "active": True, "source_sample_size": 40})
    return profile


def test_audit_table_guard_and_event_insert_are_stable():
    conn = RecordingConn()
    ensure_swing_calibration_audit_table(conn)
    log_calibration_audit_event(
        conn,
        "activate",
        profile_version="cal-new",
        previous_profile_version="cal-old",
        profile_path="data/swing_calibration_profile.json",
        created_from_sample_size=40,
        drift_status="warning",
        event_payload={"note": "test"},
    )

    joined = "\n".join(sql for sql, _ in conn.statements)
    assert "CREATE TABLE IF NOT EXISTS swing_calibration_audit_log" in joined
    assert "INSERT INTO swing_calibration_audit_log" in joined
    assert any(params and params["event_type"] == "activate" for _, params in conn.statements)


def test_recent_audit_events_returns_empty_when_storage_missing():
    assert read_recent_calibration_audit_events(RecordingConn(fail_select=True)) == []


def test_backup_active_profile_writes_versioned_copy(tmp_path: Path):
    profile_path = tmp_path / "active.json"
    persist_calibration_profile(_active_profile("cal-old"), profile_path)

    backup = backup_active_profile(profile_path)

    assert backup is not None
    assert backup.exists()
    assert "cal-old" in backup.name
    assert json.loads(backup.read_text(encoding="utf-8"))["version"] == "cal-old"


def test_rollback_restores_valid_profile_without_deleting_backups(tmp_path: Path):
    profile_path = tmp_path / "active.json"
    persist_calibration_profile(_active_profile("cal-current"), profile_path)
    backup_dir = tmp_path / "calibration_profiles"
    backup_dir.mkdir()
    backup_path = backup_dir / "swing_calibration_profile_cal-previous.json"
    backup_path.write_text(json.dumps(_active_profile("cal-previous")), encoding="utf-8")

    result = rollback_calibration_profile("cal-previous", profile_path=profile_path, backup_dir=backup_dir)

    restored = json.loads(profile_path.read_text(encoding="utf-8"))
    assert result["rolled_back"] is True
    assert result["profile_version"] == "cal-previous"
    assert restored["version"] == "cal-previous"
    assert restored["status"] == "active"
    assert restored["active"] is True
    assert restored["activated_at"]
    assert backup_path.exists()


def test_rollback_missing_target_is_safe(tmp_path: Path):
    profile_path = tmp_path / "active.json"
    persist_calibration_profile(_active_profile("cal-current"), profile_path)

    result = rollback_calibration_profile("missing", profile_path=profile_path, backup_dir=tmp_path / "calibration_profiles")

    assert result["rolled_back"] is False
    assert result["error"] == "profile_not_found"
    assert json.loads(profile_path.read_text(encoding="utf-8"))["version"] == "cal-current"
