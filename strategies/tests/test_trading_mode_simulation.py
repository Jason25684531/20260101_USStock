import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.modules.setdefault("yfinance", SimpleNamespace())

import main as main_module
import screener.engine as screener_engine_module


class _FakeNotifier:
    def __init__(self, enabled=False):
        self.is_enabled = enabled
        self.error_alerts = []
        self.flex_reports = []

    def send_error_alert(self, *_args, **_kwargs):
        self.error_alerts.append((_args, _kwargs))
        return None

    def send_daily_summary(self, *_args, **_kwargs):
        return None

    def send_flex_report(self, recommendations):
        self.flex_reports.append(recommendations)
        return None


class _FakeBroker:
    def get_account(self):
        return {"cash": 100000.0, "buying_power": 100000.0, "equity": 100000.0}

    def get_positions(self):
        return {}


class _FakeTrades:
    def count(self):
        return 1

    @property
    def records_readable(self):
        return pd.DataFrame([{"Exit Timestamp": None}])


class _FakePortfolio:
    trades = _FakeTrades()


class _FakeDB:
    def get_market_data(self, _symbol):
        return pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-05-19"]))

    def save_backtest_run(self, *_args, **_kwargs):
        return 1

    def close(self):
        return None


class _FakeScreener:
    def __init__(self, *args, **kwargs):
        self.closed = False
        self.last_run_summary = {
            "coverage_ratio": 1.0,
            "minimum_coverage_ratio": 0.6,
            "recommendations_written": True,
            "failed_symbols": [],
            "fallback_successes": 0,
            "live_successes": 1,
            "total_symbols": 1,
        }

    def scan_all(self):
        return pd.DataFrame([{"symbol": "AAPL"}])

    def get_top_recommendations(self, _df_scan):
        return [{"symbol": "AAPL", "signal": "BUY", "current_price": 100.0, "total_score": 4.5}]

    def save_to_db(self, _recommendations):
        return True

    def close(self):
        self.closed = True


class _DegradedScreener(_FakeScreener):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_run_summary = {
            "coverage_ratio": 0.2,
            "minimum_coverage_ratio": 0.6,
            "recommendations_written": False,
            "failed_symbols": [{"symbol": "QQQ", "status": "timeout"}],
            "fallback_successes": 1,
            "live_successes": 0,
            "total_symbols": 5,
            "provider_health_summary": "provider health summary",
        }

    def save_to_db(self, _recommendations):
        return False


def test_job_uses_mock_broker_in_simulation_mode_without_alpaca_calls():
    fake_broker = _FakeBroker()

    with patch.object(main_module, "TRADING_MODE", "simulation"), \
         patch.object(main_module, "STRATEGY_TYPE", "traditional"), \
         patch.object(main_module, "MockBroker", return_value=fake_broker) as mock_broker_cls, \
         patch.object(main_module, "AlpacaBroker", side_effect=AssertionError("alpaca should not initialize")) as alpaca_cls, \
         patch.object(main_module, "download_and_save", return_value={"success": [], "failed": []}), \
         patch.object(main_module, "get_notifier", return_value=_FakeNotifier()):
        main_module.job()

    mock_broker_cls.assert_called_once_with()
    alpaca_cls.assert_not_called()


def test_job_executes_trades_in_simulation_mode_with_simulation_label():
    fake_broker = _FakeBroker()
    fake_db = _FakeDB()

    with patch.object(main_module, "TRADING_MODE", "simulation"), \
         patch.object(main_module, "STRATEGY_TYPE", "traditional"), \
         patch.object(main_module, "MockBroker", return_value=fake_broker), \
         patch.object(main_module, "download_and_save", return_value={"success": ["AAPL"], "failed": []}), \
         patch.object(main_module, "DatabaseAdapter", return_value=fake_db), \
         patch.object(main_module, "run_momentum_strategy", return_value=_FakePortfolio()), \
         patch.object(main_module, "get_notifier", return_value=_FakeNotifier()), \
         patch.object(main_module, "execute_trades", return_value=[]) as execute_trades_mock:
        main_module.job()

    execute_trades_mock.assert_called_once()
    args, kwargs = execute_trades_mock.call_args
    assert args[0] is fake_broker
    assert args[1] == {"AAPL": 10}
    assert kwargs["strategy_label"] == "Simulation Trading"


def test_job_screener_mode_bypasses_generic_market_data_download():
    fake_db = _FakeDB()

    with patch.object(main_module, "TRADING_MODE", "backtest"), \
         patch.object(main_module, "STRATEGY_TYPE", "screener"), \
         patch.object(main_module, "DatabaseAdapter", return_value=fake_db), \
         patch.object(main_module, "download_and_save", side_effect=AssertionError("download_and_save should not run")), \
         patch.object(main_module, "get_notifier", return_value=_FakeNotifier()), \
         patch.object(screener_engine_module, "DailyScreener", _FakeScreener):
        main_module.job()


def test_job_screener_mode_emits_degraded_data_alert_when_write_is_skipped():
    fake_db = _FakeDB()
    notifier = _FakeNotifier(enabled=True)

    with patch.object(main_module, "TRADING_MODE", "backtest"), \
         patch.object(main_module, "STRATEGY_TYPE", "screener"), \
         patch.object(main_module, "DatabaseAdapter", return_value=fake_db), \
         patch.object(main_module, "download_and_save", side_effect=AssertionError("download_and_save should not run")), \
         patch.object(main_module, "get_notifier", return_value=notifier), \
         patch.object(screener_engine_module, "DailyScreener", _DegradedScreener):
        main_module.job()

    assert notifier.error_alerts
    assert not notifier.flex_reports
