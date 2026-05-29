from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

from adapters.database import DatabaseAdapter
from screener.swing_calibration import load_active_calibration_profile
from screener.swing_calibration_drift import (
    build_drift_report,
    list_calibration_profile_backups,
    log_calibration_audit_event,
    read_recent_calibration_audit_events,
    rollback_calibration_profile,
)
from screener.swing_performance import load_swing_performance_rows


def run_monitor(
    conn,
    *,
    report: bool = False,
    rollback: str | None = None,
    lookback_days: int | None = None,
    log_audit: bool = False,
    profile_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    min_sample_size: int | None = None,
) -> dict[str, Any]:
    if rollback:
        result = rollback_calibration_profile(
            rollback,
            profile_path=profile_path,
            backup_dir=backup_dir,
            conn=conn,
        )
        return {"mode": "rollback", "rollback": result}

    rows = []
    try:
        rows = load_swing_performance_rows(conn, limit=500)
    except Exception:
        rows = []
    active_profile = load_active_calibration_profile(profile_path)
    drift_report = build_drift_report(
        rows,
        active_profile=active_profile,
        lookback_days=lookback_days,
        min_sample_size=min_sample_size,
    )
    drift_report["recent_audit_events"] = read_recent_calibration_audit_events(conn, limit=10)
    backups = list_calibration_profile_backups(profile_path, backup_dir)
    drift_report["rollback_profiles"] = backups
    drift_report["rollback_available"] = bool(backups)
    if log_audit:
        log_calibration_audit_event(
            conn,
            "drift_check",
            profile_version=drift_report.get("active_profile_version") or drift_report.get("profile_version"),
            created_from_sample_size=drift_report.get("sample_size"),
            score_bucket_status=drift_report.get("score_bucket_status"),
            top_rank_status=drift_report.get("top_rank_status"),
            risk_flag_status=drift_report.get("risk_flag_status"),
            drift_status=drift_report.get("drift_status"),
            event_payload=drift_report,
        )
    return {"mode": "report" if report else "report", "report": drift_report}


def _print_report(result: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    if result.get("mode") == "rollback":
        rollback = result.get("rollback") or {}
        print("Swing calibration rollback")
        print(f"rolled_back={rollback.get('rolled_back')}")
        print(f"profile_version={rollback.get('profile_version')}")
        if rollback.get("error"):
            print(f"error={rollback.get('error')}")
        return
    report = result.get("report") or {}
    print("Swing calibration drift report")
    print(f"active_profile_version={report.get('active_profile_version') or report.get('profile_version')}")
    print(f"lookback_days={report.get('lookback_days')}")
    print(f"sample_size={report.get('sample_size')}")
    print(f"drift_status={report.get('drift_status')}")
    print(f"score_bucket_status={report.get('score_bucket_status')}")
    print(f"top_rank_status={report.get('top_rank_status')}")
    print(f"risk_flag_status={report.get('risk_flag_status')}")
    print(f"calibration_impact_status={report.get('calibration_impact_status')}")
    for message in report.get("messages") or []:
        print(f"message={message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor swing ranking calibration drift from local performance rows.")
    parser.add_argument("--report", action="store_true", help="Build a calibration drift report.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--lookback-days", type=int, default=None, help="Override drift lookback days.")
    parser.add_argument("--log-audit", action="store_true", help="Persist a drift_check audit event.")
    parser.add_argument("--rollback", default=None, help="Rollback to a backed-up profile version.")
    parser.add_argument("--profile-path", default=None, help="Override active profile path.")
    parser.add_argument("--backup-dir", default=None, help="Override backup profile directory.")
    args = parser.parse_args()

    db = DatabaseAdapter()
    try:
        with db.engine.begin() as conn:
            result = run_monitor(
                conn,
                report=args.report or not args.rollback,
                rollback=args.rollback,
                lookback_days=args.lookback_days,
                log_audit=args.log_audit,
                profile_path=args.profile_path,
                backup_dir=args.backup_dir,
            )
        _print_report(result, as_json=args.json)
        rollback = result.get("rollback") or {}
        if args.rollback and not rollback.get("rolled_back"):
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
