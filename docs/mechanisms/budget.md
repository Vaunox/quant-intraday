# Phase-7 mechanism-study budget (Part VI)

**Committed before P7.1 begins (Part VI / Phase-7 gate discipline; mirrors P2R.4).** These bands are
fixed **in writing, before any mechanism result exists**, so the decision to continue or stop is
honest from the start (Inviolable Rule 7). Set under the operator's standing directive to drive
Part VI to completion; the agent surfaces the trial / cycle count, the operator (or this standing
directive) decides continue / stop.

## Pre-committed bands

- **Cycle cap — 3 mechanism studies.** The pre-committed slate is exactly the three in the
  blueprint: **P7.1 index-rebalance flow**, then (conditional) **P7.2 cointegration pairs**, then
  (conditional) **P7.3 PEAD**. P7.2 and P7.3 are pursued **only if** the earlier studies do not
  clear the kill-gate. No fourth mechanism is opened without a fresh, separately-committed budget.

- **Cumulative trial cap — 40 MLflow runs** across all mechanism studies (the
  `config.mechanisms.experiment_names` experiments; P6.2 enforces the count). Every variant —
  **including discarded ones** — is one run and counts. Beyond 40 the Deflated Sharpe deflation is
  punitive enough that no realistic raw Sharpe clears criterion 2, so 40 is a hard stop regardless
  of cycle count.

- **Per-mechanism smoke stop — best smoke path-Sharpe < +0.3 → STOP that mechanism.** Mirrors the
  P2R.4 band that closed the original program. A mechanism whose strongest honest smoke is below
  +0.3 annualised net path-Sharpe is not pursued to a full battery; it is recorded KILL and the
  next conditional mechanism (if any) is considered.

- **Program stop / pivot.** **If no mechanism clears the seven-point kill-gate within the cycle
  cap, the mechanical-edge program STOPS** — an honest negative, per Inviolable Rule 7 (*"no
  tradeable mechanical edge at retail scale in this slate"* is a real, successful answer). A
  mechanism that **clears** the kill-gate routes forward to Phase 8 (CNC execution layer).

## Data-availability note (surfaced per Ground Rule 9)

The blueprint lists the **NSE reconstitution change-log** as a P7.1 dependency "already built." It
is **not** present in the repo (only a single current `data/nifty_panel/ind_nifty500list.csv`
membership snapshot exists, not a dated additions/deletions history). This is a real data-access
constraint analogous to Cycle 3b's historical-depth gate (`FINDINGS.md` §6), not a modeling choice.
Its consequence for P7.1 is recorded in `p7.1_index_rebalance_verdict.md`. The survivorship-free
daily **price** panel (`data/nifty_panel/`, 2016–2024, 2695 names) **is** present, so the
price-only mechanism (P7.2 pairs) is fully runnable on real data.

## Ledger (updated as studies run)

| Mechanism | Cycle | Status | Cumulative trials | Verdict |
|---|---|---|---|---|
| P7.1 index-rebalance | 1 | done | 0 | **DATA-GATED** (no reconstitution change-log) → route to P7.2 |
| P7.2 cointegration pairs | 2 (conditional) | done | 5 | **KILL** (+0.425 net Sharpe — strongest edge found, but < +1.0 bar and not significant, t=1.20) → route to P7.3 |
| P7.3 PEAD | 3 (conditional) | in progress | — | — |
| **Cumulative** | — | — | **5 / 40** | — |
