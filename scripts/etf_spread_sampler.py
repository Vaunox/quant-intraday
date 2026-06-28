#!/usr/bin/env python
r"""Step 2 ETF spread sampler (thin Kite ``quote()`` I/O shim).

All aggregation lives in :mod:`quant.research.etf.spreads` (Ground Rule 3). This shim
authenticates with the daily Kite token, polls ``quote()`` for the frozen Step 1 universe at
a fixed cadence across a session, appends each snapshot to a gitignored JSONL (durable), and
prints the per-leg spread summary. Run during NSE market hours (Mon-Fri 09:15-15:30 IST),
after a fresh ``scripts/kite_morning_auth.py``::

    uv run python scripts/etf_spread_sampler.py --interval 300 --minutes 375 \
        --out data/etf_spreads/quotes.jsonl

STT is resolved as negligible (``docs/etf_rotation/step1_liquidity_gate.md``); the spread
this measures plus the flat DP charge are the dominant costs at Rs 1 lakh scale (spec
Section 6). The universe is locked from Step 1 and is sampled as-is, not re-opened.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

from kiteconnect import KiteConnect

from quant.core.secrets import EnvSecrets, FileSecretStore
from quant.research.etf.spreads import QuoteSnapshot, summarize

#: Frozen tradeable universe (Step 1). Sampled as-is — the universe is not re-opened here.
UNIVERSE = ["NIFTYBEES", "BANKBEES", "MON100", "GOLDBEES", "SILVERBEES", "LIQUIDBEES"]
EXCHANGE = "NSE"


def _authenticated_kite() -> KiteConnect:  # pragma: no cover - network I/O
    """Build a KiteConnect client from the env api-key + daily file-store access token."""
    secrets = EnvSecrets(file_store=FileSecretStore.standard())
    kite = KiteConnect(api_key=secrets.get("kite_api_key"))
    kite.set_access_token(secrets.get("kite_access_token"))
    return kite


def _top_of_book(quote: dict[str, Any], symbol: str, now: dt.datetime) -> QuoteSnapshot:
    """Map one Kite quote entry to a top-of-book :class:`QuoteSnapshot`."""
    depth = quote.get("depth", {})
    buy = (depth.get("buy") or [{}])[0]
    sell = (depth.get("sell") or [{}])[0]
    return QuoteSnapshot(
        symbol=symbol,
        ts=now,
        bid=float(buy.get("price", 0) or 0),
        ask=float(sell.get("price", 0) or 0),
        bid_qty=int(buy.get("quantity", 0) or 0),
        ask_qty=int(sell.get("quantity", 0) or 0),
    )


def _poll(kite: KiteConnect, instruments: list[str]) -> list[QuoteSnapshot]:  # pragma: no cover
    """Poll quote() once and return a top-of-book snapshot per available instrument."""
    data = kite.quote(instruments)
    now = dt.datetime.now(dt.UTC)
    return [
        _top_of_book(data[inst], inst.split(":")[1], now) for inst in instruments if inst in data
    ]


def _append_jsonl(path: Path, snaps: list[QuoteSnapshot]) -> None:  # pragma: no cover - I/O
    """Append snapshots to a JSONL file (one record per line), creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for snap in snaps:
            handle.write(
                json.dumps(
                    {
                        "symbol": snap.symbol,
                        "ts": snap.ts.isoformat(),
                        "bid": snap.bid,
                        "ask": snap.ask,
                        "bid_qty": snap.bid_qty,
                        "ask_qty": snap.ask_qty,
                    }
                )
                + "\n"
            )


def _print_summary(collected: list[QuoteSnapshot]) -> None:  # pragma: no cover - reporting
    """Print the per-leg spread/depth summary table."""
    if not collected:
        print("no snapshots collected")
        return
    header = (
        f"{'symbol':12s} {'n':>4s} {'med_bps':>8s} "
        f"{'p90_bps':>8s} {'max_bps':>8s} {'top_depth':>9s}"
    )
    print("\n" + header)
    print("-" * len(header))
    for stat in summarize(collected):
        print(
            f"{stat.symbol:12s} {stat.samples:4d} {stat.median_spread_bps:8.1f} "
            f"{stat.p90_spread_bps:8.1f} {stat.max_spread_bps:8.1f} "
            f"{stat.median_top_depth_units:9.0f}"
        )


def main() -> int:  # pragma: no cover - process entry point
    """Sample spreads across a session and print the per-leg summary."""
    parser = argparse.ArgumentParser(description="ETF Step 2 live spread sampler")
    parser.add_argument("--interval", type=int, default=300, help="seconds between polls")
    parser.add_argument("--minutes", type=float, default=375.0, help="total sampling minutes")
    parser.add_argument(
        "--out", type=Path, default=Path("data/etf_spreads/quotes.jsonl"), help="JSONL output path"
    )
    args = parser.parse_args()

    kite = _authenticated_kite()
    instruments = [f"{EXCHANGE}:{sym}" for sym in UNIVERSE]
    deadline = time.monotonic() + args.minutes * 60.0
    collected: list[QuoteSnapshot] = []
    try:
        while time.monotonic() < deadline:
            snaps = _poll(kite, instruments)
            collected.extend(snaps)
            _append_jsonl(args.out, snaps)
            tightest = summarize(collected)[0] if collected else None
            note = (
                f" | tightest {tightest.symbol} {tightest.median_spread_bps:.1f}bps"
                if tightest
                else ""
            )
            stamp = f"{dt.datetime.now(dt.UTC):%H:%M:%S}"
            print(f"[{stamp}] polled {len(snaps)} legs, {len(collected)} total{note}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\ninterrupted — summarizing what was collected")
    _print_summary(collected)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
