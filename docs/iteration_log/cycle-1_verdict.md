# Phase 2R · Cycle 1 — Kill-gate verdict

**Subtask:** P2R.3 (Re-run P2.9 against the candidate) — emitted by the P2.9 machinery.
**Candidate:** `ensemble-regime-v1-0001` (the P2A.6 artifact), pooled 8-symbol universe, 15-min
clock, `2021-06-24 → 2026-06-23`, 14,150 events.
**Verdict:** **KILL** (6 of 7 criteria failed).
**Routing:** **CONTINUE** → back to Phase 2R, Cycle 2 (label sanity), per the
[cycle-1 diagnostic](cycle-1_diagnostic.md)'s cheapest-first order.

This run also serves as **P2.9's own acceptance test**: it confirms the kill-gate correctly emits
**KILL** on a candidate we already knew (from the diagnostic) would fail.

---

## The verdict

```
SEVEN-POINT KILL-GATE — net of full Indian costs + slippage, point-in-time
========================================================================
  candidate         : ensemble-regime-v1-0001
  data / feature    : 15min-8sym-20210624-20260623-1bba6975 / core-v1
  label version     : tb-cusum0.01-u2.0-d1.5-min0.002-vmax0
  observations      : 14150   honest trial count: 5
  annualisation     : 2831.9 periods/year
------------------------------------------------------------------------
  CPCV path-Sharpe distribution (annualised, NET of costs):
    paths=5  median=-0.977  mean=-1.006  std=0.221  worst=-1.288  fraction-negative=1.000
  Deflated Sharpe Ratio : 0.001
  PBO                   : 0.265
  profit factor         : 0.826   top-trade share: 0.017
  Walk-forward (full-cost, next-bar-open):
    net P&L=-98470.98  final equity=901529.02  max DD=10.85%  fills=2568
  robustness battery    : PASS
  regime mean net return: r0=-0.0000  r1=-0.0000  r2=-0.0002
------------------------------------------------------------------------
  [FAIL] (1) CPCV median path-Sharpe (annualised, after costs): -0.977 vs > 1.000
  [FAIL] (2) Deflated Sharpe Ratio (vs honest trial count):     0.001 vs >= 0.950
  [FAIL] (3) Probability of Backtest Overfitting:               0.265 vs <= 0.200
  [FAIL] (4) Narrow, positive CPCV path distribution:           neg-fraction 1.000; worst -1.288
  [FAIL] (5) P&L not concentrated in a few trades:              profit factor 0.826 (< 1.0)
  [PASS] (6) Survives the robustness battery
  [FAIL] (7) Edge stable across regimes:                        all 3 regimes loss-making net
------------------------------------------------------------------------
  VERDICT: KILL  (6 criteria failed)
```

## Reading the verdict

- **Costs are the killer, exactly as the diagnostic predicted.** The gross per-obs CPCV path-Sharpe
  was ~+0.04 (P2.8). Netting the representative ~0.17% round-trip cost per event flips the
  annualised median to **−0.977** — *every* one of the 5 CPCV paths is negative (criterion 4),
  the profit factor is **0.826** (< 1.0: it loses money net, criterion 5), and the full-cost
  walk-forward loses **−9.8%** (−₹98k on ₹10L) with a 10.85% drawdown. The edge-to-cost ratio,
  flagged as the structural backdrop in the diagnostic (d), is decisive here.
- **Criterion 6 (robustness) passed — and that is instructive, not contradictory.** The P2.8 battery
  measures the *relative* robustness of the **gross** signal: it is not a knife-edge, it degrades
  gracefully under noise, it generalises cross-symbol, it shows no spurious synthetic edge, and the
  two engines reconcile. The signal is *robustly* weak — consistently near-zero gross — which is
  precisely why it survives the battery yet dies on the cost-inclusive criteria (1, 2, 4, 5, 7).
  This is the seven-point gate working as designed: robustness alone is not profitability.
- **DSR ≈ 0.001, PBO 0.265.** With a negative observed Sharpe the Deflated Sharpe is ~0; the PBO
  (0.265) also clears the warning band — the candidate-config panel's apparent ranking does not hold
  out of sample.

**This is the system working (Inviolable Rule 7).** Most candidates die here; failing on a laptop
is free. No tweaking-until-it-passes — the next step is a *hypothesis-driven* input change.

## Routing decision

**KILL → CONTINUE.** Re-enter Phase 2R at the next cycle. Per the adopted cheapest-first order:

- **Cycle 2 — label sanity** (free, local): dump the triple-barrier touch distribution. If the
  vertical barrier dominates, the label has degenerated toward "did the session drift up," and the
  fix is labeling parameters — which may reframe the feature work. *(This is the next action.)*
- Then Cycle 3 (microstructure + features-from-finer-data), then Cycle 4 (universe expansion,
  conditional on cycles 2–3 lifting the smoke path-Sharpe meaningfully above zero).
- The **iteration budget (P2R.4)** is the operator's to set before Cycle 2 begins.

Phase 3 remains unreachable: the most recent verdict is KILL, not PASS.

## Run provenance

| item | value |
|---|---|
| MLflow | experiment `p2.9-killgate` (id **4**), kill-gate run **`cdf5dd8ff72c4555bde22050436eb042`** (verdict `KILL`) |
| fidelity | **reduced-knob local smoke** (`num_boost_round=80`, MC shuffles 200, 2 synthetic universes, CPCV 6×2) — sufficient to confirm a known-failing candidate without the deferred full-fidelity cloud spend (Part II iteration discipline) |
| data version | `15min-8sym-20210624-20260623-1bba6975` |
| thresholds | `config/default.yaml` → `kill_gate:` (set before the run, Inviolable Rule 1) |
