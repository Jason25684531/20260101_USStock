"""
Database utilities for the Web Dashboard service.

Keeps DB configuration and engine creation in one place.
Provides schema introspection helpers shared by app.py and bot/handler.py.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from security import get_secret


def get_db_config() -> Dict[str, str]:
    """Return DB connection config from env/secrets with defaults."""
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "3306")
    db_user = os.getenv("DB_USER", "root")
    db_pass = get_secret("db_root_password", default=os.getenv("DB_PASSWORD", "rootpassword"))
    db_name = os.getenv("DB_NAME", "usstock")

    return {
        "host": db_host,
        "port": db_port,
        "user": db_user,
        "password": db_pass or "",
        "name": db_name,
    }


def build_connection_string(config: Dict[str, str]) -> str:
    """Build a SQLAlchemy MySQL connection string from config."""
    return (
        f"mysql+mysqlconnector://{config['user']}:{config['password']}@"
        f"{config['host']}:{config['port']}/{config['name']}?charset=utf8mb4"
    )


def get_engine(config: Optional[Dict[str, str]] = None, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine using env/secrets config."""
    cfg = config or get_db_config()
    return create_engine(build_connection_string(cfg), echo=echo)


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


# ============================================
# Schema introspection helpers
# ============================================

def table_exists(conn, table_name: str) -> bool:
    """Check whether *table_name* exists in the current database."""
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = :table_name
        LIMIT 1
    """), {'table_name': table_name}).first()
    return row is not None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check whether *column_name* exists in *table_name*."""
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
        LIMIT 1
    """), {'table_name': table_name, 'column_name': column_name}).first()
    return row is not None
