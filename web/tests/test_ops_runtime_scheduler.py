import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"
sys.modules.setdefault("yfinance", SimpleNamespace())

import app as web_app_module
from screener.ops_runtime import build_pull_log_record, ensure_market_data_pull_log, record_market_data_pull


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Mock(mappings=Mock(return_value=Mock(first=Mock(return_value=None))))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self):
        self.conn = FakeConnection()

    def connect(self):
        return self.conn

    def begin(self):
        return self.conn


def test_runtime_endpoint_returns_safe_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "docker")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "secret-token")
    fake_engine = FakeEngine()
    web_app_module.app.config["TESTING"] = True
    web_app_module.WEB_DISABLE_AUTH = True
    client = web_app_module.app.test_client()

    with patch.object(web_app_module, "engine", fake_engine):
        response = client.get("/api/ops/runtime")

    payload = response.get_json()
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert payload["app_env"] == "docker"
    assert payload["service_name"] == "web"
    assert payload["db_connected"] is True
    assert payload["linebot_enabled"] is True
    assert "secret-token" not in text


def test_runtime_endpoint_degrades_when_db_unavailable():
    failing_engine = Mock()
    failing_engine.connect.side_effect = RuntimeError("db down")
    web_app_module.app.config["TESTING"] = True
    web_app_module.WEB_DISABLE_AUTH = True
    client = web_app_module.app.test_client()

    with patch.object(web_app_module, "engine", failing_engine):
        response = client.get("/api/ops/runtime")

    payload = response.get_json()

    assert response.status_code == 200
    assert payload["db_connected"] is False


def test_scheduler_endpoint_reports_no_scheduler_without_log(monkeypatch):
    monkeypatch.delenv("USE_SCHEDULER", raising=False)
    fake_engine = FakeEngine()
    web_app_module.app.config["TESTING"] = True
    web_app_module.WEB_DISABLE_AUTH = True
    client = web_app_module.app.test_client()

    with patch.object(web_app_module, "engine", fake_engine):
        response = client.get("/api/ops/scheduler")

    payload = response.get_json()

    assert response.status_code == 200
    assert payload["scheduler_enabled"] is False
    assert payload["message"] == "No scheduler service detected"


def test_pull_log_helpers_record_safe_payload():
    fake_engine = FakeEngine()
    record = build_pull_log_record(
        job_name="manual_pull",
        status="failed",
        error_type="json_parse_error",
        error_message="token=SECRET should be hidden",
        symbols_requested=3,
    )

    assert "SECRET" not in record["error_message"]
    assert record_market_data_pull(fake_engine, record) is True
    assert any("market_data_pull_log" in call[0] for call in fake_engine.conn.calls)
    ensure_market_data_pull_log(fake_engine.conn)
