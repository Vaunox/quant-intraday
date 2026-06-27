---
mechanism: index_rebalance
date: 2026-06-27
hypothesis: >
  Names added to a major NSE index are bid up, and names deleted are sold off, by index-tracking
  passive funds that must trade the reconstitution on a known schedule. A long-additions /
  short-deletions book entered around the announcement and exited around the effective date earns
  a positive, market-neutral net-of-cost return.
economic_rationale: >
  Index funds and ETFs replicate the index by construction, so on each semi-annual reconstitution
  they must buy the additions and sell the deletions in size, price-insensitively, on a
  pre-announced effective date. That forced, scheduled, uninformed flow is the structural edge: an
  informed trader can supply liquidity ahead of it. The counterparty (the passive fund) cannot
  avoid the trade and cannot time it — its mandate forbids both. This is a flow mechanic, not a
  directional bar-data prediction (the family the original program closed).
success_thresholds:
  cpcv_median_sharpe_min: 1.0
  dsr_min: 0.95
  pbo_max: 0.2
  min_profit_factor: 1.2
kill_thresholds:
  cpcv_median_sharpe_stop: 0.3
trial_budget: 8
---

# Pre-registration: Index-rebalance flow (P7.1)

> Committed before the first test run. The commit timestamp of this file is the audit record that
> the hypothesis preceded the evidence (Part VI / P6.3).

## 1. Hypothesis

See front-matter. A market-neutral long-additions / short-deletions book, entered on the
reconstitution **announcement** and exited around the **effective date**, earns a positive
net-of-cost return from forced passive-fund flow.

## 2. Economic rationale

Passive index replication forces scheduled, price-insensitive buying of additions and selling of
deletions on the effective date; the flow is pre-announced and unavoidable for the tracking fund.
This is a structural flow mechanic (Part VI thesis), distinct from the directional bar-data
prediction the original program tested to exhaustion (`FINDINGS.md`).

## 3. Data & universe

- **Prices:** the survivorship-free NSE daily panel (`data/nifty_panel/`, 2016–2024, 2695 names) —
  present, includes delisted names.
- **Events (the binding dependency):** a dated **reconstitution change-log** — per index review,
  the added/deleted symbols with the **announcement date** and the **effective date**. The
  `ReconstitutionEvent` schema is defined in `research/mechanisms/index_rebalance.py`.

## 4. Strategy specification

- **Event:** one reconstitution review (a batch of additions + deletions).
- **Entry:** the announcement date (first close at/after it).
- **Exit:** the effective date (first close at/after it).
- **Weight:** +1 (long) per addition, −1 (short) per deletion, equal-weighted within the event;
  the per-event return is the equal-weighted basket return over the entry→exit window, **net of
  the CNC round-trip cost** (multi-day hold). Market-neutral by construction.
- **Cost basis:** CNC delivery (multi-day), the honest 0.22% round-trip used throughout the
  daily/CNC honest runs.

## 5. Pre-committed thresholds

| Criterion | Success bar | Kill / stop line |
|---|---|---|
| CPCV median path-Sharpe (net, ann) | ≥ 1.0 | < 0.3 → STOP |
| Deflated Sharpe Ratio (honest cumulative N) | ≥ 0.95 | — |
| Probability of Backtest Overfitting | ≤ 0.2 | — |
| Profit factor | ≥ 1.2 | — |

## 6. Trial budget

Maximum variants for this mechanism: **8** (entry/exit offsets, addition-only vs. add−delete,
weighting). Every variant — including discarded ones — counts toward the cumulative DSR N (P6.2).

## 7. Pre-declared outcome routing

- **PASS:** proceed toward Phase 8 (CNC execution layer).
- **KILL / STOP / data-gated:** record the verdict in `index_rebalance_verdict.md`; per the budget,
  route to the next conditional mechanism (P7.2 cointegration pairs).
