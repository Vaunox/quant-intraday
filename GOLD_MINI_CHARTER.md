# GOLD_MINI_CHARTER.md

**Status:** PRE-REGISTRATION — commit this file to the `gold-mini` branch BEFORE writing any strategy code or running any backtest.
**Branch:** `gold-mini` (forked from the framework-complete commit, equity research excluded)
**Purpose:** Determine whether a leveraged MCX Gold Mini strategy is *doable* — defined here as passing two independent, pre-committed gates. Research is done in this repo; a clean production repo is created ONLY on a dual-gate PASS.

> The entire credibility of this test rests on the two numbers in Section 2 being filled in by the client, in writing, BEFORE the first result is unblinded. Last project's close-out was credible because the stop band was committed before the number was known. Same rule here. Do not start without these.

---

## 1. Why this exists (context)

The Phase 2R equity research program closed with an honest verdict: **META +0.148 annualised Sharpe — real, but economically untradeable at current capital scale.** All CPCV paths positive; result below the pre-committed +0.3 stop band.

The Gold Mini pivot attacks the **"at current capital scale"** clause via leverage + materially lower transaction costs (~8–10 bps modeled round-trip vs 22 bps on the equity CNC book). It does **not** attack the **"is the edge real"** clause — leverage scales returns and volatility together and leaves Sharpe unchanged. These are two separate questions and get two separate gates.

**Instrument:** MCX Gold Mini (100 g futures contract). Futures mechanics → maps to the existing MIS execution layer. Gold Petal rejected (illiquid, compulsory delivery). Gold ETF deferred (no leverage; unresolved STT cost question).

---

## 2. THE TWO GATES — client must specify both before kickoff

### Gate 1 — Is the edge REAL? (statistical)
Unchanged from the equity phase. Leverage does NOT relax this.

- **DSR-corrected Sharpe threshold: +0.3 annualised** (COMMITTED). Same band as the P2R close-out. NOT lowered for the leveraged book — leverage scales return and vol together and leaves Sharpe unchanged, so relaxing this would be the two-gates confusion this charter exists to prevent. Single-instrument gold has fewer independent samples than the 56-name book, which makes +0.3 generous here, not strict.
- **PBO < 0.5** (COMMITTED). Above 0.5 = more likely overfit than not. Binary.
- **CPCV:** all paths must be positive (COMMITTED). Binary.
- **Stress battery:** all tests green, same battery as P2.8 (COMMITTED). Binary.
- **Honest trial count (N):** tracked from trade one; every threshold, feature-set, and hyperparameter sweep counts. DSR correction applied against running N at every unblinding.

### Gate 2 — Is it economically VIABLE? (rupee target)
This is the gate leverage actually moves. The two RISK CAPS below are committed (they're risk-management standards, not preferences). The two CLIENT DECISIONS are genuine risk-appetite calls and cannot be set for the client.

**Committed risk caps:**
- **Max drawdown / risk-of-ruin: 20% hard kill** (COMMITTED). A discipline number, not a taste number. On a leveraged book this is what stops a thin-edge strategy from becoming a blow-up.
- **Leverage cap: 3x to start** (COMMITTED) — NOT the ~10x the margin allows. You're testing whether an edge exists, not maximizing exposure to one you haven't confirmed. Cheap to raise later; expensive to discover you over-levered a mirage. The backtest does NOT get to choose this.

**Client decisions (in writing, before kickoff):**
- **Capital base:** `[CLIENT TO SPECIFY — ₹]`. Frame honestly as "money you can lose entirely" — 3x leverage with a 20% DD cap makes large loss reachable.
- **Return target that counts as "doable":** `[CLIENT TO SPECIFY]`. Do not ask "what number sounds good." Ask: *given the 20% DD cap and 3x leverage, what annual/monthly return on your capital base makes this worth doing versus just buying a gold ETF and holding it?* The strategy must beat passive gold exposure net of all costs — otherwise it's effort for nothing. That ETF-benchmark is the honest floor for this number.

### Verdict logic
- **Both gates PASS** → project is doable → create clean production repo (Section 6).
- **Either gate FAILS** → documented honest "no," same as P2R close-out. No repo.
- A weak-but-real edge that fails Gate 2 is NOT rescued by cranking leverage. That just converts a small edge into a large gamble.

---

## 3. Model plan — PHASED, not a menu

> Critical: the three model families below are NOT alternatives to try until one works. Running all three and reporting the best is best-of-N selection bias — the exact inflation source the forensic audit caught. Each family tested is a trial against the DSR budget.

### Phase 1 (RUN FIRST): A + B — directional, regime-gated
Reuses ~80% of the existing framework. Maps to the already-built MIS execution layer. Fastest path to an honest verdict.

- **A — Directional model:** the EXISTING stack, not a rebuilt sign-classifier. Triple-barrier labeling, meta-labeling, LightGBM+XGBoost+logistic ensemble, purged CV. Do NOT downgrade to a fixed-horizon sign predictor with a hand-tuned probability threshold.
- **B — Regime gate:** the EXISTING GMM gate, applied as a *gate* (when/how-much to trade), NOT as cross-asset allocation — single instrument, nothing to allocate. Gold's strong regime structure (real rates, risk-off, INR/USD) is the hypothesis being tested, not an assumption.

### Phase 2 (PRE-REGISTERED FALLBACK): C — Gold–Silver cointegration pairs
Committed here, now, before Phase 1 is unblinded. Triggered ONLY if Phase 1 fails Gate 1.

- **Why pre-registered:** relative-value sidesteps the single-asset low-Sharpe / few-independent-samples problem and may be the stronger horse — which is exactly why it cannot be a post-hoc "let's just try pairs" reach. That would re-introduce selection bias.
- **Approach:** Kalman filter for the dynamic hedge ratio; cointegration test on the Gold–Silver spread. (High Gold–Silver correlation is desirable here — it's what makes cointegration viable.)
- **Off-stack caution:** the baseline doc suggested SVM. Do NOT add SVM just because it was named. Justify any new model class against the existing tree-ensemble stack before adopting.
- **New infra cost:** two-instrument data + execution, spread construction, separate cost model. Scope this honestly before starting.

### Explicitly NOT in scope (cut from equity research)
56-name survivorship universe, cross-sectional ranking, HRP / inverse-vol portfolio construction, ETF-specific paths. None survive single-instrument gold.

### Explicitly RETAINED (framework — not "research tweaks")
Triple-barrier labeling, meta-labeling, GMM regime gate, CPCV, DSR, purged CV, honest-N tracking, conservative cost modeling. Resetting past these = rebuilding the audit's three inflation traps.

---

## 4. FIRST TASK — cost-verification gate (blocks all backtests)

No Sharpe is trustable until the cost model is fed REAL numbers, not estimates. Before any strategy code runs:

1. Pull a real **MCX Gold Mini** contract note. Confirm actual CTT, exchange txn charge, GST, SEBI, stamp duty.
2. Measure **live bid-ask spread** on Gold Mini (near-month) across a few sessions — the real cost driver.
3. Add a separate **monthly roll** cost line (spread + brokerage to roll) and account for the **contango/carry** embedded in the futures basis.
4. Populate the cost model. Conservative placeholder until verified: **~8–10 bps round-trip all-in + roll line.** Replace with measured numbers before trusting any result.

---

## 5. Honest-N / trial-count policy

- N starts at 1 on the first backtest and increments on every threshold, feature-set, label-parameter, and hyperparameter choice.
- Report N alongside every Sharpe.
- DSR correction applied against the running N at every unblinding.
- If Phase 2 (C) is run, its trials add to the budget — the verdict accounts for both families tested.

---

## 6. Graduation to production repo (only on dual-gate PASS)

Trigger: Gate 1 AND Gate 2 both pass, documented.

Then, and only then:
- Create clean repo (e.g. `Vaunox/quant-gold-mini`).
- Port: verified cost model, the passing strategy, the framework modules, the charter + result.
- Build the one piece of infra the pivot still owes if the daily/ETF path is ever revisited; for Gold Mini the MIS execution layer already covers it.
- Leave the research history in `quant-intraday` for audit.

If either gate fails: write the close-out note, archive the branch, no repo. An honest no is a result.

---

## 7. Sign-off (before kickoff)

- [ ] Gate 1 thresholds confirmed (COMMITTED: +0.3 DSR, PBO<0.5, CPCV positive, stress green)
- [ ] Gate 2 risk caps confirmed (COMMITTED: 20% DD hard kill, 3x leverage cap)
- [ ] Gate 2 capital base filled in (client decision)
- [ ] Gate 2 return target filled in (client decision, using the gold-ETF-benchmark framing)
- [ ] This file committed to `gold-mini` before any strategy code
- [ ] Cost-verification gate (Section 4) scheduled as task #1
