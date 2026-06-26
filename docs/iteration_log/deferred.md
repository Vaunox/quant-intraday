# Phase 2R — Tracked but not active

Iteration ideas that are **deliberately deferred** — not abandoned. Each is held in reserve with a
stated trigger for when (if ever) it becomes active. Recording them here keeps the
[iteration budget](budget.md)'s trial count honest (a deferred idea has spent no trials) and stops
them from being silently re-litigated.

---

## Triple-barrier reward:risk asymmetry (2.0σ↑ / 1.5σ↓)

The triple-barrier `2.0↑ / 1.5↓` asymmetric reward:risk is a **deliberate design choice, not a
degeneracy.** No evidence it is binding — the [cycle-2 label-sanity finding](cycle-2_finding.md)
showed the label is sound (vertical only 16.4%, positive rate a stable ~0.45). A symmetric-barrier
A/B is **held in reserve as a cheap test before any frequency pivot** if cycles 3–4 do not clear the
kill-gate.

- **Trigger:** cycles 3–4 fail to clear the kill-gate *and* before invoking the budget's
  decision-frequency pivot.
- **Cost if activated:** cheap (a labeling-parameter A/B; reuses the whole harness).
- **Status:** not active; 0 trials.

## Depth microstructure (cycle 3b) — OFI / depth imbalance / signed flow

The diagnostic's "top feature" (Deep Dive #1 §2.2) — but **data-gated and deferred**, not closed
(see the [cycle-3b decision](cycle-3b_decision.md)). Historical 5-level depth is not available at a
retail budget; the only viable path is forward-recording via Kite's free WebSocket
([cycle-3 plan](cycle-3_plan.md) §2), which needs weeks–months of accumulation and pulls Phase-5
live-capture infrastructure forward. 3a showed finer *OHLCV* adds no signal, which *sharpens* 3b's
hypothesis (the missing signal may be genuinely microstructural) — but the frequency pivot is the
cheaper, no-wait test to run first.

- **Trigger:** the 60-min (Cycle 4) and daily-close pivots both fail. Then record depth forward
  **during Phase 5's live-ingest work** (architecturally clean) rather than as a Phase 2R side-quest.
- **Cost if activated:** ₹0 data (Kite live depth) but weeks–months of forward recording + a new
  persistent depth tier; or institutional historical depth (₹tens-of-thousands+/month).
- **Status:** not active; 0 trials.

## Universe expansion to a survivorship-correct Nifty-50/100

The research universe is 8 Nifty-heavyweight names. Expanding to a larger survivorship-correct
universe adds event count (a better DSR denominator) and cross-sectional power — but it **amplifies**
an edge, it does not **create** one (cycle-1 diagnostic, candidate (c), a multiplier not a root
cause). Deferred until a candidate shows a smoke CPCV path-Sharpe meaningfully above zero.

- **Trigger:** cycles 3–4 lift the smoke path-Sharpe meaningfully above zero (then expansion is
  worth the backfill effort — Cycle 4 in the diagnostic's cheapest-first order).
- **Cost if activated:** a multi-symbol historical backfill (operator-run, local) + survivorship
  reference data.
- **Status:** not active; 0 trials.
