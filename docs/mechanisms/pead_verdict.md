# P7.3 — Post-earnings-announcement drift: verdict

**Verdict: DATA-GATED → does not clear (last mechanism in the slate → GATE 7 honest stop).**
Pre-registration committed first (`pead_prereg.md`).

## What was built

The complete, tested PEAD machinery:

- `research/mechanisms/pead.py` — `PeadSpec`, a Part-VI `StrategySpec` over the P9.2
  `EventReactionRecord` dataset: per event the net return is `sign(surprise) * drift_return` minus
  the honest CNC 0.22% round-trip, filtered to `|surprise| >= min_abs_surprise`, ordered by
  announcement for the CPCV purge. Plugs into the **unchanged** kill-gate.
- The P9.2 recorder (`data/recorders/events.py`, merged separately) that produces the records.
- 5 tests: signed net returns, drift-against-surprise negativity, end-to-end through the existing
  CPCV harness, the surprise-filter data gate, degenerate-config guards.

## Why it does not clear (the data gate)

PEAD needs the **earnings-surprise dataset** — per announcement, the actual vs the consensus
estimate, and the drift window. The P9.2 `EventReactionRecorder` is built and tested, but its store
is **empty without an external earnings-calendar / surprise feed**, which is **not in the repo**.
This is the same class of data-access constraint as P7.1's missing reconstitution change-log and
Cycle 3b's unbuyable depth (`FINDINGS.md` §6) — a genuine external-data gate, not a modeling
choice. Fabricating earnings surprises from memory would violate Ground Rule 9; that was not done.

## What unblocks it

Populate the P9.2 store from an earnings-surprise feed (consensus estimates + actuals, with
announcement dates), and the study runs unchanged through the kill-gate.

## Trial count

**0 trials charged** (no run on real data — the store is empty). Cumulative Part-VI trial count
remains **5** (P7.1: 0, P7.2: 5, P7.3: 0), well within the budget's cap of 40.

## Routing

This is the **last** mechanism in the pre-committed slate (cycle cap 3). With P7.1 data-gated,
P7.2 KILLed, and P7.3 data-gated, **no mechanism cleared the kill-gate within the cycle cap** → the
budget's program-stop criterion engages → **GATE 7 honest stop** (`gate7_closeout.md`).
