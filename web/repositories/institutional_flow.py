"""Institutional flow read helpers shared by Dashboard and LineBot."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db import column_exists, table_exists
from serializers.presentation import (
    derive_flow_value,
    format_compact_number,
    format_money_compact,
    format_signed_number,
    format_trade_date,
)


INSTITUTIONAL_FLOW_TABLE_CANDIDATES = (
    {
        "table": "institutional_trading_daily",
        "date": ["date", "trade_date", "data_date"],
        "foreign_net": ["foreign_net", "foreign_net_shares", "foreign_net_volume"],
        "foreign_buy": ["foreign_buy", "foreign_buy_shares"],
        "foreign_sell": ["foreign_sell", "foreign_sell_shares"],
        "trust_net": ["investment_trust_net", "trust_net", "institutional_trust_net"],
        "trust_buy": ["investment_trust_buy", "trust_buy"],
        "trust_sell": ["investment_trust_sell", "trust_sell"],
        "dealer_net": ["dealer_net", "self_dealer_net", "proprietary_trader_net"],
        "dealer_buy": ["dealer_buy", "self_dealer_buy"],
        "dealer_sell": ["dealer_sell", "self_dealer_sell"],
    },
    {
        "table": "institutional_flows",
        "date": ["date", "trade_date", "data_date"],
        "foreign_net": ["foreign_net"],
        "foreign_buy": ["foreign_buy"],
        "foreign_sell": ["foreign_sell"],
        "trust_net": ["trust_net", "investment_trust_net"],
        "trust_buy": ["trust_buy", "investment_trust_buy"],
        "trust_sell": ["trust_sell", "investment_trust_sell"],
        "dealer_net": ["dealer_net"],
        "dealer_buy": ["dealer_buy"],
        "dealer_sell": ["dealer_sell"],
    },
)


def resolve_existing_column(conn, table_name: str, column_candidates) -> str | None:
    for column_name in column_candidates:
        if column_exists(conn, table_name, column_name):
            return column_name
    return None


def _row_value(row: Any, key: str):
    return row.get(key) if hasattr(row, "get") else row[key]


def load_us_institutional_activity_snapshot(conn, symbol: str) -> dict | None:
    if not table_exists(conn, "us_institutional_activity"):
        return None

    row = conn.execute(text("""
        SELECT snapshot_date,
               institution_report_date,
               mutualfund_report_date,
               institution_total_shares,
               institution_total_value,
               mutualfund_total_shares,
               mutualfund_total_value,
               insider_buys_6m,
               insider_sells_6m,
               insider_net_shares_6m
        FROM us_institutional_activity
        WHERE symbol = :sym
        ORDER BY snapshot_date DESC, updated_at DESC, id DESC
        LIMIT 1
    """), {"sym": symbol}).mappings().first()

    if not row:
        return None

    institution_parts = []
    institution_shares = format_compact_number(_row_value(row, "institution_total_shares"), " shares")
    institution_value = format_money_compact(_row_value(row, "institution_total_value"))
    if institution_shares:
        institution_parts.append(institution_shares)
    if institution_value:
        institution_parts.append(institution_value)

    mutualfund_parts = []
    mutualfund_shares = format_compact_number(_row_value(row, "mutualfund_total_shares"), " shares")
    mutualfund_value = format_money_compact(_row_value(row, "mutualfund_total_value"))
    if mutualfund_shares:
        mutualfund_parts.append(mutualfund_shares)
    if mutualfund_value:
        mutualfund_parts.append(mutualfund_value)

    insider_parts = []
    insider_net = format_signed_number(_row_value(row, "insider_net_shares_6m"))
    insider_buys = format_compact_number(_row_value(row, "insider_buys_6m"), " shares")
    insider_sells = format_compact_number(_row_value(row, "insider_sells_6m"), " shares")
    if insider_net and insider_net != "N/A":
        insider_parts.append(f"{insider_net} shares")
    if insider_buys or insider_sells:
        insider_parts.append(f"buy {insider_buys or 'N/A'} / sell {insider_sells or 'N/A'}")

    rows = [
        {"label": "Institutions", "value": " / ".join(institution_parts) or "N/A"},
        {"label": "Mutual funds", "value": " / ".join(mutualfund_parts) or "N/A"},
        {"label": "Insiders 6M", "value": " | ".join(insider_parts) or "N/A"},
    ]
    if all(item["value"] == "N/A" for item in rows):
        return None

    snapshot_date = format_trade_date(_row_value(row, "snapshot_date"))
    summary = " / ".join(f"{item['label']} {item['value']}" for item in rows if item["value"] != "N/A")
    return {
        "trade_date": snapshot_date,
        "date_label": "Snapshot date",
        "headline_label": "Institutional / insider holdings",
        "rows": rows,
        "source": "us_holder_activity",
        "summary": f"{snapshot_date} holder activity: {summary}" if snapshot_date else f"holder activity: {summary}",
        "note": "Data source: Yahoo Finance institutional_holders / mutualfund_holders / insider_purchases",
        "is_fallback": False,
    }


def load_actual_institutional_flow_snapshot(conn, symbol: str) -> dict | None:
    us_snapshot = load_us_institutional_activity_snapshot(conn, symbol)
    if us_snapshot:
        return us_snapshot

    for candidate in INSTITUTIONAL_FLOW_TABLE_CANDIDATES:
        table_name = candidate["table"]
        if not table_exists(conn, table_name):
            continue
        if not column_exists(conn, table_name, "symbol"):
            continue

        date_column = resolve_existing_column(conn, table_name, candidate["date"])
        if not date_column:
            continue

        resolved_columns = {
            "foreign_net": resolve_existing_column(conn, table_name, candidate["foreign_net"]),
            "foreign_buy": resolve_existing_column(conn, table_name, candidate["foreign_buy"]),
            "foreign_sell": resolve_existing_column(conn, table_name, candidate["foreign_sell"]),
            "trust_net": resolve_existing_column(conn, table_name, candidate["trust_net"]),
            "trust_buy": resolve_existing_column(conn, table_name, candidate["trust_buy"]),
            "trust_sell": resolve_existing_column(conn, table_name, candidate["trust_sell"]),
            "dealer_net": resolve_existing_column(conn, table_name, candidate["dealer_net"]),
            "dealer_buy": resolve_existing_column(conn, table_name, candidate["dealer_buy"]),
            "dealer_sell": resolve_existing_column(conn, table_name, candidate["dealer_sell"]),
        }

        if not any(resolved_columns.values()):
            continue

        select_columns = [f"{date_column} AS trade_date"]
        for alias, column_name in resolved_columns.items():
            if column_name:
                select_columns.append(f"{column_name} AS {alias}")

        row = conn.execute(text(f"""
            SELECT {', '.join(select_columns)}
            FROM {table_name}
            WHERE symbol = :sym
            ORDER BY {date_column} DESC
            LIMIT 1
        """), {"sym": symbol}).mappings().first()

        if not row:
            continue

        foreign_value = derive_flow_value(row, "foreign_net", "foreign_buy", "foreign_sell")
        trust_value = derive_flow_value(row, "trust_net", "trust_buy", "trust_sell")
        dealer_value = derive_flow_value(row, "dealer_net", "dealer_buy", "dealer_sell")

        if all(value is None for value in (foreign_value, trust_value, dealer_value)):
            continue

        trade_date = format_trade_date(_row_value(row, "trade_date"))
        rows = [
            {"label": "Foreign", "value": format_signed_number(foreign_value)},
            {"label": "Trust", "value": format_signed_number(trust_value)},
            {"label": "Dealer", "value": format_signed_number(dealer_value)},
        ]
        joined_values = " / ".join(f"{item['label']} {item['value']}" for item in rows)

        return {
            "trade_date": trade_date,
            "rows": rows,
            "source": "actual",
            "summary": f"{trade_date} institutional flow: {joined_values}" if trade_date else f"institutional flow: {joined_values}",
            "note": f"Data source: {table_name} latest net flow",
            "is_fallback": False,
        }

    return None
