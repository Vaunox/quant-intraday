# Step 3 — Fixed-weight benchmark (the line the ML must beat)

**Track:** `etf-rotation`. Spec: `SPEC_MultiETF_Rotation.md` §4.
**Status:** Built. Code: `src/quant/research/etf/benchmark.py` (pure, 7 unit tests, mypy-strict) + thin runner `scripts/etf_benchmark.py`. Reproduce: `uv run python scripts/etf_benchmark.py`.

## Construction (pre-registered)
- **Equal-weight** across the frozen universe (6 legs incl. cash), **monthly rebalanced**, net of the Step 2 cost model. Same universe and costs the ML will get.
- **Total-return prices:** Yahoo dividend-adjusted close for the 5 risk legs. **Cash leg modeled at an explicit 6% annual yield** — Yahoo's adjclose understates LIQUIDBEES (~3% vs the real ~6% overnight rate), and the cash leg is the pivot of the excess comparison.
- Window = common overlap, capped by SILVERBEES: **2022-02-04 → 2026-06-26, 1085 sessions (~4.3y).**

## Result (net of costs)

| Line | CAGR | Sharpe (ann.) | max DD |
|---|---:|---:|---:|
| **Equal-weight (monthly) — the benchmark** | **19.65%** | **1.53** | **−18.84%** |
| Buy-and-hold NIFTYBEES | 8.89% | 0.74 | −15.23% |
| Hold cash (LIQUIDBEES) | 6.00% | n/a | 0.00% |

The benchmark clears both Section 4 secondary floors comfortably (beats NIFTYBEES and cash).

## The honest read — this is a brutal benchmark, and it sharpens the NO-GO risk

1. **Sharpe 1.53 is a very high bar.** The ML must beat this on **DSR-corrected EXCESS** return (spec §5), not beat zero. Adding alpha on top of a 1.53-Sharpe fixed-weight basket is hard; the base rate for tactical overlays beating fixed-weight after costs is poor (spec §2). This is the central NO-GO risk, now quantified.
2. **The window is a precious-metals bull market.** GOLDBEES (~38% CAGR) and SILVERBEES carried the basket; the equal-weight Sharpe is regime-specific and likely overstated vs the long run. **~4.3y is a short sample → few independent observations → DSR correction will be punishing**, especially once Step 4's trials accumulate.
3. **The 30–35% return target is far above even the benchmark (19.65%).** The ML must *both* beat the benchmark on excess *and* reach 30–35% net — i.e., add ~10–15% of annual alpha over an already-strong basket. On a long/flat/no-leverage book over this universe, that is a very steep ask.
4. **The benchmark itself draws down −18.84%, ≈ the 20% Gate-2 cap.** A strategy with comparable exposure risks breaching the cap; staying under 20% likely forces de-risking that costs return.

This mirrors the Phase 2R prior (spec §9): the machinery is sound, but the economics look thin once the benchmark is honest. **Standing assessment going into Step 4: the bar is high enough that NO-GO is a live, probable outcome — which is exactly what Step 3 exists to establish before any ML is built.**

## Caveats / honest-N
- Benchmark-definition choices (equal-weight, monthly, 6% cash yield) are the pre-registered comparator, not strategy trials. The **strategy's** rebalance frequency, labels, lookbacks, and hyperparameters all count toward N in Step 4.
- Cash-yield sensitivity: cash is 1/6 of the book, so a 3% vs 6% assumption moves the benchmark CAGR by ~0.5%; immaterial to the verdict.
- Spreads remain provisional (Step 2 residual); the benchmark and ML both pay them, so the *excess* comparison is robust to a common spread error.

## Sensitivity: was the Sharpe-1.53 just the gold/silver bull? (post-hoc, 2026-06-28)

Checked by re-running the benchmark on an equal-weight **{NIFTYBEES, BANKBEES, MON100} + cash** basket (gold + silver removed):

| Basket / window | CAGR | Sharpe | maxDD |
|---|---:|---:|---:|
| Original 5-asset, 2022–26 | 19.65% | 1.53 | −18.84% |
| No gold/silver, 2022–26 (same window) | 13.80% | 1.31 | −12.56% |
| No gold/silver, 2016–26 (10y) | ~~15.74%~~ | ~~0.57~~ | ~~−45.04%~~ |

> **DATA-QUALITY CORRECTION (2026-06-28):** the 10y row is **contaminated by Yahoo adjusted-close bad ticks** (isolated ~90% one-day glitches in 2019-12 and 2021-06) — see `pm_viability_verdict.md`. The clean **10y benchmark with gold is Sharpe 1.54**, robustly strong; the "gold/silver + recent window flattered it" conclusion below is **WRONG** — an artifact, not a real collapse. The same-window 2022–26 rows are clean (glitches predate 2022).

**~~Confirmed~~ [RETRACTED — see correction above]:** gold/silver plus the benign recent window flattered the benchmark. Over a representative 10 years the equity-only basket is a mediocre Sharpe 0.57 with a −45% drawdown. **But this is not a valid GO universe and does not change the verdict:** (a) 3 risk assets trips the §8 `<4 independent drivers` kill; (b) −45% 10y DD breaches the 20% Gate-2 cap; (c) the Step 4 NO-GO is excess-based on the frozen 5-asset universe — a thinner cross-section makes the ML's job harder, not easier. Counts as a post-hoc trial (honest N). Data note: 10y window uses Yahoo `range=10y` (dense to 2016); `range=max` is sparse pre-2015 (Step 1 finding), so a true 15y window isn't cleanly available from this feed.

## Next
Step 4 — ML rotation through the full framework (triple-barrier/forward labels per asset, the GMM regime gate, cross-sectional ranking, HRP/inverse-vol), honest N from trade one. Step 5 — unblind **excess over this benchmark** against the +0.3 DSR bar. No strategy scoring before Step 4 is built on the framework.
