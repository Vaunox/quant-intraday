# Project Plan: Modular Auto-Trading System for the Indian Intraday Market

*A senior engineering + quantitative perspective. Last grounded against regulations and tooling as of June 2026.*

---

## 0. Read This First — The Honesty Layer

Before any architecture, three facts that should shape every decision:

1. **The base rate is brutal.** SEBI's FY25 data shows >90% of retail F&O traders lose money, with aggregate net losses of ₹1.05 lakh crore (up 41% year-on-year). You are entering a game where the median participant is a net donor of capital.

2. **Backtests lie by default.** A 2024 *Review of Financial Studies* study found that correcting for lookahead bias alone cut average reported ML-strategy Sharpe from 2.1 to 0.8. Most "winning" strategies are bias artifacts. Your single biggest engineering risk is fooling yourself.

3. **"High stable profit" is not a deliverable.** It cannot be promised by anyone, including Renaissance (whose flagship fund is capacity-capped and closed precisely *because* edge is finite). The achievable goal is a **positive-expectancy, risk-controlled system with a small, real, decaying edge that you re-mine continuously.**

**Realistic targets** (after costs, on live capital, not backtest):
- Net Sharpe of **1.0–2.0** is good and sustainable. A backtest Sharpe >3 is a red flag for overfitting, not a trophy.
- Max drawdown budget: **15–20%** is the line beyond which most retail accounts blow up psychologically and financially.
- Win rate is the wrong obsession — a 40% win rate with 3:1 winners is profitable; a 70% directional win rate on daily returns almost certainly signals lookahead bias.

This plan is built to produce the achievable version and to *kill itself fast* when the edge isn't real.

---

## 1. Research Verdict: ML vs DL vs RL

**Short answer: Gradient-boosted trees for alpha, classical stats for regime/risk, RL only for execution. Treat deep learning as optional and unproven for your scale.**

### 1.1 The evidence

| Approach | Where it wins | Where it fails | Verdict for retail intraday India |
|---|---|---|---|
| **Classical ML (XGBoost, LightGBM, linear/logistic, Random Forest)** | Tabular feature data, small/medium datasets, fast iteration, interpretable, robust. Multiple 2025 comparative studies show XGBoost + technical indicators matching or beating deep learning. | Cannot model raw sequences without feature engineering. | **PRIMARY alpha engine.** This is your workhorse. |
| **Deep Learning (LSTM, GRU, Temporal CNN, Transformers, TFT)** | Raw sequence modeling, very large datasets, microstructure/order-book data, multi-horizon. | Data-hungry, overfits on noisy financial data, expensive to retrain, hard to debug. GRU sometimes beats LSTM; neither reliably beats boosting on tabular features. | **OPTIONAL.** Only after the boosting baseline is profitable and you have order-book data + GPU budget. |
| **Reinforcement Learning (DQN, PPO, A2C, DDPG, SAC, Recurrent RL)** | Sequential decision-making, position sizing, execution/order-splitting, directly optimizing Sharpe rather than prediction accuracy. | Severe overfitting to training regimes; poor out-of-sample transfer under non-stationarity; extremely sensitive to reward design, cost modeling, and state representation. Rankings between PPO/A2C/DQN invert across market regimes. | **EXECUTION & SIZING LAYER ONLY.** Do not use RL as your raw signal source on day one. |

### 1.2 Why this ordering

- Financial data is **low signal-to-noise, non-stationary, and small** by ML standards. These are exactly the conditions where gradient boosting dominates and deep nets overfit.
- The hard problem in trading is **not model architecture** — it is features, labels, costs, regime-awareness, and avoiding leakage. A simple model on clean, leakage-free features beats a fancy model on contaminated ones every time.
- RL's theoretical appeal (optimize risk-adjusted return end-to-end, learn position sizing) is real, but its practical fragility means it belongs *downstream* of a working signal, where the action space is small and the reward is well-defined (e.g., "given this alpha signal and this inventory, how do I enter/exit to minimize cost and drawdown?").

### 1.3 Recommended modeling stack (in build order)

1. **Baseline:** logistic regression / LightGBM classifier predicting sign + magnitude of next-N-bar return. Establish this *first*. If it isn't profitable after costs, no amount of deep learning will save you.
2. **Ensemble:** LightGBM + XGBoost + linear, combined via stacking or simple rank-averaging. Diversity across model families is more robust than one big model.
3. **Regime layer:** Hidden Markov Model or Gaussian Mixture on volatility/trend features to gate strategies on/off by regime (this is a direct Renaissance lesson — see §2).
4. **Execution layer (later):** RL (PPO or a recurrent variant) or simpler optimal-execution heuristics (TWAP/VWAP-aware) for order entry/exit and sizing.
5. **Deep learning (only if justified):** Temporal Fusion Transformer or a Temporal CNN on order-book/tick data, *only* once you have the data infrastructure and a profitable baseline to beat.

---

## 2. How Renaissance & Top Quant Firms Actually Operate

### 2.1 What they actually do (the transferable parts)

- **Markets as signal processing.** Simons came from code-breaking and signal intelligence. Renaissance applied hidden Markov models, the Baum-Welch algorithm, kernel methods, and nonlinear regression — techniques from speech recognition and cryptanalysis — to price data, decades before this was common.
- **Weak signals, massive aggregation.** Individual signals may be only ~50.75% accurate. The edge is not any single brilliant prediction; it is *thousands* of tiny, statistically robust edges combined with disciplined position sizing and risk management so they compound.
- **They don't need to know "why."** Renaissance explicitly does not require an economic story for a pattern — only that it is statistically robust and likely to persist. (Caveat for you: without a story, you must be *more* paranoid about overfitting, not less.)
- **One integrated system.** Mercer and Brown's key contribution was a single system integrating all signals and portfolio constraints — not a pile of disconnected scripts. Your architecture (§4) should reflect this: signals feed one portfolio/risk optimizer.
- **Obsession with clean data and costs.** Their entire edge survives only because transaction-cost and slippage modeling is ruthless. A signal that's profitable gross and unprofitable net is worthless.
- **Short horizons, high turnover, leverage.** Patterns persisting from milliseconds to weeks; many trades; leverage applied to small per-trade edges; remarkably, low volatility relative to returns (Medallion ran roughly market-neutral).

### 2.2 What is NOT transferable (don't kid yourself)

- **Capacity-capped, closed fund.** Medallion is ~$10B and closed to outsiders because edge erodes with size. They actively *refuse* more money. Your edge will also be small and capacity-limited.
- **Co-located, ultra-low-latency infrastructure** and **decades of proprietary cleaned data** you will never have.
- **Dozens of PhDs** in math, physics, signal processing, and a culture of sharing every signal into one book.
- **The genuine HFT layer** — under SEBI's framework, anything >10 orders/second is classified HFT and triggers heavy compliance. You should deliberately stay **below 10 OPS** and compete on *signal quality and discipline*, not speed.

### 2.3 The one-sentence takeaway

Renaissance's replicable lesson is **process, not magic**: relentless data hygiene, many small statistically-validated edges, brutal cost modeling, one integrated risk-aware portfolio, and continuous re-mining as edges decay.

---

## 3 & 4. The Full Pipeline as a Modular, Scalable Architecture

The pipeline *is* the architecture. Below is the end-to-end system, decomposed into independently testable, independently deployable modules. Each module has a clear contract (input → output) so you can swap implementations without touching the rest.

```
                          ┌─────────────────────────────────────────┐
                          │            ORCHESTRATION LAYER            │
                          │  (scheduler, config, secrets, logging,    │
                          │   alerting, kill-switch, run manifests)   │
                          └─────────────────────────────────────────┘
                                          │ controls all ▼
 ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐   ┌────────────┐
 │ 1. DATA  │──▶│ 2.FEATURE│──▶│ 3. LABELING  │──▶│ 4. MODEL │──▶│ 5. SIGNAL /  │──▶│ 6. RISK &  │
 │ INGEST   │   │  STORE   │   │ & DATASET    │   │ TRAINING │   │ PORTFOLIO    │   │ POSITION   │
 │          │   │          │   │ BUILDER      │   │ & REGISTRY│  │ CONSTRUCTION │   │ SIZING     │
 └──────────┘   └──────────┘   └──────────────┘   └──────────┘   └──────────────┘   └─────┬──────┘
       ▲                                               │                                  │
       │                                               ▼                                  ▼
 ┌──────────┐                                  ┌──────────────┐                   ┌────────────┐
 │ 0. MARKET│                                  │ 4b.BACKTEST &│                   │ 7.EXECUTION│
 │  + BROKER│◀─────────────────────────────────│ WALK-FORWARD │                   │  / OMS     │
 │   APIs   │       orders / fills              │ VALIDATION   │                   │ (broker)   │
 └──────────┘                                  └──────────────┘                   └─────┬──────┘
       ▲                                                                                 │
       └─────────────────────────────────────────────────────────────────────────────────┘
                              fills, positions, P&L feedback
                                          │
                                          ▼
                          ┌─────────────────────────────────────────┐
                          │  8. MONITORING / P&L ATTRIBUTION / OOS    │
                          │     PERFORMANCE TRACKING / DRIFT ALERTS   │
                          └─────────────────────────────────────────┘
```

### Module 0 — Market & Broker Connectivity (India-specific)

- **Primary broker API:** Zerodha **Kite Connect** (₹2000/month). As of 2025 it bundles up to 10 years of intraday historical data (1-min, 3-min, 5-min, 15-min, hourly, daily candles: OHLCV+OI). Note the free **Personal API** gives order placement but **no market data** — for a data-driven system you need the paid Connect plan or a separate data feed.
- **Alternatives / redundancy:** Upstox API, Dhan, Angel One **SmartAPI**. Build the broker layer behind an **adapter interface** so you can switch or run multi-broker.
- **Open-source abstraction:** **OpenAlgo** (self-hosted, runs locally) gives a broker-agnostic order/data layer across Indian brokers — strongly recommended as your execution abstraction.
- **Rate limits to design around (Kite):** ~3 requests/sec for data, ~10/sec for orders, WebSocket subscription to ~3000 instruments, and an RMS cap of ~2000 MIS (intraday) orders/day per account. **Stay under 10 orders/second** to remain a "regular API user" under SEBI rules (§6).
- **Hard infra requirement:** Static IP whitelisting is mandatory for order placement (from April 2025). Run the live engine on a **fixed-IP cloud VPS** (AWS/GCP elastic IP) co-located in/near Mumbai for lower latency to NSE.

**Contract:** `get_historical(symbol, interval, from, to) → DataFrame`; `stream_ticks(symbols) → tick events`; `place_order(...) → order_id`; `get_positions() → positions`. Everything downstream depends only on this contract, never on the broker SDK directly.

### Module 1 — Data Ingestion

- **Historical loader:** pull multi-year minute data for your universe; store raw immutable copies.
- **Live tick/candle stream:** WebSocket consumer writing to a queue.
- **Universe definition:** liquid NSE names only (high ADV, tight spreads) — e.g., Nifty 50 / Nifty 100 + liquid F&O underlyings. Illiquid names destroy you on slippage.
- **Critical data-hygiene jobs:** corporate-action/split adjustment, **survivorship-bias handling** (include delisted/changed symbols — point-in-time index constituents), timezone/holiday calendar (NSE), missing-candle detection.

**Scalability note:** treat data as append-only and versioned. Use **Parquet** files partitioned by symbol/date for historical; a message queue (Redis Streams / Kafka if you scale) for live.

### Module 2 — Feature Store

- Compute features once, reuse for training and live (this prevents train/serve skew — the #1 source of silent bugs).
- **Feature families:** price/return transforms, volatility (realized, ATR, GARCH), momentum/mean-reversion (RSI, MACD, Bollinger, Supertrend, Donchian via TA-Lib), microstructure (spread, order-book imbalance if available, volume profile, VWAP distance), time-of-day effects (open/close auctions matter intraday), cross-sectional rank features, and regime features.
- **Point-in-time correctness:** a feature at time *t* must use only data available at *t*. Build this as a hard invariant with automated tests.

**Contract:** `compute_features(symbol, asof_time) → feature_vector` — identical code path in backtest and live.

### Module 3 — Labeling & Dataset Builder

- **Labels:** next-N-bar return sign/magnitude, or **triple-barrier labeling** (López de Prado) which sets profit-take / stop-loss / time barriers — far more realistic for intraday than fixed-horizon labels.
- **Sample weighting:** weight by uniqueness/overlap to avoid leakage from overlapping label windows.
- **Splits:** purged, embargoed walk-forward splits (no random k-fold — it leaks the future).

### Module 4 — Model Training & Registry

- Train the §1 stack. Log every run (data version, feature version, hyperparameters, metrics, git commit) to an **experiment tracker** (MLflow). Promote models to a **registry** with explicit versioning so live always knows exactly which model+features it's running.
- **Retraining cadence:** scheduled walk-forward retrain (e.g., weekly/monthly rolling window) because the edge decays. Automate it.

### Module 4b — Backtesting & Walk-Forward Validation (the make-or-break module)

This module decides whether the whole project is real or a fantasy. Build it *paranoid*.

- **Engine:** **VectorBT** for fast vectorized parameter screening (millions of combos in minutes — exploration only), then **Backtrader** (event-driven) or **QuantConnect** for realistic final validation with order-by-order simulation. Use **QuantStats** for tearsheets (30+ metrics, Monte Carlo).
- **Mandatory realism — without these your P&L is fiction:**
  - **Costs:** brokerage (₹20/order or 0.03%), STT, exchange txn charges, GST, stamp duty, SEBI fees. Indian intraday costs are *significant* and asymmetric.
  - **Slippage:** model 0.1–0.5% for liquid names, more in volatile/illiquid; widen during stress.
  - **Next-bar execution:** never decide and fill on the same candle's close. Use the *next* bar's open.
  - **Latency:** simulate execution delay.
- **Anti-overfitting protocol (non-negotiable):**
  - **Walk-forward** with purge + embargo; report out-of-sample only.
  - **Deflated Sharpe Ratio** / White's Reality Check to penalize multiple testing — if you test 100 ideas, some win by luck.
  - **Robustness tests:** Monte Carlo trade-shuffle, noise injection, parameter sensitivity, entry/exit delay perturbation, cross-symbol validation.
  - **Kill rule:** if OOS Sharpe < 1.0 after honest costs, or if performance is concentrated in a few outlier trades (check profit factor & expectancy), the strategy dies. No "tweaking until it works."

> The `marketcalls/vectorbt-backtesting-skills` repo (open source) is a ready-made VectorBT + OpenAlgo + TA-Lib + QuantStats harness with walk-forward and robustness testing built for Indian markets — a strong starting scaffold.

### Module 5 — Signal & Portfolio Construction

- Convert model outputs into target positions. Combine multiple signals/strategies into **one book** (the Renaissance lesson), with constraints: max positions, sector/name caps, gross/net exposure limits, correlation control.
- This is where many weak signals become one coherent intended portfolio.

### Module 6 — Risk & Position Sizing

- **Position sizing:** volatility-targeted sizing or fractional Kelly (use a *fraction* — full Kelly is too aggressive and assumes you know your edge precisely, which you don't).
- **Hard risk limits enforced in code, not discretion:** per-trade stop, daily loss limit (auto-flatten + halt for the day), max drawdown circuit breaker, max position size, max gross exposure.
- This is the layer where RL can later optimize sizing/entry — but the hard limits sit *outside* and *above* any learned policy and can always override it.

### Module 7 — Execution / OMS (Order Management System)

- Smart order routing, order-type selection (limit vs market vs MIS/CO), order slicing to stay under rate limits and minimize impact, retry/idempotency logic, reconciliation of intended vs actual positions.
- **Idempotency and reconciliation are critical:** every order must be tagged and traceable (SEBI requires a unique strategy ID per order anyway — §6), and the system must detect and reconcile partial fills, rejects, and disconnects.
- **Mandatory kill-switch:** a single command (and automatic triggers) that flattens all positions and stops trading.

### Module 8 — Monitoring, Attribution & Drift Detection

- Live dashboards: P&L, positions, exposure, latency, fill quality, slippage-vs-model.
- **P&L attribution:** which signal/strategy made/lost money.
- **Drift alerts:** is live performance tracking backtest? Is feature distribution drifting from training? Alert and auto-throttle when live Sharpe diverges from expectation. **Only live trading is truly out-of-sample** — treat the first months of live as the real validation, on tiny size.

### Cross-cutting: Orchestration

- Config-as-code, secrets management (never hardcode API keys/tokens), structured logging, alerting (Telegram/email), and a scheduler that respects NSE market hours, pre-open, and daily API session resets (SEBI mandates daily logout before pre-open).

---

## 5. State-of-the-Art, Battle-Tested Tooling

Prefer **boring, proven, open-source** components. Novelty in your *infrastructure* is a liability; save novelty for your *signals*.

| Layer | Battle-tested choice | Notes |
|---|---|---|
| Language | **Python** (core), with critical hot paths in Cython/Rust if ever needed | You won't need ultra-low latency under 10 OPS. |
| Data wrangling | **pandas / Polars**, **NumPy** | Polars for speed at scale. |
| Storage | **Parquet** (historical), **DuckDB** for analytics, Redis/Kafka (live stream) | Append-only, versioned. |
| Indicators | **TA-Lib** | Industry standard; avoid hand-rolled indicator bugs. |
| Classical ML | **LightGBM, XGBoost, scikit-learn** | Your alpha workhorses. |
| Deep learning (optional) | **PyTorch**, **PyTorch Forecasting** (TFT), Temporal CNNs | Only if/when justified. |
| RL (execution, later) | **Stable-Baselines3** (PPO/A2C/SAC), **FinRL** library | FinRL is purpose-built for trading RL; still treat its results skeptically. |
| Regime models | **hmmlearn**, GMMs | For regime gating. |
| Fast backtest screen | **VectorBT** | Exploration only. |
| Realistic backtest | **Backtrader**, **QuantConnect/LEAN**, **Zipline-reloaded** | Final validation. |
| Tearsheets/metrics | **QuantStats**, **pyfolio** | Deflated Sharpe, drawdowns, Monte Carlo. |
| Experiment tracking | **MLflow** | Model + data + feature versioning. |
| Broker abstraction (India) | **OpenAlgo**, **Kite Connect / Upstox / SmartAPI** SDKs | Adapter pattern. |
| Validation methodology | **López de Prado** — *Advances in Financial ML* (triple-barrier, purged CV, deflated Sharpe) | The canonical anti-overfitting playbook. |
| Infra | Docker, fixed-IP cloud VPS (Mumbai region), CI for backtests | Reproducibility + compliance. |

---

## 6. Regulatory Compliance (SEBI / NSE — mandatory, India 2026)

**This is not optional and is enforced at the broker level.** As of **April 1, 2026** the SEBI retail algo framework is fully mandatory.

- **Stay under 10 Orders Per Second (OPS).** Under 10 OPS = "regular API user" → **no formal exchange registration of your strategy required** for personal use. Over 10 OPS = classified HFT → mandatory exchange approval + rigorous testing. **Design deliberately for <10 OPS.**
- **White-box, personal use.** Transparent rule/model logic used for your own account is the lightest-compliance path. (Selling strategies to others, or black-box services, pulls you into empanelment + possibly a SEBI Research Analyst license — a different, heavier project. Don't go there unless that's the actual business.)
- **Unique Strategy ID tagging:** every algo-generated order must carry an exchange-provided unique strategy ID. Your OMS must support order tagging.
- **Static IP whitelisting:** mandatory for order placement. Register up to two static IPs in the broker developer console. Use a fixed-IP VPS.
- **2FA / OAuth login + daily session resets:** API sessions must re-authenticate daily before pre-open. Automate the OAuth flow.
- **Broker-as-principal model:** you operate through your broker's API as a regular client; the broker is responsible to the exchange.

**Action item:** before writing live-trading code, confirm your specific broker's current developer-console requirements (they change), and verify static-IP and tagging support.

---

## 7. Phased Roadmap (with explicit kill-gates)

Each phase has a **gate**: if you fail it, you stop or loop back. This prevents the classic failure of building a beautiful live system around a non-existent edge.

### Phase 0 — Foundations (Weeks 1–3)
- Set up repo, environments, broker dev account, data access, fixed-IP VPS.
- Build Module 0 + 1: pull and clean multi-year minute data for a small liquid universe; build NSE calendar, corporate-action adjustment, survivorship handling.
- **Gate:** you can reproduce clean, point-in-time, cost-aware historical bars for your universe. No leakage in data layer.

### Phase 1 — Research Harness & Baseline (Weeks 4–8)
- Build Module 2/3/4b: feature store, triple-barrier labeling, purged walk-forward backtester with **full Indian costs + slippage + next-bar fills**.
- Train the **LightGBM baseline** (§1).
- **Gate (the big one):** an honest, cost-inclusive, walk-forward OOS Sharpe **> 1.0** with **Deflated Sharpe** still positive, and performance not concentrated in a handful of trades. **If you fail this gate, do not proceed to live. Iterate on signals/features, or stop.** Most projects die here — correctly.

### Phase 2 — Strategy Hardening (Weeks 9–14)
- Add ensemble + regime gating (HMM). Add Module 5/6: portfolio construction, volatility-target/fractional-Kelly sizing, hard risk limits.
- Stress test: robustness suite (Monte Carlo, noise, parameter sensitivity, regime splits incl. 2020/2024-style stress).
- **Gate:** strategy survives robustness tests; drawdown within budget; edge stable across regimes (not just one bull run).

### Phase 3 — Paper Trading (Weeks 15–20)
- Build Module 7/8 + orchestration. Run **fully automated paper/sim trading** against live data with the real execution path, real latency, real rate limits, real session resets.
- **Gate:** live paper P&L tracks backtest within tolerance for a sustained period; slippage model matches reality; no operational failures (disconnects handled, reconciliation clean, kill-switch tested).

### Phase 4 — Live, Micro Size (Weeks 21+)
- Go live with **trivially small capital** — the goal is to validate that live ≈ paper, not to make money yet. **Live is the only true out-of-sample test.**
- Full monitoring, drift alerts, daily loss limits, automatic halt.
- **Gate:** months of live performance consistent with expectations before scaling capital — and even then, scale slowly and expect capacity limits.

### Phase 5 — Operate, Re-mine, Decay-manage (ongoing)
- Automated walk-forward retraining; continuous research pipeline for new signals (edges decay — Renaissance's whole model is *continuous re-mining*); periodic compliance review; quarterly honest performance audit with kill criteria for dying strategies.

---

## 8. Risk Management & Failure Modes (the part that actually keeps you solvent)

- **Capital you can lose.** Trade only risk capital. The 90%-lose statistic is not about other people.
- **Hard, coded, non-overridable limits:** daily loss limit → auto-flatten and halt; max drawdown circuit breaker; per-trade stop; max position and gross exposure. These sit above any model/RL policy.
- **Operational risk is as deadly as market risk:** API disconnects, partial fills, duplicate orders, clock skew, session expiry mid-day. Idempotent orders + reconciliation + a tested kill-switch are not optional.
- **Overfitting is the silent killer.** Treat every backtest as guilty until proven innocent. Deflated Sharpe, walk-forward, and live validation are your defense.
- **Edge decay.** Any edge you find will weaken as others find it. Budget continuous research, not a one-time build.
- **Regulatory risk.** Stay compliant (under 10 OPS, white-box, tagged, static IP). A blocked API account ends everything overnight.
- **Psychological risk.** Automation removes emotion only if you let it run. The most common live failure is the human overriding the system during a drawdown.

---

## 9. One-Page Summary

- **Method:** Gradient-boosted trees as the alpha engine; HMM/GMM for regime gating; RL reserved for execution/sizing later; deep learning optional and only once justified.
- **Renaissance lesson that transfers:** many small statistically-validated edges + ruthless cost modeling + one integrated risk-aware book + continuous re-mining. The infrastructure and PhD army do not transfer.
- **Pipeline:** Data → Features → Labels → Model → Backtest/Walk-forward → Signal/Portfolio → Risk/Sizing → Execution/OMS → Monitoring, all behind clean module contracts and a broker adapter.
- **Tooling:** Python, LightGBM/XGBoost, TA-Lib, VectorBT (screen) + Backtrader/QuantConnect (validate), QuantStats, MLflow, OpenAlgo + Kite Connect, López de Prado methodology.
- **India compliance:** SEBI framework mandatory (April 2026); stay <10 OPS, white-box, unique strategy IDs, static IP, 2FA, daily resets.
- **The discipline that matters most:** an honest, cost-inclusive, walk-forward Phase-1 gate that you are willing to fail. If the edge isn't real there, no architecture saves it.

*This document is an engineering and research plan, not financial advice. I am not a licensed financial advisor. Trading carries substantial risk of loss.*
