# Phase 2R · Cycle 1 — Diagnostic: where is the binding constraint?

**Subtask:** P2R.1 (Phase 2R — Research Iteration Loop). See `MASTER_BLUEPRINT_Claude_Build_Handoff.md` Part IV (Phase 2R) and Part I Inviolable Rules 1 & 7.
**Candidate under diagnosis:** the P2A.6 registry artifact `ensemble-regime-v1-0001` — cross-family ensemble (LightGBM + XGBoost + logistic) + GMM regime gate, pooled 8-symbol Nifty-heavyweight universe, 15-minute clock, `2021-06-24 → 2026-06-23`.
**Verdict being diagnosed:** expected **KILL**. The formal `cycle-1_verdict.md` is emitted by P2.9 once built — see *Sequence forward*.
**Status:** ⏳ awaiting operator review before any code change (P2R.1 done-when).

---

## Evidence base (what the numbers say)

| metric | value | source | reading |
|---|---|---|---|
| OOS combined AUC | 0.520 | P2A.6 | a hair above chance (0.500) |
| per-member OOS AUC | lgbm 0.529 / xgb 0.527 / **logistic 0.488** | P2A.6 | the linear member is *anti*-predictive |
| calibrated logloss | 0.687 | P2A.6 | ≈ ln 2 = 0.693 — barely better than a coin flip |
| calibrated Brier | 0.247 | P2A.6 | ≈ 0.25, the p = 0.5 baseline |
| pooled events / positive rate | 14,150 / 0.450 | P2A.6 | label near-balanced, ~coin-flip |
| regime-gate multipliers | (1, 1, 1) | P2A.6 | the gate found no regime worth switching off |
| CPCV per-obs path-Sharpe (P2.8 smoke) | ≈ 0.040 (variants 0.040–0.049) | P2.8 | slightly positive, far below the kill-gate's annualised > 1.0 |
| two-engine reconciliation | max money diff **0.0** | P2.8 | the backtest accounting is sound — *not* a source of error |

**Headline:** three diverse model families all sitting on AUC ≈ 0.52 with logloss ≈ ln 2 is the signature of a **feature matrix that carries almost no information about the label** — not a model that is under-fit. This is a *feature/label* problem, not a model problem, which is what the ranking below reflects. The "tune the model harder" reflex is the wrong move and Phase 2R exists to prevent it.

---

## Ranked assessment (the fixed list, P2R.1)

### (a) Feature signal strength — **PRIMARY binding constraint**
Two specific, citable gaps:
- **Microstructure/depth family is absent.** Deep Dive #1 **§2.2** names **Order Flow Imbalance from 5-level depth as "empirically the top feature"** for intraday equity. The current matrix is bars-only — OFI, depth imbalance, and signed flow (P1.7) can't be computed because the depth book isn't backfilled (the P2A.6 follow-up note flags exactly this). Part II's locked decision is *"minute bars **+ 5-level depth**"*; the depth half is missing, so the single most informative family is too.
- **"Features from finer data" deferred.** Part II locked decision: *"15-minute bars (**features from finer data**)."* Features are currently computed on **resampled** 15-min bars, so signal living at sub-15-min resolution (DD#1 §2.2 microstructure/realized-vol estimators assume finer inputs) is discarded before the model sees it.
- **Evidence it is binding:** AUC 0.52, logloss ≈ ln 2, and the *linear* member at 0.488 (no linear signal at all). Boosting cannot extract information that isn't in the matrix.
- **Citation:** DD#1 §2.2 (Feature families); Part II locked decisions (minute bars + 5-level depth; features from finer data).

### (b) Triple-barrier / CUSUM calibration vs realized intraday volatility — **likely contributing; cheapest to test FIRST**
- **Evidence:** positive rate 0.450 (suspiciously near 0.5); the barrier floor sits near the ~0.15% cost hurdle while the 15-min target is only 0.3–1% (2–6× the floor).
- **Why it matters:** if most events resolve on the **vertical** barrier rather than a directional touch, the label degenerates to *"did the session drift up,"* ≈ a coin flip — which would **also** explain AUC 0.52 independently of features. It is **free to falsify**: dump the upper/lower/vertical touch fractions. This is the cheapest thing to learn and may reframe (a).
- **Citation:** DD#2 §3.2 (The Triple-Barrier Method), §3.3 (Event-based/CUSUM sampling); Part II cost arithmetic.

### (c) Universe size & survivorship coverage — **multiplier, not root cause**
- **Evidence:** 8 names (3 financials); cross-symbol leave-one-out median held-out Sharpe ≈ 0.044 (weak generalization).
- **Why secondary:** 8 names make the sector-neutral cross-sectional ranks (DD#1 §2.3) statistically thin and starve the event count / DSR denominator. Expanding to a survivorship-correct Nifty-50/100 (DD#1 §1.3) **amplifies** an edge and improves cross-sectional features — but it does **not create** signal. Worthwhile only after (a)/(b) clear chance; universe-expand-on-a-non-edge is wasted backfill effort.
- **Citation:** DD#1 §2.3 (Normalization & encoding — cross-sectional ranks), §1.3 (data hygiene — survivorship-correct constituents).

### (d) Decision frequency — **structural backdrop, not a cycle-2/3 lever**
- **Evidence:** round-trip cost ~0.12–0.20% against 0.3–1% 15-min targets → a thin gross-to-net ratio *by construction*; a ~0.04 gross per-obs Sharpe is plausibly **negative net**.
- **Verdict:** not something to "fix" mid-loop — it is the honest reason the kill-gate exists. If cycles 2–3 don't move the needle, **a frequency pivot is the P2R.4 conversation**, not another feature tweak.
- **Citation:** Part II locked decisions (the 15-min rationale) + realistic-expectations frame; DD#2 §4b.6 (the realistic backtester — *"where most edges die"*).

### (e) Sample weighting / labeling discipline — **not the binding constraint**
- **Evidence:** P2.4 average-uniqueness × time-decay weighting is in place and tested; no sign of an IID-violation artifact *inflating* the metrics (if anything the OOS numbers are honestly low).
- **Verdict:** discipline is sound. A minor refinement candidate (e.g., return-attribution weighting) but it will not turn 0.52 AUC into an edge. *Note:* the P2.8 battery currently evaluates **unweighted** (tracked follow-up) — re-introducing weights is a low-priority refinement, not a binding fix.
- **Citation:** DD#2 §3.5 (Sample weighting — labels are NOT IID), §3.3.

### (f) Model capacity — **explicitly NOT the bottleneck; do not chase**
- **Evidence:** the config already follows the prescription — shallow/regularized (depth 4, min_child 50, λ₂ 1.0); three families agree near chance; no reported overfit gap; the regime gate left multipliers (1, 1, 1) because there is no edge to differentiate.
- **Verdict:** adding capacity only inflates the trial count the DSR will punish, with no signal to gain. This is the reflex Phase 2R exists to prevent.
- **Citation:** DD#2 §4.2 (*"shallow trees, strong regularization … a small robust edge, not a perfect in-sample fit"*), §4.1 (build order).

### (g) Something else
- **Leakage check (forward-looking).** If a *future* cycle suddenly passes "easily," inspect for leakage before trusting it (Phase 2R gating note: a first-attempt pass is statistically unlikely). Not applicable to *this* candidate — it fails honestly.
- **Structural reality (Inviolable Rule 7).** >90% of retail intraday loses; a realistic outcome of this whole exercise includes *"no tradeable edge at this configuration."* That is a valid, non-failure result — the research apparatus is reusable and no money was lost.

---

## Recommendation for the next cycle(s)

Top binding constraints, **cheapest-first** (the adopted iteration order — one input family per cycle, Phase 2R discipline):

1. **Cycle 2 — Label sanity (tests (b) first; free, local, minutes).** Dump the triple-barrier touch distribution: what fraction of events resolve on upper / lower / vertical barriers? If vertical dominates, the label has degenerated to *"did the session drift up?"* and the fix is labeling parameters (CUSUM threshold, barrier multipliers, vertical-barrier shortening), **not** features. *May reframe everything below.*
2. **Cycle 3 — Microstructure features (the (a) fix; highest expected value).** Backfill the 5-level depth book; wire OFI / depth-imbalance / signed-flow per DD#1 §2.2, and features-from-finer-data per Part II's locked decision (compute on minute/sub-minute inputs, aggregate into 15-min rows). Re-run.
3. **Cycle 4 — Universe expansion ((c); conditional).** Only if cycles 2–3 produce a smoke path-Sharpe **meaningfully above zero**. Otherwise it is wasted backfill effort.

Every variant from Cycle 2 onward — **including quickly-discarded ones** — logs to persistent MLflow, so the Deflated Sharpe trial count in P2.9 stays honest. No silent retries.

---

## Sequence forward (operator-set)

1. **This diagnostic recorded** (here) → operator review (P2R.1 done-when).
2. **P2.9 built first** — the kill-gate report machinery, *before any feature work*, so the next cycle's verdict is standardized.
3. **P2.9 emits a KILL verdict on the current candidate** → formal `docs/iteration_log/cycle-1_verdict.md`. This doubles as P2.9's acceptance test: it must correctly emit "kill" on an input we already know fails.
4. **Then Cycle 2** (label sanity) begins.
5. The iteration budget (**P2R.4**) is set by the operator before Cycle 2 begins.
