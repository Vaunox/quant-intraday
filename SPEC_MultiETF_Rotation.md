# SPEC_MultiETF_Rotation.md

**Type:** Internal research hypothesis spec. NOT a client-facing promise. NOT a validated strategy.
**Purpose:** Define a falsifiable test of whether an ML-driven tactical rotation across a basket of liquid Indian ETFs beats a fixed-weight rebalanced basket, net of costs, with the same rigor as every prior phase. Decide GO / NO-GO on *evidence*, not on the idea sounding clean.

> Read this honestly: this is the CLOSED equity architecture (cross-sectional ranking + regime gate + portfolio construction) re-pointed at a small ETF universe. It is not an escape from the Phase 2R "+0.148, real but untradeable" verdict — it is a re-run of that machinery on a different universe. The close-out is therefore *evidence*, not history. Same gates, same honest N, no fast-track because the idea feels simpler.

---

## 1. Hypothesis (the one thing being tested)

An ML model that reallocates capital across a basket of liquid ETFs (overweighting those with higher predicted forward return, underweighting/exiting those with lower) produces a **risk-adjusted return that beats a fixed-weight rebalanced version of the same basket, net of all costs, after DSR correction.**

If it cannot beat fixed-weight rebalancing net of costs → NO-GO. That is the entire test.

## 2. Why it might work / why it might not (both sides, up front)

**For:**
- Returns to **cross-sectional allocation** — the most defensible part of the existing stack, and the part discarded when the project went single-instrument. Relative calls ("which asset rises more") are easier to find and slower to arb than absolute timing.
- ETFs are **divisible** → the ₹1 lakh granularity problem that killed Gold Mini / complicated Petal disappears. Position sizing works at any capital.
- Basket assets are **genuinely different return drivers** (Indian equity, US equity, gold, cash) → real diversification lifts portfolio Sharpe even when each leg is mediocre.
- The cash leg (Liquid BeES) **earns the overnight rate (~5–6%) and is pledgeable** → "flat" is not idle drag.

**Against:**
- This is the **closed equity stack**. Unlevered, it re-opens the exact economics problem ("real but untradeable at current capital scale") that the gold pivot existed to solve. A modest edge on ₹1 lakh of ETF makes pocket change.
- **Few assets = thin cross-section.** The equity book ranked 56 names; a handful of ETFs gives the ranker almost nothing to rank. Risk: this collapses into a macro tactical-allocation call on 3–8 correlated risk assets, not a true cross-sectional edge.
- **The benchmark is brutal.** A static fixed-weight basket rebalanced quarterly costs almost nothing and is famously hard to beat. The honest base rate: most tactical overlays *underperform* fixed-weight after costs.
- ETF costs re-enter: expense-ratio drag, tracking error, and the unresolved **STT-on-ETF** question from the earlier cost analysis.

## 3. Candidate universe (LIQUIDITY-GATED, not a wishlist)

Liquidity falls off a cliff after the top names. The tradeable universe is **determined by a volume measurement (Section 7, Step 1), NOT by this list.** An ETF is only in the basket if its daily traded value supports the rebalance turnover at ₹1 lakh scale without the spread eating the edge. Indicative tiers from public 1Y avg-volume data (VERIFY live — these are scaffolding):

**Tier 1 — genuinely liquid (~₹25 cr+/day), default candidates:**
- `NIFTYBEES` — Nippon Nifty 50 (~₹80 cr/day; broad Indian large-cap)
- `SETFNIF50` — SBI Nifty 50 (~₹26 cr/day)
- `BANKBEES` — Nippon Nifty Bank (highest-volume sectoral)
- `GOLDBEES` — Nippon Gold (~₹27 cr/day; the gold leg)
- `SILVERBEES` — Nippon Silver (~₹28 cr/day; second commodity, low equity correlation)
- `LIQUIDBEES` — Nippon Nifty 1D Rate Liquid (~₹323 cr/day; the CASH leg — earns overnight rate, pledgeable)

**Tier 2 — moderate (single-digit ₹cr/day), include only if volume test passes:**
- `JUNIORBEES` — Nifty Next 50 (~₹9.7 cr/day)
- `MON100` — Motilal Oswal NASDAQ 100 (US-equity leg; **flag:** international ETFs face periodic subscription freezes from overseas-investment caps — operational risk to verify)
- `ITBEES` — Nifty IT (sectoral; correlated to MON100 via tech)
- A liquid midcap ETF (e.g. Nippon Nifty Midcap 150) if volume supports it

**Tier 3 — thin: EXCLUDE from daily/weekly rebalance regardless of how attractive the exposure looks.** Slippage will exceed any edge.

**Universe design note:** the goal is *genuinely different return drivers* with *enough breadth to rank*. A sane starting basket: Indian large-cap (NIFTYBEES), Indian banks (BANKBEES), US equity (MON100), gold (GOLDBEES), silver (SILVERBEES), cash (LIQUIDBEES) — 5 risk assets + cash. That is the floor for "something to rotate among." Widen toward 8–10 only with ETFs that clear the volume gate.

## 4. The benchmark (what GO/NO-GO is measured against)

**Primary benchmark: fixed-weight equal-weight basket, rebalanced on a fixed schedule (e.g. monthly), same universe, same cost model.** The ML strategy must beat THIS, net of costs, DSR-corrected. Not "beat zero." Not "positive Sharpe."

**Secondary floors:**
- Must beat **buy-and-hold of the single best static asset** would-be-known-only-in-hindsight is NOT a fair benchmark — but must beat **buy-and-hold NIFTYBEES** (the default "do nothing" Indian-equity option) net of costs.
- Must beat **holding LIQUIDBEES** (risk-free-ish ~5–6%). If a risk-taking strategy can't beat parked cash, it fails.

## 5. Gates (committed — same as GOLD_MINI_CHARTER, adapted to benchmark-relative)

### Gate 1 — Is the edge REAL? (statistical)
- **DSR-corrected Sharpe of (strategy − fixed-weight benchmark): > +0.3** (COMMITTED). The bar is on the *excess* over fixed-weight, because beating zero is not the question.
- **PBO < 0.5** (COMMITTED).
- **CPCV:** all paths' excess-return positive (COMMITTED).
- **Stress battery:** green (same battery as P2.8).
- **Honest N:** tracked from trade one; every universe choice, rebalance frequency, lookback, threshold, and hyperparameter counts. Note: choice of basket members is ITSELF a trial — selecting the universe that backtests well is selection bias. Pre-commit the universe before scoring, or count every variant.

### Gate 2 — Is it economically VIABLE? (rupee)
- **Capital base:** ₹1,00,000 (divisible ETFs → no granularity problem; works).
- **Leverage:** none (long/flat/rotate only). The leverage caps from the gold charter do not apply.
- **Return target:** must clear the **fixed-weight + buy-and-hold-NIFTYBEES + LIQUIDBEES floors** in Section 4, net of all costs. The client's prior 30–35% figure is only legitimate if it survives as *excess over fixed-weight*, not as gold/equity beta the basket would have earned anyway.
- **Max drawdown cap:** **20% hard kill** (CLIENT-SPECIFIED, 2026-06-28). Same discipline number as the gold charter; a real risk decision even unlevered.

### Verdict
Both gates pass on the benchmark-relative basis → GO (build properly, consider clean repo). Either fails → documented NO-GO. A strategy that makes money but loses to fixed-weight rebalancing is a NO-GO — it means the ML added nothing and you should just rebalance dumbly.

## 6. Cost model (re-uses the cost discipline, ETF-specific)

Per the earlier cost analysis — populate with MEASURED numbers before trusting any result:
- **Brokerage:** ETF delivery ~₹0 at Zerodha (verify).
- **STT on ETF:** **RESOLVED at the low end (2026-06-28), per Zerodha's official charges page** — equity ETFs (NIFTYBEES, BANKBEES) STT **0.001% sell-side only** (₹1/lakh ≈ 0.1 bps); gold/silver/liquid/gilt ETFs (GOLDBEES, SILVERBEES, LIQUIDBEES) **no STT**; international (MON100) likely exempt ("some international ETFs"). So the ~20 bps fear is off — the dominant cost is spread + DP charges, not STT. *Residual:* confirm MON100 on the NSE STT-non-applicability report / a real note; broker-page figures still want a contract-note final check before a trusted net Sharpe.
- **Exchange txn, GST, stamp, DP charges:** scaffold from broker calculator, verify on note. **Flag (2026-06-28):** Zerodha's flat **DP charge (~₹13.5 + GST per scrip per sell)** is regressive at ₹1 lakh — on a ~₹16k leg that is ~10 bps *per sell*, plausibly the dominant per-rebalance cost at this capital. Model it as a flat per-leg-sold fee, not a bps rate.
- **Bid-ask spread + impact:** THE dominant cost. Measure live per-ETF (Section 7). Rebalance turnover × spread is the real drag — a frequent rebalance on a thin leg is where the edge dies.
- **Expense-ratio drag:** continuous NAV haircut per leg (e.g. GOLDBEES ~0.35–0.8%), weighted by time held.
- **Tracking error** per leg.

## 7. Phased research plan (what to measure, in order)

**Step 1 — Universe liquidity gate (do first, pure historical data).** Pull daily traded-value history for every Tier 1/2 candidate. Keep only ETFs whose volume supports the intended rebalance turnover at ₹1 lakh without material impact. Output: the *actual* tradeable universe. This may shrink the basket — that is information, not failure.

**Step 2 — Cost model populated** with measured spreads (Section 6), STT confirmed.

**Step 3 — Build fixed-weight benchmark first.** You cannot measure excess return without the thing you're beating. Implement equal-weight monthly rebalance, net of the Step 2 cost model. This is the line in the sand.

**Step 4 — ML rotation through the full framework.** Triple-barrier / forward-return labels per asset, the existing regime gate (regimes now mean *which asset class is favoured* — gold in risk-off, equity in risk-on), cross-sectional ranking across the gated universe, portfolio construction (inverse-vol / HRP), honest N from trade one.

**Step 5 — Unblind excess return vs fixed-weight** against Gate 1. DSR-correct on running N.

## 8. Pre-registered kill criteria (decide before seeing results)

NO-GO if any of:
- Tradeable universe (Step 1) shrinks to < 4 risk assets → too thin to call it cross-sectional; it's a macro bet, abandon or redesign.
- Excess Sharpe over fixed-weight fails the +0.3 DSR bar.
- Strategy beats fixed-weight gross but not net of costs → the edge is smaller than the turnover cost; NO-GO.
- STT-on-ETF resolves to equity-rate AND turnover is high enough that costs dominate → revisit rebalance frequency before proceeding.

## 9. Relationship to prior work

- This re-uses, not discards, the Phase 2R framework. The validation machinery (CPCV, DSR, purged CV, triple-barrier, meta-labeling, regime gate, HRP) all port directly. The honest-N discipline and the forensic-audit lessons (GAN leakage, best-of-N, undercooked costs) apply unchanged.
- The "+0.148 real but untradeable" verdict is the relevant prior. If this strategy lands in similar territory unlevered, the same economic-viability problem applies — that is the thing Gate 2 exists to catch honestly rather than rationalize away.

---

## Sign-off before research starts
- [x] Universe NOT scored until liquidity gate (Step 1) defines the tradeable set — DONE 2026-06-28, frozen (`docs/etf_rotation/step1_liquidity_gate.md`)
- [ ] Fixed-weight benchmark built BEFORE the ML strategy (Step 3 before Step 4)
- [~] STT-on-ETF resolved from Zerodha's official charges page (low end: ≤0.1 bps equity legs, 0 elsewhere; §6). Contract-note final check + MON100 confirmation still owed before trusting a net Sharpe.
- [ ] Honest N includes universe selection and rebalance-frequency choices
- [x] Client max-drawdown cap recorded — 20% hard kill (2026-06-28, §5)
- [ ] Framed to client as a RESEARCH TEST with a real possible NO-GO — not a finished product
