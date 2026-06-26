# Cycle 5 — Close-out: the honest value of the "60% / +0.662" claim

**Status:** ✅ **CLOSED.** Research arc complete. No Stage 2. No live trading.
**Verdict:** the edge is **real but economically negligible** — honest ceiling **≈ +0.148 annualised path-Sharpe**, far below the +1.0 kill-gate and below the +0.3 stop. **Close-out** per the pre-committed routing.
**Frame:** a **successful Rule-7 outcome** — the apparatus took an external "60% return / +0.662 Sharpe" claim down to its true value without fooling itself once, and proved the architecture sound even though the signal is too small for retail.

This document seals the finding. It is self-contained.

---

## 1. What was tested

The previous RL-ensemble project's configuration (49-stock Nifty-50 universe, daily frequency,
~12 technical indicators + VIX, multi-day holds) claimed ~60% returns. Cycle 5 reproduced that
configuration through **this** project's honest validation apparatus, in escalating fidelity:

| Stage | Universe | Data | Cost | N | Labeler | Components | Net ann path-Sharpe |
|---|---|---|---|---|---|---|---|
| Diagnostic (smoke) | 49 (yfinance, today's list) | yfinance | 0.14% | 5 | inline daily | none | **+0.556** |
| P2.8 battery (depth) | 49 (yfinance) | yfinance | 0.14% | 5 | inline daily | none | **+0.662** (6/6 robustness green) |
| Complete pipeline — 8 names | 8 validated | Kite + yfinance | **0.22%** | **22** | **gated CNC** | **all 4** | DIRECT **−0.22**, META **−0.29** |
| Complete pipeline — 56 names | **56 survivorship-aware** | Kite + yfinance | **0.22%** | **23** | **gated CNC** | **all 4** | DIRECT **−0.16**, META **+0.148** |

MLflow: `p2r-cycle5` (diagnostic), `p2r-cycle5-p28-battery` run `08b4213b…` (battery),
`p2r-cycle5-complete-pipeline` runs `dcd93454…` (8-name) and `7397d1ce…` (56-name).

---

## 2. The honest ceiling: +0.148, real but untradeable

At full fidelity — 56 survivorship-aware names, this project's own Kite→hygiene→Parquet data,
honest CNC delivery cost (0.22%), honest cumulative trial count (N=23), the gated CNC labeler,
and all four previously-dormant components wired (MetaLabeler, cross-sectional, frac-diff,
honest N):

| Strategy | validated | yfinance | paths negative | DSR (N=23) |
|---|---|---|---|---|
| **DIRECT** (primary ensemble, `position = 2p−1`) | −0.156 | −0.196 | 100% | 0.000 |
| **META** (meta-label bet/no-bet + cross-sectional) | **+0.148** | **+0.154** | **0%** | **0.967** |

**Per-criterion kill-gate read (META):**

| # | Criterion | Value | Verdict |
|---|---|---|---|
| 1 | CPCV median path-Sharpe ann ≥ 1.0 | **+0.148** | ❌ **FAIL** (≈7× short) |
| 2 | DSR ≥ 0.95 | 0.967 † | ✅ pass |
| 4 | Fraction negative paths ≤ 0.05 | 0.000 (all 5 paths +) | ✅ pass |
| 5 | Profit factor ≥ 1.2 | 1.047 | ❌ **FAIL** |

The signal is **statistically real** (t-stat 3.71, all five CPCV paths positive, DSR-passing at
honest N, reproduced across two independent data sources) but **economically negligible**: a
+0.15 Sharpe at profit factor 1.05 fails the kill-gate's economic bar by a wide margin and is not
tradeable after honest retail costs.

† **DSR-convention honesty caveat.** The 0.967 is computed on the **path-concatenated** basis
(n = 158,865 = the φ=5 CPCV paths × ~31.8k events) — the *same* convention under which the
+0.662 battery reported "DSR 1.000," so the comparison is apples-to-apples. But the five paths are
overlapping reconstructions of the same ~31.8k events, so concatenating them inflates the effective
sample ≈ 5× and the t-stat ≈ √5. On **de-duplicated events** the t-stat is ≈ 1.66 (one-sided
p ≈ 0.05) — *marginal*, and the de-duplicated DSR would not clear 0.95. So the DSR "pass" is
convention-dependent and optimistic; the honest read is "a marginal, real, tiny edge," and it does
not change the verdict because **criterion 1 fails decisively regardless of the DSR.**

---

## 3. +0.662 → +0.148: the deflation, and its causes

The cleanest decomposition is the **DIRECT** strategy, which is the honest-input version of the
*same* `2p−1` recipe that produced +0.662:

> **+0.662** (49-name, yfinance, 0.14% cost, N=5, inline off-gated labeler, selected config)
> **→ −0.156** (56-name, validated, 0.22% cost, N=23, gated CNC labeler) — **net NEGATIVE.**

So under honest inputs the bare strategy does not merely shrink — it **goes negative**. The entire
+0.662 was inflation. The **+0.148** that the complete pipeline recovers is **not** the original
edge surviving; it is what the **cross-sectional + meta-labeling components add on top** of a
net-negative base (see §4).

The four measured causes of the deflation (aggregate measured; not individually ablated):

1. **Understated cost** — 0.14% vs the honest **0.22%** CNC delivery round-trip (0.10% STT on
   *both* legs + stamp + exchange/SEBI/GST). The gated cost model is MIS-only; 0.14% was a
   hard-coded script constant that under-charged even relative to that.
2. **Under-deflation** — N=5 vs the honest cumulative **N=23** across all P2R cycles
   (the p2.9-killgate + cycle-3a/4/5 + battery MLflow runs).
3. **Off-gated-path labeler** — the +0.662 used a Cycle-5 *inline* daily labeler (symmetric
   barriers, every-bar events). The gated path uses the project's CNC triple-barrier (asymmetric
   2.0/1.5 barriers, CUSUM event sampling) — a stricter, audited labeling.
4. **Selection** — the +0.662 battery baseline was a chosen/tuned configuration; the honest
   pipeline does not cherry-pick, and the honest-N DSR charges for the search.

---

## 4. Two things proved cleanly

**(a) The data source was never the problem.** Validated (own Kite→hygiene→Parquet) vs yfinance,
on the comparable DIRECT strategy, at both scales:

- 8-name: validated −0.222 vs yfinance −0.206 → **Δ = −0.016**
- 56-name: validated −0.156 vs yfinance −0.196 → **Δ = +0.040**
- 56-name META: validated +0.148 vs yfinance +0.154 → **Δ = −0.006**

All differences are noise-level. Moving onto this project's gated data path did **not** drop the
result — so the +0.662 was **never a yfinance hygiene or survivorship artifact.** The survivorship
universe is intact: of the names that left the Nifty-50 during 2021–2026, all were fetchable except
three (HDFC Ltd, Tata Motors, LTIMindtree) — and those three are **mergers / demergers /
restructurings, not collapses** (empirically confirmed: Kite serves removed-but-listed names like
BPCL/SHREECEM with full history; only the corporate-action-restructured symbols are gone). Excluding
them removes no tail loss, so the survivorship correction is materially complete for this universe.

**(b) Cross-sectional scale + meta-labeling is the entire edge.** The META strategy went from
**−0.285** (8 names) to **+0.148** (56 names), and at scale it beats the DIRECT strategy by **+0.30**.
The mechanism is exactly the meta-filter's design purpose: the bet/no-bet second stage sizes down
low-conviction trades, cutting cost drag enough to clear breakeven, while the cross-sectional
rank / sector-neutral features supply signal that only exists across a wide universe. On 8 names the
cross-sectional features have no power and meta-labeling cannot rescue a net-negative base; on 56
names they recover a real (if tiny) edge. The architecture is sound — it does what it was designed
to do. The signal is just too small.

---

## 5. Verdict (against the pre-committed bands)

Pre-committed routing for the 49-name honest smoke:

| Outcome | Action |
|---|---|
| honest path-Sharpe **> +1.0** | Stage 2 (execution-layer CNC build) + paper trading |
| **+0.3 to +0.8** | real-but-short → close-out with a finding |
| **≤ 0 / near zero** | close-out |

The result, **+0.148**, is positive but **below the +0.3 stop** → **CLOSE-OUT.**

**Stage 2 is not justified.** Realistic execution (depth-aware slippage, market impact, the full
Indian cost model) can only *reduce* a +0.15 Sharpe — there is no path from here to the +1.0 bar,
let alone to tradeable-at-retail. Committing the multi-week execution-layer CNC workstream to chase
a +0.15 edge that fails two kill-gate criteria would be exactly the kind of motivated continuation
the kill-gate exists to prevent.

---

## 6. What was left more complete than we found it

The gated-path infrastructure built during this cycle is correct, tested, and useful regardless of
the verdict (committed separately):

- **CNC holding mode in the gated labeler** (`barriers.vertical_anchor_positions` + `LabelingConfig.holding_mode` + both labelers) — fills a real architectural gap (the labeling layer was MIS-intraday-only and produced zero labels on daily bars). **MIS behaviour is preserved byte-for-byte**; CNC is opt-in via config, with unit tests for both modes.
- **8 new TA-Lib technical indicators** (`cci`, `directional_index`, `williams_r`, `money_flow_index`, `sma`, `volume_weighted_ma`, `bollinger_bands`, `macd_line`), all **registered in the P1.8 adversarial leakage suite** (no-lookahead + no-future-correlation).
- **The complete gated research pipeline** (`scripts/run_complete_pipeline.py`) — daily/CNC, harness features, MetaLabeler, cross-sectional, frac-diff, honest-N DSR, two-data-source comparison.

Known remaining gap (documented, **not** built — out of scope and not justified by this verdict):
the **execution layer** (P2.1 backtester, P2.8 reconciliation engines, the cost model) is still
MIS-intraday-only and would need CNC modes for a faithful end-to-end daily/CNC product. That is the
held "Stage 2" workstream.

---

## 7. The Rule-7 read

Inviolable Rule 7 is intellectual honesty — *"report what is, not what you want."* This cycle is
what that looks like in practice: a claimed 60% / +0.662 edge, pursued in good faith to full
fidelity on the project's own gated apparatus, and reported at its true value — **+0.148, real but
untradeable** — with every inflation source measured and named, the data-quality worry definitively
cleared, and the one genuinely-positive component (cross-sectional + meta-labeling) credited for
exactly what it contributes and no more. The apparatus did not fool itself, and it did not let an
appealing number survive contact with honest costs and honest deflation. The architecture is sound;
the edge is too small. **Closed.**
