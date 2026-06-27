---
mechanism: pead
date: 2026-06-27
hypothesis: >
  Stocks that report a large positive earnings surprise drift up, and large negative surprises
  drift down, over the weeks after the announcement; a book that goes long high-surprise and short
  low-surprise names and holds the drift window earns a positive net-of-cost return.
economic_rationale: >
  Post-earnings-announcement drift is one of the most-documented anomalies: prices underreact to
  the earnings surprise and adjust gradually, because attention is limited and information diffuses
  slowly. The edge is supplying the patience the slow-diffusing crowd lacks. It is an event
  mechanic keyed to a hard information event, not a directional bar-data prediction.
success_thresholds:
  cpcv_median_sharpe_min: 1.0
  dsr_min: 0.95
  pbo_max: 0.2
  min_profit_factor: 1.2
kill_thresholds:
  cpcv_median_sharpe_stop: 0.3
trial_budget: 8
---

# Pre-registration: Post-earnings-announcement drift (P7.3)

> Committed before the first test run. The commit timestamp is the audit record that the
> hypothesis preceded the evidence (Part VI / P6.3).

## 1. Hypothesis

See front-matter. A surprise-sorted long/short book held over the drift window earns a positive
net-of-cost return.

## 2. Economic rationale

PEAD: prices underreact to earnings surprises and drift in the surprise direction for weeks. The
edge is the patience premium for holding through the slow diffusion. An event mechanic (Part VI
thesis), distinct from directional bar-data prediction.

## 3. Data & universe

- **Events:** the P9.2 event-reaction dataset (`EventReactionRecord`: surprise, reaction, drift),
  accrued by `EventReactionRecorder` from an earnings-calendar / surprise feed.
- **The binding dependency** is that feed — an earnings-surprise source is **external** and not
  present in the repo (the P9.2 recorder is built and tested, but its store is empty without a
  feed). Prices come from the survivorship-free panel / archive.

## 4. Strategy specification

- **Event:** one earnings announcement (an `EventReactionRecord`).
- **Position:** `sign(surprise)` (long positive surprise, short negative), optionally filtered to
  `|surprise| >= min_abs_surprise`.
- **Return:** `sign(surprise) * drift_return` over the PEAD window, **net** of the CNC round-trip
  cost.
- **Cost basis:** CNC delivery (multi-day hold), honest 0.22% round-trip.

## 5. Pre-committed thresholds

| Criterion | Success bar | Kill / stop line |
|---|---|---|
| CPCV median path-Sharpe (net, ann) | ≥ 1.0 | < 0.3 → STOP |
| Deflated Sharpe Ratio (honest cumulative N) | ≥ 0.95 | — |
| Probability of Backtest Overfitting | ≤ 0.2 | — |
| Profit factor | ≥ 1.2 | — |

## 6. Trial budget

Maximum variants for this mechanism: **8** (surprise filter, drift horizon, weighting). Every
variant — including discarded ones — counts toward the cumulative DSR N (P6.2).

## 7. Pre-declared outcome routing

- **PASS:** proceed toward Phase 8 (CNC execution layer).
- **KILL / STOP / data-gated:** record the verdict in `pead_verdict.md`; this is the last mechanism
  in the pre-committed slate — if it does not clear, the budget's program-stop criterion engages
  (an honest negative, Inviolable Rule 7).
