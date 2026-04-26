#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from strategies.src.config import BACKTEST_SYMBOLS, DB_URI, calc_atr
from strategies.src.core.position_sizing import calculate_position_size
from strategies.src.core.risk_manager import RiskManager
from strategies.src.core.trading_costs import FRICTION_COST, calculate_friction_cost

ML_STRATEGY_MODULE_PATH = PROJECT_ROOT / "strategies" / "src" / "strategies" / "ml_strategy.py"
ML_STRATEGY_SPEC = importlib.util.spec_from_file_location("usstock_portfolio_ml_strategy", ML_STRATEGY_MODULE_PATH)
if ML_STRATEGY_SPEC is None or ML_STRATEGY_SPEC.loader is None:
    raise ImportError(f"無法載入 ML 策略模組: {ML_STRATEGY_MODULE_PATH}")

ML_STRATEGY_MODULE = importlib.util.module_from_spec(ML_STRATEGY_SPEC)
ML_STRATEGY_SPEC.loader.exec_module(ML_STRATEGY_MODULE)

BEAR_MARKET = ML_STRATEGY_MODULE.BEAR_MARKET
calculate_valuation_targets = ML_STRATEGY_MODULE.calculate_valuation_targets
calculate_v30_features = ML_STRATEGY_MODULE.calculate_v30_features
get_market_regime = ML_STRATEGY_MODULE.get_market_regime
load_data_from_db = ML_STRATEGY_MODULE.load_data_from_db
run_xgboost_inference = ML_STRATEGY_MODULE.run_xgboost_inference

DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_TOP_N = 5
DEFAULT_SCORE_THRESHOLD = 0.5
DEFAULT_MONTHS = 6
DEFAULT_SYMBOL_COUNT = 20
LOOKBACK_BUFFER_DAYS = 420
REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "portfolio_backtest.png"


def _is_rebalance_day(trade_date: pd.Timestamp) -> bool:
    return pd.Timestamp(trade_date).weekday() == 4


@dataclass
class Holding:
    symbol: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    last_price: float
    highest_price: float
    cost_basis: float


@dataclass
class Portfolio:
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    cash: float = field(default=DEFAULT_INITIAL_CAPITAL)
    positions: dict[str, Holding] = field(default_factory=dict)
    equity_history: list[dict[str, Any]] = field(default_factory=list)
    trade_log: list[dict[str, Any]] = field(default_factory=list)

    def buy(self, symbol: str, price: float, allocation_value: float, trade_date: pd.Timestamp) -> bool:
        if price <= 0 or allocation_value <= 0:
            return False

        max_affordable_shares = int(min(allocation_value, self.cash) / (price * (1 + FRICTION_COST)))
        if max_affordable_shares <= 0:
            return False

        notional = max_affordable_shares * price
        friction = calculate_friction_cost(notional)
        total_cost = notional + friction
        if total_cost > self.cash:
            return False

        self.cash -= total_cost
        self.positions[symbol] = Holding(
            symbol=symbol,
            shares=max_affordable_shares,
            entry_price=price,
            entry_date=pd.Timestamp(trade_date),
            last_price=price,
            highest_price=price,
            cost_basis=total_cost,
        )
        self.trade_log.append(
            {
                "date": pd.Timestamp(trade_date),
                "symbol": symbol,
                "side": "BUY",
                "price": round(price, 4),
                "shares": max_affordable_shares,
                "notional": round(notional, 4),
                "friction": round(friction, 4),
            }
        )
        return True

    def sell(self, symbol: str, price: float, trade_date: pd.Timestamp, reason: str) -> bool:
        holding = self.positions.get(symbol)
        if holding is None or price <= 0:
            return False

        notional = holding.shares * price
        friction = calculate_friction_cost(notional)
        proceeds = notional - friction
        self.cash += proceeds
        self.trade_log.append(
            {
                "date": pd.Timestamp(trade_date),
                "symbol": symbol,
                "side": "SELL",
                "price": round(price, 4),
                "shares": holding.shares,
                "notional": round(notional, 4),
                "friction": round(friction, 4),
                "reason": reason,
            }
        )
        del self.positions[symbol]
        return True

    def total_equity(self, close_prices: dict[str, float]) -> float:
        market_value = 0.0
        for symbol, holding in self.positions.items():
            mark_price = close_prices.get(symbol, holding.last_price)
            market_value += holding.shares * mark_price
        return self.cash + market_value

    def update_market_value(self, trade_date: pd.Timestamp, close_prices: dict[str, float]) -> float:
        market_value = 0.0
        for symbol, holding in self.positions.items():
            mark_price = close_prices.get(symbol)
            if mark_price is None or pd.isna(mark_price) or float(mark_price) <= 0:
                mark_price = holding.last_price
            else:
                mark_price = float(mark_price)
            holding.last_price = mark_price
            holding.highest_price = max(holding.highest_price, mark_price)
            market_value += holding.shares * mark_price

        total_equity = self.cash + market_value
        self.equity_history.append(
            {
                "date": pd.Timestamp(trade_date),
                "cash": round(self.cash, 4),
                "market_value": round(market_value, 4),
                "total_equity": round(total_equity, 4),
            }
        )
        return total_equity


def _load_fundamental_history(symbols: list[str], end_date: str) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}

    engine = create_engine(DB_URI)
    placeholders = ", ".join(f":s{i}" for i in range(len(symbols)))
    params = {f"s{i}": symbol.upper() for i, symbol in enumerate(symbols)}
    params["end_date"] = end_date
    query = text(
        f"""
        SELECT data_date, symbol, pe_ratio, forward_pe, peg_ratio, pb_ratio, market_cap
        FROM stock_fundamentals
        WHERE symbol IN ({placeholders})
          AND data_date <= :end_date
        ORDER BY symbol ASC, data_date ASC
        """
    )
    try:
        df = pd.read_sql(query, con=engine, params=params)
    except Exception as error:
        print(f"[WARN] [回測] 讀取基本面歷史失敗: {error}")
        return {}
    finally:
        engine.dispose()

    if df.empty:
        return {}

    df["data_date"] = pd.to_datetime(df["data_date"], errors="coerce")
    df = df.dropna(subset=["data_date"]).sort_values(["symbol", "data_date"])

    history: dict[str, pd.DataFrame] = {}
    for symbol, group in df.groupby("symbol"):
        history[str(symbol).upper()] = group.set_index("data_date").drop(columns=["symbol"])
    return history


def _get_fundamental_snapshot(history: dict[str, pd.DataFrame], symbol: str, as_of_date: pd.Timestamp) -> dict:
    symbol_history = history.get(symbol.upper())
    if symbol_history is None or symbol_history.empty:
        return {}

    snapshot = symbol_history.loc[symbol_history.index <= pd.Timestamp(as_of_date)]
    if snapshot.empty:
        return {}
    return snapshot.iloc[-1].to_dict()


def _derive_eps_ttm(current_price: float, fundamentals: dict) -> float | None:
    if current_price <= 0:
        return None

    for pe_key in ("pe_ratio", "forward_pe"):
        pe_value = fundamentals.get(pe_key)
        if pe_value is not None and pd.notna(pe_value) and float(pe_value) > 0:
            return float(current_price) / float(pe_value)
    return None


def _get_price_on_date(df: pd.DataFrame, trade_date: pd.Timestamp, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    trade_date = pd.Timestamp(trade_date)
    if trade_date not in df.index:
        return None
    value = df.loc[trade_date, column]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _get_execution_price(df: pd.DataFrame, signal_date: pd.Timestamp, execution_date: pd.Timestamp) -> tuple[float | None, str]:
    next_open = _get_price_on_date(df, execution_date, "open")
    if next_open is not None and next_open > 0:
        return next_open, "T+1 open"

    next_close = _get_price_on_date(df, execution_date, "close")
    if next_close is not None and next_close > 0:
        return next_close, "T+1 close fallback"

    signal_close = _get_price_on_date(df, signal_date, "close")
    if signal_close is not None and signal_close > 0:
        return signal_close, "signal-day close fallback"

    return None, "no execution price"


def preload_data(symbols: list[str], start_date: str, end_date: str) -> dict[str, Any]:
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    buffered_start = start_ts - pd.Timedelta(days=LOOKBACK_BUFFER_DAYS)

    price_data: dict[str, pd.DataFrame] = {}
    feature_data: dict[str, pd.DataFrame] = {}
    excluded: dict[str, str] = {}

    all_symbols = sorted({symbol.upper() for symbol in symbols} | {"SPY"})
    for symbol in all_symbols:
        df = load_data_from_db(symbol)
        if df.empty:
            excluded[symbol] = "missing price history"
            continue

        df = df.loc[(df.index >= buffered_start) & (df.index <= end_ts)].copy()
        if df.empty:
            excluded[symbol] = "empty in requested window"
            continue

        df["atr_14"] = calc_atr(df, period=14)
        price_data[symbol] = df

        if symbol == "SPY":
            continue

        features_df = calculate_v30_features(df)
        features_df = features_df.loc[features_df.index >= start_ts]
        if features_df.empty:
            excluded[symbol] = "insufficient feature history"
            continue
        feature_data[symbol] = features_df

    valid_symbols = sorted(symbol for symbol in symbols if symbol.upper() in feature_data)
    spy_df = price_data.get("SPY")
    if spy_df is not None and not spy_df.empty:
        decision_dates = pd.DatetimeIndex(spy_df.loc[(spy_df.index >= start_ts) & (spy_df.index <= end_ts)].index)
    else:
        union_index = None
        for df in feature_data.values():
            union_index = df.index if union_index is None else union_index.union(df.index)
        decision_dates = pd.DatetimeIndex([] if union_index is None else union_index)

    fundamental_history = _load_fundamental_history(valid_symbols, end_ts.strftime("%Y-%m-%d"))
    return {
        "price_data": price_data,
        "feature_data": feature_data,
        "fundamental_history": fundamental_history,
        "decision_dates": decision_dates,
        "valid_symbols": valid_symbols,
        "excluded_symbols": excluded,
    }


def _score_symbol_as_of(features_df: pd.DataFrame, as_of_date: pd.Timestamp, symbol: str) -> float | None:
    window = features_df.loc[features_df.index <= pd.Timestamp(as_of_date)]
    if window.empty:
        return None
    try:
        return float(run_xgboost_inference(window, symbol, log_missing_features=False))
    except Exception as error:
        print(f"[WARN] [{symbol}] XGBoost 推論失敗: {error}")
        return None


def _compute_metrics(equity_df: pd.DataFrame) -> dict[str, float]:
    if equity_df.empty:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }

    equity_series = equity_df["total_equity"].astype(float)
    total_return = equity_series.iloc[-1] / equity_series.iloc[0] - 1
    day_span = max((equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days, 1)
    years = day_span / 365.25
    cagr = (equity_series.iloc[-1] / equity_series.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0

    daily_returns = equity_series.pct_change().dropna()
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))

    running_peak = equity_series.cummax()
    drawdown = equity_series / running_peak - 1
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
    }


def _plot_equity_curve(equity_df: pd.DataFrame, save_path: Path) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    if not MATPLOTLIB_AVAILABLE or equity_df.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(equity_df["date"], equity_df["total_equity"], color="#0B6E4F", linewidth=2)
    ax.set_title("Cross-Sectional Portfolio Equity Curve", fontsize=14, fontweight="bold")
    ax.set_ylabel("Total Equity")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def run_portfolio_backtest(
    symbols: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    top_n: int = DEFAULT_TOP_N,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> tuple[pd.DataFrame, dict[str, float], Portfolio]:
    preload = preload_data(symbols, start_date, end_date)
    price_data = preload["price_data"]
    feature_data = preload["feature_data"]
    fundamental_history = preload["fundamental_history"]
    decision_dates = preload["decision_dates"]
    valid_symbols = preload["valid_symbols"]
    excluded_symbols = preload["excluded_symbols"]

    if len(decision_dates) < 2:
        raise ValueError("可用交易日不足，無法執行投資組合回測")

    print("\n=== 橫截面投資組合回測 ===")
    print(f"股票池: {len(valid_symbols)} 檔 | 排除: {len(excluded_symbols)} 檔")
    if excluded_symbols:
        for symbol, reason in sorted(excluded_symbols.items())[:10]:
            print(f"  - {symbol}: {reason}")
    print(f"期間: {decision_dates[0].strftime('%Y-%m-%d')} -> {decision_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Top N: {top_n} | 初始資金: ${initial_capital:,.2f} | 單邊摩擦: {FRICTION_COST * 100:.2f}%")

    portfolio = Portfolio(initial_capital=initial_capital)
    risk_manager = RiskManager(max_hold_days=30, atr_multiplier=2.0)

    initial_prices = {
        symbol: _get_price_on_date(price_data[symbol], decision_dates[0], "close")
        for symbol in valid_symbols
        if symbol in price_data
    }
    portfolio.update_market_value(decision_dates[0], initial_prices)

    for current_date, next_date in zip(decision_dates[:-1], decision_dates[1:]):
        spy_df = price_data.get("SPY", pd.DataFrame())
        market_regime = get_market_regime(spy_df.loc[spy_df.index <= current_date]) if not spy_df.empty else "BULL_MARKET"
        is_rebalance_day = _is_rebalance_day(current_date)

        current_close_prices = {}
        current_atrs = {}
        for symbol in valid_symbols:
            symbol_prices = price_data.get(symbol)
            if symbol_prices is None:
                continue
            close_price = _get_price_on_date(symbol_prices, current_date, "close")
            if close_price is not None:
                current_close_prices[symbol] = close_price
            atr_value = _get_price_on_date(symbol_prices, current_date, "atr_14")
            if atr_value is not None:
                current_atrs[symbol] = atr_value

        exit_candidates: dict[str, str] = {}
        if risk_manager.positions:
            risk_results = risk_manager.check_all(current_close_prices, current_atrs, current_date.date())
            for symbol, (should_exit, reason) in risk_results.items():
                if should_exit:
                    exit_candidates[symbol] = reason

        for symbol, reason in exit_candidates.items():
            if symbol not in portfolio.positions:
                continue
            symbol_prices = price_data.get(symbol)
            if symbol_prices is None:
                continue
            execution_price, execution_source = _get_execution_price(symbol_prices, current_date, next_date)
            if execution_price is None:
                continue
            if portfolio.sell(symbol, execution_price, next_date, f"{reason} | {execution_source}"):
                risk_manager.remove_position(symbol)

        next_close_prices = {
            symbol: _get_price_on_date(price_data[symbol], next_date, "close")
            for symbol in valid_symbols
            if symbol in price_data
        }

        if not is_rebalance_day:
            portfolio.update_market_value(next_date, next_close_prices)
            continue

        candidates: list[dict[str, Any]] = []
        for symbol in valid_symbols:
            features_df = feature_data.get(symbol)
            symbol_prices = price_data.get(symbol)
            if features_df is None or symbol_prices is None:
                continue
            if current_date not in features_df.index:
                continue

            score = _score_symbol_as_of(features_df, current_date, symbol)
            if score is None or score < score_threshold:
                continue

            current_price = current_close_prices.get(symbol)
            if current_price is None:
                continue

            fundamentals = _get_fundamental_snapshot(fundamental_history, symbol, current_date)
            eps_ttm = _derive_eps_ttm(current_price, fundamentals)
            valuation = calculate_valuation_targets(current_price=current_price, eps_ttm=eps_ttm)
            if valuation["valuation_status"] == "OVERVALUED":
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "current_price": current_price,
                    "valuation": valuation,
                    "eps_ttm": eps_ttm,
                }
            )

        candidates = sorted(candidates, key=lambda item: item["score"], reverse=True)
        top_candidates = candidates[:top_n]
        top_symbols = {item["symbol"] for item in top_candidates}

        for symbol in list(portfolio.positions.keys()):
            if symbol not in top_symbols and symbol not in exit_candidates:
                exit_candidates[symbol] = "Top5 replacement"

        for symbol, reason in exit_candidates.items():
            if symbol not in portfolio.positions:
                continue
            symbol_prices = price_data.get(symbol)
            if symbol_prices is None:
                continue
            execution_price, execution_source = _get_execution_price(symbol_prices, current_date, next_date)
            if execution_price is None:
                continue
            if portfolio.sell(symbol, execution_price, next_date, f"{reason} | {execution_source}"):
                risk_manager.remove_position(symbol)

        sizing_equity = portfolio.total_equity(current_close_prices)
        sizing = calculate_position_size(
            total_equity=sizing_equity,
            is_bear_market=market_regime == BEAR_MARKET,
        )
        allocation_value = float(sizing["max_position_value"])

        for candidate in top_candidates:
            symbol = candidate["symbol"]
            if symbol in portfolio.positions:
                continue
            symbol_prices = price_data.get(symbol)
            if symbol_prices is None:
                continue
            execution_price, execution_source = _get_execution_price(symbol_prices, current_date, next_date)
            if execution_price is None:
                continue
            desired_allocation = min(allocation_value, portfolio.cash)
            if desired_allocation <= 0:
                break
            if portfolio.buy(symbol, execution_price, desired_allocation, next_date):
                atr_value = current_atrs.get(symbol, 0.0)
                risk_manager.add_position(symbol, execution_price, next_date.date(), atr=max(float(atr_value), 0.0))

        portfolio.update_market_value(next_date, next_close_prices)

    equity_df = pd.DataFrame(portfolio.equity_history)
    metrics = _compute_metrics(equity_df)
    _plot_equity_curve(equity_df, REPORT_PATH)
    return equity_df, metrics, portfolio


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-sectional portfolio backtester")
    parser.add_argument("--symbols", type=str, default=None, help="股票代碼，逗號分隔")
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS, help="快速驗證月數")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="每日持有前幾名")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL, help="初始資金")
    args = parser.parse_args()

    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    else:
        symbols = BACKTEST_SYMBOLS[:DEFAULT_SYMBOL_COUNT]

    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.DateOffset(months=max(int(args.months), 1))

    equity_df, metrics, portfolio = run_portfolio_backtest(
        symbols=symbols,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        initial_capital=float(args.initial_capital),
        top_n=int(args.top_n),
    )

    print("\n=== 回測績效摘要 ===")
    print(f"總報酬率: {metrics['total_return']:+.2%}")
    print(f"年化報酬率(CAGR): {metrics['cagr']:+.2%}")
    print(f"最大回撤(MDD): {metrics['max_drawdown']:+.2%}")
    print(f"夏普值: {metrics['sharpe']:.2f}")
    print(f"最終淨值: ${equity_df['total_equity'].iloc[-1]:,.2f}" if not equity_df.empty else "最終淨值: N/A")
    print(f"交易筆數: {len(portfolio.trade_log)}")
    print(f"圖表輸出: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())