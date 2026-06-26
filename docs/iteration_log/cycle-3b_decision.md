# Phase 2R · Cycle 3b — Decision: defer depth; pivot frequency

**Subtask:** P2R.2 cycle 3 decision (the 3b half of feature signal **(a)**). See the
[cycle-3 plan](cycle-3_plan.md) (§2 cost tiers), the [cycle-3a finding](cycle-3a_finding.md), the
[iteration budget](budget.md), and [deferred.md](deferred.md).
**Decision:** **3b deferred** (tracked, not closed). **Pivot to 60-min** (Cycle 4 next).
**One-line rationale:** data-cost reality + 3a's directional finding both favour a frequency pivot
over a depth side-quest.

---

## Rationale (recorded)

1. **3b is not buildable as originally envisioned at a retail budget.** Historical 5-level depth as
   a real product exists only at institutional tiers (₹tens-of-thousands+/month, quote-based,
   redistribution-licensed — [cycle-3 plan §2](cycle-3_plan.md)). The only viable retail path is
   **forward-recording via Kite's existing WebSocket**, which needs **weeks-to-months of calendar
   time** to accumulate usable history *and* **pulls Phase-5 live-capture infrastructure forward
   into Phase 2R — inverting the blueprint's dependency order.**
2. **3a's directional finding actively supports coarser frequency.** Finer-than-15-min went the
   *wrong* way ([cycle-3a finding](cycle-3a_finding.md)): the available bar-data information is
   **not** sub-15-min. The natural next test is whether it sits at **coarser** resolution, where
   bar data is **already available** — no waiting, no data spend, no infrastructure inversion.
3. **A 60-min pivot improves the cost-to-edge ratio by ~3–5×.** Target moves of ~0.5–2% against the
   same ~0.15% round-trip cost is structurally friendlier arithmetic than 15-min's 0.3–1%. This is
   exactly the pre-committed pivot reasoning in [budget.md](budget.md), applied **now** while it is
   the disciplined response (not after exhausting the budget on a depth side-quest).
4. **3b remains a viable *Phase-5 parallel track*, not a closed door.** If the 60-min and
   daily-close pivots both fail, recording depth forward **during Phase 5's live-ingest work**
   (rather than as a Phase 2R side-quest) is the architecturally clean way to eventually attempt
   depth-augmented features. Tracked in [deferred.md](deferred.md).

## Budget impact (explicit bookkeeping)

I count **3a + this 3b decision together as one cycle — Cycle 3** (the two halves of the
feature-signal investigation), so the 60-min pivot is **Cycle 4** — which is exactly where the
budget defines its hard reassessment + stop checkpoint.

- **Cycles consumed: 3 of 6** — Cycle 1 (diagnostic + P2.9 KILL verdict), Cycle 2 (label sanity),
  Cycle 3 (3a finer features + 3b decision).
- **Cycles remaining: 3** — Cycle 4 (60-min pivot, next), then 5 and 6.
- **Trials consumed:** 2 new in 3a (5-min, 1-min); cumulative distinct candidate configs remain
  single-digit, well within the 50-trial cap.

## Stop-criterion tracking (confirmed)

Per [budget.md](budget.md), the **60-min pivot is Cycle 4**, and the stop criterion is evaluated
**after Cycle 4**:
- If Cycle 4's best smoke CPCV path-Sharpe is **still below +0.3**, the **stop criterion engages**.
- Before stopping, **one more pivot option remains: daily-close** (Cycle 5).
- If that also fails, the budget's terminal options are **stop the project** or **pivot
  instruments** — the operator's call.

This is tracked: 60-min = Cycle 4 = the stop-checkpoint cycle.

## Routing → Cycle 4 (teed up; holds for operator go)

**Cycle 4 — Frequency pivot to 60-min.** Run the **existing pipeline** against **re-aggregated
60-min bars** (same 8-symbol universe, **no new data, no depth**), and report the smoke CPCV
path-Sharpe delta vs the 15-min cycle-1 baseline. One input family (decision frequency); every
variant logged to MLflow toward the 50-trial cap. **Holds for the operator's explicit go before
Cycle 4 begins.**
