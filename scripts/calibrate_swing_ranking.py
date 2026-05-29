from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

from adapters.database import DatabaseAdapter
from screener.swing_calibration import (
    build_calibration_payload,
    create_profile_from_calibration,
    deactivate_calibration_profile,
    load_active_calibration_profile,
    persist_calibration_profile,
)
from screener.swing_calibration_drift import backup_active_profile, log_calibration_audit_event
from screener.swing_performance import load_swing_performance_rows


def run_calibration(
    conn,
    *,
    limit: int = 500,
    min_sample_size: int = 30,
    min_segment_sample_size: int | None = None,
    max_adjustment: float = 5.0,
    include_provider_statuses: Iterable[str] | None = None,
    activate: bool = False,
    deactivate: bool = False,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    if deactivate:
        previous = load_active_calibration_profile(profile_path)
        removed = deactivate_calibration_profile(profile_path)
        result = {"status": "deactivated", "deactivated": removed, "activated": False}
        log_calibration_audit_event(
            conn,
            "deactivate",
            profile_version=previous.get("version") if removed else None,
            profile_path=str(profile_path) if profile_path else None,
            event_payload=result,
        )
        return result

    rows = load_swing_performance_rows(conn, limit=limit)
    payload = build_calibration_payload(
        rows,
        min_sample_size=min_sample_size,
        min_segment_sample_size=min_segment_sample_size,
        max_adjustment=max_adjustment,
        include_provider_statuses=include_provider_statuses,
    )
    result = {
        **payload,
        "activated": False,
        "profile_path": str(profile_path) if profile_path else None,
        "comparison": {
            "before": payload.get("baseline") or {},
            "after": {
                "mode": "projected_after_next_ranking_run",
                "recommended_adjustments": payload.get("recommended_adjustments") or {},
                "note": "Apply the generated profile and re-run recommendation/performance evaluation for measured after metrics.",
            },
        },
    }
    if not activate:
        return result

    if payload.get("status") != "ready":
        result["activation_error"] = "insufficient_data"
        return result

    previous = load_active_calibration_profile(profile_path)
    backup_path = backup_active_profile(profile_path)
    profile = create_profile_from_calibration(payload)
    saved_path = persist_calibration_profile(profile, profile_path)
    result["activated"] = True
    result["profile_path"] = str(saved_path)
    result["profile_version"] = profile["version"]
    result["backup_path"] = str(backup_path) if backup_path else None
    log_calibration_audit_event(
        conn,
        "activate",
        profile_version=profile.get("version"),
        previous_profile_version=previous.get("version") if previous.get("active") else None,
        profile_path=str(saved_path),
        created_from_sample_size=profile.get("created_from_sample_size") or profile.get("source_sample_size"),
        event_payload=result,
    )
    return result


def _print_summary(result: dict[str, Any]) -> None:
    if result.get("deactivated"):
        print("Swing ranking calibration profile deactivated")
        return
    baseline = result.get("baseline") or {}
    print("Swing ranking calibration analysis complete")
    print(f"status={result.get('status')}")
    print(f"sample_size={baseline.get('sample_size', 0)}")
    print(f"required_sample_size={result.get('required_sample_size')}")
    print(f"avg_forward_return_20d={baseline.get('avg_forward_return_20d')}")
    print(f"hit_rate_20d={baseline.get('hit_rate_20d')}")
    print(f"excluded_rows={json.dumps(result.get('excluded_rows') or {}, sort_keys=True)}")
    adjustments = result.get("recommended_adjustments") or {}
    print(f"setup_adjustments={json.dumps(adjustments.get('setup_adjustments') or [], ensure_ascii=False)}")
    print(f"risk_penalties={json.dumps(adjustments.get('risk_penalties') or [], ensure_ascii=False)}")
    comparison = result.get("comparison") or {}
    print(f"comparison={json.dumps(comparison, ensure_ascii=False, default=str)}")
    if result.get("activated"):
        print(f"activated_profile={result.get('profile_version')}")
        print(f"profile_path={result.get('profile_path')}")
        if result.get("backup_path"):
            print(f"backup_path={result.get('backup_path')}")
    elif result.get("activation_error"):
        print(f"activation_error={result.get('activation_error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate the deterministic swing ranking model from local performance rows.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum performance rows to read.")
    parser.add_argument("--min-sample-size", type=int, default=30, help="Minimum eligible fresh rows required for activation.")
    parser.add_argument("--min-segment-sample-size", type=int, default=None, help="Minimum rows required for a segment adjustment.")
    parser.add_argument("--max-adjustment", type=float, default=5.0, help="Maximum score adjustment per calibration run.")
    parser.add_argument("--include-provider-status", action="append", default=[], help="Provider status to include despite default exclusion.")
    parser.add_argument("--activate", action="store_true", help="Persist a valid generated profile.")
    parser.add_argument("--deactivate", action="store_true", help="Remove the active profile and return to default behavior.")
    parser.add_argument("--profile-path", default=None, help="Override the active profile JSON path.")
    args = parser.parse_args()

    db = DatabaseAdapter()
    try:
        with db.engine.begin() as conn:
            result = run_calibration(
                conn,
                limit=args.limit,
                min_sample_size=args.min_sample_size,
                min_segment_sample_size=args.min_segment_sample_size,
                max_adjustment=args.max_adjustment,
                include_provider_statuses=args.include_provider_status,
                activate=args.activate,
                deactivate=args.deactivate,
                profile_path=args.profile_path,
            )
        _print_summary(result)
        if args.activate and not result.get("activated"):
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
