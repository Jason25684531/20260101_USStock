"""
Database utilities for the US Stock Trading System (strategy service).

Centralizes DB configuration and connection string construction to avoid
duplication across modules and scripts.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .security import get_secret


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
