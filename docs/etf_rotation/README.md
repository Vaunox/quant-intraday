# ETF-rotation track — index & closeout

**Branch:** `etf-rotation` (forked from framework-complete `4c7762d`). **Status: CLOSED — NO-GO.**
**Question:** can an ML rotation — or any portfolio manager — across liquid Indian ETFs be
economically viable at ₹1 lakh? **Answer: no.** See the README scoreboard for the one-line summary.

## Modular code map (`src/quant/research/etf/`, each pure + unit-tested)
| Module | Role |
|---|---|
| `liquidity.py` | Step 1 universe liquidity gate (turnover/continuity screen) |
| `spreads.py` | Step 2 bid-ask spread/depth aggregation (live Kite sampler feeds it) |
| `costs.py` | Step 2 cost model — per-leg spread/TER/STT + Zerodha statutory charges + flat DP fee |
| `benchmark.py` | Step 3 fixed-weight equal-weight rebalanced benchmark (the line to beat) |
| `rotation.py` | Step 4 ML cross-sectional rotation (purged-CV ensemble → rank → weights → backtest) |
| `portfolio.py` | Risk-managed PM (vol-target risk-parity, no ML) |

Thin runnable shims in `scripts/etf_*.py` (Yahoo/Kite I/O only; logic stays in `src/`).

## Pre-registrations & verdicts (read in order)
1. [`step1_liquidity_gate.md`](step1_liquidity_gate.md) — universe frozen (turnover non-binding).
2. [`step2_cost_model.md`](step2_cost_model.md) — STT resolved low; flat DP fee dominates.
3. [`step3_benchmark.md`](step3_benchmark.md) — benchmark Sharpe 1.53/1.54 (+ data-quality correction).
4. [`step4_5_verdict.md`](step4_5_verdict.md) — ML rotation **NO-GO**; universe robustness; best-of-N rejection.
5. [`pm_viability_prereg.md`](pm_viability_prereg.md) → [`pm_viability_verdict.md`](pm_viability_verdict.md) — risk-managed PM **NO-GO**.

## Re-run (all reproduce from a clean checkout; Yahoo `.NS` data, no credentials)
```bash
uv run python scripts/etf_liquidity_gate.py      # Step 1
uv run python scripts/etf_benchmark.py           # Step 3
uv run python scripts/etf_rotation.py            # Step 4-5 (ML grid, a few min)
uv run python scripts/etf_portfolio.py           # PM viability (cleans bad ticks)
uv run python scripts/etf_spread_sampler.py      # Step 2 live spreads (needs a Kite session)
```

## If revisited
The binding constraint was never tooling — it was **too few independent liquid drivers** and the
**Gate-1 weakness** of the underlying edge. A real reattempt needs a genuinely broader/uncorrelated
universe (likely less-liquid → more capital) or a new mechanism, committed as a **fresh
pre-registration** — not more universe/window slicing on this one (that manufactures best-of-N false
positives, as the 3-ETF run demonstrated).
