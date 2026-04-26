"""Compatibility shim for shared LINE Flex helpers."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT_STR = str(_PROJECT_ROOT)
if _PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT_STR)

from strategies.src.utils.line_flex import *  # type: ignore[reportMissingImports]
