#!/usr/bin/env python
"""P3X.1d — build the survivorship-free daily panel from the NSE bhavcopy archive.

Walks the trading calendar over ``[start, end]``, downloads + parses each daily bhavcopy (P3X.1b),
and writes one Parquet **shard per day** (so a multi-thousand-file crawl is resumable — a re-run
skips days already on disk). Then assembles the shards into wide ``date x symbol`` close / value /
volume panels for the factor pipeline.

Renames are collapsed by **ISIN**: every row's symbol is remapped to the latest symbol seen for its
ISIN, so a company that changed ticker stays one continuous column (survivorship-correct). Output
lands under ``data/nifty_panel/`` (git-ignored — it is large, reproducible data, not source).

Usage::

    python scripts/build_nifty500_panel.py                       # 2016-2024, download + assemble
    python scripts/build_nifty500_panel.py --start 2019-01-01
    python scripts/build_nifty500_panel.py --assemble-only       # re-pivot existing shards
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# ruff: noqa: E402  (quant.* imports follow the sys.path bootstrap above — research entry point)
from quant.data.ingest.bhavcopy import HttpBhavcopyFetcher, parse_bhavcopy


def trading_weekdays(start: date, end: date) -> Iterator[date]:
    """Yield Mon-Fri dates in ``[start, end]`` (NSE holidays self-skip: the fetch 404s → None)."""
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            yield cursor
        cursor += timedelta(days=1)


def download_shards(
    start: date, end: date, daily_dir: Path, fetcher: HttpBhavcopyFetcher, *, delay: float
) -> None:
    """Download one Parquet shard per trading day into ``daily_dir`` (resumable)."""
    daily_dir.mkdir(parents=True, exist_ok=True)
    fetched = skipped = no_file = 0
    for day in trading_weekdays(start, end):
        shard = daily_dir / f"{day:%Y-%m-%d}.parquet"
        if shard.exists():
            skipped += 1
            continue
        raw = fetcher.fetch(day)
        if raw is None:
            no_file += 1
            continue
        parse_bhavcopy(raw, day).to_parquet(shard, index=False)
        fetched += 1
        if fetched % 50 == 0:
            print(f"  ...{fetched} days fetched (through {day})", flush=True)
        time.sleep(delay)
    print(f"download: {fetched} fetched, {skipped} already present, {no_file} no-file (holidays)")


def assemble(daily_dir: Path, out_dir: Path) -> None:
    """Concatenate day shards and pivot to wide close / value / volume panels (ISIN-collapsed)."""
    shards = sorted(daily_dir.glob("*.parquet"))
    if not shards:
        raise SystemExit(f"no shards in {daily_dir}; run the download first")
    long = pd.concat((pd.read_parquet(shard) for shard in shards), ignore_index=True)

    # Collapse ticker renames: map each ISIN to its most-recent symbol, then key columns on that.
    latest_symbol = long.sort_values("timestamp").groupby("isin")["symbol"].last()
    canonical = long["isin"].map(latest_symbol)
    long["csymbol"] = canonical.where(canonical.notna(), long["symbol"])

    for field in ("close", "value", "volume"):
        panel = long.pivot_table(index="timestamp", columns="csymbol", values=field, aggfunc="last")
        panel = panel.sort_index()
        panel.to_parquet(out_dir / f"{field}.parquet")
        print(f"  {field}: {panel.shape[0]} dates x {panel.shape[1]} names")
    print(f"assembled panels -> {out_dir}")


def main() -> int:
    """Download (unless --assemble-only) then assemble the survivorship-free daily panel."""
    parser = argparse.ArgumentParser(description="Build the NSE bhavcopy daily panel (P3X.1d).")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--out-dir", default=str(_REPO_ROOT / "data" / "nifty_panel"))
    parser.add_argument("--delay", type=float, default=0.3, help="polite inter-request delay (s)")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    daily_dir = out_dir / "daily"
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if not args.assemble_only:
        print(f"building bhavcopy panel {start} -> {end} into {out_dir}")
        download_shards(start, end, daily_dir, HttpBhavcopyFetcher(), delay=args.delay)
    assemble(daily_dir, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
