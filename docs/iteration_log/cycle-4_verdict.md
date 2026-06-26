# Phase 2R · Cycle 4 — Verdict: STOP

**Subtask:** P2R.3/P2R.4 cycle-4 verdict (operator decision). See the
[cycle-4 finding](cycle-4_finding.md), the [iteration budget](budget.md), and the
[research-phase close-out](closeout.md).
**Verdict:** **STOP.** The budget's stop criterion engaged on honest numbers after Cycle 4; the
operator is honoring the commitment made in writing before iteration began.
**Routing:** the project's **research phase is complete**. Phases 3+ deferred **indefinitely** (not
deleted). **No live trading. No further iteration on this configuration.**

---

## Why STOP (operator decision, recorded)

1. **The evidence across four cycles is internally consistent.** Labels sound (cycle 2: vertical
   barrier only 16.4%, positive rate a stable ~0.45). Model not the bottleneck (cycle 1: three
   diverse families all near chance, AUC ≈ 0.52). Finer frequency *hurts* (cycle 3a). Coarser
   frequency *flat* (cycle 4). **The binding constraint was never frequency, labels, or model
   capacity — it is the absence of a real predictive edge in bar-data intraday features for this
   universe at retail Indian costs.**
2. **The two remaining options are not within-system pivots — they are different projects wearing
   the same architecture.** Daily-close requires CNC / no-short / overnight-gap restructuring and
   enters the most-mined corner of public quant finance with retail tools. Pivot-instruments is
   starting a new research program essentially blind. Both stretch the budget's pivot clause past
   where it was designed to bear weight.
3. **The discipline clause is explicit:** tightening (stopping earlier) is allowed; loosening
   (continuing past the limits) is not. Choosing daily-close or instrument-pivot would be
   *loosening* — picking a different problem to keep going on, after the original problem honestly
   didn't carry an edge.
4. **Stopping here is a successful execution of Inviolable Rule 7, not a failure.** The apparatus
   did exactly what it was built to do: **refused to trade a non-edge — cheaply, on a laptop, with
   ₹0 of real capital at risk.**

## Budget — final state

- **Cycles consumed: 4 of 6** (1 diagnostic/verdict, 2 label, 3 feature-signal, 4 frequency pivot).
  Cycles 5–6 **not used** — the stop criterion engaged first, and the discipline clause forbids
  spending them to loosen.
- **Trials consumed: single-digit** of 50 — the trial cap was never the binding constraint; the
  *signal* was.
- **Best smoke CPCV path-Sharpe across all candidates:** gross +0.047 per-obs; **net −0.90
  annualised** — far below the +0.3 stop threshold, and negative after costs.

## Status

Research phase **complete and stopped at Cycle 4.** Tagged `research-phase-stop-cycle-4`. The
apparatus, the blueprint, and all artifacts remain in place for a future research program if one is
ever defined (see [closeout.md](closeout.md)). Gate 2 (the kill-gate) was **never passed**; no
strategy proceeds toward capital.
