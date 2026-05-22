from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_ingest_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_full_data.py"
    spec = importlib.util.spec_from_file_location("ingest_full_data_under_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_ingestion_symbols_prefers_active_registry_symbols(monkeypatch):
    ingest = _load_ingest_module()

    class FakeDB:
        engine = object()

    monkeypatch.delenv("SYMBOLS", raising=False)
    monkeypatch.setattr(
        ingest,
        "load_active_symbols",
        lambda engine, fallback_symbols=None, include_benchmarks=False: ["AAPL", "MSFT", "NVDA"],
    )

    symbols, source = ingest.resolve_ingestion_symbols(FakeDB(), fallback_symbols=["TSLA"])

    assert symbols == ["AAPL", "MSFT", "NVDA"]
    assert source == "registry"


def test_resolve_ingestion_symbols_reads_engine_from_ingestion_db_adapter(monkeypatch):
    ingest = _load_ingest_module()
    captured = {}

    class FakeIngestion:
        class DBAdapter:
            engine = object()

        db = DBAdapter()

    monkeypatch.delenv("SYMBOLS", raising=False)

    def fake_load_active_symbols(engine, fallback_symbols=None, include_benchmarks=False):
        captured["engine"] = engine
        return ["AAPL", "MSFT", "NVDA"]

    monkeypatch.setattr(ingest, "load_active_symbols", fake_load_active_symbols)

    symbols, source = ingest.resolve_ingestion_symbols(FakeIngestion(), fallback_symbols=["TSLA"])

    assert captured["engine"] is FakeIngestion.db.engine
    assert symbols == ["AAPL", "MSFT", "NVDA"]
    assert source == "registry"


def test_resolve_ingestion_symbols_uses_override_and_fallback(monkeypatch):
    ingest = _load_ingest_module()

    class FakeDB:
        engine = object()

    monkeypatch.setenv("SYMBOLS", " nvda, aapl, NVDA ")
    symbols, source = ingest.resolve_ingestion_symbols(FakeDB(), fallback_symbols=["TSLA"])

    assert symbols == ["NVDA", "AAPL"]
    assert source == "override"

    monkeypatch.delenv("SYMBOLS", raising=False)

    def fail_registry(*args, **kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(ingest, "load_active_symbols", fail_registry)

    symbols, source = ingest.resolve_ingestion_symbols(FakeDB(), fallback_symbols=["TSLA", "MSFT"])

    assert symbols == ["TSLA", "MSFT"]
    assert source == "fallback"


def test_fetch_yahoo_prices_in_batches_sleeps_between_non_final_batches(monkeypatch):
    ingest = _load_ingest_module()
    ingestion = object.__new__(ingest.DataIngestion)
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_fetch(symbols, start_date=None, end_date=None, delay=0.5):
        calls.append(list(symbols))
        return {symbol: f"rows-{symbol}" for symbol in symbols}

    monkeypatch.setattr(ingestion, "fetch_yahoo_prices", fake_fetch)
    monkeypatch.setattr(ingest.random, "uniform", lambda low, high: 33.0)
    monkeypatch.setattr(ingest.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = ingest.fetch_yahoo_prices_in_batches(
        ingestion,
        [f"S{i:02d}" for i in range(45)],
        batch_size=20,
        min_batch_sleep=20,
        max_batch_sleep=40,
    )

    assert calls == [
        [f"S{i:02d}" for i in range(20)],
        [f"S{i:02d}" for i in range(20, 40)],
        [f"S{i:02d}" for i in range(40, 45)],
    ]
    assert sleeps == [33.0, 33.0]
    assert len(result) == 45
