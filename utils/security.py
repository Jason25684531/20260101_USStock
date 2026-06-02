"""Security helper compatibility module for root-level utility imports."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


SECRETS_PATH = Path("/run/secrets")


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError):
            pass

    return os.environ.get(secret_name.upper(), default)
