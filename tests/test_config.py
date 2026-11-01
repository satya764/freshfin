from datetime import date

import pytest

from freshfin.config import ModelSpec, load_models


def test_load_models(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text(
        '[[model]]\nname = "a"\nlabel = "A"\nprovider = "anthropic"\nprice_in = 1.0\nprice_out = 5.0\n'
        "fresh_after = 2026-06-30\n"
        '[[model]]\nname = "b"\nlabel = "B"\nprovider = "openai_compatible"\nfresh_after = "2025-04-29"\n'
    )
    models = load_models(path)
    assert models["a"].fresh_after == date(2026, 6, 30)
    assert models["b"].fresh_after == date(2025, 4, 29)
    assert models["a"].cost(1_000_000, 100_000) == 1.5


def test_bad_provider(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text('[[model]]\nname = "x"\nlabel = "X"\nprovider = "magic"\n')
    with pytest.raises(ValueError):
        load_models(path)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_models(tmp_path / "nope.toml")


def test_example_file_loads():
    from pathlib import Path

    models = load_models(Path(__file__).parent.parent / "models.example.toml")
    assert set(models) == {"claude-haiku-5-5", "claude-sonnet-5-5", "qwen3-16k"}
    assert all(isinstance(m, ModelSpec) for m in models.values())
