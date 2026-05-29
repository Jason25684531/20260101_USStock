from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
sys.modules.setdefault("yfinance", SimpleNamespace())

from screener.market_data_resilience import (
    DATA_MODE_FAILED,
    DATA_MODE_FALLBACK,
    DATA_MODE_LIVE,
    DATA_MODE_STALE,
    build_provider_health_diagnostics,
    empty_provider_health,
    normalize_provider_health,
    prune_provider_health_log,
)
from scripts.provider_health_diagnostics import build_provider_health_diagnostics_report


class _FakeConnection:
    def __init__(self, rowcount=0):
        self.calls = []
        self.rowcount = rowcount

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return SimpleNamespace(rowcount=self.rowcount)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, rowcount=0):
        self.conn = _FakeConnection(rowcount=rowcount)

    def begin(self):
        return self.conn


def test_normalize_provider_health_reports_healthy_current_run():
    payload = normalize_provider_health({
        "run_at": "2026-05-20 21:00:00",
        "total_symbols": 10,
        "live_successes": 8,
        "fallback_successes": 0,
        "failed_symbols": 2,
        "skipped_symbols": 2,
        "coverage_ratio": 0.8,
        "minimum_coverage_ratio": 0.6,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_LIVE,
        "recommendations_written": True,
        "provider_counts": {"openbb": 8},
        "top_error_types": {"timeout": 2},
        "provider_attempts": [{"provider": "openbb", "success": True}],
    })

    assert payload["status"] == "healthy"
    assert payload["coverage"] == 0.8
    assert payload["provider_coverage_ratio"] == 0.8
    assert payload["effective_provider"] == "openbb"
    assert payload["is_stale"] is False
    assert payload["recommendation_source"] == "current_run"
    assert payload["is_using_last_valid_snapshot"] is False
    assert payload["top_error_types"] == {"timeout": 2}


def test_normalize_provider_health_reports_stale_and_snapshot_metadata():
    payload = normalize_provider_health({
        "run_at": "2026-05-21 21:00:00",
        "coverage_ratio": 0.35,
        "minimum_coverage_ratio": 0.6,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_STALE,
        "stale_data_used": True,
        "stale_age_days": 4,
        "recommendations_written": False,
        "last_valid_recommendation_time": "2026-05-19",
        "provider_counts": {"market_data": 5},
        "fallback_attempts": [{"provider": "market_data", "cache_age_days": 4}],
    })

    assert payload["status"] == "stale"
    assert payload["is_stale"] is True
    assert payload["stale_age_days"] == 4
    assert payload["effective_provider"] == "market_data"
    assert payload["recommendation_source"] == "last_valid_snapshot"
    assert payload["is_using_last_valid_snapshot"] is True
    assert payload["last_valid_recommendation_at"] == "2026-05-19"


def test_normalize_provider_health_marks_critical_for_low_coverage_or_critical_stale_age():
    low_coverage = normalize_provider_health({
        "coverage_ratio": 0.1,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
        "recommendations_written": False,
    })
    too_stale = normalize_provider_health({
        "coverage_ratio": 0.4,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_STALE,
        "stale_data_used": True,
        "stale_age_days": 11,
        "critical_stale_days": 10,
        "recommendations_written": False,
    })

    assert low_coverage["status"] == "critical"
    assert too_stale["status"] == "critical"


def test_empty_provider_health_uses_unknown_defaults():
    payload = empty_provider_health()

    assert payload["provider_health_available"] is False
    assert payload["status"] == "unknown"
    assert payload["current_data_mode"] == "unknown"
    assert payload["recommendation_source"] == "unknown"


def test_prune_provider_health_log_deletes_rows_older_than_retention_cutoff():
    engine = _FakeEngine(rowcount=3)

    deleted = prune_provider_health_log(
        engine,
        retention_days=30,
        now=datetime(2026, 5, 27, 12, 0, 0),
    )

    assert deleted == 3
    statement, params = engine.conn.calls[-1]
    assert "DELETE FROM provider_health_log" in statement
    assert str(params["cutoff"]).startswith("2026-04-27")


def test_prune_provider_health_log_is_safe_when_table_is_empty():
    engine = _FakeEngine(rowcount=0)

    assert prune_provider_health_log(engine, retention_days=30) == 0


def test_provider_health_diagnostics_collapses_repeated_openbb_parse_errors():
    payload = normalize_provider_health({
        "coverage_ratio": 0.0,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
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

    diagnostics = build_provider_health_diagnostics(payload)

    assert diagnostics["root_cause"] == "openbb_json_parse_error"
    assert diagnostics["attempt_summary"] == "openbb:openbbjson_parse_error x3"
    assert diagnostics["fallback_outcome"] == "unavailable"
    assert diagnostics["snapshot_preserved"] is True
    assert "OpenBB" in diagnostics["display_message"]
    assert "前次有效推薦" in diagnostics["display_message"]
    assert any("OpenBB" in action for action in diagnostics["operator_actions"])


def test_normalize_provider_health_includes_safe_diagnostics_when_attempts_missing():
    payload = normalize_provider_health({
        "coverage_ratio": 0.0,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
        "recommendations_written": False,
        "top_error_types": {"json_parse_error": 1},
    })

    diagnostics = payload["diagnostics"]

    assert diagnostics["root_cause"] == "provider_unavailable"
    assert diagnostics["fallback_outcome"] == "unavailable"
    assert diagnostics["snapshot_preserved"] is False
    assert diagnostics["display_status"] == "critical"
    assert diagnostics["operator_actions"]


def test_dataops_provider_health_report_includes_repair_workflow():
    payload = normalize_provider_health({
        "run_at": "2026-05-28 16:00:00",
        "coverage_ratio": 0.0,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
        "recommendations_written": False,
        "last_valid_recommendation_time": "2026-05-28 00:00:00",
        "provider_attempts": [
            {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
        ],
        "top_error_types": {"json_parse_error": 1},
    })

    report = build_provider_health_diagnostics_report(payload)

    assert "Provider health diagnostics" in report
    assert "root_cause=openbb_json_parse_error" in report
    assert "fallback_outcome=unavailable" in report
    assert "snapshot_preserved=True" in report
    assert "檢查 OpenBB response/parser contract" in report
    assert "確認 yfinance fallback 可用" in report
    assert "確認本機 market_data stale age" in report
    assert "確認前次有效推薦快照" in report
