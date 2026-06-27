# Phase 3X — P3X.4b: cluster-selection combiner A/B vs baseline composite

**Date:** 2026-06-27 · **Verdict: MARGINAL — clustering beats the baseline but still KILLs the gate,
and the gain is not cleanly attributable to clustering.** · MLflow `p3x-factor-gate` run
`26acef44ecc54ccd909c8f1a4d4fd9a5` (cluster arm), live cumulative **N = 3**.

An A/B variant of the P3X.4 signal-combination step (not a new strategy): does K-Means
cluster-selection add anything over the baseline equal-weight z-score composite, judged by the
**identical** benchmark-relative seven-point gate? Same universe, same CNC costs, same CPCV scheme,
same thresholds — only the combiner differs.

## Setup (identical to cycle-1)

Survivorship-free bhavcopy panel (2221 dates × 2695 names), 624 split/bonus back-adjustments,
liquidity top-500 → **1065 ever-eligible** names, ~95 monthly rebalances, top-quintile inverse-vol
book, CNC 0.22% round-trip, equal-weight eligible-universe benchmark, CombinatorialPurgedCV.

- **Pre-committed config** (`config/factor_default.yaml` → `combination.cluster_selection`,
  committed **before** this run): `k = 5`, `random_state = 7`, `n_init = 10`, thesis weights
  **equal on {momentum, low_vol, residual_mom}** (the three IC-positive factors). Not tuned; no grid
  search.
- **Honest N pulled live** from the MLflow run count (`p3x-factor-gate`: 2 existing + 1 = **3**),
  never hard-coded.

## Head-to-head — every gate criterion side by side

| # | Criterion | Baseline composite | Cluster-selection |
|---|---|---|---|
| 1 | active IR (annualised, net) ≥ 0.75 | **KILL** −0.815 | **KILL** **+0.090** |
| 2 | Deflated Sharpe Ratio ≥ 0.95 (honest N) | **KILL** 0.000 | **KILL** 0.664 |
| 3 | PBO ≤ 0.2 | KILL (not computed) | KILL (not computed) |
| 4a | fraction negative paths ≤ 0.05 | **KILL** 1.000 | **PASS** 0.000 |
| 4b | worst path IR ≥ −0.3 | **KILL** −0.815 | **PASS** +0.090 |
| 5 | every active path net-positive | **KILL** (all negative) | **PASS** (all positive) |
| 6 | survives robustness battery | KILL (not run) | KILL (not run) |
| 7a | max sector weight ≤ 25% | PASS 0.250 | ~at cap 0.250 |
| 7b | max single-factor active share ≤ 0.6 | KILL (not computed) | KILL (not computed) |
| — | **dedup t-stat** (honest, FINDINGS §3) | **−2.30** | **+0.25** |
| — | **overall verdict** | **KILL** | **KILL** |

**Position overlap (mean Jaccard of held names per rebalance): 0.243.** The two books share only
~24% of names — clustering selects **genuinely different** names, it is *not* merely reorganizing
the same information the baseline rank already holds.

## Reading the result honestly

Clustering is a **real improvement** over the baseline: it flips the active IR from −0.815 to
**+0.090**, turns *every* CPCV path positive (criteria 4a/4b/5 go KILL → PASS), and lifts the DSR
from 0.000 to 0.664 and the dedup t-stat from −2.30 to +0.25. On the path-distribution criteria it
is unambiguously better.

But it **still KILLs the gate**, decisively, on the criteria that matter:
- **Criterion 1**: +0.090 active IR is **~8× short** of the +0.75 bar.
- **Criterion 2 / significance**: DSR 0.664 < 0.95, and the honest **dedup t-stat is +0.25** —
  statistically **indistinguishable from zero**. The flip to a positive IR is not significant.

### The confound (surfaced, not hidden — Ground Rule 9)

The improvement is **not cleanly attributable to clustering**. The cluster's thesis vector weights
only the **three IC-positive factors** (momentum, low-vol, residual-momentum), while the baseline
composite equal-weights **all five** — including the two factors cycle-1 found IC-weak/negative
(short-term reversal +0.010, Amihud −0.016). So part of the −0.82 → +0.09 swing is simply **dropping
the bad factors**, which cycle-1 already flagged as a lever ("drop Amihud / re-weight toward
momentum + low-vol + residual"). Isolating the clustering contribution would require a third arm — a
3-factor equal-weight composite on the same {momentum, low_vol, residual_mom} — but that is another
trial, and the pre-registered discipline is **pick once, do not sweep**. So the honest statement is:
the cluster arm conflates (a) thesis factor-selection with (b) K-Means clustering, and the combined
effect is still economically negligible.

## One-line verdict

**MARGINAL.** Cluster-selection beats plain ranking on the path distribution (IR −0.82 → +0.09, all
paths positive, 0.24 name-overlap so genuinely different selection) — but the edge is **~8× below
the bar and statistically insignificant (dedup t +0.25)**, both arms **KILL**, and the gain is
**confounded** with the thesis vector excluding the two IC-weak factors. **Clustering does not
produce a tradeable cross-sectional edge here; it is not a pass.** That is the answer — the A/B
working as designed.

## Reproduce

```
# code + pre-committed k/w committed first (config/factor_default.yaml)
.venv-research/Scripts/python.exe scripts/run_factor_gate.py --ab   # mlflow + sklearn + pandas 2
```
MLflow: experiment `p3x-factor-gate`, run `26acef44ecc54ccd909c8f1a4d4fd9a5` (cluster arm,
`position_overlap=0.243`, `n_trials=3`).
