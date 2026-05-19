import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("yfinance", SimpleNamespace())

from screener.engine import DailyScreener


def test_daily_screener_auto_detects_ml_from_shared_model_resolver():
    with patch("screener.engine.find_existing_model_path", return_value=Path("/tmp/model.pkl"), create=True), \
         patch.object(DailyScreener, "_init_ml") as init_ml:
        screener = DailyScreener(symbols=["AAPL"], use_ml=None)

    assert screener.use_ml is True
    init_ml.assert_called_once_with()
