"""Smoke tests for the scaffolding (P0.1).

These do not test business logic - there is none yet. They prove the package is
importable and the tooling (pytest, mypy, the editable install) is wired up, so
CI has a real, passing test to run. Real per-module tests arrive with each
subsequent subtask.
"""

import importlib

import quant


def test_package_imports() -> None:
    """The top-level package imports and exposes a non-empty version string."""
    assert isinstance(quant.__version__, str)
    assert quant.__version__


def test_layer_subpackages_importable() -> None:
    """Every layer subpackage imports cleanly (the folder structure is wired)."""
    for layer in ("core", "data", "research", "capital", "execution", "ops", "control"):
        module = importlib.import_module(f"quant.{layer}")
        assert module.__doc__, f"quant.{layer} is missing its module docstring"
