"""
Security utilities for the US Stock Trading System.

This module provides secure secret management using environment variables.
Environment variables are loaded from the .env file (docker-compose env_file directive).
Falls back to Docker Secrets for backward compatibility.

Author: Quant System
Created: 2025-12-31
Updated: 2025-02-09 - Migrated to environment variables from Docker Secrets
"""

import os
from pathlib import Path
from typing import Optional


# Docker Secrets base path (for backward compatibility)
SECRETS_PATH = Path("/run/secrets")


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a secret value securely.
    
    Priority order:
    1. Environment variable (from .env file) - PRIMARY METHOD
    2. Docker Secrets (/run/secrets/<secret_name>) - for backward compatibility
    3. Default value (if provided)
    
    Args:
        secret_name: The name of the secret to retrieve.
                     Can be provided in lowercase or uppercase.
        default: Optional default value if secret is not found.
        
    Returns:
        The secret value as a string, or None/default if not found.
        
    Example:
        >>> db_password = get_secret("db_password")
        >>> api_key = get_secret("ALPACA_API_KEY", default="paper_trading_key")
    """
    # Normalize the secret name to uppercase for environment variable lookup
    env_var_name = secret_name.upper()
    
    # Priority 1: Environment variable (from .env file)
    env_value = os.environ.get(env_var_name)
    if env_value is not None:
        return env_value
    
    # Priority 2: Docker Secrets (backward compatibility)
    secret_file = SECRETS_PATH / secret_name
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except (IOError, PermissionError) as e:
            print(f"Warning: Could not read secret file {secret_file}: {e}")
    
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
                     Can be provided in lowercase or uppercase.
        
    Returns:
        The secret value as a string.
        
    Raises:
        ValueError: If secret is not found in any source.
        
    Example:
        >>> db_password = require_secret("db_password")
        >>> api_key = require_secret("ALPACA_API_KEY")
    """
    value = get_secret(secret_name)
    if value is None:
        env_var_name = secret_name.upper()
        raise ValueError(
            f"Required secret '{secret_name}' not found. "
            f"Provide it via environment variable '{env_var_name}' in .env file or Docker Secrets."
        )
    return value


def is_production() -> bool:
    """
    Check if running in production (Docker) environment.
    
    Returns:
        True if Docker Secrets path exists (indicating Docker environment).
    """
    return SECRETS_PATH.exists()


def is_simulation_mode() -> bool:
    """
    Check if running in simulation mode.
    
    Returns:
        True if TRADING_MODE environment variable is set to 'simulation'.
    """
    trading_mode = os.getenv('TRADING_MODE', '').lower()
    return trading_mode == 'simulation'


def require_secret_if_not_simulation(secret_name: str) -> Optional[str]:
    """
    Retrieve a required secret value, but only if not in simulation mode.
    
    In simulation mode, returns None instead of raising an error.
    Useful for optional secrets like ALPACA_API_KEY when using MockBroker.
    
    Args:
        secret_name: The name of the secret to retrieve.
        
    Returns:
        The secret value as a string, or None if in simulation mode.
        
    Raises:
        ValueError: If not in simulation mode and secret is not found.
        
    Example:
        >>> # In simulation mode, returns None without error
        >>> api_key = require_secret_if_not_simulation("ALPACA_API_KEY")
    """
    if is_simulation_mode():
        return None
    
    return require_secret(secret_name)
