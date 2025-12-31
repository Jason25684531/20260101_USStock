"""
Security utilities for the US Stock Trading System.

This module provides secure secret management following Zero Trust principles.
Secrets are read from Docker Secrets first (/run/secrets/), with ENV fallback
for local development only.

Author: Quant System
Created: 2025-12-31
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
    1. Docker Secrets (/run/secrets/<secret_name>)
    2. Environment variable (for local dev only)
    3. Default value (if provided)
    
    Args:
        secret_name: The name of the secret to retrieve.
        default: Optional default value if secret is not found.
        
    Returns:
        The secret value as a string, or None/default if not found.
        
    Raises:
        ValueError: If secret is required but not found (when default is None).
        
    Example:
        >>> db_password = get_secret("db_password")
        >>> api_key = get_secret("alpaca_api_key", default="paper_trading_key")
    """
    # Priority 1: Docker Secrets (production)
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError) as e:
            print(f"Warning: Could not read secret file {secret_file}: {e}")
    
    # Priority 2: Environment variable (local dev fallback)
    env_value = os.environ.get(secret_name.upper())
    if env_value is not None:
        return env_value
    
    # Priority 3: Default value
    if default is not None:
        return default
    
    # No secret found
    return None


def require_secret(secret_name: str) -> str:
    """
    Retrieve a required secret value. Raises if not found.
    
    Args:
        secret_name: The name of the secret to retrieve.
        
    Returns:
        The secret value as a string.
        
    Raises:
        ValueError: If secret is not found in any source.
        
    Example:
        >>> db_password = require_secret("db_password")
    """
    value = get_secret(secret_name)
    if value is None:
        raise ValueError(
            f"Required secret '{secret_name}' not found. "
            f"Provide it via Docker Secrets or environment variable '{secret_name.upper()}'."
        )
    return value


def is_production() -> bool:
    """
    Check if running in production (Docker) environment.
    
    Returns:
        True if Docker Secrets path exists (indicating production).
    """
    return SECRETS_PATH.exists()
