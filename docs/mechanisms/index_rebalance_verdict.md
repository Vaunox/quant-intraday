# P7.1 — Index-rebalance flow: verdict

**Verdict: DATA-GATED → does not clear (route to P7.2).** Pre-registration committed first
(`index_rebalance_prereg.md`, commit precedes this study). Per the Phase-7 budget
(`budget.md`), a mechanism that does not clear routes to the next conditional mechanism.

## What was built

The complete, tested index-rebalance machinery (`src/quant/research/mechanisms/index_rebalance.py`):

- `ReconstitutionEvent` — one index review (additions + deletions, announcement + effective dates).
- `load_reconstitution_events` — reads a dated change-log CSV (`review_id, announcement_date,
  effective_date, symbol, action`) into events.
- `IndexRebalanceSpec` — a Part-VI `StrategySpec`: equal-weight **long additions / short
  deletions**, enter at the first close at/after the announcement, exit at the first close at/after
  the effective date; per-event return is the basket return over that window, **net of the honest
  CNC 0.22% round-trip cost** (Rule 4). Market-neutral by construction. Plugs into the **unchanged**
  CPCV + seven-point kill-gate via the P6.1 harness.
- `evaluate_index_rebalance` — runs the spec through the existing CPCV engine.

A synthetic-event test plants an addition-up / deletion-down flow and confirms the harness recovers
a positive net-of-cost edge end-to-end; data-gate tests confirm the missing-change-log and
untradeable-event paths fail loudly.

## Why it does not clear (the data gate)

The study needs a **dated NSE reconstitution change-log** — per semi-annual review, which symbols
were added / deleted, with the announcement and effective dates. **This change-log is not present
in the repo.** Only a single *current* membership snapshot exists
(`data/nifty_panel/ind_nifty500list.csv`), not a dated additions/deletions history. The
survivorship-free daily **price** panel (`data/nifty_panel/`, 2016–2024, 2695 names incl. delisted)
*is* present and is what the spec consumes — but without the event dates there are **no events to
judge**.

This is a genuine data-access constraint, not a modeling choice — the same class of blocker as
Cycle 3b's historical-depth gate (`FINDINGS.md` §6). The blueprint (Part VI / P7.1 "Depends on")
lists the reconstitution change-log as "already built"; it is **not** in the repo, and per Ground
Rule 9 that conflict is surfaced rather than patched around. Fabricating reconstitution dates from
memory would violate Ground Rule 9 (no guessing) and produce an untrustworthy verdict; that was
not done.

## What unblocks it

Drop a change-log CSV at a known path (schema above) — e.g. sourced from NSE index-review press
releases or a vendor — and the study runs unchanged through the kill-gate (the machinery is done).
Until then P7.1 cannot produce a trustworthy PASS/KILL on real events.

## Trial count

**0 trials charged** (no run was executed on real data — there was nothing to run). The cumulative
DSR N (P6.2) is unchanged. The budget's per-mechanism cap (8) is untouched.

## Routing

Per `budget.md`: P7.1 does not clear → **proceed to P7.2 (cointegration pairs)**, which needs only
the price panel (present) and is fully runnable on real data.
