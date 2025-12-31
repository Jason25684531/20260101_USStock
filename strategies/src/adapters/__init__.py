"""
Adapters module for the US Stock Trading System.

This package provides data adapters for market data, databases, and APIs.
"""

from .market_data import fetch_data, fetch_multiple, get_latest_price

__all__ = ["fetch_data", "fetch_multiple", "get_latest_price"]
