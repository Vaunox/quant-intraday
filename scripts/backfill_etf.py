#!/usr/bin/env python
r"""Operator-run: backfill the Phase-3T ETF baskets (daily) into the Parquet archive.

Thin shim (Ground Rule 3): the pinned universe lives in ``config/etf_universe.yaml`` and is
loaded by :mod:`quant.research.etf.universe`; this only resolves the symbol list and
delegates to the unit-tested backfill CLI with ``--interval day --tier parquet``. Run on the
static-IP engine host after the morning Kite session seed::

    uv run python scripts/backfill_etf.py --start 2016-01-01 --end 2026-06-30 \
        --request-token <today's request_token>

``--basket`` selects ``frozen`` | ``spec_literal`` | ``both`` (default ``both`` = the
de-duplicated union of the two baskets, so the shared legs are fetched once).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from quant.data.ingest.backfill_cli import main as backfill_main
from quant.research.etf.universe import basket_symbols, load_etf_universe


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator (network+creds)
    """Resolve the basket symbols and delegate to the backfill CLI (daily → Parquet)."""
    parser = argparse.ArgumentParser(
        prog="backfill_etf", description="Backfill the Phase-3T ETF baskets (daily)."
    )
    parser.add_argument("--start", required=True, help="inclusive start date YYYY-MM-DD (IST)")
    parser.add_argument("--end", required=True, help="inclusive end date YYYY-MM-DD (IST)")
    parser.add_argument("--basket", choices=("frozen", "spec_literal", "both"), default="both")
    parser.add_argument("--request-token", default=None, help="today's Kite request_token")
    parser.add_argument("--env", default=None, help="config environment (dev | paper | live)")
    args = parser.parse_args(argv)

    symbols = basket_symbols(load_etf_universe(), args.basket)
    delegate = [
        "--start",
        args.start,
        "--end",
        args.end,
        "--interval",
        "day",
        "--tier",
        "parquet",
        "--symbols",
        *symbols,
    ]
    if args.request_token:
        delegate += ["--request-token", args.request_token]
    if args.env:
        delegate += ["--env", args.env]
    return backfill_main(delegate)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
