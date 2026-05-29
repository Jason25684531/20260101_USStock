import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"
sys.modules.setdefault("yfinance", SimpleNamespace())

import app as web_app_module


def test_build_backtest_diagnostics_reports_no_trade_and_flat_equity():
    equity_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]),
            "total_equity": [100000.0, 100000.0, 100000.0],
        }
    )

    diagnostics = web_app_module._build_backtest_diagnostics(
        start_date="2026-05-01",
        end_date="2026-05-03",
        equity_df=equity_df,
        trade_rows=[],
        requested_symbols=["AAPL", "MSFT"],
    )

    assert diagnostics["data_start"] == "2026-05-01"
    assert diagnostics["data_end"] == "2026-05-03"
    assert diagnostics["price_rows"] == 3
    assert diagnostics["trade_count"] == 0
    assert diagnostics["equity_flat_after"] == "2026-05-01"
    assert diagnostics["flat_reason"] == "no_trades"
    assert "no trades" in diagnostics["warnings"][0].lower()


def test_build_backtest_diagnostics_reports_missing_data_symbols():
    diagnostics = web_app_module._build_backtest_diagnostics(
        start_date="2026-05-01",
        end_date="2026-05-03",
        equity_df=pd.DataFrame(),
        trade_rows=[],
        requested_symbols=["AAPL", "MSFT"],
        symbols_with_data=["AAPL"],
    )

    assert diagnostics["symbols_missing_data"] == ["MSFT"]
    assert any("MSFT" in warning for warning in diagnostics["warnings"])


def test_backtest_status_payload_includes_diagnostics():
    web_app_module.app.config["TESTING"] = True
    web_app_module.WEB_DISABLE_AUTH = True
    client = web_app_module.app.test_client()

    response = client.get("/api/backtest/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert "diagnostics" in payload
    assert "trade_count" in payload["diagnostics"]


def test_backtest_template_has_diagnostics_panel_and_flat_copy():
    template = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")

    assert "backtestDiagnosticsPanel" in template
    assert "renderBacktestDiagnostics" in template
    assert "Equity flat after" in template
    assert "symbols_missing_data" in template
    assert "holding_days" in template
    assert "exit_reason" in template
