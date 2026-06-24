#!/usr/bin/env python
r"""Runnable entry point for the P2A.3 post-backfill data-quality check.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.data.ingest.check_cli` (Ground Rule 3). Run it after a backfill, over the same
range, to read the data back and report its quality (P1.5 gaps + P1.9 dashboard), e.g.::

    uv run python scripts/check_backfill.py --start 2021-06-24 --end 2026-06-23

Read-only: no broker, no network. Exits non-zero only if a symbol has no data. See
``docs/operator_runbooks/P2A.3_backfill.md``.
"""

from quant.data.ingest.check_cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
