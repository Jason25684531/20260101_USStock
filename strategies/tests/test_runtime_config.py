from pathlib import Path

from utils.runtime_config import (
    DEFAULT_MODEL_PATH,
    find_existing_model_path,
    get_model_load_candidates,
    resolve_model_path,
)


def test_resolve_model_path_prefers_explicit_path():
    explicit = "custom/model.pkl"

    assert resolve_model_path(explicit_path=explicit) == Path(explicit)


def test_resolve_model_path_uses_env_then_container_default():
    assert resolve_model_path(env={"MODEL_PATH": "/tmp/model.pkl"}) == Path("/tmp/model.pkl")
    assert resolve_model_path(env={}) == DEFAULT_MODEL_PATH


def test_get_model_load_candidates_adds_only_explicit_test_fallback():
    candidates = get_model_load_candidates(
        env={"MODEL_PATH": "/app/data/model.pkl", "TEST_MODEL_PATH": "/tmp/test_model.pkl"}
    )

    assert candidates == [Path("/app/data/model.pkl"), Path("/tmp/test_model.pkl")]


def test_find_existing_model_path_returns_first_existing_candidate(tmp_path):
    primary = tmp_path / "model.pkl"
    fallback = tmp_path / "test_model.pkl"
    fallback.write_bytes(b"stub")

    assert find_existing_model_path(
        env={"MODEL_PATH": str(primary), "TEST_MODEL_PATH": str(fallback)}
    ) == fallback
