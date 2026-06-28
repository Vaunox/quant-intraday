#!/usr/bin/env python
r"""Risk-managed PM viability runner (thin Yahoo I/O shim) — pre-registered Gate-2 test.

Logic lives in :mod:`quant.research.etf.portfolio` (Ground Rule 3). This shim fetches
dividend-adjusted closes, **drops Yahoo adjusted-close bad ticks** (isolated ~90% glitches
that fake huge drawdowns — see the verdict doc), runs the pre-registered vol-targeted
risk-parity PM over the committed 10y window, and prints the Gate-2 verdict::

    uv run python scripts/etf_portfolio.py

Pre-registration: docs/etf_rotation/pm_viability_prereg.md. ML is set aside (NO-GO).
"""

from __future__ import annotations

import datetime as dt
import statistics

import requests

from quant.research.etf.benchmark import (
    buy_and_hold,
    equal_weight_rebalanced,
    synthetic_cash_prices,
)
from quant.research.etf.costs import DEFAULT_LEGS, ETFCostModel
from quant.research.etf.portfolio import PMConfig, run_risk_parity_pm

RISK = ["NIFTYBEES", "BANKBEES", "MON100", "GOLDBEES"]
CASH = "LIQUIDBEES"
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?range=10y&interval=1d&events=div"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_clean(symbol: str) -> dict[dt.date, float]:  # pragma: no cover - network I/O
    """Fetch adjusted closes, dropping bad ticks (>40% off the centered 21-day median)."""
    resp = requests.get(_URL.format(sym=symbol), headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    rows = [
        (dt.datetime.fromtimestamp(t, dt.UTC).date(), float(a))
        for t, a in zip(result["timestamp"], adj, strict=False)
        if a is not None
    ]
    vals = [a for _, a in rows]
    out: dict[dt.date, float] = {}
    for i, (day, value) in enumerate(rows):
        neigh = vals[max(0, i - 10) : i] + vals[i + 1 : i + 11]
        med = statistics.median(neigh) if neigh else value
        if med > 0 and (value / med < 0.6 or value / med > 1.7):
            continue  # isolated adjusted-close glitch -> drop
        out[day] = value
    return out


def main() -> int:  # pragma: no cover - process entry point
    """Run the pre-registered PM and print the Gate-2 verdict (clean data)."""
    ser = {s: fetch_clean(s) for s in RISK}
    common = sorted(set.intersection(*(set(s) for s in ser.values())))
    prices: dict[str, list[float]] = {s: [ser[s][d] for d in common] for s in RISK}
    prices[CASH] = synthetic_cash_prices(common, 0.06)

    model = ETFCostModel(legs={k: DEFAULT_LEGS[k] for k in (*RISK, "LIQUIDBEES")})
    pm = run_risk_parity_pm(common, prices, model, PMConfig(), cash_symbol=CASH)
    ew = equal_weight_rebalanced(common, prices, model)
    nifty = buy_and_hold(common, prices["NIFTYBEES"], "NIFTYBEES", model)

    print(f"clean window {common[0]} -> {common[-1]} ({len(common)} sessions)")
    for name, curve in [
        ("PM (vol-target risk-parity)", pm),
        ("equal-weight", ew),
        ("buy-hold NIFTY", nifty),
    ]:
        print(
            f"  {name:30s} CAGR {curve.cagr() * 100:6.2f}%  Sharpe {curve.ann_sharpe():5.2f}  "
            f"maxDD {curve.max_drawdown() * 100:7.2f}%"
        )
    p1 = pm.max_drawdown() >= -0.20
    p2 = pm.ann_sharpe() > nifty.ann_sharpe() and pm.cagr() > nifty.cagr()
    p3 = pm.cagr() > 0.06
    dd = pm.max_drawdown() * 100
    print(f"\nGate2 (1) maxDD<=20%:        {'PASS' if p1 else 'FAIL'} ({dd:.1f}%)")
    print(f"Gate2 (2) beat buy-hold NIFTY: {'PASS' if p2 else 'FAIL'}")
    print(f"Gate2 (3) beat cash (>6%):     {'PASS' if p3 else 'FAIL'}")
    print(f"\nVERDICT: {'VIABLE PM' if (p1 and p2 and p3) else 'NO-GO'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
