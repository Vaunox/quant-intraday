# P7.2 — Cointegration pairs / statistical arbitrage: verdict

**Verdict: KILL — the strongest mechanical edge found, but real-but-too-weak and not
statistically significant.** Pre-registration committed first
(`cointegration_pairs_prereg.md`). Run on **real data** (the survivorship-free NSE daily panel),
fully cost-inclusive, point-in-time. Per the budget, smoke ≥ +0.3 did **not** auto-stop — it was
escalated to the kill-gate, which KILLs it on criterion 1.

## What was run

`scripts/run_p7_pairs.py` over the 20 most-liquid full-history large-caps in
`data/nifty_panel/close.parquet` (2016–2024), CPCV 6×2, honest CNC **0.22%** round-trip cost,
**5 config variants** (each one trial, P6.2): formation length, p-value cutoff, pair count, z-cap.

| Variant | net ann CPCV median path-Sharpe | profit factor | months |
|---|---|---|---|
| **baseline** (formation 252, p≤0.05, 5 pairs, z-cap 2) | **+0.425** | 1.721 | 95 |
| formation 504 | +0.254 | 1.222 | 81 |
| p-value ≤ 0.01 | +0.399 | 1.593 | 71 |
| 10 pairs | +0.404 | 1.699 | 95 |
| z-cap 3 | +0.414 | 1.701 | 95 |

Best (baseline): **+0.425 net annualised Sharpe** (gross +0.470 — cost drag ~0.045). Market-neutral
by construction; profit factor 1.72; every CPCV path positive.

## Per-criterion kill-gate read (baseline, the strongest variant)

| # | Criterion | Threshold | Value | Verdict |
|---|---|---|---|---|
| 1 | CPCV median path-Sharpe (net, ann) | ≥ 1.0 | **+0.425** | ❌ **FAIL** (~2.4× short) |
| 2 | Deflated Sharpe Ratio | ≥ 0.95 | 1.000 (path-concat) / **honest t = 1.20, p ≈ 0.12** | ❌ **FAIL** (not significant, honest basis) |
| 4 | Fraction negative paths / worst path | ≤ 0.05 / ≥ −0.5 | 0.00 / +0.425 | ✅ (but degenerate — see caveat) |
| 5 | Profit factor | ≥ 1.2 | 1.72 | ✅ |

**Verdict: KILL.** Criterion 1 fails decisively and criterion 2 fails on the honest significance
basis, so the full robustness battery (criterion 6) is not spent — it cannot lift +0.425 to ≥ 1.0
(the same "confirm a known-failing candidate cheaply" discipline the original program used at
Gate 2 / Cycle 1).

## Two honesty caveats (surfaced, not hidden)

1. **The CPCV path distribution is degenerate for this class of spec.** P7.x mechanisms are
   *rule-based*: their per-period returns are precomputed point-in-time and do **not** depend on
   the train/test split, so CPCV reconstructs **φ identical paths** (measured path-Sharpe std =
   1.4e-17). The "median path-Sharpe" therefore equals the **full-sample annualised Sharpe**, and
   criterion 4 (narrow positive distribution) is trivially satisfied and uninformative. The genuine
   out-of-sample validity comes from the **point-in-time construction** (trailing-formation pair
   selection, forward-realised return), and the genuine significance from the **de-duplicated
   t-stat** — not from CPCV path variance. CPCV's path-distribution machinery earns its keep only
   for refit-per-split models (the original program's ensemble), not for fixed-rule mechanisms.

2. **The DSR is convention-inflated; the honest significance is marginal-to-null.** DSR = 1.000 is
   computed on the path-concatenated sample (5 × 95 = 475 overlapping obs — the FINDINGS §3
   convention). The **de-duplicated** t-stat is **+1.20** (one-sided p ≈ 0.12) — the edge is **not
   statistically distinguishable from zero** at honest significance. Reported both; the honest
   (insignificant) reading stands.

## Bottom line

A market-neutral cointegration-pairs book on real NSE large-caps shows a **+0.42 net-of-cost
annualised Sharpe point estimate** — the **strongest mechanical edge this program has found**, and
the first to clear the +0.3 continue band. But it is **below the +1.0 economic bar by ~2.4×** and
**not statistically significant** (t = 1.20 on 95 months). This is the same structural finding as
the original program (`FINDINGS.md`): a real but economically negligible edge that does not survive
the kill-gate. **KILL.**

## Trial count

**5 trials charged** (the 5 config variants). Cumulative Part-VI trial count → 5 (P7.1 charged 0).
Well within the budget's cap of 40.

## Routing

Per `budget.md`: P7.2 does not clear → **proceed to P7.3 (PEAD)**, the last conditional mechanism.
