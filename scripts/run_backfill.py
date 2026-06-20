#!/usr/bin/env python
r"""Runnable entry point for the historical market-data backfill (P1.4).

A thin shim: all orchestration lives in the importable, unit-tested
:mod:`quant.data.ingest.backfill_cli` (Ground Rule 3 — production logic in
``src/quant``, scripts stay thin). Run it on the static-IP engine host after the
morning Kite session seed, e.g.::

    python scripts/run_backfill.py --start 2024-01-01 --end 2024-12-31 \
        --request-token <today's request_token>

See ``backfill_cli`` for the full argument list; the run is resumable.
"""

from quant.data.ingest.backfill_cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
