# Deep Dive #2 — The Research Layer

*Modules 3, 4, 4b of the pipeline: labeling & dataset construction, the model stack, and the anti-overfitting validation engine. This is where you find out whether any edge is real. Equal depth on all three, as requested.*

**Context locked from Deep Dive #1:** first system trades **liquid cash equities intraday (MIS)** on a **15-minute decision clock**, square-off by ~15:20, features computed from finer data but decisions on 15-min bars. Two facts from that choice shape everything below:
- The **vertical (time) barrier is bounded by auto-square-off** — you physically cannot hold overnight, so every label resolves within the same session (≤ ~25 fifteen-minute bars).
- The **all-in round-trip cost hurdle is ~0.12–0.20%** of a liquid MIS position. *Every* labeling and modeling decision must respect that an average trade has to clear this to be worth taking.

---

## The mental model for this layer

Most retail quant effort goes into models. That's backwards. The ranking of what actually determines success:

1. **Not fooling yourself (validation).** A wrong validation makes everything else noise.
2. **Labels.** What you ask the model to predict matters more than the model.
3. **Sample weighting & stationarity.** Financial data violates the IID assumptions ML libraries silently rely on.
4. **The model.** Genuinely the easy part once 1–3 are right.

So this document front-loads labeling and back-loads the model, then spends the most rigor on validation.

---

## Module 3 — Labeling & Dataset Construction

### 3.1 Why fixed-horizon labels are a trap

The naive label — "return over the next N bars, sign it" — has three fatal flaws for intraday trading:

- It ignores the **path**. A trade that would have hit your stop-loss at -1% before recovering to +0.5% gets labeled +1 (a winner), but you'd have been stopped out in reality. The label teaches a fantasy.
- It uses a **fixed horizon** regardless of volatility. The same N bars means something completely different in a calm open vs a volatile post-news spike.
- It labels **every bar**, including bars where nothing is happening — drowning the real signal in noise.

### 3.2 The Triple-Barrier Method (the correct intraday label)

For each candidate entry, set **three barriers** and label by whichever is touched *first* (this path-dependence is the whole point — it directly solves the stop-loss problem):

- **Upper / profit-take barrier** → label **+1**
- **Lower / stop-loss barrier** → label **−1**
- **Vertical / time barrier** (max holding period) → label **0** (or the sign of the return at expiry)

```
 price
   │            ┌───────────────  ← upper barrier (+1)  e.g. +2σ
   │      ╱╲   ╱
   │     ╱  ╲ ╱
   │ ───●────╳──────────────────  entry
   │         ╲
   │          ╲___________________ ← lower barrier (−1) e.g. −1.5σ
   └──────────────┴───────────────── time
                  ↑ vertical barrier = square-off / max hold (0)
```

**Critical design choices for our context:**
- **Barriers are volatility-scaled, not fixed.** Set upper/lower as multiples of recent realized volatility (e.g. rolling ATR or EWMA σ): `upper = k_up · σ_t`, `lower = k_dn · σ_t`. This makes labels comparable across calm and volatile periods. Asymmetric multiples encode your risk preference (e.g. tighter stop than target).
- **The lower barrier must clear the cost hurdle logic.** A profit-take barrier smaller than ~0.2% is labeling moves you can't profit from after costs. Size barriers so a +1 is actually a tradeable win.
- **The vertical barrier = end-of-session.** Because MIS auto-squares-off, the natural max-hold is "rest of the day." You can also set it shorter (e.g. 2 hours) to control turnover.

### 3.3 Event-based sampling (don't label every bar)

Rather than evaluating an entry at every 15-min bar, use a **CUSUM filter** to trigger candidate events only when cumulative price movement exceeds a threshold — i.e., sample when *something is happening*. This:
- removes long stretches of dead, noisy bars,
- produces more balanced, more informative labels,
- reduces the dataset to meaningful decision points.

You can also trigger events on your own primary signal firing (see meta-labeling below) — that's often the most natural event definition.

### 3.4 Meta-Labeling (the single highest-leverage technique here)

This is López de Prado's key contribution and it maps *perfectly* onto the cost-hurdle problem. Split the decision into two models:

- **Primary model → SIDE.** Decides long / short / flat. Tune it for **high recall** — catch most of the real opportunities, tolerate false positives.
- **Secondary (meta) model → BET or NO-BET (and size).** A binary classifier that takes the primary model's signal *plus* features and decides **whether to actually take the trade**, correcting the primary model's low precision.

Why this is so powerful for us:
- The meta-model is the **natural home for the cost hurdle.** You train it to bet only when the expected, probability-weighted move exceeds your ~0.15% round-trip cost. It learns "is this signal strong enough to be worth the friction?"
- It improves accuracy, precision, recall, and F1 of the overall system.
- It cleanly separates **what direction** (primary) from **how confident / how much** (meta), which is also exactly the input bet-sizing needs (Deep Dive #3).
- The primary model can even be a *simple rule* (e.g. a momentum or mean-reversion signal); the ML lives in the meta-model deciding when to trust it.

**Bet sizing from meta-probability:** the calibrated probability from the meta-model maps to position size — higher conviction, larger size (capped). This requires **calibrated** probabilities (Platt/isotonic scaling), or your sizing is garbage.

### 3.5 Sample weighting — because financial labels are NOT IID

ML libraries assume independent samples. Financial labels violate this badly: overlapping triple-barrier windows share the same underlying returns, so two "samples" can be largely the same information. Train naively and the model is effectively trained on far fewer independent observations than your row count suggests — and it overfits.

The fixes (all from *Advances in Financial ML*, ch. 4):

- **Concurrency / uniqueness.** At each time *t*, count how many label windows are simultaneously active: `c_t`. The **instantaneous uniqueness** of a sample at *t* is `1/c_t`. A label's **average uniqueness** is the mean of `1/c_t` over its window. Overlapping (redundant) labels get down-weighted; unique ones get up-weighted. This is the single most important correction.
- **Sequential bootstrap.** When bagging, draw samples in proportion to uniqueness rather than uniformly, so each bootstrap sample carries more independent information. (This is *why* a uniqueness-aware bagged ensemble generalizes better.)
- **Time-decay weights.** Weight more recent observations higher — markets are non-stationary and older relationships decay.
- **Return-attribution weights.** Weight samples by the magnitude of the return they're associated with, so large, meaningful moves matter more than tiny ones.

### 3.6 Fractionally Differentiated Features — the stationarity/memory dilemma

ML wants **stationary** inputs (stable distribution); raw prices are non-stationary. The usual fix — take returns (full differencing, `d=1`) — makes the series stationary but **erases its memory** (level information, long-range structure). That memory is often where the signal is.

**Fractional differentiation** is a "dimmer switch" between the two: differentiate to a *fractional* order `d ∈ [0,1]`.
- `d=0`: raw series — full memory, non-stationary.
- `d=1`: returns — stationary, memoryless.
- **Goal:** find the *minimum* `d` that just passes a stationarity test (ADF), preserving the maximum possible memory while satisfying the model's statistical needs.

Apply this to price-derived features so they're stationary *and* retain predictive memory. (Note: this matters more for level/price features than for already-stationary microstructure features like OFI.)

**Output contract of Module 3:** an event-sampled, triple-barrier-labeled, sample-weighted dataset with stationary-but-memory-preserving features, a primary-side label, and a meta bet/no-bet label — built point-in-time, versioned, ready for purged cross-validation.

---

## Module 4 — The Model Stack

The order matters: establish the simplest thing that could work, prove it, then add complexity only to beat a measured baseline.

### 4.1 Build order

**Step 1 — Baseline (do this first, always).**
Logistic regression / a single **LightGBM** classifier on the primary-side label. If a clean, well-labeled, cost-aware baseline isn't profitable in honest validation, **no deeper model will save it** — that's your signal to iterate on features/labels or kill the idea, cheaply.

**Step 2 — Gradient-boosted ensemble (the workhorse).**
**LightGBM + XGBoost** as the core. Gradient boosting consistently matches or beats deep learning and RL on tabular, low-signal-to-noise financial data. Use uniqueness-aware bagging (sequential bootstrap). This is your primary alpha engine.

**Step 3 — Cross-family ensemble.**
Combine boosting + a linear/logistic model + (optionally) a shallow net via **rank-averaging or stacking**. Diversity across model *families* is more robust than one big tuned model. Diversity is a free lunch; tuning a single model harder is not.

**Step 4 — Regime gate.**
An **HMM or Gaussian Mixture Model** on volatility/trend features classifies the current regime (trending / ranging / high-vol / low-vol). Strategies/models are switched on or off — or sized down — by regime. This directly addresses non-stationarity and is a core Renaissance-style idea (different patterns persist in different regimes).

**Step 5 — Meta-model (from §3.4).**
The binary bet/no-bet classifier sits on top, encoding the cost hurdle and producing calibrated conviction for sizing.

### 4.2 Things people get wrong

- **Feature importance: use MDA/SHAP, not MDI.** Mean-Decrease-Impurity (the default `feature_importances_`) is biased toward high-cardinality features and is distorted by substitution effects among correlated features. Use **Mean-Decrease-Accuracy (permutation importance)** or SHAP, computed *within the purged CV* so importance isn't itself leaking.
- **Probability calibration is mandatory** if you size by conviction. Raw boosting/​net probabilities are not calibrated; apply isotonic/Platt scaling on a held-out (purged) set.
- **Hyperparameter tuning must use purged CV.** Tuning with ordinary k-fold leaks and overfits the tuning itself — you'll pick hyperparameters that look great only because they memorized leaked future data.
- **Keep capacity modest.** Shallow trees, strong regularization, early stopping on a purged validation fold. The goal is a small robust edge, not a perfect in-sample fit.

### 4.3 What we are deliberately NOT doing yet (and why)

- **Deep learning (TCN, LSTM/GRU, Temporal Fusion Transformer, 1D-CNN on the book).** Real upside *only* with rich order-book/tick data and a GPU budget, and it overfits noisy financial data without heavy care. Revisit **only after** the boosting baseline is profitable and you have live 5-depth data to learn from. 1D-CNNs and sequence models genuinely shine at extracting features from order-book dynamics and trade-flow imbalance — but that's a phase-2 capability, not a day-1 one.
- **RL for alpha.** Fragile, overfits training regimes, poor out-of-sample transfer. Reserved for the **execution/sizing** layer (Deep Dive #4), where the action space is small and the reward well-defined.

**Output contract of Module 4:** a versioned, calibrated primary+meta model pipeline with permutation/SHAP importances, trained under purged CV, gated by a regime model — every artifact tagged with the data + feature + label versions it was trained on.

---

## Module 4b — The Anti-Overfitting Validation Engine

This is the make-or-break module. Two *different* questions need two *different* tools — conflating them is a classic error:

> **Q1: Is the edge real, or did I overfit?** → CPCV + Deflated Sharpe + PBO.
> **Q2: What would live trading realistically have looked like?** → walk-forward with a full cost model.

### 4b.1 Purging and embargoing (the foundation under everything)

Ordinary k-fold cross-validation **leaks** in finance because (a) labels span time windows that overlap across folds, and (b) serial correlation makes adjacent observations non-independent. Two corrections, applied to *every* CV here:

- **Purging:** remove from the *training* set any observation whose label window overlaps the test set's time span. Kills the most direct leak.
- **Embargoing:** drop a small buffer of observations immediately *after* the test set before resuming training, so serial correlation can't leak test information into training. Embargo length ≈ the label horizon.

Without these, every number below is optimistic fiction.

### 4b.2 Combinatorial Purged Cross-Validation (CPCV) — the SOTA for "is it real?"

Walk-forward gives you exactly **one** historical path, so its Sharpe reflects one particular ordering of luck. CPCV instead generates **many** out-of-sample paths and looks at the whole distribution.

**Mechanics:** partition the timeline into **N groups**. Choose **k** of them as the test set each time. This yields `C(N,k)` train/test splits, which stitch together into

**φ = C(N,k) · k / N  distinct backtest paths**

(e.g., N=6, k=2 → C(6,2)=15 splits → φ = 15·2/6 = **5 complete paths**, each covering the full timeline once). Compute the performance metric (Sharpe, etc.) **per path** — *the paths, not the individual splits, are the correct unit*.

**How to read it — this is the key insight:**
- A **robust** strategy shows a **narrow, positive distribution** of path-Sharpes — it works across many temporal configurations.
- A **fragile** strategy shows **wild variance** across paths — high mean is meaningless if some paths are deeply negative. Fragility disqualifies a strategy *regardless of its average*.

The synthetic-controlled literature finds CPCV materially better than walk-forward at false-discovery prevention (lower PBO, higher Deflated Sharpe). This is your primary "is the edge real?" test.

### 4b.3 Deflated Sharpe Ratio (DSR) — correcting for how many things you tried

A high Sharpe is trivially manufacturable if you try enough configurations. The **Deflated Sharpe Ratio** corrects the significance of an observed Sharpe for:
- the **number of trials** you ran (every strategy/parameter combo you tested),
- the **skewness and kurtosis** of returns (finance is fat-tailed and skewed),
- the **sample length**.

You must therefore **honestly track your trial count** — every backtest variant counts, even the ones you discarded. Report DSR, not raw Sharpe. A raw Sharpe of 2 from 500 trials can deflate to insignificance.

### 4b.4 Probability of Backtest Overfitting (PBO)

Via **Combinatorially Symmetric Cross-Validation (CSCV)**: estimate the probability that the configuration that looked **best in-sample** actually **underperforms the median out-of-sample**. It's model-free and non-parametric. A high PBO means your selection process is just picking lucky overfits. Report it; treat anything above ~0.2–0.5 as a serious warning. As the multiple-testing literature (Harvey et al., the "factor zoo") argues, a new signal should clear a **t-statistic hurdle of ~3.0, not the conventional 2.0**, precisely because so many things have been tried.

### 4b.5 Walk-forward — the realistic-simulation tool (Q2)

Walk-forward (Pardo) re-optimizes on a rolling/expanding window and tests on the next out-of-sample slice, repeatedly — the closest thing to "what would I have actually experienced trading this live, re-fitting as I went." It remains the **industry standard for realistic simulation** even though CPCV beats it for false-discovery detection. Use it for the realistic equity curve, drawdown experience, and turnover — *after* CPCV says the edge is real. Consider **regime-aware segmentation** (condition train/test windows on volatility regime) to stress non-stationarity.

### 4b.6 The realistic backtester — where most "edges" die

The simulation must model reality or the P&L is fantasy. Mandatory:

- **Next-bar-open execution.** A decision on bar *t*'s close fills at bar *t+1*'s open. Never fill on the same close you used to decide. (Identical rule in research and live.)
- **Full Indian cost model — exact, per the broker's current schedule.** For intraday equity (MIS), the components are roughly:
  - Brokerage: lower of ~0.03% or ₹20 **per executed order**
  - STT: ~0.025% on the **sell side only** (intraday equity)
  - Exchange transaction charges: ~0.003% per side (NSE; verify current)
  - SEBI charges + stamp duty: small (stamp ~0.003% on buy)
  - GST: 18% on (brokerage + transaction + SEBI charges)
  - → all-in **~0.12–0.20% round trip** for a liquid name (lower for larger positions where the ₹20 cap dominates). **Pull exact numbers from a current brokerage calculator — these change.**
- **Slippage model:** 0.05–0.20% for liquid names, wider in volatile windows and near the open; scale with order size vs available depth (your 5-level depth from Deep Dive #1 informs this). Be conservative.
- **Latency:** simulate a realistic decision→fill delay.

### 4b.7 Robustness battery (run before trusting anything)

- **Parameter sensitivity:** does performance survive small parameter perturbations, or is it a knife-edge? Knife-edges are overfit.
- **Monte Carlo trade shuffle:** randomize trade order; is the equity curve's shape robust or luck?
- **Noise injection:** add small noise to prices/features; does the edge persist?
- **Cross-symbol validation:** does a signal trained on one set of names work on held-out names? Universal signals generalize; symbol-specific ones often overfit.
- **Synthetic-data backtesting:** simulate price paths (e.g., from an estimated OU/GARCH process) and test the strategy on data containing *no real historical luck* — López de Prado's recommended complement to historical backtests.
- **Implementation-risk check:** run the same strategy through **two engines** (fast VectorBT screen vs event-driven Backtrader/Nautilus) and reconcile — the same strategy can produce materially different numbers in different engines, and that discrepancy is itself a source of error you must quantify.

### 4b.8 Tooling

- **Methodology library:** `mlfinlab` (Hudson & Thames) implements triple-barrier, meta-labeling, uniqueness weighting, fractional differentiation, purged CV, CPCV, DSR, PBO — or implement from *Advances in Financial ML* directly. Either way, **understand the math**, don't black-box it.
- **Fast screening backtest:** **VectorBT** (vectorized, millions of param combos in minutes — exploration only).
- **Realistic backtest:** **Backtrader** or **Nautilus Trader** (modern, event-driven, high-fidelity) or **QuantConnect/LEAN**.
- **Tearsheets:** **QuantStats** / **pyfolio** (30+ metrics, drawdowns, Monte Carlo, rolling stats).
- **Experiment tracking:** **MLflow** — log every trial (this is also how you get an honest trial count for DSR).

**Output contract of Module 4b:** a validation report per strategy containing the CPCV path-Sharpe distribution, Deflated Sharpe, PBO, honest trial count, full-cost walk-forward equity curve, and the robustness battery results — sufficient to make a binary trade/don't-trade decision.

---

## The kill-gate (the most important paragraph in this document)

Before *any* capital — paper or real — a strategy must pass **all** of these, on honest, cost-inclusive, point-in-time data:

1. **CPCV median path-Sharpe > 1.0** after full Indian costs and slippage.
2. **Deflated Sharpe Ratio positive and significant** given your true trial count.
3. **PBO below ~0.2–0.5.**
4. **Narrow, positive CPCV path distribution** — no deeply negative paths (not fragile).
5. **Performance not concentrated in a handful of trades** (check profit factor and expectancy — a few outliers carrying everything is a red flag).
6. **Survives the robustness battery** (parameter sensitivity, noise, cross-symbol, synthetic).
7. **Edge stable across regimes**, not confined to one bull run.

**If it fails, it dies.** No tweaking-until-it-passes — that *is* overfitting, and it inflates your trial count (which DSR will then punish). Most ideas fail here. That is the system working correctly: failing on a laptop is free, failing on live capital is not.

---

## What I'd build for this layer (concrete spec)

A `research/` package:

1. **`labeling/`** — CUSUM event sampler; volatility-scaled triple-barrier labeler (vertical barrier = square-off); meta-label generator; sample-weighting (concurrency/uniqueness, time-decay, return-attribution); sequential bootstrap.
2. **`features_research/`** — fractional differentiation (auto-select min `d` via ADF); stationarity tests; the bridge to Deep Dive #1's feature store.
3. **`models/`** — baseline → LightGBM/XGBoost ensemble → cross-family stack → HMM/GMM regime gate → meta-model; permutation/SHAP importance under purged CV; isotonic calibration.
4. **`validation/`** — purged k-fold + embargo; **CPCV** with path reconstruction; **DSR**; **PBO/CSCV**; walk-forward with the **Indian cost model**; robustness battery; two-engine reconciliation; MLflow trial logging.
5. **`reports/`** — automated validation report + QuantStats tearsheet, emitting the kill-gate checklist as pass/fail.

**Build/validate order:** purged-CV + cost model + CPCV harness **first** (the judge before the contestants) → triple-barrier labels → LightGBM baseline → run the kill-gate → only if it passes, add ensemble/regime/meta and re-run. Do not proceed to the Capital Layer (Deep Dive #3) until a strategy clears the kill-gate.

---

## Open questions to settle for this layer

- **Primary signal seed:** start the primary model as a simple momentum rule, a mean-reversion rule, or a from-scratch ML classifier? (Meta-labeling works with any of these; a simple primary + smart meta-model is often the most robust first cut.)
- **Long-only vs long-short:** intraday equity MIS allows short-selling, but shorting has its own constraints/costs. Long-only is simpler for a first system.
- **Barrier asymmetry & max-hold:** how tight a stop vs target, and full-session hold vs a shorter cap (e.g. 2 hours)? This trades off win-rate, turnover, and cost drag.
- **PBO threshold and DSR significance level:** set the exact kill-gate thresholds before running, not after (setting them after seeing results is itself a form of overfitting).

---

*Next installment (Deep Dive #3 — the Capital Layer): turning calibrated signals into positions — signal combination, portfolio construction under exposure/correlation limits, position sizing (volatility targeting, fractional Kelly, the role of the meta-probability), and the hard, coded, non-overridable risk limits that sit above every model.*

*This is an engineering/research reference, not financial advice. Trading carries substantial risk of loss.*
