from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CORE_MODULE_PATH = Path(__file__).resolve().parent / "src" / "strategies" / "ml_strategy.py"
CORE_SPEC = importlib.util.spec_from_file_location("usstock_local_ml_strategy", CORE_MODULE_PATH)
if CORE_SPEC is None or CORE_SPEC.loader is None:
    raise ImportError(f"無法載入核心模組: {CORE_MODULE_PATH}")

CORE_MODULE = importlib.util.module_from_spec(CORE_SPEC)
CORE_SPEC.loader.exec_module(CORE_MODULE)
main = CORE_MODULE.main


if __name__ == "__main__":
    raise SystemExit(main())