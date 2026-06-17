# Deep Dive #3 — The Capital Layer

*Modules 5 and 6 of the pipeline: turning calibrated signals into actual positions. Signal combination → portfolio construction → position sizing → the hard, coded risk limits that sit above every model. This is the layer where accounts actually blow up, so the emphasis is on robustness and survival, not optimization.*

**Context carried forward:** liquid cash equities, intraday MIS, 15-minute decision clock, square-off ~15:20. From Deep Dive #2 we now have, per candidate trade, a **side** (long/short/flat) and a **calibrated meta-probability** `p` (conviction that the trade clears the cost hurdle), with triple-barrier target/stop levels defining the payoff ratio.

---

## The mental model for this layer

A profitable signal and a blown-up account are fully compatible — the bridge between them is sizing and risk. The empirical and historical record is blunt about the hierarchy:

1. **Survival first.** No edge compounds if the account is dead. Hard limits dominate everything.
2. **Robust beats optimal.** The "optimal" portfolio/size computed from noisy estimates is usually worse out-of-sample than a simpler, robust rule. (Even equal-weighting routinely beats mean-variance optimization out-of-sample — a humbling, well-replicated result.)
3. **Sizing is a bigger lever than signal.** Going from full-Kelly to fractional-Kelly changes your survival odds more than a marginal signal improvement changes your returns.

So this layer is deliberately conservative. The fancy math (HRP, Kelly) is included, but the defaults lean simple.

---

## Module 5 — Signal & Portfolio Construction

### 5.1 From many signals to one target portfolio

The Renaissance lesson from Deep Dive #1: combine many weak signals into **one integrated book**, not a pile of independent bets. Concretely, at each 15-min decision point:

1. **Generate signals** for every name in the universe (side + meta-probability + expected edge).
2. **Combine** multiple models/strategies into a single conviction score per name.
3. **Rank** names cross-sectionally.
4. **Select** a candidate set (top-ranked longs, bottom-ranked shorts, subject to filters).
5. **Allocate** capital across the candidate set (portfolio construction).
6. **Size** each position and apply risk limits (Module 6).

**Signal combination methods (robust → fragile):**
- **Rank-averaging** (most robust): convert each model's output to a cross-sectional rank, average the ranks. Insensitive to any single model's scale/calibration quirks. Recommended default.
- **IC-weighted blending:** weight each signal by its recent **Information Coefficient** (rank-correlation of signal with realized forward return), so signals that have been working lately count more. A measured, adaptive step up from equal blending.
- **Stacking** (most powerful, most overfit-prone): a meta-learner combines signals. Only with the purged-CV discipline from Deep Dive #2, and only if it beats rank-averaging in honest validation.

Keep combination **simple first**. A robust blend of decent signals beats an overfit optimal combination of the same signals.

### 5.2 Cross-sectional selection

Intraday, **cross-sectional** signals (this stock vs its peers right now) are often more robust than pure time-series signals because they cancel market-wide moves — you're betting on *relative* performance, which is less exposed to a sudden index lurch. Select, e.g., the top-N by conviction for longs and bottom-N for shorts, after applying:
- **Liquidity/eligibility filters** (carried from Deep Dive #1): adequate ADV, tight spread, and — India-specific — **exclude ESM and T2T (trade-to-trade) surveillance stocks, which cannot be traded intraday at all.**
- **Spread/cost filter:** drop names whose current spread makes the expected edge fail the cost hurdle (the meta-model already encodes this, but a hard filter is a cheap safety net).
- **Event filter:** optionally avoid names with imminent scheduled events (earnings, etc.) unless the strategy is designed for them.

### 5.3 Portfolio construction — how to weight the selected names

This is where people reach for Markowitz and get punished. The decision ladder, from what I'd *start* with to what's *available*:

| Method | What it does | When to use | Caveats |
|---|---|---|---|
| **Equal weight (1/N)** | Same capital per position | **Default baseline.** Shockingly hard to beat out-of-sample; zero estimation error | Ignores risk differences across names |
| **Inverse-volatility / vol-weighting** | Weight ∝ 1/σ; lower-vol names get more | **Recommended v1.** Equalizes risk contribution crudely, still nearly estimation-free | Ignores correlations |
| **Hierarchical Risk Parity (HRP)** | Clusters names by correlation, allocates risk top-down via recursive bisection | When the universe is larger and correlations matter | Needs a stable correlation estimate; more machinery |
| **Mean-Variance Optimization (MVO/CLA)** | Maximize return/risk via quadratic optimization | **Avoid for a retail intraday system** | Markowitz's curse |

**Why avoid MVO here:** it requires inverting the covariance matrix and supplying an expected-return vector — both notoriously noisy. Small input errors produce wild, concentrated, unstable weights ("error maximization"). In a 500-name universe MVO estimates >125,000 covariance parameters; tiny errors blow up the weights. It famously underperforms even equal-weighting out-of-sample.

**Why HRP is the right *advanced* option (when you need one):** López de Prado's HRP replaces matrix inversion with three steps —
1. **Hierarchical clustering** of assets by correlation (a tree),
2. **Quasi-diagonalization** (reorder the correlation matrix into block-diagonal form),
3. **Recursive bisection** (split capital top-down, inverse-variance within each split).

It **does not require inverting** (or even the invertibility of) the covariance matrix — it works on ill-conditioned or singular matrices where MVO simply fails — and it needs **no expected-return vector**, removing a huge source of model risk. Monte Carlo and empirical studies show lower out-of-sample variance than the variance-minimizing optimizer itself, and meaningful drawdown reduction. Use `mlfinlab`/`PyPortfolioOpt`/`riskfolio-lib` implementations.

**My recommendation:** start with **inverse-volatility weighting** on the selected names. Graduate to **HRP** once the universe is large enough that correlation structure clearly matters and you've validated it beats inverse-vol in honest, cost-inclusive backtests. Skip MVO.

### 5.4 Portfolio-level constraints (applied after weighting)

These are *construction* constraints (distinct from the *risk limits* in Module 6, which are hard circuit-breakers):
- **Max weight per name** (e.g. ≤ 10–15% of deployed capital) — concentration cap.
- **Sector/industry caps** — don't let the book become an accidental single-sector bet.
- **Gross and net exposure targets** — gross = Σ|weights| (total leverage used), net = Σ(weights) (directional tilt). A market-neutral-ish intraday book keeps net small; a directional one doesn't. Decide deliberately.
- **Max number of positions** — operational sanity and cost control.
- **Turnover control** — penalize churn. Because each rebalance costs ~0.12–0.20% round trip, only trade when the new target differs from the current book by enough to justify the cost (a **no-trade band** around current positions). This is one of the highest-impact, most-overlooked profit levers for a frequent strategy.

**Output contract of Module 5:** a target portfolio — a set of (symbol, side, target weight) tuples — that respects all construction constraints and is the *intended* book before sizing/risk overlay.

---

## Module 6 — Position Sizing & Risk

### 6.1 The leverage reality in India (read before sizing anything)

- **Max 5x leverage (20% upfront margin)** on eligible equities via MIS. The eligible list and multiples are set by broker policy within SEBI's floor.
- **Peak margin regime:** margin is assessed on your **maximum intraday exposure**, sampled multiple times per day — not just at entry or close. Shortfalls draw penalties (≈0.5–5% of the shortfall per day). You must hold margin for your *peak* gross position, so keep a buffer.
- **Bracket/Cover Orders discontinued** by most brokers post-regulation (their embedded stop-loss could no longer guarantee the risk fit the fractional margin). So you cannot lean on broker-side guaranteed stops; **your system owns the stop logic.**
- **Auto-square-off** ~15:20–15:25; margin shortfall can trigger forced square-off earlier. Plan around it.

**My recommendation for v1: little to no leverage (gross exposure ≤ 1x, maybe up to 2x once proven).** The arithmetic of leverage on a small, uncertain edge is unforgiving — leverage multiplies your edge *and* your estimation error *and* your drawdowns, and a single bad cluster of trades at 5x can be terminal. Earn the right to leverage with a long, honest live track record first.

### 6.2 Volatility targeting (the portfolio-level dial)

Target a constant *risk* level rather than a constant *capital* level. If recent realized portfolio volatility is `σ_realized` and your target is `σ_target`, scale overall exposure by `σ_target / σ_realized`. Effects:
- Position sizes shrink automatically when markets get violent and grow when calm — this alone smooths the equity curve and cuts tail drawdowns.
- It makes the risk you're running *intentional and stable*, instead of an accident of current prices.
- Set `σ_target` conservatively (a modest annualized number) and cap the max scaling so a quiet period doesn't lever you up dangerously.

### 6.3 Kelly and fractional Kelly (per-trade sizing, tied to the meta-probability)

This is where Deep Dives #2 and #3 connect cleanly. The triple-barrier setup gives each trade a payoff structure: win `+b` (target) vs lose `−1` (stop), with the meta-model's calibrated probability `p` of the win. The **Kelly fraction** — the bet size that maximizes long-run log-growth — is:

```
   f* = p − (1 − p) / b
```

(For continuous/Gaussian returns the equivalent is `f* = μ / σ²` — bet proportional to edge over variance, which is essentially a Sharpe-squared rule.)

**Why you must use a *fraction* of Kelly (typically ¼ to ½):**
- Full Kelly assumes you **know** `p` and `b` exactly. You don't — they're noisy estimates, and **overestimating your edge makes Kelly overbet catastrophically.** Estimation error pushes the safe bet *well below* the full-Kelly number.
- Full Kelly produces gut-wrenching drawdowns (50%+ peak-to-trough is normal at full Kelly even when you're right). Most humans — and most accounts — can't survive that.
- **Half-Kelly keeps ~75% of the growth rate at ~half the volatility**; quarter-Kelly is safer still. For a first system with uncertain edge, **quarter-Kelly or a flat small fraction is the responsible choice.**

**Practical sizing rule for v1 (robust, simple):** size each position from `min(fractional-Kelly using meta-probability, a fixed risk-per-trade cap)`, then apply the portfolio-level volatility-target scalar, then clamp to the construction weight caps. The cap matters more than the cleverness — a fixed **risk-per-trade of ~0.25–1% of equity** (distance to stop × position size ≤ that budget) is a perfectly good, survivable starting point even before Kelly.

### 6.4 The hard risk limits — coded, automatic, non-overridable

These are **not** model outputs and **not** discretionary. They sit *above* every signal, sizing rule, and (later) RL policy, and they can always veto or flatten. This hierarchy is the single most important structural decision in the whole system:

```
            ┌─────────────────────────────────────────────┐
            │   HARD RISK LIMITS  (coded, non-overridable) │  ← can always flatten / halt
            │   • per-trade stop                           │
            │   • daily loss limit → halt for the day      │
            │   • max drawdown circuit breaker             │
            │   • max position / max gross exposure        │
            │   • consecutive-loss throttle                │
            │   • global kill-switch                       │
            └───────────────────────┬─────────────────────┘
                                     │ vetoes / clamps
            ┌───────────────────────▼─────────────────────┐
            │   SIZING  (vol target, fractional Kelly)     │
            ├──────────────────────────────────────────────┤
            │   PORTFOLIO CONSTRUCTION (weights, caps)      │
            ├──────────────────────────────────────────────┤
            │   SIGNALS / MODELS  (primary + meta)          │
            └──────────────────────────────────────────────┘
```

The non-negotiable limits:
- **Per-trade stop-loss.** Every position has a predefined stop (the triple-barrier lower barrier). Since broker BO/CO guaranteed stops are gone, the **system enforces stops itself** — monitor live and exit. (Belt-and-suspenders: also place an exchange stop-loss order where possible.)
- **Daily loss limit.** If cumulative realized+unrealized P&L for the day hits −X% of equity, **flatten everything and stop trading until tomorrow.** This single rule prevents the "revenge-trading death spiral" that ends most retail accounts. Set X conservatively (e.g. 2–3%).
- **Max drawdown circuit breaker.** If trailing drawdown from peak equity exceeds a threshold (e.g. 10–15%), halt the whole system pending manual review — the edge may have decayed or regime-shifted.
- **Max position size & max gross exposure.** Absolute caps independent of what sizing suggests, enforced at order time. Respect the peak-margin buffer.
- **Consecutive-loss throttle.** After N consecutive losing trades, automatically cut size (or pause) — a cheap, robust response to "something has changed."
- **Global kill-switch.** One command (and automatic triggers: data-feed loss, abnormal latency, reconciliation mismatch, fat-finger detection) that **flattens all positions and stops the engine.** Test it regularly; an untested kill-switch is not a kill-switch.

Every limit is enforced in code and logged. None can be disabled by a model or by a human mid-session in a moment of hope — that's the entire point. The most common live failure mode is a human overriding the system during a drawdown; the architecture should make that hard.

### 6.5 Where RL fits (and where it doesn't)

RL can later optimize **position sizing and entry/exit timing** — given a signal and current inventory, learn an entry/exit/sizing policy that improves risk-adjusted return. That's a legitimate, bounded use (small action space, well-defined reward). But:
- It is a **phase-2+ enhancement**, after the rule-based sizing above is working and profitable.
- The **hard limits in §6.4 sit above any RL policy and override it unconditionally.** RL optimizes *within* the risk envelope; it never sets the envelope.

**Output contract of Module 6:** final, risk-checked orders (symbol, side, quantity) ready for the execution layer — each already inside every hard limit, with the kill-switch and daily/drawdown guards live.

---

## What I'd build for this layer (concrete spec)

A `capital/` package:

1. **`combine/`** — signal aggregation (rank-averaging default; IC-weighting; optional stacking under purged CV); cross-sectional ranking; candidate selection with liquidity/ESM-T2T/spread/event filters.
2. **`portfolio/`** — weighting engines (`equal_weight`, `inverse_vol` [default], `hrp`); construction constraints (per-name cap, sector cap, gross/net targets, max positions); **no-trade band / turnover control**.
3. **`sizing/`** — volatility-target scalar; fractional-Kelly sizer driven by the meta-probability + barrier payoff ratio; fixed risk-per-trade cap; clamps to weight caps.
4. **`risk/`** — the hard-limit engine: per-trade stop manager, daily-loss halt, drawdown circuit breaker, exposure/position caps, consecutive-loss throttle, **kill-switch** with automatic triggers. This module has authority to veto/flatten and is tested in isolation with simulated breach scenarios.

**Build/validate order:** risk-limit engine **first** (the safety harness before anything can trade) → equal-weight + fixed risk-per-trade sizing → backtest with Deep Dive #2's cost model and confirm the limits actually fire in simulation → add inverse-vol, vol-targeting, fractional-Kelly → only later HRP and (much later) RL sizing. Re-run the kill-gate after each addition.

---

## Open questions to settle for this layer

- **Market-neutral vs directional:** keep net exposure ≈ 0 (long-short balanced, lower market risk) or allow a directional tilt (higher return potential, higher risk)? Recommend near-neutral for a first cross-sectional system.
- **Exact hard-limit thresholds:** daily loss %, drawdown %, risk-per-trade %, consecutive-loss N. Set these *before* live, conservatively, and treat them as inviolable.
- **Leverage policy:** confirm 1x gross for v1; define the track-record bar required before considering 2x.
- **Number of concurrent positions / capital base:** affects diversification, per-position size vs the ₹20 brokerage cap economics, and WebSocket/operational load.

---

*Next installment (Deep Dive #4 — the Execution Layer): the OMS and order routing — order types (MIS/limit/market), smart execution and slicing to minimize impact and stay under 10 OPS, slippage and the gap between intended and realized fills, idempotency and reconciliation, partial-fill and disconnect handling, exchange strategy-ID tagging, and where a bounded RL or optimal-execution (Almgren-Chriss-style) policy genuinely earns its place.*

*This is an engineering/research reference, not financial advice, and nothing here is a recommendation to use leverage or take any particular position. Trading carries substantial risk of loss.*
