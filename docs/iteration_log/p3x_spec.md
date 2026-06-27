# Phase 3X — Cross-Sectional Multi-Factor Equity Strategy (Nifty 500, Monthly)

**Build spec / handoff document.** Re-points the existing quant-intraday apparatus at a new
alpha source: a monthly-rebalanced, cross-sectional, multi-factor equity strategy on the
Nifty 500, judged by a pre-committed, **benchmark-relative** kill-gate. Not a rewrite — it
reuses the validation engine, cost model, data layer, and (once built) portfolio construction,
and replaces only the alpha source, the labeling layer, and the rebalance frequency.

Pre-committed contract: [`config/factor_default.yaml`](../../config/factor_default.yaml).
Parallel data track + the validity-critical survivorship decision:
[`p3x_data_sourcing.md`](p3x_data_sourcing.md). Prior arc close-out: [`../FINDINGS.md`](../FINDINGS.md).

---

## 0. Why this exists

[FINDINGS](../FINDINGS.md) established the Phase-2R binding constraint: weak directional signal
in bar-data features at retail frequencies, eaten by realistic costs; three model families
converged at OOS AUC ≈ 0.52. That ceiling is set by the information content of intraday bar data
on liquid large-caps, not the algorithm — so no rewrite of the intraday directional stack moves
it. This spec attacks the constraint from the other two Grinold–Kahn axes (**IR = IC × √Breadth**):

- **Frequency → monthly.** Turnover collapses, so the CNC cost wall (0.22% round-trip) stops
  dominating: a 1-month hold against ~0.22% cost is a ~5–15% drag on the move, vs the 15–50%
  drag that killed the 15-minute design.
- **Alpha source → cross-sectional factors.** Momentum (12-1) and the low-volatility anomaly
  are the most replicated, cost-robust, price-based edges in Indian equities — different
  information from directional bar-data ML, buildable from data already held.
- **Breadth → wide + decorrelated.** Nifty 500 instead of 56 names; sector-neutral scoring so
  bets aren't an accidental single-sector tilt; factor diversification for signal independence.

**Honest framing.** Long-only, benchmark-relative. The success metric is the **active
information ratio vs Nifty 500 TRI**, not absolute Sharpe (a long-only book's absolute Sharpe is
mostly market beta; skill lives in the active return). Realistic factor IRs land 0.5–0.9; the
pre-committed bar is **≥ 0.75**. "Beat 1.0 absolute Sharpe by skill alone" was always partly a
category error for a long-only design.

---

## 1. Reused / modified / new

| Component | Verdict | Note |
|---|---|---|
| Data layer (Kite → hygiene → Parquet/Arctic) | **Reuse** | Need Nifty-500 point-in-time membership in `ConstituentRegistry`. |
| `ConstituentRegistry` (survivorship-aware) | **Modify** | Extend Nifty-50-union → Nifty-500-union, point-in-time. |
| Feature library (P1.6/P1.7) | **Reuse + extend** | Cross-sectional rank + sector-neutral z-score exist; add factor primitives (P3X.2). |
| Labeling (CUSUM + triple-barrier) | **Replace** | Cross-sectional fixed-horizon forward-return labels (P3X.3). |
| Model stack (LGBM/XGB/logistic) | **Reuse, optional** | Baseline is a transparent z-score composite; ML is the trial-charged enhancement. |
| GMM regime gate, meta-labeler | **Defer** | Not in the first cut. |
| **Portfolio construction** (inverse-vol → HRP, sector caps, no-trade band) | **⚠ BUILD (not reuse)** | The Capital Layer (`src/quant/capital/`) is empty scaffolding; Phase 3 (P3.1/P3.3/P3.4) is unbuilt. Config knobs exist; implementations do not. This is the heaviest item. |
| Cost model (`IndianCostModel`) | **Modify** | Add a CNC delivery mode (0.10% STT both legs + stamp + charges). |
| Validation engine (CPCV, DSR, PBO, robustness) | **Reuse** | Purge/embargo must respect the 21-session label horizon (P3X.5). |
| Backtester (event-driven, next-bar-open) | **Modify** | Add monthly-rebalance / CNC hold mode; remove square-off. |
| Kill-gate | **Rewrite** | Benchmark-relative criteria (§4), fixed before any run. |

> **Correction to the original handoff** (verified against the repo): portfolio construction was
> marked "Reuse"; it is in fact unbuilt (`capital/{combine,portfolio,risk,sizing}` are bare
> `__init__.py`, Phase 3 is ☐ todo). P3X.7 is therefore "build the Capital Layer," not a freebie.

---

## 2. Strategy definition (the contract)

- **Universe:** Nifty 500, point-in-time membership (includes names that later left the index).
- **Liquidity screen:** median 60-day traded value ≥ ₹X cr and ≥ 252 sessions of history at the
  rebalance date; failing names excluded as of that date (no look-ahead).
- **Rebalance:** monthly — decision on the last session of month *m* using only data available at
  close; entered at next session's open; held ~21 sessions. Quarterly as a config toggle.
- **Product:** CNC long-only, top-quintile by composite (top-decile variant). Benchmark =
  Nifty 500 TRI. Long-short via single-stock futures is a §6 extension, not first-cut.
- **Signal:** sector-neutral z-score composite of the P3X.2 factor set, combined per P3X.4.
- **Weighting:** inverse-vol within the selected quintile → HRP once the book is wide enough to
  validate HRP beats inverse-vol OOS. Sector cap ≤ 25%; per-name ≤ 5%; no-trade band (only adjust
  a name when target weight moves > τ, start τ = 25% relative).

---

## 3. Work breakdown (one subtask per session)

- **P3X.1 — Nifty-500 point-in-time universe.** Survivorship-correct membership + per-date
  liquidity screen + backfill OHLCV for all members incl. delisted. *Done when:*
  `registry.members(as_of=d)` correct for arbitrary historical *d*; delisted names present with
  history to exit; tested against ≥2 known reconstitutions. **⚠ Gated on the survivorship data
  decision — see [`p3x_data_sourcing.md`](p3x_data_sourcing.md).**
- **P3X.2 — Price-based factor library (Phase A).** `research/factors/`: momentum 12-1,
  short-term reversal, low-vol (+ beta variant), residual momentum, Amihud illiquidity — each a
  pure cross-sectional transform. *Done when:* forward-shift invariant under the P1.8 leakage
  suite; vectorized == incremental; unit-tested on a known panel.
- **P3X.3 — Cross-sectional forward-return labeling.** `research/labeling/cross_sectional.py`:
  21-session forward total return (regression target) + cross-sectional decile rank
  (classification target); `label_times` (t0 = rebalance, t1 = t0+21) feed purged splitters.
- **P3X.4 — Signal combination.** One `SignalCombiner` interface: (a) baseline = sector-neutral
  z-score equal-weight composite (zero free parameters — must clear the gate first); (b) ML
  ensemble enhancement (trial-charged, increments `TrialTracker`).
- **P3X.5 — Validation harness adaptation.** Purge/embargo ≥ 21 sessions; CPCV over time blocks;
  path-Sharpe/DSR/PBO on **active** (vs Nifty 500 TRI) return; honest cumulative N; walk-forward
  equity + turnover + factor-exposure attribution. Report de-duplicated t-stat (FINDINGS §3).
- **P3X.6 — CNC cost model + monthly backtester.** CNC mode (0.10% STT both legs + stamp +
  charges → ~0.22% round-trip); monthly-rebalance backtester (next-open, 21-session hold, no
  square-off, no-trade band before costing); reconcile two engines to < 1e-9.
- **P3X.7 — Portfolio construction + sizing (BUILD the Capital Layer).** Top-quintile → sector
  caps → inverse-vol (then HRP) → no-trade band → vol-target scalar.
- **P3X.8 — Pre-committed gate run.** Baseline (zero-parameter) composite through the full
  battery on honest CNC cost; verdict logged. Only if it clears do trials get spent on ML.

---

## 4. The kill-gate (benchmark-relative)

Fixed in [`config/factor_default.yaml`](../../config/factor_default.yaml) before P3X.8 (Rule 1).
Clear **all seven**; numbers tighten, never loosen.

| # | Criterion | Threshold |
|---|---|---|
| 1 | CPCV median active IR vs Nifty 500 TRI (net, annualised) | ≥ **0.75** |
| 2 | Deflated Sharpe Ratio on active return (honest N) | ≥ **0.95** |
| 3 | Probability of Backtest Overfitting | ≤ **0.2** |
| 4 | Fraction of negative active paths / worst active path-IR | ≤ **0.05** / ≥ **−0.3** |
| 5 | Net active return after CNC costs, every CPCV path | **> 0** |
| 6 | Survives robustness battery (param, MC shuffle, noise, leave-one-sector-out, synthetic) | yes |
| 7 | Max sector weight ≤ 25%; no single factor > 60% of active return | yes |

De-duplicated DSR t-stat reported alongside the path-concatenated one (FINDINGS §3 caveat).

---

## 5. Probability and decision discipline (pre-committed)

- ~40–55% the price-only baseline (momentum + low-vol + residual-mom, sector-neutral, monthly,
  long-only) clears IR ≥ 0.75 net — a real coin-flip-plus, not a lock (published index IRs 0.5–0.9).
- ~20–30% positive-but-sub-threshold (IR 0.4–0.75) → escalate to Phase B (value/quality, once a
  fundamentals feed is wired) — mirrors the Cycle-4→5 logic.
- ~20–30% it doesn't clear even with fundamentals → clean stop; the finding *"retail-accessible
  factor signals on Nifty 500 don't clear IR 0.75 net after honest costs"* is itself valuable.

**Pre-commit (before P3X.8):** 6-config cap on the baseline; STOP and escalate to Phase B if
baseline best active IR < 0.4; do **not** data-mine factor weights to hit the bar.

---

## 6. Documented extensions (not first-cut)

- **Long-short via single-stock futures** — shorting the bottom quintile removes market beta,
  raises effective breadth, makes absolute Sharpe skill-driven. Needs the ~180–200 liquid F&O
  names + a futures cost/roll model. Build only if the long-only book clears.
- **Factor timing (factor momentum)** — adds turnover and trials; later enhancement, not baseline.
- **Phase B fundamentals (value, quality)** — highest expected IC lift; gated entirely on a
  point-in-time fundamentals feed. Do not start without it.

---

## 7. Brief

Build a monthly-rebalanced, cross-sectional, long-only multi-factor equity strategy on the
point-in-time Nifty 500, reusing the validation engine and data layer and building the capital
layer. Replace triple-barrier labels with 21-session forward-return / decile-rank labels; build
price-only factors (momentum 12-1, short-term reversal, low-vol, residual momentum, Amihud);
combine as a sector-neutral equal-weight z-score composite first (zero free parameters), ML only
as a trial-charged enhancement; add a CNC cost mode + monthly backtester; judge the baseline
against the §4 benchmark-relative gate, thresholds fixed before the run. One P3X subtask per
session; respect the leakage suite and honest trial count; write the verdict to MLflow. No real
orders, no credentials held.
