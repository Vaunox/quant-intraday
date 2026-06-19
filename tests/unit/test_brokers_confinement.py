"""Structural guarantee: the kiteconnect SDK is referenced only in data/brokers/.

Ground Rule 1 / Deep Dive #1 §0.3 and the P1.1 acceptance criterion ("no SDK import
outside this package"). This scans the whole ``quant`` source tree so the rule is
enforced in CI, not just by review — a stray ``import kiteconnect`` anywhere else
fails the build.
"""

from pathlib import Path

import quant

_ALLOWED_PACKAGE = ("data", "brokers")


def test_kiteconnect_referenced_only_within_brokers_package() -> None:
    root = Path(quant.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts[:2] == _ALLOWED_PACKAGE:
            continue
        if "kiteconnect" in path.read_text(encoding="utf-8"):
            offenders.append(str(relative))
    assert offenders == [], f"kiteconnect referenced outside data/brokers/: {offenders}"
