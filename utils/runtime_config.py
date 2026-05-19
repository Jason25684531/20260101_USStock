from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


DEFAULT_MODEL_PATH = Path("/app/data/model.pkl")


def resolve_model_path(explicit_path: Optional[str] = None, env: Optional[dict] = None) -> Path:
    """Resolve the primary model artifact path."""
    if explicit_path:
        return Path(explicit_path)

    env_map = env or os.environ
    configured = env_map.get("MODEL_PATH")
    if configured:
        return Path(configured)
    return DEFAULT_MODEL_PATH


def resolve_test_model_path(explicit_path: Optional[str] = None, env: Optional[dict] = None) -> Optional[Path]:
    """Resolve an explicit local/test fallback model path when configured."""
    if explicit_path:
        return Path(explicit_path)

    env_map = env or os.environ
    configured = env_map.get("TEST_MODEL_PATH")
    if configured:
        return Path(configured)
    return None


def get_model_load_candidates(
    explicit_path: Optional[str] = None,
    explicit_test_path: Optional[str] = None,
    env: Optional[dict] = None,
) -> List[Path]:
    """Return ordered model lookup candidates with explicit fallback only."""
    primary = resolve_model_path(explicit_path=explicit_path, env=env)
    fallback = resolve_test_model_path(explicit_path=explicit_test_path, env=env)
    candidates = [primary]
    if fallback and fallback != primary:
        candidates.append(fallback)
    return candidates


def find_existing_model_path(
    explicit_path: Optional[str] = None,
    explicit_test_path: Optional[str] = None,
    env: Optional[dict] = None,
) -> Optional[Path]:
    """Return the first configured model artifact path that currently exists."""
    for candidate in get_model_load_candidates(
        explicit_path=explicit_path,
        explicit_test_path=explicit_test_path,
        env=env,
    ):
        if candidate.exists():
            return candidate
    return None
