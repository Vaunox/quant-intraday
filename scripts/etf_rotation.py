#!/usr/bin/env python
r"""Step 4 ML rotation runner + Step 5 unblind (thin shim).

All logic lives in :mod:`quant.research.etf.rotation` (Ground Rule 3). This shim fetches the
total-return price panel, rebuilds the Step 3 benchmark, runs the pre-registered configuration
grid through the full framework (purged-CV ensemble OOS predictions, cross-sectional ranking,
inverse-vol sizing, causal regime gate), and unblinds the **excess over the benchmark**,
DSR-corrected on the honest trial count (SPEC_MultiETF_Rotation.md §§4-5, Gate 1)::

    uv run python scripts/etf_rotation.py --cash-yield 0.06

Gate 1 needs DSR-corrected excess Sharpe > +0.3. A NO-GO is the expected, valid outcome.
"""

from __future__ import annotations

import argparse
import datetime as dt

import requests

from quant.research.etf.benchmark import equal_weight_rebalanced, synthetic_cash_prices
from quant.research.etf.costs import default_cost_model
from quant.research.etf.rotation import RotationConfig, run_grid

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


#: Pre-registered grid. Each row is a trial counted against the DSR budget (SPEC §5).
GRID = [
    RotationConfig(top_k=2, use_regime_gate=False),
    RotationConfig(top_k=3, use_regime_gate=False),
    RotationConfig(top_k=2, use_regime_gate=True),
    RotationConfig(top_k=3, use_regime_gate=True),
]


def main() -> int:  # pragma: no cover - process entry point
    """Run the grid and print the Gate-1 verdict on excess over the benchmark."""
    parser = argparse.ArgumentParser(description="ETF Step 4 ML rotation + Step 5 unblind")
    parser.add_argument("--cash-yield", type=float, default=0.06)
    args = parser.parse_args()

    series = {sym: fetch_adjclose(sym) for sym in RISK_LEGS}
    common = sorted(set.intersection(*(set(s) for s in series.values())))
    prices: dict[str, list[float]] = {sym: [series[sym][d] for d in common] for sym in RISK_LEGS}
    prices[CASH_LEG] = synthetic_cash_prices(common, args.cash_yield)

    model = default_cost_model()
    benchmark = equal_weight_rebalanced(common, prices, model)
    verdict = run_grid(
        common,
        prices,
        benchmark,
        model,
        GRID,
        cash_symbol=CASH_LEG,
        market_symbol="NIFTYBEES",
    )

    print(f"window: {common[0]} -> {common[-1]} ({len(common)} sessions)")
    print(f"benchmark: CAGR {benchmark.cagr() * 100:.2f}%  Sharpe {benchmark.ann_sharpe():.2f}\n")
    print(f"{'config':32s} {'strat_CAGR%':>11s} {'excess_Sharpe':>14s}")
    print("-" * 60)
    for res in verdict.results:
        cfg = res.config
        label = f"top_k={cfg.top_k} regime={'on' if cfg.use_regime_gate else 'off'}"
        print(f"{label:32s} {res.strategy.cagr() * 100:11.2f} {res.excess_ann_sharpe:14.2f}")
    print("-" * 60)
    print(f"trials (honest N):           {verdict.n_trials}")
    print(
        f"best excess ann Sharpe:      {verdict.best_excess_ann_sharpe:+.3f}  (Gate 1 needs > +0.3)"
    )
    print(f"DSR significance P(excess>0): {verdict.dsr_probability:.3f}  (needs ~0.95)")
    passed = verdict.best_excess_ann_sharpe > 0.3 and verdict.dsr_probability > 0.95
    print(f"\nGate 1 (excess edge real?): {'PASS' if passed else 'NO-GO'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
