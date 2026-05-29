from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text


def _safe_message(value: Any, limit: int = 500) -> str | None:
    if value in (None, ""):
        return None
    message = str(value)
    for marker in ("token", "api_key", "apikey", "secret", "password", "authorization", "bearer"):
        lower = message.lower()
        pos = lower.find(marker)
        while pos >= 0:
            end = pos
            while end < len(message) and message[end] not in {" ", "\n", "\r", "\t", "&", ",", ";"}:
                end += 1
            message = message[:pos] + f"{marker}=[redacted]" + message[end:]
            lower = message.lower()
            pos = lower.find(marker, pos + len(marker) + 10)
    return message[:limit]


def build_pull_log_record(**values: Any) -> dict[str, Any]:
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    return {
        "job_name": values.get("job_name") or "market_data_pull",
        "status": values.get("status") or "unknown",
        "started_at": values.get("started_at") or now,
        "finished_at": values.get("finished_at"),
        "provider_status": values.get("provider_status"),
        "coverage": values.get("coverage"),
        "symbols_requested": int(values.get("symbols_requested") or 0),
        "symbols_updated": int(values.get("symbols_updated") or 0),
        "rows_updated": int(values.get("rows_updated") or 0),
        "error_type": values.get("error_type"),
        "error_message": _safe_message(values.get("error_message")),
    }


def ensure_market_data_pull_log(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS market_data_pull_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            job_name VARCHAR(80) NOT NULL,
            status VARCHAR(32) NOT NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            provider_status VARCHAR(64) NULL,
            coverage DECIMAL(8, 4) NULL,
            symbols_requested INT NOT NULL DEFAULT 0,
            symbols_updated INT NOT NULL DEFAULT 0,
            rows_updated INT NOT NULL DEFAULT 0,
            error_type VARCHAR(80) NULL,
            error_message TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_market_data_pull_created_at (created_at),
            INDEX idx_market_data_pull_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))


def record_market_data_pull(engine, record: dict[str, Any]) -> bool:
    payload = build_pull_log_record(**(record or {}))
    try:
        with engine.begin() as conn:
            ensure_market_data_pull_log(conn)
            conn.execute(text("""
                INSERT INTO market_data_pull_log (
                    job_name, status, started_at, finished_at, provider_status, coverage,
                    symbols_requested, symbols_updated, rows_updated, error_type, error_message
                ) VALUES (
                    :job_name, :status, :started_at, :finished_at, :provider_status, :coverage,
                    :symbols_requested, :symbols_updated, :rows_updated, :error_type, :error_message
                )
            """), payload)
        return True
    except Exception:
        return False


def load_latest_market_data_pull(conn) -> dict[str, Any] | None:
    ensure_market_data_pull_log(conn)
    row = conn.execute(text("""
        SELECT job_name, status, started_at, finished_at, provider_status, coverage,
               symbols_requested, symbols_updated, rows_updated, error_type, error_message, created_at
        FROM market_data_pull_log
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """)).mappings().first()
    if not row:
        return None
    return {
        "job_name": row.get("job_name"),
        "status": row.get("status"),
        "started_at": str(row.get("started_at")) if row.get("started_at") else None,
        "finished_at": str(row.get("finished_at")) if row.get("finished_at") else None,
        "provider_status": row.get("provider_status"),
        "coverage": float(row.get("coverage")) if row.get("coverage") is not None else None,
        "symbols_requested": int(row.get("symbols_requested") or 0),
        "symbols_updated": int(row.get("symbols_updated") or 0),
        "rows_updated": int(row.get("rows_updated") or 0),
        "error_type": row.get("error_type"),
        "error_message": _safe_message(row.get("error_message")),
        "created_at": str(row.get("created_at")) if row.get("created_at") else None,
    }
