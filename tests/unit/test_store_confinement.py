"""Structural guarantee: the optional storage SDKs are imported only in data/store/.

Ground Rule 1 / Deep Dive #1 §1.2 ("storage is behind a repository interface"): nothing
outside ``data/store/`` may import the ``arcticdb`` or ``redis`` client. This scans the
whole ``quant`` tree so the rule is enforced in CI, not just by review.

Import detection is AST-based (not a substring scan): it inspects ``import`` statements
only, so a non-import mention — e.g. the ``redis_url`` config field — is correctly
ignored.
"""

import ast
from pathlib import Path

import quant

#: The only package allowed to import the optional storage clients.
_ALLOWED_PACKAGE = ("data", "store")
#: Top-level modules whose import must stay confined.
_GUARDED_MODULES = frozenset({"arcticdb", "redis"})


def _imported_top_level_modules(tree: ast.Module) -> set[str]:
    """Return the set of top-level module names imported anywhere in ``tree``."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_optional_store_clients_referenced_only_within_store_package() -> None:
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
    assert offenders == [], f"optional storage clients imported outside data/store/: {offenders}"
