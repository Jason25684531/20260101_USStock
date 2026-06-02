from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SHARED_RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[3] / "utils" / "runtime_config.py"
_SHARED_RUNTIME_CONFIG_SPEC = spec_from_file_location(
    "_shared_utils_runtime_config",
    _SHARED_RUNTIME_CONFIG_PATH,
)
_SHARED_RUNTIME_CONFIG_MODULE = module_from_spec(_SHARED_RUNTIME_CONFIG_SPEC)
assert _SHARED_RUNTIME_CONFIG_SPEC is not None and _SHARED_RUNTIME_CONFIG_SPEC.loader is not None
_SHARED_RUNTIME_CONFIG_SPEC.loader.exec_module(_SHARED_RUNTIME_CONFIG_MODULE)

DEFAULT_MODEL_PATH = _SHARED_RUNTIME_CONFIG_MODULE.DEFAULT_MODEL_PATH
find_existing_model_path = _SHARED_RUNTIME_CONFIG_MODULE.find_existing_model_path
get_model_load_candidates = _SHARED_RUNTIME_CONFIG_MODULE.get_model_load_candidates
resolve_model_path = _SHARED_RUNTIME_CONFIG_MODULE.resolve_model_path
resolve_test_model_path = _SHARED_RUNTIME_CONFIG_MODULE.resolve_test_model_path

__all__ = [
    "DEFAULT_MODEL_PATH",
    "find_existing_model_path",
    "get_model_load_candidates",
    "resolve_model_path",
    "resolve_test_model_path",
]
