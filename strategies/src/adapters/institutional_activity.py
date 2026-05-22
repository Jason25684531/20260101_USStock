from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

try:
    from strategies.src.config import DB_URI, UNIVERSE_TICKERS
except ModuleNotFoundError:
    from config import DB_URI, UNIVERSE_TICKERS

try:
    import yfinance as yf
except ImportError:
    yf = None

ACTIVITY_SOURCE = 'yfinance-holders'
DEFAULT_ACTIVITY_SYMBOLS = tuple(sorted({symbol.upper() for symbol in UNIVERSE_TICKERS} | {'SPY'}))


def _safe_date(value) -> date | None:
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        return None
    return parsed.date()


def _safe_int(value) -> int | None:
    numeric = pd.to_numeric(value, errors='coerce')
    if pd.isna(numeric):
        return None
    return int(round(float(numeric)))


def _safe_float(value) -> float | None:
    numeric = pd.to_numeric(value, errors='coerce')
    if pd.isna(numeric):
        return None
    return float(numeric)


def _prepare_holders_snapshot(df: pd.DataFrame | None, prefix: str) -> dict[str, Any]:
    empty_snapshot = {
        f'{prefix}_report_date': None,
        f'{prefix}_holders_count': 0,
        f'{prefix}_total_shares': None,
        f'{prefix}_total_value': None,
        f'{prefix}_avg_pct_change': None,
    }
    if df is None or df.empty:
        return empty_snapshot

    report_dates = pd.to_datetime(df.get('Date Reported'), errors='coerce')
    shares = pd.to_numeric(df.get('Shares'), errors='coerce')
    values = pd.to_numeric(df.get('Value'), errors='coerce')
    pct_change = pd.to_numeric(df.get('pctChange'), errors='coerce')

    return {
        f'{prefix}_report_date': None if report_dates.dropna().empty else report_dates.dropna().max().date(),
        f'{prefix}_holders_count': int(len(df)),
        f'{prefix}_total_shares': None if shares.dropna().empty else int(shares.fillna(0).sum()),
        f'{prefix}_total_value': None if values.dropna().empty else int(values.fillna(0).sum()),
        f'{prefix}_avg_pct_change': None if pct_change.dropna().empty else float(pct_change.dropna().mean()),
    }


def _prepare_insider_metrics(df: pd.DataFrame | None) -> dict[str, Any]:
    metrics = {
        'insider_buys_6m': None,
        'insider_sells_6m': None,
        'insider_net_shares_6m': None,
        'insider_total_transactions_6m': None,
        'insider_total_shares_held': None,
    }
    if df is None or df.empty:
        return metrics

    buy_trans = None
    sell_trans = None
    label_column = 'Insider Purchases Last 6m'
    for _, row in df.iterrows():
        label = str(row.get(label_column) or '').strip().lower()
        shares = _safe_int(row.get('Shares'))
        transactions = _safe_int(row.get('Trans'))

        if label == 'purchases':
            metrics['insider_buys_6m'] = shares
            buy_trans = transactions
        elif label == 'sales':
            metrics['insider_sells_6m'] = shares
            sell_trans = transactions
        elif 'net shares purchased' in label:
            metrics['insider_net_shares_6m'] = shares
            metrics['insider_total_transactions_6m'] = transactions
        elif 'total insider shares held' in label:
            metrics['insider_total_shares_held'] = shares

    if metrics['insider_net_shares_6m'] is None and metrics['insider_buys_6m'] is not None and metrics['insider_sells_6m'] is not None:
        metrics['insider_net_shares_6m'] = metrics['insider_buys_6m'] - metrics['insider_sells_6m']
    if metrics['insider_total_transactions_6m'] is None and (buy_trans is not None or sell_trans is not None):
        metrics['insider_total_transactions_6m'] = int((buy_trans or 0) + (sell_trans or 0))

    return metrics


def build_institutional_activity_snapshot(symbol: str) -> dict[str, Any]:
    if yf is None:
        return {}

    ticker = yf.Ticker(symbol.upper())

    try:
        institution_df = ticker.institutional_holders
    except Exception:
        institution_df = pd.DataFrame()

    try:
        mutualfund_df = ticker.mutualfund_holders
    except Exception:
        mutualfund_df = pd.DataFrame()

    try:
        insider_df = ticker.insider_purchases
    except Exception:
        insider_df = pd.DataFrame()

    institution_snapshot = _prepare_holders_snapshot(institution_df, 'institution')
    mutualfund_snapshot = _prepare_holders_snapshot(mutualfund_df, 'mutualfund')
    insider_snapshot = _prepare_insider_metrics(insider_df)

    if all(
        value in (None, 0)
        for value in (
            institution_snapshot['institution_total_shares'],
            mutualfund_snapshot['mutualfund_total_shares'],
            insider_snapshot['insider_net_shares_6m'],
        )
    ):
        return {}

    return {
        'symbol': symbol.upper(),
        'snapshot_date': date.today().isoformat(),
        **institution_snapshot,
        **mutualfund_snapshot,
        **insider_snapshot,
        'source': ACTIVITY_SOURCE,
    }


def save_institutional_activity(snapshot: dict[str, Any], db_uri: str = DB_URI) -> bool:
    if not snapshot:
        return False

    engine = create_engine(db_uri)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO us_institutional_activity (
                    symbol, snapshot_date,
                    institution_report_date, mutualfund_report_date,
                    institution_holders_count, institution_total_shares, institution_total_value, institution_avg_pct_change,
                    mutualfund_holders_count, mutualfund_total_shares, mutualfund_total_value, mutualfund_avg_pct_change,
                    insider_buys_6m, insider_sells_6m, insider_net_shares_6m,
                    insider_total_transactions_6m, insider_total_shares_held,
                    source
                ) VALUES (
                    :symbol, :snapshot_date,
                    :institution_report_date, :mutualfund_report_date,
                    :institution_holders_count, :institution_total_shares, :institution_total_value, :institution_avg_pct_change,
                    :mutualfund_holders_count, :mutualfund_total_shares, :mutualfund_total_value, :mutualfund_avg_pct_change,
                    :insider_buys_6m, :insider_sells_6m, :insider_net_shares_6m,
                    :insider_total_transactions_6m, :insider_total_shares_held,
                    :source
                )
                ON DUPLICATE KEY UPDATE
                    institution_report_date = VALUES(institution_report_date),
                    mutualfund_report_date = VALUES(mutualfund_report_date),
                    institution_holders_count = VALUES(institution_holders_count),
                    institution_total_shares = VALUES(institution_total_shares),
                    institution_total_value = VALUES(institution_total_value),
                    institution_avg_pct_change = VALUES(institution_avg_pct_change),
                    mutualfund_holders_count = VALUES(mutualfund_holders_count),
                    mutualfund_total_shares = VALUES(mutualfund_total_shares),
                    mutualfund_total_value = VALUES(mutualfund_total_value),
                    mutualfund_avg_pct_change = VALUES(mutualfund_avg_pct_change),
                    insider_buys_6m = VALUES(insider_buys_6m),
                    insider_sells_6m = VALUES(insider_sells_6m),
                    insider_net_shares_6m = VALUES(insider_net_shares_6m),
                    insider_total_transactions_6m = VALUES(insider_total_transactions_6m),
                    insider_total_shares_held = VALUES(insider_total_shares_held),
                    updated_at = CURRENT_TIMESTAMP
            """), snapshot)
        return True
    finally:
        engine.dispose()


def fetch_and_store_institutional_activity(symbol: str, db_uri: str = DB_URI) -> dict[str, Any]:
    snapshot = build_institutional_activity_snapshot(symbol)
    if not snapshot:
        return {}
    save_institutional_activity(snapshot, db_uri=db_uri)
    return snapshot
