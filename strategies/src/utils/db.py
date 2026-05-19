"""
Strategy-side wrapper around the shared root-level DB helper.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.engine import Engine


_SHARED_DB_PATH = Path(__file__).resolve().parents[3] / "utils" / "db.py"
_SHARED_DB_SPEC = spec_from_file_location("_shared_utils_db", _SHARED_DB_PATH)
_SHARED_DB_MODULE = module_from_spec(_SHARED_DB_SPEC)
assert _SHARED_DB_SPEC is not None and _SHARED_DB_SPEC.loader is not None
_SHARED_DB_SPEC.loader.exec_module(_SHARED_DB_MODULE)

build_connection_string = _SHARED_DB_MODULE.build_connection_string
get_db_config = _SHARED_DB_MODULE.get_db_config
get_engine = _SHARED_DB_MODULE.get_engine

__all__ = ["build_connection_string", "get_db_config", "get_engine", "Dict", "Optional", "Engine"]
