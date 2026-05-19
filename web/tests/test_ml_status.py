import os
import pickle
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"

flask_httpauth = ModuleType("flask_httpauth")


class _DummyHTTPBasicAuth:
    def login_required(self, func):
        return func

    def verify_password(self, func):
        return func


flask_httpauth.HTTPBasicAuth = _DummyHTTPBasicAuth
sys.modules.setdefault("flask_httpauth", flask_httpauth)

db_module = ModuleType("db")
db_module.get_db_config = lambda: {
    "host": "db",
    "port": "3306",
    "user": "trader",
    "password": "secret",
    "name": "usstock",
}
db_module.get_engine = lambda *_args, **_kwargs: Mock()
db_module.table_exists = lambda *_args, **_kwargs: False
db_module.column_exists = lambda *_args, **_kwargs: False
sys.modules.setdefault("db", db_module)

import app as web_app_module


class MlStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_app_module.app.config["TESTING"] = True
        web_app_module.WEB_DISABLE_AUTH = True

    def setUp(self):
        self.client = web_app_module.app.test_client()

    def test_ml_status_uses_shared_model_path_resolver(self):
        with TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "model.pkl"
            feature_importance = pd.DataFrame(
                [{"feature": "revenue_growth_yoy", "importance": 0.42}]
            )
            with open(model_path, "wb") as handle:
                pickle.dump({"feature_importance": feature_importance}, handle)

            fake_connection = object()
            fake_engine = Mock()
            fake_context = Mock()
            fake_context.__enter__ = Mock(return_value=fake_connection)
            fake_context.__exit__ = Mock(return_value=False)
            fake_engine.connect.return_value = fake_context

            with patch.object(web_app_module, "find_existing_model_path", return_value=model_path, create=True) as resolver_mock, \
                 patch.object(web_app_module, "engine", fake_engine), \
                 patch.object(web_app_module, "_table_exists", return_value=False):
                response = self.client.get("/api/ml_status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        resolver_mock.assert_called_once_with()
        self.assertTrue(payload["model_loaded"])
        self.assertEqual(payload["feature_importance"][0]["feature"], "revenue_growth_yoy")


if __name__ == "__main__":
    unittest.main()
