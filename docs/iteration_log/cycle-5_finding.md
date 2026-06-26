# Phase 2R · Cycle 5 — Previous project config under honest harness (finding)

**Subtask:** P2R.2 Cycle 5.  See [cycle-5 diagnostic](cycle-5_diagnostic.md) for full method.
**Input change:** previous project's 49-stock universe, daily frequency, 12 stockstats-equivalent
indicators + VIX, 5-day triple-barrier, CNC cost model 0.14% RT.
**Verdict:** **MARGINAL — real signal present, but below the +1.0 kill-gate smoke threshold.**
**Trial-budget cost:** **1 new trial** (cycle-5).  Cumulative: N=5 trials used, 45 remaining.

---

## Key Findings (verbatim record)

1. **Net annualised Sharpe +0.556** at daily/CNC frequency on 49-stock Nifty 50 universe.

2. **60% previous result confirmed ~4–5x inflated** from GAN leakage + selection bias (best-of-42
   without DSR deflation) + cost understatement (0.02% vs 0.14% CNC); but **real underlying signal
   confirmed** — the honest net edge is +0.556, not zero.

3. **Daily frequency is structurally correct for this feature set** — net Sharpe improved from
   −0.94 at 15-min to +0.556 at daily.  The same gross signal (+0.042 vs +0.068/obs) has
   breathing room when costs are paid once per 5-day hold rather than per bar.

4. **Verdict: MARGINAL** — above stop criterion (+0.3), below kill-gate pass (+1.0).
   Budget impact: **N=5 trials used, 45 remaining**.
   Cycle count: **Cycle 5 complete, Cycle 6 remaining** under committed budget.

---

## Results — CPCV median path-Sharpe (smoke: 6x2, phi=5 paths, 80 boost rounds)

| variant | n_obs | round-trip cost | gross/obs | net/obs | gross annualised | net annualised | MLflow run |
|---|---|---|---|---|---|---|---|
| **prev-project config (cycle 5)** | **189,617** | **0.0014** | **+0.0680** | **+0.0350** | **+1.079** | **+0.556** | `p2r-cycle5` |
| 15-min baseline (cycle 3a) | 14,138 | 0.00206 | +0.0424 | −0.0177 | +2.257 | −0.943 | `56b042f4bc35` |
| 60-min pivot (cycle 4) | 9,323 | 0.00206 | +0.0471 | −0.0208 | +2.035 | −0.897 | `b23019c5cf0a` |

Universe: 49/49 stocks usable (all downloaded full history).  +rate = 0.525 (binary label balance).
Elapsed: 13.3 min (download + label + CPCV).  Logged to MLflow experiment `p2r-cycle5`.

## DSR / PBO

| metric | value | threshold | verdict |
|---|---|---|---|
| DSR (N=5 trials) | **1.0000** | > 0.95 | **PASS** |
| PBO | **0.412** | < 0.5 | **PASS** |

## Verdict — real signal, but marginal; previous project's 60% was ~4-5x inflated

### What the numbers say

1. **The feature set has a real gross signal at daily frequency.** Gross per-obs +0.068,
   annualised +1.08.  This is meaningfully above chance (AUC >> 0.52) and above the intraday
   result (+0.042 at 15-min).  Daily bars with these 12 indicators genuinely predict direction.

2. **Net is positive after CNC costs (0.14% RT), but below the kill-gate.** Net per-obs +0.035,
   net annualised **+0.556**.  Per the pre-committed routing table: +0.3 to +1.0 is the
   MARGINAL zone — above the "stop" threshold, below the "PASS" threshold.

3. **DSR passes, PBO is low.** With only 5 cumulative trials the deflation benchmark is low,
   so DSR=1.000.  PBO=0.412 means the IS-best strategy stays best OOS more often than not.
   Neither metric flags these numbers as pure noise.

4. **The previous project's 60% return was ~4-5x inflated**, but NOT entirely fabricated:
   - **Confirmed artifact sources:** GAN augmentation trained on the validation period (the
     most significant); selection of best-of-42 bots without DSR deflation (~2x inflator at
     42 trials); understated costs (0.02% vs 0.14% CNC = 7x cost understatement).
   - **Confirmed real component:** the underlying feature set + daily frequency + large-cap
     Indian universe *does* have signal.  The honest estimate is net annualised ~+0.56 (smoke),
     not 60%.

5. **The daily cost regime is fundamentally better than 15-min.** At 15-min, net was −0.94
   annualised (costs destroyed the edge).  At daily, net is +0.556 — the same feature signal
   (+0.042 vs +0.068/obs gross) has breathing room because costs are paid once per 5-day hold
   rather than once per 15-min bar.  This is the cost-to-edge reversal the cycle-4 routing
   mentioned as the structural reason daily is "a different strategy," not just a frequency
   tweak.

### What cycle 5 does NOT prove

- That the full P2.9 kill-gate would pass.  Net +0.556 at 80 boost rounds is a smoke reading;
  the full battery (300 rounds, walk-forward OOS, reconciliation, robustness stress tests)
  would either confirm it or reveal degradation.
- That the previous project's 60% figure is reproducible under any honest methodology.

---

## Full P2.8 robustness battery (depth-300, 8×2 CPCV)

Run 2026-06-27, **local** (14.7 min, $0 — cloud deferred while commits are held).
MLflow exp `p2r-cycle5-p28-battery` run `08b4213b50f0481cb9682b6ac931618b` (FINISHED).
Script: `scripts/run_cycle5_robustness.py` (uncommitted).

**Baseline at full depth confirms — and slightly strengthens — the smoke edge:**
net median path-Sharpe **+0.0417/obs → +0.662 annualised** (vs +0.556 at smoke 6×2/80),
with **0 / φ negative paths**.  Going 80→300 boost rounds and 5→7 CPCV paths did not erode
the edge — it firmed up.  Still **MARGINAL** (< +1.0 kill-gate).

| stress test (§4b.7) | result | flag |
|---|---|---|
| Parameter sensitivity (5 single-knob variants) | CV **0.140**, spread 0.013, no knife-edge, no sign flip | **PASS** |
| Monte Carlo trade shuffle (500) | obs MDD 5.11 > shuffled-p50 1.96; percentile rank **1.000** | **PASS** (order-robust) |
| Noise injection (3 levels × 3) | graceful decay +0.0354 → 0.0165 → 0.0120 → 0.0068; **edge persists** | **PASS** |
| Cross-symbol LOO (20 names) | median held-out Sharpe **+0.063**, 60% positive | **PASS** (generalizes) |
| Synthetic GBM (5 universes) | mean median **−0.0542**, 0/5 positive — no spurious edge | **PASS** (no leak) |
| Two-engine reconciliation (daily) | max money diff **2.4e-11** | **PASS** |

**Battery verdict: 6/6 green.** The edge is *robust* — it survives parameter perturbation,
trade re-ordering, feature noise, out-of-universe symbols, and the no-real-luck synthetic
control, and the accounting reconciles to floating-point noise.  What it is **not** is *large*:
+0.66 annualised is a real, well-behaved signal that still sits below the +1.0 kill-gate.
Robustness and magnitude are different axes; cycle 5 passes the first and falls short on the
second.  The P2.9 seven-point verdict remains the only authority on capital.

---

## Routing — operator decision required (pre-committed table)

| condition | this cycle | decision |
|---|---|---|
| Net annualised > +1.0 | +0.556 — NO | n/a |
| Net annualised +0.3 to +1.0 | +0.556 — **YES** | **MARGINAL: operator decides** |
| Net annualised < +0.3 | NO | n/a |

**Options (operator's call, not pre-committed):**

**(A) Stop / accept close-out verdict.** The research apparatus found that *some* signal exists
at daily frequency, but the smoke reading (+0.556) is below the kill-gate (+1.0).  Rolling into
a full P2.8 battery requires operator decision to open a new research program (this cycle
formally exhausted the Phase 2R budget's pre-committed scope).  Given the P2R arc — intraday
found nothing, daily shows marginal signal at smoke — the disciplined call is to note the finding
and not commit further cycles without a fresh budget.

**(B) Full P2.8 robustness battery on the cycle-5 configuration.** This is the legitimate
next step if the operator believes +0.556 smoke is likely to harden to +1.0 at full depth
(300 boost rounds, walk-forward OOS 2022-2026).  Budget commitment: 1 more cycle (cycle 6 of 6),
~1-2 h compute, 1 additional trial.

**(C) Treat as a new research program.** Daily CNC on 49 Nifty-50 stocks with these features
is materially different from the original project scope (15-min MIS, 8 names).  A fresh
diagnostic + budget + kill-gate, anchored to the cycle-5 smoke finding, is the architecturally
clean path rather than squeezing it into the tail of P2R.

**My read:** option (B) — run Cycle 6 as the full battery on this exact config — is the only
call that produces a *definitive* answer within the existing budget.  Option (C) is equivalent
but with cleaner accounting.  Option (A) is valid if the operator wants to stop here; the
finding that daily/CNC carries real signal is itself a transferable research output.

---

## Budget after cycle 5

- **Cycles consumed:** 5 of 6 (cycle-6 remains and is the natural follow-on).
- **MLflow trials (cumulative):** N=5 used, 45 remaining (of 50-trial cap).
- **Budget status:** within limits; cycle-6 is available.
