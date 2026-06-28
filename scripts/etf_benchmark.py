#!/usr/bin/env python
r"""Step 3 fixed-weight benchmark runner (thin Yahoo I/O shim).

All benchmark logic lives in :mod:`quant.research.etf.benchmark` (Ground Rule 3). This shim
fetches dividend-adjusted daily closes (total return) for the frozen universe's 5 risk legs,
synthesises the cash leg at an explicit yield (Yahoo understates LIQUIDBEES), aligns to the
common window, and prints the equal-weight monthly-rebalanced benchmark plus the Section 4
secondary floors (buy-and-hold NIFTYBEES, hold cash), all net of the Step 2 cost model::

    uv run python scripts/etf_benchmark.py --cash-yield 0.06

This is the line the ML must beat on EXCESS return. No ML is built or scored before it.
"""

from __future__ import annotations

import argparse
import datetime as dt

import requests

from quant.research.etf.benchmark import (
    EquityCurve,
    buy_and_hold,
    equal_weight_rebalanced,
    synthetic_cash_prices,
)
from quant.research.etf.costs import default_cost_model

RISK_LEGS = ["NIFTYBEES", "BANKBEES", "MON100", "GOLDBEES", "SILVERBEES"]
CASH_LEG = "LIQUIDBEES"
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?range=5y&interval=1d&events=div"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_adjclose(symbol: str) -> dict[dt.date, float]:  # pragma: no cover - network I/O
    """Fetch dividend-adjusted daily closes (total return) keyed by date."""
    resp = requests.get(_URL.format(sym=symbol), headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    out: dict[dt.date, float] = {}
    for ts, value in zip(result["timestamp"], adj, strict=False):
        if value is not None:
            out[dt.datetime.fromtimestamp(ts, dt.UTC).date()] = float(value)
    return out


def _row(label: str, curve: EquityCurve) -> str:
    """Format one metrics row for a curve."""
    return (
        f"{label:28s} {curve.cagr() * 100:8.2f} {curve.ann_sharpe():8.2f} "
        f"{curve.max_drawdown() * 100:8.2f}"
    )


def main() -> int:  # pragma: no cover - process entry point
    """Build and print the fixed-weight benchmark and the secondary floors."""
    parser = argparse.ArgumentParser(description="ETF Step 3 fixed-weight benchmark")
    parser.add_argument(
        "--cash-yield", type=float, default=0.06, help="annual total return for the cash leg"
    )
    args = parser.parse_args()

    series = {sym: fetch_adjclose(sym) for sym in RISK_LEGS}
    common = sorted(set.intersection(*(set(s) for s in series.values())))
    prices: dict[str, list[float]] = {sym: [series[sym][d] for d in common] for sym in RISK_LEGS}
    prices[CASH_LEG] = synthetic_cash_prices(common, args.cash_yield)

    model = default_cost_model()
    benchmark = equal_weight_rebalanced(common, prices, model)
    nifty = buy_and_hold(common, prices["NIFTYBEES"], "NIFTYBEES", model)
    cash = EquityCurve(common, [100_000.0 * p for p in prices[CASH_LEG]])

    print(f"common window: {common[0]} -> {common[-1]} ({len(common)} sessions)")
    print(f"cash-leg yield assumption: {args.cash_yield * 100:.1f}%\n")
    print(f"{'line':28s} {'CAGR%':>8s} {'Sharpe':>8s} {'maxDD%':>8s}")
    print("-" * 56)
    print(_row("equal-weight (monthly, net)", benchmark))
    print(_row("buy-and-hold NIFTYBEES (net)", nifty))
    # Cash is riskless by construction -> Sharpe is undefined (zero dispersion).
    print(f"{'hold cash (LIQUIDBEES)':28s} {cash.cagr() * 100:8.2f} {'n/a':>8s} {0.0:8.2f}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
