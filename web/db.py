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
