# Project Findings — Quant Intraday Research Program

**Authoritative close-out of the research arc.** This document is the honest record of what
this program built, what it tested, what it found, and why it concluded. It is self-contained:
a reader who has never seen the project should be able to finish it understanding exactly what
the apparatus is, what the honest ceiling of the edge actually is, and why no candidate ever
cleared the kill-gate.

**One-line verdict:** the apparatus is sound and complete; the honest edge in this strategy
family is **real but economically negligible (≈ +0.148 annualised CPCV path-Sharpe)** and does
not clear the seven-point kill-gate. The research program **closes** at this finding, on budget,
$0 of capital risked. This is a successful Inviolable-Rule-7 outcome — *"no tradeable edge at
retail scale in this strategy family"* is a real, honestly-earned answer.

Cross-references: [`PROGRESS.md`](PROGRESS.md) (authoritative build log) ·
[`iteration_log/`](iteration_log/) (per-cycle records) · [`deep_dives/`](deep_dives/) (design) ·
[`iteration_log/cycle-5_closeout.md`](iteration_log/cycle-5_closeout.md) (the final cycle seal).

---

## 1. What we built (the apparatus)

A complete, gated, point-in-time research pipeline for Indian cash-equity trading. Every layer
is real (not stubbed), unit-tested, type-checked under mypy strict, and leakage-guarded in CI
(1077 tests green at close). The apparatus itself is the **durable asset** — it is sound and
reusable regardless of this strategy's verdict.

**Data layer (Layer 1).** Zerodha Kite Connect adapter (SDK-confined behind our own Protocols)
→ paginated resumable backfill → three-tier storage behind one `Repository` interface
(immutable Parquet cold archive, versioned Arctic warm store, Redis hot store). Hygiene jobs
are pure transforms over a canonical bars schema: corporate-action back-adjustment
(`CorporateActionAdjuster`), point-in-time survivorship membership (`ConstituentRegistry`,
includes delisted names), bad-tick filtering (point-in-time spike test vs previous *valid*
close), calendar-aware gap detection, and a liquidity screen. A data-quality dashboard composes
these into a per-symbol report.

**Feature library (Layer 1, P1.6/P1.7).** All features are pure, causal, point-in-time:
core (multi-horizon returns, realized/ATR/Parkinson volatility, intraday VWAP-deviation),
microstructure (order-flow imbalance, spread, depth imbalance, signed volume — over depth/trade
frames), technical (TA-Lib: RSI, MACD, Bollinger, CCI, DX, Williams %R, MFI, SMA, VWMA),
cyclical temporal (time-of-day/day-of-week), cross-sectional (rank + sector-neutral z-score over
a wide panel), and regime descriptors. The **dual-path harness** computes features identically
for backtest (vectorized) and live (incremental) so there is no train/serve skew *by
construction*. The **P1.8 adversarial leakage suite** enforces this in CI: forward-shift
invariance, no-future-correlation, trailing-only normalization, and skew-freeness — applied to
the real library (CI fails if a feature turns leaky) and proven to fire on deliberately-leaky
features.

**Labeling (Layer 2, P2.3/P2.5).** CUSUM event sampling → triple-barrier labels (volatility-
scaled, cost-floored, conservative same-bar-tie-to-stop). Two holding modes:
**MIS** (intraday square-off, the original) and **CNC** (multi-day overnight holds — added in
Cycle 5; see §6). Meta-labeling (`MetaLabeler`) produces side-aware bet/no-bet labels for the
second-stage filter. Sample weighting corrects non-IID overlapping labels (average uniqueness ×
time-decay; sequential bootstrap).

**Model stack (Layer 2, P2.6/P2.7).** A cross-family ensemble — LightGBM + XGBoost + a
hand-rolled logistic — blended by rank-averaging or stacking, behind a **GMM regime gate** that
switches off regimes whose train-set net edge is non-positive, with optional **meta-labeling**
as a bet/no-bet second stage sizing conviction. Capacity is deliberately modest (shallow trees,
strong regularization) — a small robust edge, not a perfect in-sample fit.

**Validation engine (Layer 2, P2.1/P2.2/P2.8/P2.9).** This is the heart of the apparatus, built
*before* the models ("build the judge before the contestant"): purged k-fold + embargo CV,
**Combinatorial Purged CV** (CPCV, φ reconstructed paths), **Deflated Sharpe Ratio** (DSR,
deflates for trial count), **Probability of Backtest Overfitting** (PBO via CSCV), a
**robustness battery** (parameter sensitivity, Monte-Carlo trade shuffle, noise injection,
cross-symbol leave-one-out, synthetic-data control), **two-engine reconciliation** (independent
event-driven and vectorized backtests must agree to floating-point noise), the full **Indian
transaction-cost model**, and the **seven-point kill-gate** that judges all of it on
cost-inclusive data.

The thresholds were fixed *before* any candidate was run (Inviolable Rule 1), in
[`config/default.yaml`](../config/default.yaml):

| # | Kill-gate criterion | Threshold |
|---|---|---|
| 1 | CPCV median path-Sharpe (annualised, **net**) | ≥ **1.0** |
| 2 | Deflated Sharpe Ratio | ≥ **0.95** |
| 3 | Probability of Backtest Overfitting | ≤ **0.2** |
| 4 | Fraction of negative paths / worst path-Sharpe | ≤ **0.05** / ≥ **−0.5** |
| 5 | Profit factor / max trade concentration | ≥ **1.2** / ≤ **0.5** |
| 6 | Survives the robustness battery | yes |
| 7 | Every observed regime's mean net return | ≥ **0.0** |

A candidate proceeds toward capital only if it clears **all seven**.

---

## 2. The research arc and what we tested

The build advanced through hard gates (Part IV of the master blueprint). **Gate 0** (tooling)
and **Gate 1** (data + features, tag `gate-1-data`) passed. The model + validation stack was
then built (P2.1–P2.9) and a final real-data artifact trained.

**P2A.6 — the final real-data artifact.** MLflow experiment `p2a6-final-run` (id 2), run-ID
**`e24c0cd6354f40e7bae024ce9f6b16c1`** (FINISHED), registered as **`ensemble-regime-v1-0001`**.
Trained on the real 8-symbol minute archive (`2021-06-24 → 2026-06-23`). **Combined OOS AUC
0.520** (LightGBM 0.529 / XGBoost 0.527 / logistic 0.488). This number is the headline of the
entire program (see §4): three independent model families, given the same point-in-time
bar-data features, all converge a hair above coin-flip.

**Gate 2 — the kill-gate, on the original 15-minute intraday MIS design.** MLflow experiment
`p2.9-killgate` (id 4), run **`cdf5dd8ff72c4555bde22050436eb042`** (`verdict=KILL`). **VERDICT:
KILL — 6 of 7 criteria failed.** Net CPCV median path-Sharpe **−0.977** annualised (all 5 paths
negative, worst −1.288); profit factor 0.826. The gross edge was real but small; the full
Indian MIS cost (~0.17–0.21% round-trip) flipped it negative. This is the correct, expected
outcome — and the candidate was routed into a disciplined iteration loop rather than abandoned.

**Phase 2R — the iteration loop.** A pre-committed budget ([`iteration_log/budget.md`](iteration_log/budget.md),
P2R.4): a **6-cycle cap**, a **50-trial cap**, **STOP if the best smoke path-Sharpe is < +0.3
after cycle 4**, **PIVOT frequency if < +0.5**, tighten-only. The bands were written down before
any result was known.

| Cycle | Hypothesis | Outcome | Record |
|---|---|---|---|
| **1** | Where is the edge dying — model, label, or cost? | **KILL → continue.** Binding constraint ranked: feature signal (primary) + label calibration, *not* model capacity. Net CPCV median **−0.977**; costs flip the gross edge negative. | `cycle-1_diagnostic.md`, `cycle-1_verdict.md` |
| **2** | Are the labels broken (mislabeled / degenerate)? | **Refuted — labels SOUND.** Vertical-barrier hits only 16.4%; positive rate stable ~0.45. Labeling closed. 0 trials. | `cycle-2_finding.md` |
| **3a** | Do finer-grid OHLCV features (5/1-min) add signal? | **No.** Gross/obs +0.012 / +0.015 vs the +0.042 baseline — finer bars add nothing. | `cycle-3a_finding.md` |
| **3b** | Does 5-level depth / microstructure add signal? | **Deferred → pivot.** Historical depth data is inaccessible at retail budget; the microstructure family cannot be populated. | `cycle-3b_decision.md` |
| **4** | Does a coarser frequency (60-min) cut cost drag enough? | **No lift.** Gross flat (+0.047); net **−0.90** annualised. Best smoke path-Sharpe far below +0.3 → **STOP criterion engaged.** | `cycle-4_finding.md`, `closeout.md` |

Phase 2R **STOPPED at cycle 4** (tag `research-phase-stop-cycle-4`): no edge survived costs at
the original configuration (intraday cash equity, 8 names, bar data, retail costs). A disciplined,
budget-honoring stop.

**Cycle 5 — operator-directed re-open: a different strategy scope.** An uploaded prior project
(an RL ensemble claiming ~60% returns) used a materially different configuration — **49-stock
universe, daily frequency, CNC (delivery, multi-day) holds**. Cycle 5 ran *that* configuration
through this project's honest apparatus, in escalating fidelity. The daily/CNC cost regime
(costs paid once per multi-day hold, not per intraday bar) produced the program's **first positive
smoke**:

- **Diagnostic** (MLflow `p2r-cycle5`, 6×2 CPCV / 80 rounds): net **+0.556** annualised
  (gross +1.079; gross/obs +0.068, net/obs +0.035), DSR 1.000 (N=5), **PBO 0.412**. Verdict:
  MARGINAL (above the +0.3 stop, below the +1.0 gate).
- **P2.8 robustness battery** (MLflow `p2r-cycle5-p28-battery` id 8, run
  **`08b4213b50f0481cb9682b6ac931618b`**, 8×2 CPCV / 300 rounds): net **+0.662** annualised,
  **6/6 robustness flags green** (no knife-edge, order-robust, edge persists under noise,
  cross-symbol generalizes, no synthetic-data leak, two engines reconcile to 2.4e-11).

This +0.662 — robust on the battery, on a real large-cap daily universe — is the number the
final assembly had to honestly reproduce. It did not (see §3, §4). The provenance of +0.662 was
audited and confirmed clean of contamination (no GAN data, no prior-project CSV, no foreign
dependency); it was a *configuration* replication on a **partly off-gated-path** harness
(yfinance data, standalone indicators, an inline daily labeler) at understated cost and trial
count. Bringing it fully onto the gated path is exactly what deflated it.

---

## 3. The headline result

The complete gated pipeline (MLflow experiment `p2r-cycle5-complete-pipeline`) was run at full
fidelity: this project's own **Kite → hygiene → Parquet** data, the **P1.7 harness** features,
**CUSUM + gated CNC triple-barrier** labels, the **MetaLabeler** bet/no-bet second stage,
**cross-sectional** rank + sector-neutral z-score, **frac-diff** of price-level columns, **honest
CNC cost 0.22%**, and an **honest cumulative trial count N = 23**.

**Final run — 56 survivorship-aware names** (run **`7397d1cee4c944acb18ac01d36b7e6df`**), with a
yfinance control arm, two strategies each:

| Strategy | validated (Kite) | yfinance | negative paths | DSR (N=23) |
|---|---|---|---|---|
| **DIRECT** (primary ensemble, `position = 2p−1`) | **−0.156** ann (obs −0.0098) | −0.196 ann | 100% | 0.000 |
| **META** (meta-label + cross-sectional) | **+0.148** ann (obs +0.0093) | +0.154 ann | **0%** (all 5 paths +) | **0.967** |

META path-Sharpes (per-path): +0.0109, +0.0070, +0.0093, +0.0123, +0.0069. Profit factor 1.047;
t-stat 3.71 on the path-concatenated sample (n = 158,865 = φ=5 paths × ~31.8k events).

An earlier **8-name** run (`dcd93454c75e462299030a6cfc65905b`) had DIRECT −0.222 / META −0.285 —
both negative; the universe was too small for the cross-sectional features to have any power.

### Per-criterion kill-gate read (final META, the strongest candidate)

| # | Criterion | Threshold | Value | Verdict |
|---|---|---|---|---|
| 1 | CPCV median path-Sharpe (net, ann) | ≥ 1.0 | **+0.148** | ❌ **FAIL** (≈7× short) |
| 2 | Deflated Sharpe Ratio | ≥ 0.95 | **0.967** † | ✅ pass (caveated) |
| 3 | Probability of Backtest Overfitting | ≤ 0.2 | not re-run on this config; **0.412 at the +0.556 diagnostic** | ❌ (last measured) |
| 4 | Fraction negative paths / worst path | ≤ 0.05 / ≥ −0.5 | **0.000** / **+0.0069** | ✅ pass |
| 5 | Profit factor / trade concentration | ≥ 1.2 / ≤ 0.5 | **1.047** / n/c | ❌ **FAIL** |
| 6 | Survives robustness battery | yes | green on the +0.662 config (run `08b4213b…`); not re-run on the honest config | — |
| 7 | Every regime mean net return ≥ 0 | yes | not computed on this config | — |

† **DSR honesty caveat.** The 0.967 is on the **path-concatenated** basis — the same convention
under which the +0.662 battery reported "DSR 1.000," so it is apples-to-apples. But the five CPCV
paths are overlapping reconstructions of the same ~31.8k events, so concatenating them inflates
the effective sample ≈ 5× and the t-stat ≈ √5. On **de-duplicated events** the t-stat is ≈ **1.66**
(one-sided p ≈ 0.05) — *marginal*, and the de-duplicated DSR would not clear 0.95. The DSR "pass"
is convention-dependent and optimistic; it does **not** change the verdict, because **criterion 1
fails decisively regardless.**

**Bottom line:** the META edge is *statistically detectable* (all paths positive, DSR-passing at
honest N, reproduced across two data sources) but *economically negligible* (Sharpe +0.148,
profit factor 1.047). It fails the kill-gate's economic criteria — criterion 1 by ~7×, criterion
5 outright. **The kill-gate is not passed.**

---

## 4. Why the kill-gate was never passed — the factors, quantified

This is the core of the document.

### 4.1 The +0.662 smoke was ≈ 4.5× inflated; the honest number is +0.148

The cleanest decomposition is the **DIRECT** strategy, which is the honest-input version of the
*same* `2p−1` recipe that produced +0.662:

> **+0.662** (49-name, yfinance, **0.14%** cost, **N=5**, inline off-gated labeler, selected config)
> **→ −0.156** (56-name, validated Kite, **0.22%** cost, **N=23**, gated CNC labeler)

Under honest inputs the bare directional strategy does not merely shrink — it goes **net
negative**. The entire +0.662 was inflation. The **+0.148** the complete pipeline recovers is
**not** the original edge surviving; it is what the **cross-sectional + meta-labeling components
add on top** of a net-negative base (see §5).

The measured causes of the deflation (aggregate measured; not individually ablated):

| Cause | Correction | Universe-independent? |
|---|---|---|
| **(a) Understated transaction cost** | 0.14% → honest CNC **0.22%** round-trip (0.10% STT on *both* legs + 0.015% stamp + exchange/SEBI/GST). The 0.14% was a hard-coded script constant; the gated cost model is MIS-only and could not even price delivery. | **Yes** |
| **(b) Under-deflation of trial count** | hard-coded **N=5** → honest cumulative **N=23** (live MLflow count: `p2.9-killgate`:15 + `p2r-cycle3a`:3 + `p2r-cycle4`:2 + `p2r-cycle5`:1 + `p2r-cycle5-p28-battery`:1 + `p2r-cycle5-complete-pipeline`:1). | **Yes** |
| **(c) Off-gated-path labeler** | the +0.662 used a Cycle-5 *inline* daily labeler (symmetric barriers, every-bar events); the gated path uses CUSUM event sampling + the project's asymmetric (2.0/1.5) triple-barrier — stricter, audited. | Interacts with universe |
| **(d) Selection effects** | the +0.662 battery baseline was a chosen/tuned configuration; the honest pipeline does not cherry-pick, and the honest-N DSR charges for the search. | Interacts with universe |

Causes **(a) and (b) are universe-independent** — they pull the number down by the same amount
regardless of how many names are traded. **(c) and (d) interact with universe size.** What the
larger 56-name universe *adds back* is cross-sectional power and ~70× the observations (~31.8k
vs ~2.6k), which the meta-labeled strategy converts into the residual +0.148.

### 4.2 The binding constraint, stated plainly

**Weak directional signal in bar-data features at retail-accessible frequencies, eaten by
realistic costs at retail scale.**

The evidence is upstream of the model. The P2A.6 artifact (run `e24c0cd6…`) shows **three
independent model families converging at OOS AUC ≈ 0.52** — LightGBM 0.529, XGBoost 0.527,
logistic 0.488, combined **0.520**. When three different learners, given the same point-in-time
features, all land a hair above coin-flip, the ceiling is set by the **information content of the
data**, not the algorithm. Cycle 1 ranked this correctly (binding constraint = feature signal +
cost, not model capacity); Cycle 3a confirmed finer bars add nothing (+0.012/+0.015 vs +0.042);
Cycle 3b confirmed the one feature family that might carry more signal (depth/microstructure) is
inaccessible at retail budget. The gross edge that exists (~+0.04–0.07 per observation) is
**real but smaller than the realistic round-trip cost** at every frequency tested:
−0.977 (15-min MIS), −0.90 (60-min), and at daily/CNC the bare directional edge is −0.156. Only
the cross-sectional + meta-labeling stack, at full universe scale, claws back a +0.148 that is
itself below the bar.

The constraint is structural and external to the codebase. No amount of model tuning moves it;
that is precisely what the kill-gate and the binding-constraint diagnostic were built to detect,
and they detected it.

---

## 5. What we ruled out (clean negatives)

So they are never re-litigated:

- **The data source was not the problem.** validated Kite data ≈ yfinance, within noise, at both
  scales: DIRECT data-source delta = **−0.016** (8 names) and **+0.040** (56 names); META delta
  **−0.006** (56 names). Moving onto the project's own gated data path did not drop the result —
  the +0.662 was **never a yfinance hygiene or survivorship artifact**.
- **Survivorship was not the problem.** The survivorship-aware universe was built from the
  point-in-time Nifty-50 union over 2021–2026. Of the names that left the index, all were
  fetchable except three (HDFC Ltd, Tata Motors, LTIMindtree) — and those three are
  **mergers / demergers / restructurings, not collapses** (empirically confirmed: Kite serves
  removed-but-listed names like BPCL/SHREECEM with full history; only corporate-action-restructured
  symbols are gone). No concealed tail loss is excluded; the correction is materially complete.
- **The labels were sound.** Cycle 2's touch-distribution check refuted the mislabeling
  hypothesis: vertical-barrier hits only 16.4%, stable ~0.45 positive rate.
- **The model and its components genuinely worked.** Three families learn the (weak) signal
  consistently; the regime gate and meta-labeling do what they are designed to do. The
  cross-sectional + meta-labeling stack recovered **real** signal at scale: META went from
  **−0.285** (8 names) to **+0.148** (56 names) — the cross-sectional features gaining power as
  the universe widened, the meta-filter trimming low-conviction trades to survive cost. **The
  architecture was sound; the edge was just too small.**

---

## 6. The weak points and constraints we hit

Stated plainly:

- **Historical 5-level depth data is inaccessible at retail budget** (Cycle 3b). This closed off
  the microstructure feature family — plausibly the richest remaining source of intraday signal —
  before it could be tested. A genuine data-access constraint, not a modeling choice.
- **Capital scale makes even a real small edge negligible.** At a ₹40k–₹1 lakh account, a +0.15
  Sharpe produces trivial absolute income and cannot diversify across enough names to realize the
  cross-sectional edge cleanly. The edge that *exists* is too small to matter at the scale this
  program targets.
- **Daily/CNC required architecture the original design lacked.** The gated labelers (P2.3/P2.5)
  were MIS-only and produced *zero* labels on daily bars (each daily bar is its own session). A
  **CNC multi-day hold mode** had to be added to express the strategy on the gated path (done,
  committed, MIS preserved byte-for-byte). The original architecture was built for a frequency
  where the edge does not survive costs.
- **The DSR path-concatenation convention inflates significance.** The reported 0.967 rests on a
  5×-overlapping sample; the de-duplicated t-stat is ~1.66. We report both and let the honest
  (marginal) reading stand.
- **The execution layer remains MIS-only.** The P2.1 event-driven backtester, the P2.8
  reconciliation engines, and the cost model all hard-assume intraday square-off. A faithful
  end-to-end daily/CNC product would require CNC modes in all three (the held "Stage 2"
  workstream). **Stage 2 was correctly not undertaken** — the smoke already showed the edge
  untradeable, and realistic execution (slippage, impact, the full cost model) can only *reduce*
  a +0.148 Sharpe, never lift it toward +1.0.

---

## 7. The verdict, and why it is a successful outcome

**The project closes at the kill-gate, per the pre-committed budget.** P2R.4 fixed, in writing
and before any result was known, that a best smoke path-Sharpe **below +0.3** is a STOP. The
honest final number is **+0.148**. It is below the band. The program **closes** — not because the
result disappointed, but because the rule said so and the rule was set before the result existed.

This is a **successful Inviolable-Rule-7 (intellectual honesty) outcome.** The apparatus took an
external **"60% return / +0.662 Sharpe"** claim and walked it, in good faith and at full fidelity,
down to its true value — **≈ +0.148 Sharpe: real, statistically detectable, and too small to
trade at retail** — measuring and naming every inflation source, clearing the data-quality worry
definitively, and crediting the one genuinely-positive component (cross-sectional + meta-labeling)
for exactly what it contributes and no more. It did this **on a laptop, for $0, before a single
rupee of capital was risked.**

The finding — **"no tradeable edge at retail scale in this strategy family (bar-data features,
retail-accessible frequencies, retail costs and capital)"** — is a real, valuable, honestly-earned
answer. The negative is as informative as a positive would have been, and far cheaper than
learning it with live capital. The apparatus that produced it is sound, complete, and reusable;
the kill-gate did its job; the budget held; nothing fooled itself.

**Status: research arc closed. No live trading. No capital at risk.**

---

## 8. Part VI addendum — the mechanical-edge program (2026-06-27)

After this close-out, a **second research arc** was opened (blueprint Part VI): the thesis that
retail alpha comes from **non-directional mechanical edges** (structural flows, statistical
relationships, event mechanics), judged by the **same** seven-point kill-gate. The validation
engine was reused, not rebuilt.

- **Harness (GATE 6 ☑).** A `StrategySpec` layer (`research/mechanisms/`) plugs any mechanism into
  the unchanged CPCV + kill-gate; the DSR trial count is pulled **automatically** from the live
  cumulative MLflow run count (the structural fix for §4.1 cause (b) — N can never be hard-coded
  again); each mechanism is **pre-registered** in git before its first test run.
- **Mechanism slate (GATE 7 ⊘ honest stop).** Three mechanisms, judged in sequence under a
  pre-committed budget. **Cointegration pairs** — run on the real survivorship-free panel — is the
  **strongest edge this entire project has found: +0.425 net annualised Sharpe**, market-neutral,
  the first to clear the +0.3 continue band. But it is **still real-but-too-weak**: below the +1.0
  kill-gate bar by ~2.4× and **not statistically significant** (de-dup t = 1.20, p ≈ 0.12 on 95
  months) — the *same structural finding* as the original program. **Index-rebalance** and **PEAD**
  are **data-gated** on external feeds the repo lacks (a reconstitution change-log; an
  earnings-surprise feed) — their machinery is built and tested. No mechanism cleared → honest stop.
- **Phase 8 (CNC execution) correctly not built** (gated on a research winner; none exists).
- **Phase 9 proprietary-data recorders built** (live 5-level depth; earnings reaction/drift) — the
  forward-accrual answer to the data gates, compounding over months.

The mechanical-edge arc confirms and extends the original finding: across **directional prediction
and three non-directional mechanics**, no edge clears the kill-gate at retail scale — the strongest
(pairs, +0.42) is real but economically negligible and statistically marginal. The apparatus,
budget discipline, and intellectual honesty held throughout. Authoritative Part-VI record:
[`mechanisms/gate7_closeout.md`](mechanisms/gate7_closeout.md). **Still no live trading; $0 risked.**

---

### Appendix — MLflow run registry (for reproduction)

| What | Experiment | Run-ID | Headline |
|---|---|---|---|
| Final real-data artifact (P2A.6) | `p2a6-final-run` (id 2) | `e24c0cd6354f40e7bae024ce9f6b16c1` | OOS AUC 0.520 (lgbm .529 / xgb .527 / logit .488) |
| Gate-2 kill-gate (15-min MIS) | `p2.9-killgate` (id 4) | `cdf5dd8ff72c4555bde22050436eb042` | KILL, 6/7 failed, net −0.977 |
| Cycle-5 diagnostic (daily/CNC smoke) | `p2r-cycle5` | — | net +0.556, DSR 1.000 (N=5), PBO 0.412 |
| Cycle-5 P2.8 battery | `p2r-cycle5-p28-battery` (id 8) | `08b4213b50f0481cb9682b6ac931618b` | net +0.662, 6/6 robustness green |
| Complete pipeline, 8 names | `p2r-cycle5-complete-pipeline` | `dcd93454c75e462299030a6cfc65905b` | DIRECT −0.222 / META −0.285 |
| Complete pipeline, 56 names | `p2r-cycle5-complete-pipeline` | `7397d1cee4c944acb18ac01d36b7e6df` | DIRECT −0.156 / **META +0.148** (DSR 0.967, PF 1.047) |

Cost basis throughout the daily/CNC honest runs: **0.22% round-trip** (CNC delivery). Honest
cumulative trial count: **N = 23**. Universe: **56** survivorship-aware Nifty-50 names,
`2021-06-24 → 2026-06-23`. CI at close: **1077 passed**, mypy strict clean, leakage suite green.
