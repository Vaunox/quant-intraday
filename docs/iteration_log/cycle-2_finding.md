# Phase 2R · Cycle 2 — Label sanity check (finding)

**Subtask:** P2R.2 cycle 2, diagnosis step (label sanity — *diagnosis before fix*). See the
[cycle-1 diagnostic](cycle-1_diagnostic.md) (binding-constraint candidate **(b)**, triple-barrier
calibration) and the [iteration budget](budget.md).
**Input family under test:** labeling (triple-barrier / CUSUM calibration).
**Verdict:** **label is sound — no parameter change.** Iteration axis (b) is **closed**.
**Trial-budget cost:** **0 of 50** MLflow trials (no model trained, no Sharpe computed — free,
local diagnosis).

The cycle-1 diagnostic flagged the cheapest hypothesis: that the triple-barrier label might have
degenerated toward *"did the session drift up?"* — which would show up as the **vertical** (timeout)
barrier dominating the touch distribution. This is the free test of that hypothesis.

---

## Method

Production labeling, unchanged (`cusum=0.01`, barriers `2.0σ↑ / 1.5σ↓` floored at `0.002`, vertical
= session end), over the real 8-symbol minute archive, `2021-06-24 → 2026-06-23`. For every CUSUM
event, recorded which barrier was touched first (`upper` / `lower` / `vertical`) and the label sign.
**14,172 events.** (Reproduces P2A.6's positive rate 0.450 exactly — faithful reconstruction.)

## Touch distribution

| | upper | lower | **vertical** | positive-rate |
|---|---|---|---|---|
| **Overall (n=14,172)** | 0.352 | 0.484 | **0.164** | 0.450 |

Per-symbol: vertical fraction 0.149–0.191; positive-rate 0.423–0.469 (**std 0.013**).

Internal consistency (labels are well-formed): upper-touch → `P(label>0)=1.000`; lower-touch →
`≈0`; vertical-touch → `0.595`.

## Positive-rate stability by year (pooled)

| year | n | positive-rate | vertical frac |
|---|---|---|---|
| 2021 | 1,599 | 0.436 | 0.133 |
| 2022 | 3,415 | 0.446 | 0.167 |
| 2023 | 2,337 | 0.455 | 0.148 |
| 2024 | 2,947 | 0.460 | 0.158 |
| 2025 | 2,320 | 0.452 | 0.172 |
| 2026* | 1,554 | 0.445 | 0.210 |

*2026 partial (through June). Spread 0.436–0.460.

## Verdict — label sound; axis (b) closed

1. **Vertical does NOT dominate (16.4%).** 83.6% of events resolve on a *directional* barrier — the
   feared timeout-collapse is not happening. The cycle-1 hypothesis (b) is **refuted**.
2. **Positive rate is balanced (~0.45) and stable** across symbols (std 0.013) and years
   (0.436–0.460). No class collapse, no temporal drift, no per-symbol pathology.
3. **The lower > upper asymmetry (0.484 vs 0.352) is by construction** (the 1.5σ↓ barrier is closer
   than the 2.0σ↑), not a degeneracy — see the deferred A/B in [deferred.md](deferred.md).

**No labeling-parameter change is warranted.** Labeling is removed as an active iteration axis. The
binding constraint is the diagnostic's **primary** candidate — **feature signal (a)**: the model
cannot predict *which* directional barrier is hit (AUC 0.52) even though the barriers are clean.

## Routing

Proceed to **Cycle 3 — feature signal**, split by cost (operator-authorized split):
- **Cycle 3a** — features from finer data (existing minute archive; cheapest, no backfill).
- **Cycle 3b** — microstructure from 5-level depth (requires forward depth capture or a vendor —
  **no historical depth exists** in the storage layer; held pending the operator's go on the split).

Run 3a first. Budget after Cycle 2: **0 / 50 trials used**, 1 active cycle consumed.
