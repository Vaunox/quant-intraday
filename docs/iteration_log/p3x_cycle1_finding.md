# Phase 3X — Cycle 1 finding: real cross-sectional factor gate (liquidity universe)

**Date:** 2026-06-27 · **Verdict: KILL** · MLflow `p3x-factor-gate` run `af66c3667f6e476b9440aded98261687`

The first **real** (non-synthetic) run of the Phase-3X cross-sectional multi-factor strategy, on a
survivorship-bias-free Indian daily panel built entirely from free NSE data.

## Setup (all free, all survivorship-correct)

| Component | Value |
|---|---|
| Price data | NSE **bhavcopy** archive, 2016-01-01 → 2024-12-31 — **2221 trading days × 2695 names**, incl. delisted names while they traded (P3X.1b/1d) |
| Corporate actions | **624 split/bonus** ex-dates from NSE's CA API, back-adjusted via the observed overnight ratio (P3X.1e) — real crashes left untouched |
| Universe | liquidity top-500 by trailing-126d median traded value → **1065 ever-eligible** names (P3X.1c) |
| Rebalances | **95 monthly** (post 252-day warm-up), 21-session forward-return labels |
| Book | top-quintile composite, inverse-vol weights, sector ≤25% + name ≤5% caps, 25% no-trade band |
| Cost | CNC delivery **0.22%** round-trip |
| Benchmark | equal-weight return of the eligible universe each month (cap-weighted TRI proxy — see caveat) |
| Validation | CombinatorialPurgedCV (4×2), active IR + DSR, seven-point benchmark-relative kill-gate |

## Result — KILL

```
active IR -0.815 | DSR 0.000 | dedup t -2.30 | max sector wt 0.250 (PASS)
fraction of CPCV active paths negative: 1.00
```

Only the diversification cap (sector ≤25%) passes; the return criteria fail decisively. The
long-only composite **does not beat the equal-weight universe after CNC cost**.

## Why it's KILL but NOT a bug — the IC check

A −0.82 active IR with *all* paths negative could be a sign error, so the composite's predictive
power was measured directly (average rank-IC over the 107 rebalances, eligible names only):

| Signal | rank-IC |
|---|---|
| **composite** | **+0.0513** |
| momentum 12-1 | +0.0455 |
| low-volatility | +0.0402 |
| residual momentum | +0.0332 |
| short-term reversal | +0.0100 |
| Amihud illiquidity | −0.0161 |

**The composite IC is positive (+0.051) — a respectable cross-sectional signal.** Momentum, low-vol,
and residual-momentum all carry genuine signal in survivorship-free Indian data; Amihud does not (no
illiquidity premium in a liquid top-500). So the negative active IR is **not** a sign bug: the rank
is right, the edge is simply **too weak to overcome (a) CNC cost and (b) a demanding equal-weight
benchmark.** This is the arc's recurring shape — real signal, not economically tradeable as framed.

## Caveats (honest scope of the verdict)

1. **Benchmark.** The gate spec is *active IR vs cap-weighted Nifty-500 TRI*; this run uses the
   **equal-weight** eligible universe as the proxy (bhavcopy carries no free-float market cap).
   EW is a **harder** benchmark than cap-weighted (it banks the size/rebalancing premium), so the
   active IR here is **conservatively biased downward**. A cap-weighted comparison needs free-float
   caps and was not fabricated.
2. **Universe.** Liquidity top-500, not the exact official Nifty-500 membership (operator decision —
   no free PIT membership exists). Factor premia are universe-robust, so the go/no-go holds.
3. **Long-only.** The positive IC says a **long-short** book (top-minus-bottom quintile, the §6
   extension) would isolate the alpha without the benchmark-choice problem — untested here.
4. Dividends ignored (price-return factors); CNC cost applied to the book, benchmark costless.

## What would change the verdict (if pursued)

- **Cap-weighted TRI benchmark** (source free-float caps) — the spec-correct, easier comparison.
- **Long-short variant** — converts the +0.051 IC into a benchmark-independent return stream.
- **Drop Amihud / re-weight** toward momentum + low-vol + residual (the IC-positive factors).
- **Exact Nifty-500 membership** — fidelity upgrade, unlikely to flip a −0.8 → +0.75 swing.

**Bottom line:** the apparatus is real and the data is honest; the equal-weight, long-only,
CNC-costed multi-factor baseline **fails the pre-committed bar (KILL)**, while carrying a genuine
but economically insufficient +0.05 cross-sectional IC.
