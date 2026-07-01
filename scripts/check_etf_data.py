#!/usr/bin/env python
r"""Operator-run: data-quality check on the backfilled ETF baskets (read-only).

Thin shim (Ground Rule 3): resolves the symbol list from ``config/etf_universe.yaml`` and
delegates to the unit-tested check CLI, which reads the Parquet archive and runs the P1.9
data-quality dashboard (coverage / gaps / bad-ticks) per symbol. Touches no broker and no
network. Run after ``scripts/backfill_etf.py``::

    uv run python scripts/check_etf_data.py --start 2016-01-01 --end 2026-06-30

Records the per-ETF history depth + any liquidity/continuity caveats for the P3T.2 doc; a
thin/young ETF here is a flag for the P3T.4 spread/impact charge, not an auto-fail.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from quant.data.ingest.check_cli import main as check_main
from quant.research.etf.universe import basket_symbols, load_etf_universe


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator entry (disk I/O)
    """Resolve the basket symbols and delegate to the read-only DQ check CLI."""
    parser = argparse.ArgumentParser(
        prog="check_etf_data", description="Data-quality check on the backfilled ETF baskets."
    )
    parser.add_argument("--start", required=True, help="inclusive start date YYYY-MM-DD (IST)")
    parser.add_argument("--end", required=True, help="inclusive end date YYYY-MM-DD (IST)")
    parser.add_argument("--basket", choices=("frozen", "spec_literal", "both"), default="both")
    parser.add_argument("--env", default=None, help="config environment (dev | paper | live)")
    args = parser.parse_args(argv)

    symbols = basket_symbols(load_etf_universe(), args.basket)
    delegate = [
        "--start",
        args.start,
        "--end",
        args.end,
        "--tier",
        "parquet",
        "--symbols",
        *symbols,
    ]
    if args.env:
        delegate += ["--env", args.env]
    return check_main(delegate)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
