from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


SECRETS_PATH = Path("/run/secrets")
DEFAULT_DB_USER = "trader"


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """Read Docker secrets first, then env vars for local development."""
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip()
        except OSError:
            return default

    # In a Docker-secrets environment, do not silently switch to unrelated env vars.
    if SECRETS_PATH.exists():
        return default

    env_value = os.environ.get(secret_name.upper())
    if env_value is not None:
        return env_value
    return default


def resolve_db_password(db_user: Optional[str], env: Optional[dict] = None) -> str:
    """Resolve the correct password source for root vs application users."""
    env_map = env or os.environ
    normalized_user = (db_user or env_map.get("DB_USER") or DEFAULT_DB_USER).strip() or DEFAULT_DB_USER

    if normalized_user.lower() == "root":
        return get_secret("db_root_password", default=env_map.get("DB_ROOT_PASSWORD", "rootpassword")) or ""

    return get_secret("db_password", default=env_map.get("DB_PASSWORD", "userpassword")) or ""


def get_db_config(env: Optional[dict] = None) -> Dict[str, str]:
    """Return DB connection config using explicit app-vs-root credential rules."""
    env_map = env or os.environ
    db_user = (env_map.get("DB_USER") or DEFAULT_DB_USER).strip() or DEFAULT_DB_USER

    return {
        "host": env_map.get("DB_HOST", "localhost"),
        "port": env_map.get("DB_PORT", "3306"),
        "user": db_user,
        "password": resolve_db_password(db_user, env=env_map),
        "name": env_map.get("DB_NAME", "usstock"),
    }


def build_connection_string(config: Dict[str, str]) -> str:
    return (
        f"mysql+mysqlconnector://{config['user']}:{config['password']}@"
        f"{config['host']}:{config['port']}/{config['name']}?charset=utf8mb4"
    )


def get_engine(config: Optional[Dict[str, str]] = None, echo: bool = False, env: Optional[dict] = None) -> Engine:
    cfg = config or get_db_config(env=env)
    return create_engine(
        build_connection_string(cfg),
        echo=echo,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
