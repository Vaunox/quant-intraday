# Phase 2R · Cycle 4 — Frequency pivot to 60-min (finding)

**Subtask:** P2R.2 cycle 4 (the budget's pre-committed frequency pivot; **the stop-checkpoint
cycle**). See the [cycle-3b decision](cycle-3b_decision.md) and the [iteration budget](budget.md).
**Input change:** decision frequency 15-min → 60-min (existing pipeline, re-aggregated bars, same
8-symbol universe, no new data, no depth).
**Verdict:** **the pivot did not help.** Best smoke CPCV path-Sharpe stays far below +0.3 →
**the budget's stop criterion has engaged.**
**Trial-budget cost:** **1 new trial** (60-min); the 15-min run is the baseline.

---

## Results — CPCV median path-Sharpe

| frequency | n_obs | round-trip cost | gross/obs | net/obs | gross annualised | net annualised | MLflow run |
|---|---|---|---|---|---|---|---|
| **15-min (baseline)** | 14,138 | 0.00206 | +0.0424 | −0.0177 | +2.257 | **−0.943** | `a96907533495` |
| 60-min (pivot) | 9,323 | 0.00206 | +0.0471 | −0.0208 | +2.035 | **−0.897** | `b23019c5cf0a` |

**Delta 60-min vs 15-min:** gross/obs **+0.005**, net/obs **−0.003**, net annualised **+0.046**.
MLflow experiment `p2r-cycle4` (id 6).

## Verdict — the pivot didn't move the needle; the edge-to-cost problem is structural

1. **Gross signal is essentially flat** (+0.042 → +0.047 per-obs) — the per-decision predictability
   is no better at 60-min. **Net stays deeply negative** at both frequencies (−0.90 to −0.94
   annualised): costs dominate the edge at 15-min *and* 60-min alike.
2. **The +0.046 net-annualised "improvement" is an artifact, not a gain.** 60-min has fewer
   events/year (~1,865 vs ~2,828), so the annualisation factor is smaller (√1865 ≈ 43 vs √2828 ≈
   53); the *per-observation* net is actually slightly worse (−0.0208 vs −0.0177). The marginally
   less-negative annualised number is the smaller √-factor applied to a slightly worse per-obs
   Sharpe — a wash, not a real edge improvement.
3. **The cost-to-edge hypothesis is refuted for this universe.** The expectation was that 60-min's
   larger target moves against the same ~0.2% round-trip cost would lift the net edge. It did not —
   because there is **no real gross edge to protect** (gross ~0.047 per-obs ≈ chance; AUC was 0.52).
   You cannot fix a missing edge by changing the frequency; you only change how the (absent) edge
   is annualised. This is consistent with the entire arc: weak AUC, sound labels, finer features
   *worse*, coarser features flat.

## Budget — the stop criterion has engaged

Per [budget.md](budget.md): *"the project ends if after cycle 4 the best smoke CPCV path-Sharpe
across all candidates remains below +0.3."* The best across all cycles:

- **gross per-obs: +0.047** (60-min) — far below +0.3.
- **net, after costs: −0.90 annualised / −0.018 per-obs** — far below +0.3, and **negative.**

**Under any reading of "smoke CPCV path-Sharpe," we are far below +0.3. The stop criterion is
met.** (The pivot criterion is also not satisfied: net after costs never even turned positive.)

**Bookkeeping:** **4 of 6 cycles consumed** (Cycle 4 = the 60-min pivot); 2 remain (5, 6). **2
cumulative trials counted toward the 50-cap** across cycles 3–4 (single-digit; the cap was never
the binding constraint — the *signal* was).

## Routing — operator decision (P2R.4 is operator-only)

The budget's terminal options after a met stop criterion. **Holding for the operator's call:**

- **(A) Stop the project (the disciplined default).** The honest conclusion: **no tradeable edge at
  this configuration** — 15-min/60-min intraday cash equity, 8-name liquid universe, bar-data
  features, after realistic Indian costs. Per Inviolable Rule 7 this is a **successful** outcome: a
  validated, reusable research apparatus (data → features → labels → CPCV/DSR/PBO → kill-gate) that
  correctly **refused to trade a non-edge**, on a laptop, for ₹0 of capital lost.
- **(B) One more frequency pivot — daily-close (Cycle 5).** Permitted by the budget, but note it is
  **not a within-system knob**: daily-close means **overnight holds**, which leaves the intraday
  MIS design (square-off ~15:20, no overnight, no gap risk) — i.e. a *different strategy/instrument
  regime* (a swing system with gap risk and different costs/margins), closer to an instrument pivot
  than a frequency tweak. Reuses features/labels/harness pointed at a daily clock.
- **(C) Pivot instruments** — a universe/asset class where the cost-to-edge arithmetic differs
  (the budget's terminal alternative to stopping).

**My honest read:** the result argues the binding constraint was never frequency — it is the
**absence of a real predictive edge in bar-data intraday features** for this universe at retail
costs. (A) is the disciplined call the budget was written to enable; (B) is a deliberate new
research program, not a continuation. The decision is the operator's.
