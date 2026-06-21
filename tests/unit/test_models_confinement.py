"""Structural guarantee: LightGBM and MLflow are imported only within research/models/.

Ground Rule 1 (the same confinement discipline as the broker SDK in P1.1 and the optional
storage clients in P1.3): the gradient-boosting library and the optional experiment-tracking
backend stay behind the model package's own interfaces, so the rest of the system depends on
neither. AST-based (inspects ``import`` statements only), enforced in CI.
"""

import ast
from pathlib import Path

import quant

#: The only package allowed to import LightGBM / MLflow.
_ALLOWED_PACKAGE = ("research", "models")
#: Top-level modules whose import must stay confined.
_GUARDED_MODULES = frozenset({"lightgbm", "mlflow"})


def _imported_top_level_modules(tree: ast.Module) -> set[str]:
    """Return the set of top-level module names imported anywhere in ``tree``."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_model_libraries_referenced_only_within_models_package() -> None:
    root = Path(quant.__file__).parent
    offenders: list[tuple[str, list[str]]] = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts[:2] == _ALLOWED_PACKAGE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        leaked = _GUARDED_MODULES & _imported_top_level_modules(tree)
        if leaked:
            offenders.append((str(relative), sorted(leaked)))
    assert offenders == [], f"model libraries imported outside research/models/: {offenders}"
