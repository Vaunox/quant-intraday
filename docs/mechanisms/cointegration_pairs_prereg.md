---
mechanism: cointegration_pairs
date: 2026-06-27
hypothesis: >
  Genuinely cointegrated NSE equity pairs have a stationary spread; when the spread deviates from
  its trailing formation mean it reverts, so a dollar-neutral long-cheap / short-rich position,
  re-selected monthly on a trailing Engle-Granger test, earns a positive net-of-cost return.
economic_rationale: >
  Two firms exposed to the same fundamental drivers (sector, factor, supply chain) are tied by a
  long-run no-arbitrage relationship; idiosyncratic order flow pushes the spread around that
  relationship, and the relationship pulls it back. The edge is the reversion premium for supplying
  liquidity to the temporary divergence — a statistical relationship, not a directional prediction
  of either leg. Market-neutral by construction, so it is not market beta.
success_thresholds:
  cpcv_median_sharpe_min: 1.0
  dsr_min: 0.95
  pbo_max: 0.2
  min_profit_factor: 1.2
kill_thresholds:
  cpcv_median_sharpe_stop: 0.3
trial_budget: 12
---

# Pre-registration: Cointegration pairs / statistical arbitrage (P7.2)

> Committed before the first test run on real data. The commit timestamp is the audit record that
> the hypothesis preceded the evidence (Part VI / P6.3).

## 1. Hypothesis

See front-matter. A monthly-rebalanced, market-neutral spread-reversion book on cointegrated pairs
earns a positive net-of-cost return.

## 2. Economic rationale

Cointegration encodes a long-run equilibrium between two prices; deviations are transient and
mean-revert. Trading against the deviation supplies liquidity and harvests the reversion. This is a
statistical-relationship mechanic (Part VI thesis), distinct from the directional bar-data
prediction the original program closed.

## 3. Data & universe

- **Prices:** the survivorship-free NSE daily panel (`data/nifty_panel/`, 2016–2024, 2695 names
  incl. delisted) — present. The candidate set is a liquidity-screened subset with full history
  over the window (chosen by the runner; recorded in the verdict).
- **Point-in-time:** pairs are re-selected each month on a **trailing** formation window; returns
  are realised the following month. No future data enters any decision (Inviolable Rule 2).

## 4. Strategy specification

- **Selection:** monthly, Engle-Granger cointegration test on the trailing formation window
  (`statsmodels.coint`), with a formation-correlation pre-filter; keep the lowest-p-value pairs.
- **Position:** per pair, `-clip(z, ±z_cap)/z_cap` on the spread `log(y) − β·log(x)` (β, μ, σ from
  the formation window) — bet against the deviation, in [−1, 1]. Dollar-neutral.
- **Return:** equal-weight average pair spread-return over the following month, **net** of the CNC
  round-trip cost on the rebalanced gross exposure.
- **Cost basis:** CNC delivery (multi-day), honest 0.22% round-trip.

## 5. Pre-committed thresholds

| Criterion | Success bar | Kill / stop line |
|---|---|---|
| CPCV median path-Sharpe (net, ann) | ≥ 1.0 | < 0.3 → STOP |
| Deflated Sharpe Ratio (honest cumulative N) | ≥ 0.95 | — |
| Probability of Backtest Overfitting | ≤ 0.2 | — |
| Profit factor | ≥ 1.2 | — |

## 6. Trial budget

Maximum variants for this mechanism: **12** (formation length, p-value cutoff, z-cap, pair count,
candidate-set size). Every variant — including discarded ones — counts toward the cumulative DSR N.

## 7. Pre-declared outcome routing

- **PASS:** proceed toward Phase 8 (CNC execution layer).
- **KILL / STOP:** record the verdict in `cointegration_pairs_verdict.md`; per the budget, route to
  the next conditional mechanism (P7.3 PEAD).
