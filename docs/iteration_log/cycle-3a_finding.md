# Phase 2R · Cycle 3a — Features from finer data (finding)

**Subtask:** P2R.2 cycle 3a (feature signal, the cheap half of binding constraint **(a)**). See the
[cycle-3 plan](cycle-3_plan.md), the [cycle-1 diagnostic](cycle-1_diagnostic.md), and the
[iteration budget](budget.md).
**Input change:** compute the existing feature families on a finer bar grid (5-min / 1-min), point-
in-time aligned to the 15-min decision rows (merged: `feat/iteration-cycle3a-features-finer`).
**Verdict:** **finer bars do NOT add signal — they slightly degrade it.** Hypothesis **refuted.**
**Trial-budget cost:** **2 new trials** (5-min, 1-min); the 15-min run is the baseline recipe.

The cycle-3 plan's 3a hypothesis: the model is signal-starved because resampling to 15-min *before*
featurising discards sub-15-min structure (Part II "features from finer data"). This is the cheap
test of that hypothesis — existing data (minute archive), no backfill, no new deps.

---

## Method

Reduced-knob smoke (`num_boost_round=80`, CPCV `6×2` → φ=5 paths, embargo 1%), real 8-symbol
universe `2021-06-24 → 2026-06-23`. For `feature_frequency_minutes ∈ {15 (baseline), 5, 1}`: build
the pooled dataset with features on that grid, evaluate the ensemble + regime gate under CPCV, and
record the gross and net (after a representative `0.00206` round-trip cost) median path-Sharpe.
Logged to MLflow experiment `p2r-cycle3a` (id 5).

## Results — CPCV median path-Sharpe

| features | n_obs | gross/obs | net/obs | gross annualised | net annualised | MLflow run |
|---|---|---|---|---|---|---|
| **15-min (baseline)** | 14,138 | **+0.0424** | −0.0177 | +2.257 | −0.943 | `56b042f4bc35` |
| 5-min | 14,158 | +0.0121 | −0.0358 | +0.641 | −1.903 | `3800017da068` |
| 1-min | 14,171 | +0.0151 | 0.000* | +0.802 | 0.000* | `91ecc56b3f30` |

*The 1-min net 0.000 is the regime gate switching fully off → flat, **not** a positive edge.

**Delta vs 15-min baseline:** 5-min `gross/obs −0.030`; 1-min `gross/obs −0.027`.

## Verdict — hypothesis refuted; 3b's case sharpened

1. **The baseline reproduces cycle-1 exactly** (gross/obs +0.042 ≈ P2.8's 0.04; net annualised
   −0.94 ≈ P2.9's −0.98) — the harness is validated, the comparison is apples-to-apples.
2. **Both finer frequencies score *lower* gross signal than 15-min.** Computing the *existing*
   price/vol/range/regime families on finer bars makes them **noisier** (the same window *counts*
   look back over a shorter calendar window), not more informative. The best smoke gross
   path-Sharpe stays **+0.042** — far below the budget's **+0.2** reference, nowhere near the +1.0
   kill-gate.
3. **This is informative, not just negative.** As the cycle-3 plan predicted: *"if 3a does not lift
   it, that argues 3b's depth features are more likely creating signal, not amplifying."* Finer
   *OHLCV* bars don't help ⇒ the missing signal is more likely **in the microstructure itself**
   (order-flow imbalance / depth — the diagnostic's "top feature"), which finer price bars
   structurally cannot provide. 3a was the cheap way to learn this, and it did.

## Routing

- **Labeling (b): closed** (cycle 2). **Finer OHLCV features (3a): closed** — no lift.
- The remaining live feature hypothesis is **3b — depth microstructure**, which is **data-gated**:
  no historical 5-level depth exists (see the [cycle-3 plan](cycle-3_plan.md) §1–2). The 3b go is an
  **operator decision** (forward depth capture vs a paid L2 vendor vs the budget's frequency pivot).
- **Budget status:** 2 new trials this cycle (cumulative distinct candidate configs still
  single-digit, well within 50); 3 cycles consumed (cycle-4 hard checkpoint not yet reached).
