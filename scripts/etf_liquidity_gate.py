#!/usr/bin/env python
r"""Step 1 universe liquidity gate for the multi-ETF rotation track (thin I/O shim).

All gate logic lives in the importable, unit-tested :mod:`quant.research.etf.liquidity`
(Ground Rule 3). This shim only fetches daily bars from Yahoo Finance for the candidate
ETFs, builds the panel, and prints the ranked gate result, e.g.::

    uv run python scripts/etf_liquidity_gate.py --csv data/etf_liquidity/summary.csv

Yahoo is a coarse turnover/continuity screen only; the real bid-ask spread is the live
Step 2 measurement (SPEC_MultiETF_Rotation.md Section 6). The committed gate thresholds
are recorded in ``docs/etf_rotation/step1_liquidity_gate.md`` and count toward honest N.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import requests

from quant.research.etf.liquidity import DailyBar, LiquidityGate, run_gate

#: Candidate universe (scaffolding) -> human-readable exposure. The *tradeable* universe is
#: whatever clears the gate; substitutes and correlated drivers are resolved in the doc.
CANDIDATES: dict[str, str] = {
    "NIFTYBEES": "India large-cap",
    "SETFNIF50": "India large-cap",
    "BANKBEES": "India banks",
    "GOLDBEES": "Gold",
    "SETFGOLD": "Gold",
    "SILVERBEES": "Silver",
    "LIQUIDBEES": "Cash (overnight)",
    "JUNIORBEES": "India Next50",
    "MON100": "US equity (Nasdaq100)",
    "ITBEES": "India IT",
    "MID150BEES": "India midcap",
    "MIDCAPETF": "India midcap",
}

#: Committed Step 1 thresholds (see the finding doc). Rs 5 crore = 5e7.
GATE = LiquidityGate(min_median_traded_value=5e7, min_continuity_pct=99.0, window=252)

_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?range=2y&interval=1d"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_daily(symbol: str) -> list[DailyBar]:  # pragma: no cover - network I/O
    """Fetch ~2y of daily bars for ``symbol`` from Yahoo, dropping rows with no close."""
    resp = requests.get(_YAHOO.format(sym=symbol), headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    bars: list[DailyBar] = []
    rows = zip(result["timestamp"], quote["close"], quote["volume"], strict=False)
    for ts, close, volume in rows:
        if close is None:
            continue
        day = dt.datetime.fromtimestamp(ts, dt.UTC).date()
        bars.append(DailyBar(day=day, close=float(close), volume=float(volume or 0)))
    return bars


def main() -> int:  # pragma: no cover - process entry point
    """Fetch the candidate panel, run the gate, and print the ranked result."""
    parser = argparse.ArgumentParser(description="ETF Step 1 universe liquidity gate")
    parser.add_argument(
        "--csv", type=Path, default=None, help="optional path to write a CSV summary"
    )
    args = parser.parse_args()

    panel = {sym: fetch_daily(sym) for sym in CANDIDATES}
    stats = run_gate(panel, GATE)

    header = (
        f"{'symbol':12s} {'exposure':22s} {'1y_from':11s} "
        f"{'n':>4s} {'med_cr/day':>10s} {'cont%':>6s} {'gate':>5s}"
    )
    print(header)
    print("-" * len(header))
    lines = ["symbol,exposure,window_start,sessions,median_cr_day,continuity_pct,gate"]
    for stat in stats:
        med_cr = stat.median_traded_value / 1e7
        verdict = "PASS" if stat.passes(GATE) else "fail"
        exposure = CANDIDATES[stat.symbol]
        print(
            f"{stat.symbol:12s} {exposure:22s} {stat.window_start.isoformat():11s} "
            f"{stat.sessions:4d} {med_cr:10.1f} {stat.continuity_pct:6.1f} {verdict:>5s}"
        )
        lines.append(
            f"{stat.symbol},{exposure},{stat.window_start.isoformat()},{stat.sessions},"
            f"{med_cr:.2f},{stat.continuity_pct:.1f},{verdict}"
        )

    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
