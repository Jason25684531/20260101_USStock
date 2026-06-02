from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

try:
    import yfinance  # noqa: F401
except Exception:
    sys.modules.setdefault("yfinance", SimpleNamespace())

from screener.market_data_resilience import empty_provider_health, normalize_provider_health
from utils.db import get_db_config, get_engine


REPAIR_WORKFLOW = [
    "檢查 OpenBB response/parser contract",
    "確認 yfinance fallback 可用",
    "確認本機 market_data stale age",
    "確認前次有效推薦快照",
    "修復 provider 後重新執行 screener 並檢查 coverage",
]


LEGACY_REPAIR_WORKFLOW = [
    "檢查 OpenBB response/parser contract",
    "確認 yfinance fallback 是否可恢復覆蓋率",
    "確認 local market_data stale age",
    "確認 last-valid snapshot 是否仍被保留",
    "重新執行 provider smoke，確認 screener 可用 fallback coverage",
]


def _parse_error_fixture() -> dict[str, Any]:
    return normalize_provider_health({
        "run_at": "2026-05-28 16:00:00",
        "coverage_ratio": 0.0,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": "failed",
        "recommendations_written": False,
        "last_valid_recommendation_time": "2026-05-28 00:00:00",
        "effective_provider": "openbb",
        "provider_attempts": [
            {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
            {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
            {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
        ],
        "top_error_types": {"json_parse_error": 2},
        "skip_reasons": {"provider_data_unavailable": 2},
    })


def load_latest_provider_health(conn) -> dict[str, Any]:
    try:
        row = conn.execute(text("""
            SELECT *
            FROM provider_health_log
            ORDER BY run_at DESC, id DESC
            LIMIT 1
        """)).mappings().first()
    except Exception:
        return empty_provider_health()
    return normalize_provider_health(dict(row)) if row else empty_provider_health()


def build_provider_health_diagnostics_report(provider_health: Mapping[str, Any] | None) -> str:
    payload = normalize_provider_health(dict(provider_health or {}))
    diagnostics = payload.get("diagnostics") or {}
    actions = diagnostics.get("operator_actions") or []
    lines = [
        "Provider health diagnostics",
        f"run_at={payload.get('run_at') or 'N/A'}",
        f"status={payload.get('status')}",
        f"coverage={payload.get('coverage')}",
        f"root_cause={diagnostics.get('root_cause')}",
        f"fallback_outcome={diagnostics.get('fallback_outcome')}",
        f"recommendation_source={payload.get('recommendation_source')}",
        f"snapshot_preserved={diagnostics.get('snapshot_preserved')}",
        f"last_valid_recommendation_at={payload.get('last_valid_recommendation_at') or 'N/A'}",
        f"attempts={diagnostics.get('attempt_summary')}",
        f"top_errors={diagnostics.get('top_error_summary')}",
        f"skip_reasons={diagnostics.get('skip_summary')}",
        f"display_message={diagnostics.get('display_message')}",
    ]
    for action in actions:
        lines.append(f"operator_action={action}")
    lines.append("Repair workflow")
    for index, step in enumerate(REPAIR_WORKFLOW, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize latest provider health root cause, fallback outcome, "
            "snapshot preservation, and concrete repair workflow."
        )
    )
    parser.add_argument("--fixture", choices=["parse-error"], help="Use a deterministic local fixture instead of the DB.")
    parser.add_argument("--latest", action="store_true", help="Read the latest provider health row from the DB.")
    parser.add_argument("--json", action="store_true", help="Emit normalized provider health JSON.")
    args = parser.parse_args()

    if args.fixture == "parse-error":
        payload = _parse_error_fixture()
    else:
        config = get_db_config()
        engine = get_engine(config, echo=False)
        with engine.connect() as conn:
            payload = load_latest_provider_health(conn)
        engine.dispose()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(build_provider_health_diagnostics_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
