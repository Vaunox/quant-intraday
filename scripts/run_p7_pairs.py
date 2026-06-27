"""Run the P7.2 cointegration-pairs study on the real survivorship-free panel (Part VI).

Loads ``data/nifty_panel/close.parquet``, screens a liquid candidate set (full history over the
window), and judges the cointegration-pairs mechanism through the **existing** CPCV + kill-gate
machinery — across a small config panel whose every variant is one honest trial (P6.2). Prints each
variant's net annualised CPCV median path-Sharpe (the smoke) and the best, against the
pre-committed +0.3 stop band (``docs/mechanisms/budget.md``).

Run: ``uv run python scripts/run_p7_pairs.py`` (reads only local Parquet; no broker/network).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from quant.research.mechanisms.pairs import MONTHLY_PERIODS_PER_YEAR, CointegrationPairsSpec
from quant.research.mechanisms.spec import evaluate_spec_under_cpcv
from quant.research.mechanisms.trials import TrackerTrialCountSource, deflated_sharpe_auto
from quant.research.models.tracking import InMemoryExperimentTracker, RunRecord
from quant.research.reports.report import profit_factor
from quant.research.validation.cpcv import CombinatorialPurgedCV

#: Honest CNC round-trip cost (the daily/CNC basis used throughout, FINDINGS §3).
ROUND_TRIP_COST = 0.0022
#: Cap the candidate universe so the O(n^2) cointegration scan stays tractable.
MAX_CANDIDATES = 20


@dataclass(frozen=True, slots=True)
class Variant:
    """One config variant (a trial): the searched pairs knobs."""

    name: str
    formation_days: int
    pvalue_max: float
    max_pairs: int
    z_cap: float
    min_correlation: float


VARIANTS = (
    Variant("baseline", 252, 0.05, 5, 2.0, 0.75),
    Variant("formation_504", 504, 0.05, 5, 2.0, 0.75),
    Variant("pvalue_01", 252, 0.01, 5, 2.0, 0.75),
    Variant("pairs_10", 252, 0.05, 10, 2.0, 0.75),
    Variant("zcap_3", 252, 0.05, 5, 3.0, 0.75),
)


def _candidates(panel: pd.DataFrame) -> list[str]:
    """Liquid full-history candidate set: backfilled large-caps present in the panel."""
    backfilled = sorted({p.name.split("=")[1] for p in Path("data/parquet").glob("symbol=*")})
    full = set(panel.columns[panel.notna().all()].tolist())
    cands = [s for s in backfilled if s in full]
    return cands[:MAX_CANDIDATES]


def main() -> int:
    """Run every variant through CPCV; print the smoke and the budget decision."""
    panel = pd.read_parquet("data/nifty_panel/close.parquet")
    cands = _candidates(panel)
    sub = panel[cands]
    print(f"panel: {panel.shape}; candidates ({len(cands)}): {cands}", flush=True)

    cpcv = CombinatorialPurgedCV(6, 2, embargo_pct=0.01)
    tracker = InMemoryExperimentTracker()
    results: list[tuple[str, float, float, float, float]] = []
    for v in VARIANTS:
        t0 = time.time()
        spec = CointegrationPairsSpec(
            sub,
            round_trip_cost=ROUND_TRIP_COST,
            formation_days=v.formation_days,
            pvalue_max=v.pvalue_max,
            max_pairs=v.max_pairs,
            z_cap=v.z_cap,
            min_correlation=v.min_correlation,
        )
        ev = evaluate_spec_under_cpcv(spec, cpcv, periods_per_year=MONTHLY_PERIODS_PER_YEAR)
        net = ev.representative_path.to_numpy(dtype="float64")
        pf = profit_factor(net)
        sharpe = ev.annualised_median_sharpe
        tracker.log_run(RunRecord(run_name=f"p7.2-{v.name}", params={}, metrics={}))
        results.append((v.name, sharpe, ev.fraction_negative, pf, spec.n_periods))
        print(
            f"[{v.name}] periods={spec.n_periods} ann_median_sharpe={sharpe:+.3f} "
            f"frac_neg={ev.fraction_negative:.2f} worst={ev.worst_path_sharpe:+.3f} "
            f"profit_factor={pf:.3f} ({time.time() - t0:.0f}s)",
            flush=True,
        )

    best = max(results, key=lambda r: r[1])
    # DSR of the best variant at the honest cumulative trial count (every variant counted).
    spec = CointegrationPairsSpec(
        sub,
        round_trip_cost=ROUND_TRIP_COST,
        formation_days=next(v.formation_days for v in VARIANTS if v.name == best[0]),
        pvalue_max=next(v.pvalue_max for v in VARIANTS if v.name == best[0]),
        max_pairs=next(v.max_pairs for v in VARIANTS if v.name == best[0]),
        z_cap=next(v.z_cap for v in VARIANTS if v.name == best[0]),
        min_correlation=0.75,
    )
    ev = evaluate_spec_under_cpcv(spec, cpcv, periods_per_year=MONTHLY_PERIODS_PER_YEAR)
    variance = float(np.var(ev.distribution.path_sharpes, ddof=1))
    source = TrackerTrialCountSource(tracker)
    dsr = deflated_sharpe_auto(ev.combined, variance, trial_source=source)

    print("\n==== P7.2 cointegration-pairs SMOKE ====", flush=True)
    print(f"trials (cumulative N): {source.cumulative_trial_count()}", flush=True)
    print(f"best variant: {best[0]}  net ann CPCV median path-Sharpe: {best[1]:+.3f}", flush=True)
    print(f"DSR (honest N): {dsr:.3f}", flush=True)
    print(f"de-dup t-stat: {ev.dedup_tstat:+.3f}", flush=True)
    verdict = (
        "ABOVE +0.3 -> escalate to full battery" if best[1] >= 0.3 else "BELOW +0.3 -> STOP (KILL)"
    )
    print(f"budget stop band (+0.3): {verdict}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
