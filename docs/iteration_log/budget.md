# Phase 2R — Iteration budget (P2R.4)

**Subtask:** P2R.4 (Iteration budget and stop discipline — operator-only). See
`MASTER_BLUEPRINT_Claude_Build_Handoff.md` Part IV (Phase 2R) and Inviolable Rule 7.
**Set by:** the operator, **before Cycle 2 begins** (committed in writing per P2R.4).
**Status:** committed. These numbers govern the Phase 2R loop and **must not be relaxed
mid-iteration** (see the discipline clause).

The iteration loop exists because most candidates fail the kill-gate; this budget exists so the
loop cannot become infinite or degenerate into overfitting search. The agent surfaces the trial
count and cycle count at the end of every cycle and consults this file; the **operator** decides
continue / pivot / stop.

---

## Committed limits

### Cycle cap — 6 total cycles
At most **6** Phase 2R cycles. A **hard reassessment checkpoint at cycle 4**: if no candidate
across cycles 2–4 has produced a **smoke CPCV path-Sharpe meaningfully above zero**, the cycle-1
diagnostic's ranking of binding constraints is likely wrong, and continued iteration along the
same axis is increasingly likely to be **overfitting search** rather than finding signal.

### Trial cap — 50 MLflow trials total (across all cycles)
At most **50** trials logged to MLflow across the entire loop. **Every variant tried counts —
including quickly-discarded ones.** Rationale (the DSR arithmetic): at **50** trials a raw Sharpe
of **~1.7+** is the Deflated-Sharpe-significant bar; at **200** trials the bar rises to **~2.5+**,
which is implausible for a retail intraday system at a 15-min cash-equity clock. Spending more
trials does not buy a real edge — it just raises the bar DSR will hold you to.

### Stop criterion — best smoke CPCV path-Sharpe < +0.3 after cycle 4
The **project ends** if, after cycle 4, the **best smoke CPCV path-Sharpe across all candidates
remains below +0.3**. Reasoning: anything below +0.3 at cycle 4 has **no plausible path** to clear
the +1.0 kill-gate after costs even with further iteration — it would require finding another
**3×+** gain at that stage, which is implausibly large. Stopping a project that is honestly not
converging is the disciplined, successful outcome (a reusable research apparatus, no money lost).

### Pivot criterion — positive but < +0.5 after cycle 4 → change the decision frequency
If cycles 2–4 produced **positive** smoke Sharpes but **none cleared +0.5 after costs**, **pivot
to a different decision frequency** — **60-minute or daily-close** as the leading candidate.
Reasoning: 15-min may simply not be the right frequency for the **signal-to-cost ratio** available
to a sub-10-OPS retail bot. The pivot **reuses** the harness, OMS, features, and labels — pointed
at a different decision clock — so it is not a restart.

### Trial-budget exhaustion clause
If the **50-trial cap is reached before either smoke threshold is hit**, **stop or pivot
regardless of cycle count.** DSR will not let those numbers be called real, so there is nothing to
be gained by spending the remaining cycles.

### Continuation clause
**Continue iterating only if** the smoke CPCV path-Sharpe is on a **measurably improving
trajectory across cycles** *and* trial budget remains. **No-trend iteration is overfitting in slow
motion** — flat-but-positive is not a reason to keep going.

### Discipline clause (the reason this file exists)
These numbers are **committed in writing before Cycle 2 begins** and **must not be relaxed
mid-iteration.** **Tightening** (stopping earlier than the limits) is allowed; **loosening**
(continuing past the limits, raising the trial cap, lowering the thresholds) is **not**. Changing
them mid-iteration is exactly the discipline failure they exist to prevent — that is how a research
program rationalises its way into trading an overfit.

---

## Decision table (consulted at the end of each cycle)

| Condition (smoke CPCV path-Sharpe, after costs) | Decision |
|---|---|
| A candidate clears the kill-gate (P2.9 PASS, all seven) | **PASS** → route to Phase 3 |
| Trial cap (50) reached, no candidate at threshold | **STOP or PIVOT** (per below), regardless of cycle |
| After cycle 4, best < **+0.3** | **STOP** (project ends) |
| After cycle 4, positive but none > **+0.5** | **PIVOT** decision frequency (60-min / daily-close) |
| Improving trajectory + trials remain + cycles ≤ 6 | **CONTINUE** (next cycle) |
| Flat / no trend (even if positive) | **STOP or PIVOT** — no-trend iteration is overfitting |

**Tracking:** the agent reports the running **cycle count** and **cumulative MLflow trial count**
at the end of each cycle and consults this table; the operator makes the call.
