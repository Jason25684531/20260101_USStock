import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


class _FakeMappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)


class _FakeConnection:
    def __init__(self, row):
        self.row = row
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return _FakeResult(self.row)


def test_db_optional_column_helpers_resolve_existing_columns(monkeypatch):
    import db as web_db

    existing = {("daily_recommendations", "target_price")}
    monkeypatch.setattr(web_db, "column_exists", lambda _conn, table, column: (table, column) in existing)

    assert web_db.resolve_existing_column(None, "daily_recommendations", ["buy_price", "target_price"]) == "target_price"
    assert web_db.optional_column_expr(None, "daily_recommendations", ["buy_price", "target_price"], "price") == "target_price AS price"
    assert web_db.select_optional_column(None, "daily_recommendations", ["missing"], "price", default_sql="0") == "0 AS price"


def test_presentation_helpers_keep_dashboard_and_linebot_formatting_stable():
    from serializers.presentation import (
        derive_flow_value,
        format_compact_number,
        format_money_compact,
        format_signed_number,
        format_trade_date,
        json_loads_safe,
    )

    assert json_loads_safe('{"a": 1}') == {"a": 1}
    assert json_loads_safe("not-json", default={}) == {}
    assert format_trade_date(datetime(2026, 6, 2, 12, 0)) == "2026-06-02"
    assert format_signed_number(1250) == "+1,250"
    assert format_compact_number(2_500_000, suffix=" shares") == "2.50M shares"
    assert format_money_compact(1500) == "$1.50K"
    assert derive_flow_value({"buy": 12, "sell": 5}, None, "buy", "sell") == 7.0


def test_institutional_flow_repository_uses_shared_candidate_resolution(monkeypatch):
    import repositories.institutional_flow as flow_repo

    row = {
        "trade_date": "2026-06-01",
        "foreign_buy": 100,
        "foreign_sell": 25,
        "trust_net": -12,
        "dealer_net": 0,
    }
    conn = _FakeConnection(row)
    existing_columns = {
        ("institutional_trading_daily", "symbol"),
        ("institutional_trading_daily", "trade_date"),
        ("institutional_trading_daily", "foreign_buy"),
        ("institutional_trading_daily", "foreign_sell"),
        ("institutional_trading_daily", "trust_net"),
        ("institutional_trading_daily", "dealer_net"),
    }

    monkeypatch.setattr(flow_repo, "table_exists", lambda _conn, table: table == "institutional_trading_daily")
    monkeypatch.setattr(flow_repo, "column_exists", lambda _conn, table, column: (table, column) in existing_columns)
    monkeypatch.setattr(flow_repo, "load_us_institutional_activity_snapshot", lambda _conn, _symbol: None)

    snapshot = flow_repo.load_actual_institutional_flow_snapshot(conn, "AAPL")

    assert snapshot["trade_date"] == "2026-06-01"
    assert snapshot["source"] == "actual"
    assert snapshot["is_fallback"] is False
    assert [item["value"] for item in snapshot["rows"]] == ["+75", "-12", "0"]
    assert "institutional_trading_daily" in conn.statements[0][0]
    assert conn.statements[0][1] == {"sym": "AAPL"}
