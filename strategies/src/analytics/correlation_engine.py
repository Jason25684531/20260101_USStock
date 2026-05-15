from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

import pandas as pd


def build_sector_breakdown(holdings: Iterable[Mapping]) -> list[dict]:
    counter: Counter[str] = Counter()
    for holding in holdings:
        sector = str(holding.get("sector") or "Unknown").strip() or "Unknown"
        counter[sector] += 1
    return [
        {"sector": sector, "count": count}
        for sector, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_correlation_payload(
    symbols: list[str],
    price_history: Mapping[str, pd.DataFrame],
    window_days: int = 60,
) -> dict:
    unique_symbols = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
    if len(unique_symbols) < 2:
        return {
            "window_days": int(window_days),
            "symbols": [],
            "matrix": [],
            "reason": "至少需要 2 檔持倉才能計算相關性",
        }

    close_series: dict[str, pd.Series] = {}
    for symbol in unique_symbols:
        df = price_history.get(symbol)
        if df is None or df.empty:
            continue
        frame = df.copy()
        close_col = "close" if "close" in frame.columns else "Close" if "Close" in frame.columns else None
        if close_col is None:
            continue
        series = pd.to_numeric(frame[close_col], errors="coerce").dropna()
        if series.empty:
            continue
        series.index = pd.to_datetime(series.index)
        close_series[symbol] = series.sort_index().tail(window_days + 1)

    if len(close_series) < 2:
        return {
            "window_days": int(window_days),
            "symbols": [],
            "matrix": [],
            "reason": "持倉價格資料不足，無法建立相關性矩陣",
        }

    closes = pd.DataFrame(close_series).dropna(how="any")
    returns = closes.pct_change().dropna(how="any")
    if returns.empty or len(returns) < 20:
        return {
            "window_days": int(window_days),
            "symbols": [],
            "matrix": [],
            "reason": "有效報酬樣本不足，無法計算相關性",
        }

    corr = returns.corr(method="pearson")
    if corr.empty or corr.isna().all().all():
        return {
            "window_days": int(window_days),
            "symbols": [],
            "matrix": [],
            "reason": "相關性矩陣不可計算",
        }

    ordered_symbols = list(corr.columns)
    matrix: list[list[float | None]] = []
    for row_symbol in ordered_symbols:
        row: list[float | None] = []
        for col_symbol in ordered_symbols:
            value = corr.at[row_symbol, col_symbol]
            row.append(None if pd.isna(value) else round(float(value), 4))
        matrix.append(row)

    return {
        "window_days": int(window_days),
        "symbols": ordered_symbols,
        "matrix": matrix,
        "reason": "",
    }
