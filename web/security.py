"""
Security utilities for the Web Dashboard.

This module provides secure secret management following Zero Trust principles.
Secrets are read from Docker Secrets first (/run/secrets/), with ENV fallback
for local development only.

Author: Quant System
Created: 2026-02-02
"""

import os
from pathlib import Path
from typing import Optional


# Docker Secrets base path
SECRETS_PATH = Path("/run/secrets")


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a secret value securely.
    
    Priority order:
    1. Docker Secrets (/run/secrets/<secret_name>) - REQUIRED in production
    2. Environment variable (for local dev ONLY when not in production)
    3. Default value (if provided)
    
    Args:
        secret_name: The name of the secret to retrieve.
        default: Optional default value if secret is not found.
        
    Returns:
        The secret value as a string, or None/default if not found.
        
    Example:
        >>> db_password = get_secret("db_password")
        >>> api_key = get_secret("line_channel_token")
    """
    # Priority 1: Docker Secrets (production)
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError) as e:
            print(f"Warning: Could not read secret file {secret_file}: {e}")
    
    # If in production (Docker Secrets path exists), do NOT fall back to env vars
    if SECRETS_PATH.exists():
        return default
    
    # Priority 2: Environment variable (local dev fallback ONLY)
    env_value = os.environ.get(secret_name.upper())
    if env_value is not None:
        return env_value
    
    # Priority 3: Default value
    return default


def is_production() -> bool:
    """
    Check if running in production environment.
    
    Returns:
        True if Docker Secrets directory exists (production), False otherwise.
    """
    return SECRETS_PATH.exists()
