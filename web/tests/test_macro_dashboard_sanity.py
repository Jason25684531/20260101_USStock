import os
import sys
import unittest
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


class MacroDashboardSanityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_app_module.app.config["TESTING"] = True
        web_app_module.WEB_DISABLE_AUTH = True

    def setUp(self):
        self.client = web_app_module.app.test_client()

    def _sector_engine(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(scalar=Mock(return_value="2026-05-28")),
            [
                ("Technology", "XLK", 17.776, -13.228, 35.25, 1),
                ("Healthcare", "XLV", 0.052, -0.031, 0.118, 2),
            ],
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn
        return fake_engine

    def test_sector_momentum_outliers_render_as_none_with_warning(self):
        with patch.object(web_app_module, "engine", self._sector_engine()), \
             patch.object(web_app_module, "_table_exists", return_value=True), \
             patch.object(web_app_module, "_column_exists", return_value=True):
            response = self.client.get("/api/sectors")

        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(payload["sectors"][0]["return_20d"])
        self.assertIsNone(payload["sectors"][0]["return_63d"])
        self.assertIsNone(payload["sectors"][0]["return_252d"])
        self.assertEqual(payload["sectors"][1]["return_20d"], 0.052)
        self.assertTrue(payload["has_unavailable_momentum"])
        self.assertIn("diagnostics", payload)
        self.assertEqual(payload["diagnostics"][0]["invalid_reason"], "outlier_return")

    def test_macro_diagnostics_endpoint_exposes_sector_invalid_reasons(self):
        with patch.object(web_app_module, "engine", self._sector_engine()), \
             patch.object(web_app_module, "_table_exists", return_value=True), \
             patch.object(web_app_module, "_column_exists", return_value=True):
            response = self.client.get("/api/macro/diagnostics")

        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["sector_momentum"][0]["symbol"], "XLK")
        self.assertEqual(payload["sector_momentum"][0]["outlier_reason"], "abs_return_gt_3.0")

    def test_dashboard_template_has_na_rendering_for_macro_momentum(self):
        template_text = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn("pctOrNA", template_text)
        self.assertIn("macroUnavailableWarning", template_text)


if __name__ == "__main__":
    unittest.main()
