"""
Core module for the US Stock Trading System.

This package contains the backtesting engine and strategy logic.
"""

from .backtest import (
    run_sma_strategy,
    print_performance_report,
    calculate_metrics
)

__all__ = [
    "run_sma_strategy",
    "print_performance_report",
    "calculate_metrics"
]
