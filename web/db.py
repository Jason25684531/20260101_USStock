"""
Database utilities for the Web Dashboard service.

Keeps DB configuration and engine creation in one place.
Provides schema introspection helpers shared by app.py and bot/handler.py.
"""

from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from utils.db import build_connection_string, get_db_config, get_engine


# ============================================
# Schema introspection helpers
# ============================================

def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the current database."""
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = :table_name
        LIMIT 1
    """), {'table_name': table_name}).first()
    return row is not None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
        LIMIT 1
    """), {'table_name': table_name, 'column_name': column_name}).first()
    return row is not None


def resolve_existing_column(conn, table_name: str, column_candidates) -> Optional[str]:
    """Return the first candidate column that exists for a table."""
    for column_name in column_candidates:
        if column_exists(conn, table_name, column_name):
            return column_name
    return None


def optional_column_expr(conn, table_name: str, column_candidates, alias: str, default_sql: str = "NULL") -> str:
    """Return a SQL select expression for the first existing candidate column."""
    column_name = resolve_existing_column(conn, table_name, column_candidates)
    if column_name:
        return f"{column_name} AS {alias}"
    return f"{default_sql} AS {alias}"


def select_optional_column(conn, table_name: str, column_candidates, alias: str, default_sql: str = "NULL") -> str:
    """Compatibility alias for optional select-column expressions."""
    return optional_column_expr(conn, table_name, column_candidates, alias, default_sql=default_sql)
