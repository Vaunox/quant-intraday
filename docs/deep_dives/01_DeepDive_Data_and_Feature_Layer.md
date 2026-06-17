# Deep Dive #1 — The Data & Feature Layer

*Modules 0, 1, 2 of the pipeline: broker/market connectivity, data ingestion + storage, and feature engineering. This is the foundation; every bug here is silently inherited by every model and backtest downstream. Grounded June 2026.*

---

## Why this cluster comes first

Three failure modes kill more retail quant projects at this layer than anywhere else, and they are all *silent* — the system runs, produces numbers, and the numbers are wrong:

1. **Lookahead leakage** — a feature uses information that wasn't available at decision time. Backtest looks brilliant, live trading bleeds.
2. **Survivorship bias** — your universe only contains names that survived to today, so the model never saw the disasters. Inflates every result.
3. **Train/serve skew** — the feature computed in research differs subtly from the one computed live (different code path, different rounding, different data source). The model in production is effectively running on inputs it was never trained on.

The architecture below is designed to make all three *structurally hard to commit*, not just discouraged by good intentions.

---

## Module 0 — Broker & Market Connectivity

### 0.1 What you can and cannot actually get (the constraint map)

This is the single most important thing to internalize before designing features, because it bounds what's possible.

| Data type | Available to retail via API? | Source | Notes |
|---|---|---|---|
| 1-min/3-min/5-min/15-min/60-min/day OHLCV+OI candles, ~10 yrs history | **Yes** | Kite Connect (bundled free since Feb 2025), GDFL, TrueData, NSE official | This is your primary research substrate. |
| Live L1 quote (LTP, OHLC, volume) | **Yes** | Kite WebSocket (`ltp`/`quote` modes), GDFL, TrueData | 1-second or tick cadence depending on vendor. |
| **5-level** bid/ask market depth (live) | **Yes** | Kite WebSocket `full` mode | 5 best bids + 5 best asks, with timestamp. This is your ceiling for live order-book features. |
| **20-level** depth (live) | **No (via API)** | Kite web/mobile app only | Exchange prohibits redistributing 20-depth over API. You'd need direct NSE/authorized-distributor access. **Design as if you only have 5.** |
| True tick-by-tick (TBT) full order book | **No (retail-practical)** | Exchange colo / institutional feeds | Not redistributable to retail API. GDFL/TrueData give *trade* ticks + L1, not full TBT depth. |
| Historical raw tick (trade-by-trade) | **Partially** | GDFL, TrueData, TickData.com (NSE since 2012) | Millisecond timestamps; native exchange-sourced. Needed only if you go to sub-minute strategies. |

**Practical conclusion:** build a **minute-bar + 5-level-depth** system. That is the honest envelope for a SEBI-compliant (<10 OPS) retail bot. Order-flow-imbalance-style features are computable from 5-level depth (most of the OFI literature uses top-of-book or 5 levels anyway), but anything requiring full TBT reconstruction is off the table — and reconstructed ticks from third parties should never be used for execution modeling because the synthetic sequence misrepresents real fills.

### 0.2 Kite Connect mechanics you must design around

- **WebSocket modes:** `ltp` (last price only), `quote` (OHLC + volume), `full` (adds 5-level depth + timestamp). You subscribe to tokens, then `set_mode`.
- **Subscription limits:** up to **3000 instruments per WebSocket connection**, **3 connections per API key** (≈9000 instruments max). More than enough for a Nifty-100-scale universe; a real constraint if you ever want all-F&O.
- **REST rate limits:** ~3 requests/sec for data endpoints, ~10/sec for orders; quote API gives 5-level depth too.
- **RMS cap:** ~2000 MIS (intraday) orders/day per account — design your turnover under this.
- **Static IP mandatory for order placement** (since April 2025) — order requests from non-whitelisted IPs are rejected; data endpoints are exempt. Register up to 2 static IPs in the developer console. → live engine runs on a **fixed-IP VPS** (AWS/GCP elastic IP, ideally Mumbai region for latency to NSE colo).
- **Daily session reset:** SEBI mandates daily logout/re-auth before pre-open; the OAuth `request_token → access_token` flow must be automated to run every morning.
- **Personal API caveat:** the *free* Kite Connect Personal API gives order placement but **no market data**. For a data-driven system you need the paid Connect plan (₹2000/mo, includes historical) or a separate data vendor.

### 0.3 The broker-adapter pattern (non-negotiable for modularity)

Never let the rest of the system import `kiteconnect` directly. Define one interface and implement it per broker. This is what makes the system broker-agnostic and lets you run redundancy or switch when a broker's API degrades.

```python
class BrokerAdapter(Protocol):
    # --- market data ---
    def get_historical(self, token: int, interval: str,
                       start: datetime, end: datetime) -> pd.DataFrame: ...
    def stream(self, tokens: list[int], on_tick: Callable) -> None: ...
    # --- trading ---
    def place_order(self, req: OrderRequest) -> str: ...          # returns order_id
    def modify_order(self, order_id: str, req: OrderRequest) -> None: ...
    def cancel_order(self, order_id: str) -> None: ...
    # --- account ---
    def positions(self) -> list[Position]: ...
    def margins(self) -> Margins: ...
```

Implementations: `KiteAdapter`, `UpstoxAdapter`, `DhanAdapter`, `SmartAPIAdapter`. Strongly consider **OpenAlgo** (self-hosted, open-source) as a ready-made unifying layer across all major Indian brokers — it already normalizes order/data semantics so you don't re-implement each broker's quirks.

**Output contract of Module 0:** clean, timezone-correct candles on demand; a live tick callback; idempotent order primitives. Nothing downstream knows which broker is behind it.

---

## Module 1 — Data Ingestion & Storage

### 1.1 Vendor selection

You generally need **two** things, and they can come from different vendors: (a) *historical* depth for research, (b) *live* feed for trading.

| Vendor | Strength | Use it for | Rough cost |
|---|---|---|---|
| **Kite Connect** | Bundled 10-yr 1-min history + live L1/5-depth, same API as execution | Default for a Zerodha-based system; minimizes moving parts | ₹2000/mo |
| **GlobalDataFeeds (GDFL)** | Native exchange tick, ms timestamps, OptionChain API, ~99.995% uptime, redundant failover | Execution-sensitive / sub-minute research; clean tick sequences | from ~₹1735/mo |
| **TrueData** | Multi-year tick archives, option analytics, APIs + VPS | Intraday research needing precise tick history | subscription tiers |
| **NSE official** | Authoritative 1-min bars | Ground-truth reconciliation / validation | paid |
| **TickData.com** | NSE trade+quote ticks since 2012, cleaned | Deep historical microstructure research | premium |

Avoid: free scraped sources for anything you'll trade on, and third-party *reconstructed* ticks for execution modeling.

**Recommended start:** Kite Connect for both history and live (single integration), add GDFL/TrueData later only if you move below 1-minute decisions or need cleaner ticks.

### 1.2 Storage architecture — a tiered design

Market data is **append-heavy, time-ordered, rarely updated** — exactly the workload general databases handle badly and time-series stores handle well. The pragmatic modern pattern is **three tiers**:

```
  HOT (today / live)         WARM (research)            COLD (archive)
 ┌──────────────────┐      ┌────────────────────┐     ┌──────────────────┐
 │ in-memory / queue │ ───▶ │  columnar TSDB or   │ ──▶ │ Parquet on object │
 │ Redis Streams     │      │  ArcticDB           │     │ storage (S3/GCS)  │
 │ (live ticks)      │      │  (research frames)  │     │ (immutable raw)   │
 └──────────────────┘      └────────────────────┘     └──────────────────┘
```

**Choosing the warm store** (the one decision that matters):

| Option | Best when | Notes |
|---|---|---|
| **ArcticDB** (Man Group, open-source) | You live in Python/pandas, want versioned dataframes, S3-backed, zero-ops | *Purpose-built for quant research.* Versioning gives you point-in-time dataset snapshots — directly fights lookahead/leakage. **My default recommendation for a solo/small quant.** |
| **QuestDB** (Apache 2.0) | You want SQL, `ASOF JOIN` (perfect for aligning trades↔quotes), highest ingest throughput, Parquet cold-tiering built in | Beats kdb+ on some read-heavy benchmarks; gentle learning curve. Great if you want a real-time DB. |
| **ClickHouse** | Mixed analytical workloads, high cardinality, huge scale, great compression | Heavier ops; excellent general-purpose market-data backbone. |
| **Parquet + DuckDB** | Minimum cost, simplest, research-only | Object storage is cheap; query with DuckDB/Polars. Perfectly adequate to start. No live-DB features. |
| **TimescaleDB** | You already use Postgres; storing bars + metadata relationally | Fine for aggregated bars/metadata, not raw tick firehoses. |
| **kdb+** | You have institutional budget + expertise | Gold standard, deterministic low latency — but commercial cost and steep curve make it overkill here. |

**My concrete recommendation for this project:** **ArcticDB for the research store + Parquet on object storage as immutable raw archive + Redis Streams (or a simple in-process ring buffer) for live ticks.** If you want SQL and a live DB later, swap ArcticDB → QuestDB without touching the rest (storage is behind a repository interface).

Partition raw archives by `symbol/date` and keep them **immutable and versioned** — you never overwrite history; corrections become new versions. This is how you can later prove a backtest used only point-in-time data.

### 1.3 Data hygiene — the unglamorous jobs that decide whether anything works

Build each as an idempotent, tested job. These are not optional polish; they are the difference between a real edge and a bias artifact.

1. **NSE trading calendar & session handling.** Market hours 09:15–15:30 IST; separate pre-open (09:00–09:15) and special sessions/holidays. Every timestamp normalized to IST; no naive UTC. Tag the opening-auction and closing bars specially — intraday behavior at the open/close is structurally different and many naive strategies are just trading the open-auction noise.

2. **Corporate-action adjustment.** Splits, bonuses, dividends, mergers create artificial price jumps. Maintain an adjustment-factor table and store **both** raw and adjusted series. Use adjusted prices for return/feature computation; raw prices for realistic fill simulation. A 1:5 split misread as a -80% return will poison a model instantly.

3. **Survivorship-bias control.** Use **point-in-time index constituents** — the Nifty-50 of June 2019 is not today's Nifty-50. Include delisted/merged/renamed symbols in historical sets. If your training universe is "today's liquid names," the model has literally never seen a company collapse, and it will be blind to exactly the tail events that blow up intraday accounts.

4. **Bad-tick / outlier filtering.** Exchange feeds contain erroneous prints, zero-volume bars, frozen quotes, and gaps. Apply sane filters (price within circuit limits, volume ≥ 0, spread plausibility, no stale-quote repeats) — but **log every correction**, never silently mutate. A filtered tick that was actually real is its own form of lookahead if you used future info to decide it was bad.

5. **Continuity & gap detection.** Missing minute bars are common. Decide a policy (forward-fill vs leave-gap vs flag) and apply it identically in research and live. Alert on unexpected gaps live.

6. **Universe liquidity screen.** Restrict to genuinely liquid names (high average daily value, tight median spread, consistent volume). Illiquid names destroy you on slippage and make backtests fantastically optimistic. Start with Nifty 50 / Nifty 100 + liquid F&O underlyings.

**Output contract of Module 1:** a versioned, point-in-time, corporate-action-adjusted, liquidity-screened dataset of clean bars (+5-level depth snapshots where available), retrievable by `(symbol, interval, time_range)` — identical interface for research and live.

---

## Module 2 — Feature Engineering

This is where domain edge is encoded. The hard truth from the literature: **a simple model on clean, leakage-free features beats a sophisticated model on contaminated features every time.** So most of the effort here goes into *correctness* and *signal families*, not cleverness.

### 2.1 The cardinal rule: point-in-time correctness

Every feature value at time *t* must be computable from data available **at or before *t*** — never the close of the same bar you're about to trade on. Enforce this structurally:

- Features are functions `f(history_up_to_t) → vector`. No function may peek forward.
- Decisions made on bar *t*'s close are **executed at bar *t+1*'s open** (carried through to backtest and live identically).
- Any normalization statistic (mean, std, min/max) must be computed on a **trailing/expanding window**, never the full sample. Full-sample z-scoring is one of the most common silent leaks — it leaks the future distribution into the past.

### 2.2 Feature families (with intuition)

These are the families that recur across the strongest recent empirical work. SHAP studies on microstructure data consistently rank **order-flow imbalance** as the single most informative family, with spread and VWAP-deviation close behind.

**A. Microstructure / order-flow (from 5-level depth + trades) — highest empirical value**

- **Order Flow Imbalance (OFI).** The net pressure of bids vs asks. Top-of-book version:
  `OFI_t = ΔBidQty_t − ΔAskQty_t` (changes in best-level sizes, signed by price moves). Multi-level OFI aggregates across the 5 levels you have, weighting nearer levels more. Empirically the effect on returns is monotone with concavity at extremes (pressure saturates). **Computable from Kite's 5-depth — build this first.**
- **Bid-ask spread** (absolute and relative). Wider spread → attenuated, lower-confidence signals and higher costs (adverse selection). Use as both a feature and a trade-eligibility filter.
- **Depth imbalance.** `(ΣBidQty − ΣAskQty)/(ΣBidQty + ΣAskQty)` across available levels.
- **VWAP-to-mid deviation.** Distance of price from intraday VWAP; short-horizon asymmetries show transient pressure followed by mean-reversion as depth replenishes. A workhorse intraday feature.
- **Trade-flow features.** Signed volume (buy-initiated vs sell-initiated, via tick rule), trade-size distribution, volume spikes.

**B. Price / return transforms**

- Multi-horizon log returns (1, 3, 5, 15, 30, 60 min), return autocorrelation, distance from rolling highs/lows, gap from previous close.

**C. Volatility**

- Realized volatility (rolling), ATR, Parkinson/Garman-Klass range estimators, optionally a lightweight GARCH for conditional vol. Volatility is both a feature *and* the basis for position sizing (Deep Dive #3).

**D. Momentum / mean-reversion technicals** (via **TA-Lib**, never hand-rolled — indicator bugs are insidious)

- RSI, MACD, Bollinger %B, Supertrend, Donchian, EMA crossovers, KAMA/HMA. Treat these as weak features to be *combined*, not standalone strategies.

**E. Time-of-day / seasonality**

- Minute-of-day, time-since-open, time-to-close, day-of-week. Intraday markets have strong, exploitable diurnal patterns (open volatility, lunch lull, close auction pressure). Encode cyclically (sin/cos) rather than as raw integers.

**F. Cross-sectional features**

- Rank a name's return/volume/volatility **relative to its universe** at each timestamp (sector-neutral standardization). Cross-sectional signals (this stock vs its peers right now) are often more robust intraday than pure time-series signals because they cancel market-wide moves.

**G. Regime features**

- Trend vs range classification, volatility regime (from an HMM/GMM — detailed in Deep Dive #2/#3), index-level state. Used to *gate* strategies on/off.

### 2.3 Normalization & encoding

- **Sector-/cross-sectional-neutral standardization** for cross-sectional models — standardize within sector/universe at each time slice so you're modeling *relative* signal, not absolute level.
- **Trailing/rolling normalization** for time-series features — expanding or rolling window only.
- **Robust scaling** (median/IQR) rather than mean/std where features are fat-tailed (most are).
- Winsorize extreme outliers (cap at e.g. 1st/99th rolling percentile) so a single bad print doesn't dominate.

### 2.4 The Feature Store — compute once, serve identically

The mechanism that **eliminates train/serve skew**: one function library, two callers (backtest and live), guaranteed identical code path.

```
                ┌────────────────────────┐
   bars/depth ─▶│  feature library       │  pure functions, point-in-time,
                │  f(history_asof_t)→vec  │  fully unit-tested
                └───────────┬────────────┘
                            │ same code, two callers
              ┌─────────────┴───────────────┐
              ▼                              ▼
     backtest path                     live path
 (vectorized over history)        (incremental, per new bar)
              │                              │
              ▼                              ▼
   training dataset  ◀── must be ──▶   live feature vector
```

Design rules:
- **One implementation per feature**, used by both paths. If you must vectorize for backtest speed, write a test asserting the vectorized output equals the incremental output bar-by-bar on a sample. This test is your skew tripwire.
- **Materialize and version features** (ArcticDB symbol per feature-set version). When you change a feature, it's a new version; models record which feature version they trained on.
- **Feature metadata:** for every feature store its compute window, dependencies, and as-of semantics. This is what lets you audit "could this feature have known the future?" mechanically.
- **Leakage tests in CI:** automated tests that (a) shift inputs forward and assert features don't change retroactively, (b) check no feature correlates suspiciously with the *future* label beyond plausibility, (c) verify normalization uses only trailing data.

**Output contract of Module 2:** `compute_features(symbol, asof_time) → versioned feature vector`, point-in-time-correct by construction, bit-identical in research and live, with leakage tests passing in CI.

---

## What I'd build for this layer (concrete spec)

A `data/` package with four sub-packages, each independently testable:

1. **`brokers/`** — `BrokerAdapter` protocol + `KiteAdapter` (start), optional `OpenAlgoAdapter`. Handles auth/OAuth daily-refresh, static-IP awareness, WebSocket lifecycle (reconnect, heartbeat, resubscribe), rate-limit-aware REST client.
2. **`ingest/`** — historical backfill jobs (paginated, resumable), live WebSocket consumer → Redis Stream, all writing through a `Repository` interface.
3. **`store/`** — `Repository` interface + `ArcticRepository` (research) + `ParquetArchive` (immutable raw) + `RedisLiveStore` (hot). Swappable to `QuestDBRepository` later.
4. **`features/`** — pure feature functions by family (microstructure, price, vol, technical, temporal, cross-sectional, regime), the dual-path harness, versioning, and the CI leakage-test suite.

Plus a **data-quality dashboard** (gaps, bad-tick counts, feed latency, coverage) and the **NSE calendar** as a shared utility used everywhere.

**Build/validate order:** calendar + adapter → historical backfill → storage → hygiene jobs (with logging) → minimal feature set (returns, vol, VWAP-dev, OFI) → leakage tests green → expand features. Do **not** move to modeling (Deep Dive #2) until leakage tests pass and you can reproduce a point-in-time dataset on demand.

---

## Open questions to settle before/while building this layer

- **Decision frequency:** 1-min, 3-min, or 5-min bars? This drives turnover, cost sensitivity, and OPS. (I lean 5-min or 15-min for a first system — lower cost drag, lower overfitting surface, comfortably <10 OPS.)
- **Universe size:** Nifty 50 vs Nifty 100 vs liquid-F&O set. Affects WebSocket connection planning and cross-sectional feature quality.
- **Cash vs F&O:** intraday equity (MIS) vs index/stock futures vs options. Each has different cost, margin, liquidity, and microstructure — and options add the entire greeks/implied-vol feature dimension. (Recommend starting with liquid cash equities or index futures, *not* options, for a first system.)
- **Live order-book features now or later:** the 5-depth OFI features add real value but also real engineering (live depth handling, reconnection state). A first cut can be bars-only; add depth in a second pass.

---

*Next installment (Deep Dive #2 — the Research Layer): triple-barrier & meta-labeling, sample weighting for overlapping labels, the model stack in build order, and the anti-overfitting validation engine — purged/embargoed and combinatorial cross-validation, deflated Sharpe, and the realistic-cost backtester. That's where we decide whether any edge is real.*

*This is an engineering/research reference, not financial advice. Trading carries substantial risk of loss.*
