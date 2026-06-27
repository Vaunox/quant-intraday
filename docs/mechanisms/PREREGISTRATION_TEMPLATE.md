---
# === Pre-registration front-matter (structured, machine-checked) ===
# Copy this file to docs/mechanisms/<mechanism>_prereg.md, fill it in, and COMMIT IT
# BEFORE writing or running any code that tests the mechanism (Part VI / P6.3).
# `mechanism` must equal the <mechanism> in the filename.
mechanism: <mechanism_id>            # e.g. index_rebalance  (file: index_rebalance_prereg.md)
date: <YYYY-MM-DD>                    # the date this hypothesis was committed
hypothesis: >
  One or two sentences stating the falsifiable claim. What edge do you expect, on what
  events, in which direction (or market-neutral), over what horizon?
economic_rationale: >
  WHY this edge should exist structurally — the mechanism, not a backtest. Who is the
  forced/uninformed counterparty, and why can't they avoid it? (e.g. index-tracking funds
  must buy additions and sell deletions on a pre-announced schedule, price-insensitively.)
# Pre-committed PASS thresholds — fixed BEFORE any result exists (Inviolable Rule 1).
# These mirror the seven-point kill-gate (config/default.yaml `kill_gate`); list the bars
# this mechanism must clear. No tweaking-until-it-passes.
success_thresholds:
  cpcv_median_sharpe_min: 1.0        # (1) annualised CPCV median path-Sharpe, net of costs
  dsr_min: 0.95                      # (2) Deflated Sharpe Ratio at the honest cumulative N
  pbo_max: 0.2                       # (3) Probability of Backtest Overfitting
  min_profit_factor: 1.2             # (5) profit factor
# Pre-committed KILL thresholds — the lines that, if crossed, end the study (an honest
# negative is a successful Rule-7 outcome). Often the inverse of the success bar plus a
# stop band (mirror the P2R.4 budget discipline).
kill_thresholds:
  cpcv_median_sharpe_stop: 0.3       # below this smoke path-Sharpe → STOP this mechanism
# Planned trial budget — the maximum number of variants you will run for THIS mechanism.
# Every variant (including discarded ones) counts toward the cumulative DSR N (P6.2).
trial_budget: 10
---

# Pre-registration: <Mechanism name>

> Committed before the first test run. The commit timestamp of this file is the audit
> record that the hypothesis preceded the evidence (Part VI / P6.3).

## 1. Hypothesis

Restate and expand the front-matter `hypothesis`. Be specific and falsifiable.

## 2. Economic rationale

Expand the front-matter `economic_rationale`. Cite the structural mechanism and the
forced/uninformed counterparty. Reference the relevant deep dive / FINDINGS section.

## 3. Data & universe

What data feeds this study (e.g. the survivorship-correct `ConstituentRegistry`, the
survivorship-free NSE-bhavcopy panel)? What is the event set and the universe?

## 4. Strategy specification

The `StrategySpec` shape: events, entry, exit, holding window, per-event weight (sign + size).
Market-neutral? Cost basis (MIS vs CNC)?

## 5. Pre-committed thresholds (restate the front-matter)

| Criterion | Success bar | Kill / stop line |
|---|---|---|
| CPCV median path-Sharpe (net, ann) | ≥ 1.0 | < 0.3 → STOP |
| Deflated Sharpe Ratio (honest N) | ≥ 0.95 | — |
| Probability of Backtest Overfitting | ≤ 0.2 | — |
| Profit factor | ≥ 1.2 | — |

## 6. Trial budget

Maximum variants for this mechanism: **<trial_budget>**. Every variant — including discarded
ones — is one MLflow run and counts toward the cumulative DSR N (P6.2).

## 7. Pre-declared outcome routing

- **PASS** (all seven kill-gate criteria clear): proceed toward Phase 8 (CNC execution layer).
- **KILL** (any criterion fails) or **STOP** (smoke below the stop band): record the verdict in
  `docs/mechanisms/<mechanism>_verdict.md`; the budget decides continue / stop (operator-only).
