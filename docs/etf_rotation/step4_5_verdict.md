# Step 4–5 — ML rotation unblind & verdict: **NO-GO**

**Track:** `etf-rotation`. Spec: `SPEC_MultiETF_Rotation.md` §§4–5, 8. Gate 1 (excess edge real?).
**Status:** COMPLETE. **Verdict: NO-GO.** The ML rotation loses to the fixed-weight benchmark in every configuration. No production repo (spec §6 trigger not met).
**Code:** `src/quant/research/etf/rotation.py` (pure pipeline, 5 unit tests; 32 ETF tests total, mypy-strict). Reproduce: `uv run python scripts/etf_rotation.py`.

## What was built (full framework, as requested)
Cross-sectional rotation reusing the framework: per-asset momentum/vol features → cross-sectional outperformance labels → **leakage-free OOS predictions via `PurgedKFold` + the calibrated LightGBM+XGBoost+logistic ensemble (`build_ensemble`)** → rank → inverse-vol sizing within top-k → causal regime gate → cost-aware weighted backtest → **excess over the Step 3 benchmark**, DSR-corrected on the honest trial count.

## Pre-registered grid (honest N = 4) and result
Window 2022-02-04 → 2026-06-26 (1085 sessions). Benchmark: CAGR 19.65%, Sharpe 1.53.

| Config | Strategy CAGR | Excess ann Sharpe |
|---|---:|---:|
| top_k=2, regime off | 15.33% | **−0.34** |
| top_k=3, regime off | 18.43% | **−0.12** |
| top_k=2, regime on | 15.57% | **−0.35** |
| top_k=3, regime on | 17.04% | **−0.26** |

- **Best excess ann Sharpe: −0.116** (Gate 1 needs **> +0.3**). Negative — the ML never beat fixed-weight.
- **DSR significance P(excess > 0): 0.318** (needs ~0.95). Not significant.
- Every config underperforms the 19.65% benchmark outright.

## Verdict: NO-GO
This is the spec's textbook NO-GO (§§4, 8): *"A strategy that makes money but loses to fixed-weight rebalancing is a NO-GO — the ML added nothing and you should just rebalance dumbly."* The rotation makes money (15–18% CAGR) but **loses to the dumb equal-weight basket in all four configurations**, and the best excess is negative and insignificant. Gate 1 fails. No production repo.

## Why (structural, honest)
1. **The cross-section is too thin.** 5 risk drivers, ~3–4 genuinely independent (the Step 1 flag), is almost nothing to rank — the ML cannot extract cross-sectional alpha that survives costs. This is the spec's §2 "few assets → macro bet, not a cross-section" risk, realised.
2. **The benchmark already holds the winners.** Equal-weight captured the 2022–26 gold/silver boom (Sharpe 1.53); tilting away from equal-weight mostly *reduced* exposure to the legs that ran, hence negative excess.
3. **Turnover drag.** The monthly rotation pays the regressive DP/spread cost (Step 2: ~15–32 bps/leg) the benchmark largely avoids, a headwind on every rebalance.
4. This repeats the **Phase 2R prior** (spec §9): sound machinery, real but absent/negative edge once the comparison is honest.

## Robustness of the NO-GO (residuals don't rescue it)
- **Provisional spreads** (Step 2 residual) don't change the verdict: strategy and benchmark pay the *same* costs, so excess is near-invariant to the spread level — and conservative (inflated) spreads only hurt the higher-turnover strategy more.
- **GMM regime gate**: this pass used a causal trailing-vol regime proxy, not the framework GMM (flagged in `rotation.py`). It doesn't matter — the regime-on configs were also negative, and elaborating the GMM is unjustified once Stage 1 fails (the project's standing discipline).
- The verdict fails on **raw negative excess**, upstream of any cost-precision or model-nuance that could plausibly flip it.

## Honest-N ledger (running)
| N | Choice |
|---:|---|
| 1 | Step 1 liquidity gate threshold |
| 2–5 | Step 4 grid: {top_k∈2,3} × {regime on/off} (4 trials) |

DSR deflation applied against N=4 at unblind. (Feature set, horizon, lookbacks, capacity were held fixed, not searched — had they been tuned, N and the deflation would be larger, making the bar *harder*, not easier.)

## Universe robustness (post-hoc variants — all NO-GO; honest N grows)

> **DATA-QUALITY CORRECTION (2026-06-28):** the **10y and 2020–26 rows below are contaminated**
> by Yahoo adjusted-close bad ticks (~90% one-day glitches, 2019-12 & 2021-06) found later
> (see `pm_viability_verdict.md`). Their drawdown/return/Sharpe figures are unreliable; the
> clean 10y benchmark is Sharpe ~1.5, not weak. The verdicts are unaffected (the apparent
> 3-ETF pass was rejected on best-of-N/no-selection grounds, independent of the data bug), but
> the numbers in rows 2–4 should be read as contaminated. **The core NO-GO (variant 1, the
> frozen-5 over 2022–26) is on clean data and stands.**


Iterating the universe is itself best-of-N (spec §5); each variant is a trial that *raises*
the DSR bar. Tried so far, all NO-GO:

| # | Universe | Window | Benchmark Sharpe | ML best excess Sharpe |
|---|---|---|---:|---:|
| 1 | NIFTY, BANK, MON100, GOLD, SILVER + cash (frozen) | 2022–26 | 1.53 | **−0.116** |
| 2 | drop gold/silver → NIFTY, BANK, MON100 + cash | 2022–26 / 2016–26 | 1.31 / 0.57 | benchmark-only check |
| 3 | NIFTY, BANK, MON100, **MID150BEES, ITBEES** + cash | 2020–26 | 1.23 | **−0.160** |

| 4 | frozen-5 over 10y → infeasible (SILVERBEES inception 2022); feasible proxy drops silver, keeps gold: NIFTY, BANK, MON100, GOLD + cash | 2016–26 | 0.49 | +0.311 (DSR as-run **0.874 < 0.95**; honest-N N=20 → **0.089**) |

Variant 4 (the long-window frozen proxy): benchmark CAGR 15.89%, Sharpe 0.49, **maxDD −55.82%**
— over 10y the gold-inclusive basket is weak and breaches the 20% DD cap by itself, confirming
the 2022–26 Sharpe 1.53 was a recent-window/precious-metals artifact. The ML's +0.311 fails the
significance bar even before honest-N deflation, and collapses to 0.089 after.

Variant 3 is telling: the equal-weight benchmark (1.23) barely beats buy-and-hold NIFTYBEES
(1.26) — the added ETFs are equity-correlated, so they restore the asset *count* but add no
diversification and no rankable independent signal. **The NO-GO is structural and robust:**
the ML's raw excess is negative in every configuration of every variant, upstream of any DSR
adjustment. No reachable liquid universe at ₹1 lakh fixes this — the genuinely independent
drivers (gold, silver, US equity) are too few, and the rest are correlated Indian equity.

## The 3-ETF "PASS" — surfaced and rejected as best-of-N (2026-06-28)

Running the ML on the 3-risk-asset universe (NIFTY, BANK, MON100 + cash) produced an apparent
pass — and it is instructive precisely because it is a textbook selection-bias false positive:

- 10y (2016–26): best excess +0.382, DSR(as-run, N=4) **0.958** → printed PASS.
- 2022–26: best excess +0.414, DSR 0.550 → NO-GO.

**Rejected on three independent grounds:**
1. **Best-of-N.** The 0.958 deflates against only the final 4-config grid. Against the honest
   trial count (3 universes × 2 windows × 4 configs ≈ 16–20), the same result deflates to
   **0.44 (N=8) → 0.25 (N=16) → 0.21 (N=20)** — far below 0.95. (Recomputed with the full-
   search cross-trial Sharpe variance.)
2. **No selection.** The winning cell is `top_k=3`, which holds *all three* risk assets — no
   cross-sectional ranking occurs. The excess is inverse-vol construction + cash/regime tilt
   vs equal-weight, **not** the ML rotation hypothesis. The real-selection configs (`top_k=2`)
   give only +0.30/+0.29.
3. **Window-dependent.** `top_k=2` is +0.30 on 10y but **−0.25/−0.33 on 2022–26**; the 10y
   "edge" is largely the cash/inverse-vol tilt dodging the −45% COVID drawdown in one window.

This is the forensic-audit lesson applied in real time: an apparent pass produced by iterating
universes/windows, correctly killed by honest-N deflation. **Verdict unchanged: NO-GO.**

## Outcome
**Documented NO-GO**, same discipline as the P2R close-out and the gold-mini infeasibility. No live trading, $0 risked. The `etf-rotation` branch holds the full apparatus (re-runnable) and this verdict. If revisited, the honest levers would be a genuinely broader/independent universe (needs more capital to trade cleanly) — not more model tuning on these 6 correlated legs.
