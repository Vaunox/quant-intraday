# MASTER BLUEPRINT — Indian Intraday Algorithmic Trading System
### Claude Build Handoff Document

*A single, self-contained specification for building a modular, compliant, risk-controlled intraday trading system for Indian liquid cash equities, plus a mobile master-control app. This document consolidates six detailed design deep-dives into one operational build plan. It is written to be handed to Claude (or any capable engineer) and worked through one session-sized subtask at a time.*

---

## HOW TO USE THIS DOCUMENT WITH CLAUDE

This file is the operating manual for the build. Work it **top to bottom, one subtask per session.**

**At the start of every coding session, tell Claude:**
> "Follow the Engineering Ground Rules in this blueprint (Part I). We are working on subtask **[P_._]**. Read its reference section, build it to its acceptance criteria, write the tests, and update the Progress Log at the end."

**Rules of engagement for the whole build:**
- Do **one subtask per session.** Finish its acceptance criteria before moving on.
- **Respect dependencies and phase gates.** Do not start a phase until the previous phase's gate passes. The gates exist for safety, not bureaucracy.
- **Update the Progress Log (Part V)** at the end of each session.
- Claude **cannot and must not**: compile/sign the production APK, run the live trading system, hold broker credentials or signing keys, or place real orders. Those belong to the human operator. Claude **asks for explicit confirmation** before any step that would touch real money, real credentials, or place real orders.
- When a decision is ambiguous, choose the **simpler, more robust, more testable** option. This is the recurring principle of the entire design.

---

# PART I — ENGINEERING GROUND RULES

These are non-negotiable standards for every line of code in this project. Re-read them before each subtask.

## 1. Modularity

Write modular code where every component has one clear responsibility and can be tested and replaced independently.

- **One module = one job.** Data ingestion, feature computation, labeling, modeling, validation, portfolio construction, sizing, risk, execution, monitoring, and control each live in their own package with a clear boundary.
- **Program to interfaces, not implementations.** Define `Protocol`/abstract interfaces for anything with more than one possible implementation — the broker (`BrokerAdapter`), the storage layer (`Repository`), the model, the portfolio constructor, the sizer. Nothing outside `data/brokers/` may import the broker SDK directly; nothing outside `data/store/` may import the database client directly. This lets you swap Kite for another broker, or ArcticDB for QuestDB, without touching the rest of the system.
- **Dependency injection.** Pass dependencies in (constructor or function arguments); do not reach out to globals or construct collaborators inside business logic. This makes everything unit-testable with fakes/stubs.
- **No global mutable state.** State lives in explicit, owned objects with clear lifecycles.
- **Pure functions where possible**, especially feature computation — given the same inputs, always the same output, no side effects. This is also what makes point-in-time correctness enforceable.
- **Define the contract for each module up front** (its inputs and outputs) so downstream work can proceed against the interface.

## 2. Avoid Hard-Coding

No magic numbers, paths, credentials, thresholds, or environment assumptions in the code.

- **All parameters live in versioned configuration** (`config/`), loaded at runtime: the universe, decision frequency, barrier multiples, risk-limit thresholds, cost-model rates, retrain cadence, file paths, broker endpoints, rate limits, everything.
- **Layered config:** a `default.yaml` base, overridden per environment (`dev`/`paper`/`live`), overridden by environment variables. One source of truth; every run reproducible from its config.
- **Secrets are never in code or config files.** API keys, secrets, tokens, and credentials come only from a secrets manager / environment variables, accessed through a single `secrets` interface. They are never committed, never logged, never embedded in the client app.
- **Named constants** for anything fixed (e.g. NSE session times) — defined once, in `core/`, and imported. If a value might ever change or differ by environment, it is config, not a literal.
- **Test:** searching the source for hard-coded numbers, paths, or credentials should return essentially nothing in business logic.

## 3. Standard Structure

Maintain a single, standardized project layout so anyone can navigate it instantly. Use this structure:

```
quant-intraday/
├── README.md                     # overview, setup, how to run
├── pyproject.toml                # deps, build, tool config (ruff, mypy, pytest)
├── .pre-commit-config.yaml       # lint/format/type hooks
├── .gitignore                    # secrets/, data/, models/, .env, __pycache__
├── .github/workflows/ci.yml      # CI: lint + type-check + tests on every push
├── config/
│   ├── default.yaml              # base configuration
│   ├── universe.yaml             # tradable universe definition
│   └── env/                      # dev.yaml, paper.yaml, live.yaml overrides
├── src/quant/
│   ├── core/                     # domain types, interfaces (Protocols), config loader,
│   │                             #   secrets interface, logging setup, NSE calendar, constants
│   ├── data/                     # LAYER 1 — Data & Feature
│   │   ├── brokers/              #   BrokerAdapter protocol + KiteAdapter
│   │   ├── ingest/               #   historical backfill + live stream consumer
│   │   ├── store/                #   Repository + ArcticDB/Parquet/Redis implementations
│   │   ├── hygiene/              #   corp-action, survivorship, bad-tick, gaps, liquidity
│   │   └── features/             #   pure point-in-time feature functions + dual-path harness
│   ├── research/                 # LAYER 2 — Research
│   │   ├── labeling/             #   CUSUM sampler, triple-barrier, meta-labels, weighting
│   │   ├── features_research/    #   fractional differentiation, stationarity
│   │   ├── models/               #   baseline, ensemble, regime gate, meta-model, calibration
│   │   ├── validation/           #   purged CV, embargo, CPCV, DSR, PBO, cost backtester, robustness
│   │   └── reports/              #   validation report + tearsheet + kill-gate emitter
│   ├── capital/                  # LAYER 3 — Capital
│   │   ├── combine/              #   signal combination + cross-sectional selection
│   │   ├── portfolio/            #   equal-weight / inverse-vol / HRP + constraints
│   │   ├── sizing/               #   vol-target + fractional-Kelly + risk-per-trade cap
│   │   └── risk/                 #   the hard-limit engine + kill-switch
│   ├── execution/                # LAYER 4 — Execution
│   │   ├── oms/                  #   order state machine + durable order store
│   │   ├── router/               #   order-type selection, slicer, ≤10-OPS throttle
│   │   ├── reconcile/            #   intended↔broker↔positions + stop-existence guarantee
│   │   ├── safety/               #   system-side stop monitor, self-square-off, backoff
│   │   └── shortfall/            #   implementation-shortfall / slippage measurement
│   ├── ops/                      # LAYER 5 — Operations
│   │   ├── scheduler/            #   daily lifecycle state machine + morning auth routine
│   │   ├── monitor/              #   metrics emission + dashboard
│   │   ├── attribution/          #   per-strategy P&L + signal-vs-execution decomposition
│   │   ├── drift/                #   performance / data / concept drift detectors
│   │   ├── mlops/                #   scheduled+triggered retrain, champion/challenger, registry
│   │   └── platform/             #   audit log, alerting, secrets wiring, DR, backups
│   └── control/                  # LAYER 6 — Control API gateway (backend for the app)
├── app/                          # mobile master-control app (PWA → APK)
├── tests/
│   ├── unit/                     # per-module unit tests
│   ├── integration/              # cross-module + against broker sandbox
│   └── adversarial/              # injected-failure tests (execution, risk limits, leakage)
├── notebooks/                    # research exploration only — never production logic
├── scripts/                      # runnable ops scripts (backfill, daily run, etc.)
├── docs/
│   └── deep_dives/               # the 6 detailed reference documents
└── data/                         # local data cache (gitignored)
```

- Source, tests, config, docs, scripts, and app are cleanly separated.
- Test files mirror the source tree.
- `notebooks/` is for exploration; production logic must live in `src/quant/`, imported by notebooks, never copy-pasted.

## 4. No Temporary Patch Fixes

Solve the underlying problem, not the symptom. Avoid quick hacks that create technical debt.

- **No band-aids.** If a test is flaky, fix the root cause, don't add a sleep or a retry that masks it. If a value is occasionally wrong, find why, don't clamp it silently.
- **No commented-out code, no "TODO: fix later" in merged work.** If something is genuinely deferred, it is a tracked subtask in this blueprint, not a buried note.
- **No silent workarounds for the broker/data quirks** — handle them explicitly, in the right module, with a test that documents the behavior.
- **Refactor when the design strains** rather than piling special cases onto a structure that no longer fits.
- **The fix must respect the architecture.** A change that requires reaching across module boundaries or violating an interface is a signal to reconsider the design, not to break the boundary.
- A correct, slightly slower solution beats a fast, fragile one — this is a system that handles money; reliability dominates cleverness.

## 5. Code Comments

Comment the *why*, not the *what*. Make the codebase legible to a future developer (including future-Claude).

- **Docstrings on every public module, class, and function**: purpose, parameters, returns, and any important invariants (e.g., "feature functions must be point-in-time; inputs are only data available at or before `asof`").
- **Inline comments explain rationale and non-obvious logic** — why a barrier is volatility-scaled, why reconciliation happens before retry, why a limit is clamped server-side. Do not narrate obvious code.
- **Document invariants and assumptions explicitly**, especially the safety-critical ones (point-in-time correctness, next-bar-open execution, limits-above-models).
- **Reference the source.** Where a piece of logic implements a specific technique, cite it (e.g., "triple-barrier labeling, López de Prado; see docs/deep_dives/02").
- Comments must stay truthful — update them when the code changes; a stale comment is worse than none.

## 6. Git Best Practices

Keep a clean, reviewable history.

- **Branch per subtask:** `feat/p1.3-storage-layer`, `feat/p3.1-risk-engine`, etc. Never commit straight to `main`.
- **Small, atomic commits** with clear, descriptive messages (conventional-commit style: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`). Each commit does one coherent thing and leaves the tree in a working state.
- **A subtask = a pull request.** The PR description lists the subtask's acceptance criteria as a checklist; it merges only when all are met and CI is green.
- **Never commit** secrets, credentials, tokens, raw market data, trained model binaries, or anything in `.gitignore`. Add and verify `.gitignore` early (Phase 0).
- **Tag phase gates** (e.g., `gate-1-data-layer`) so the project's milestones are visible in history.
- Pull/rebase before pushing; keep history linear and readable; write commit messages that explain *why* the change was made.
- Run lint, type-check, and tests **before** committing (enforced by pre-commit + CI).

## 7. Professional Standards

Hold a high bar for craftsmanship throughout.

- **Clean, readable, efficient code.** Clear names, small functions, consistent style enforced by the formatter/linter (ruff + black or equivalent). No dead code.
- **Static typing everywhere.** Full type hints; `mypy`/`pyright` must pass in CI. Types are documentation that can't go stale.
- **Code review discipline.** Every subtask's PR is reviewed (by the human operator, or by Claude self-reviewing against the acceptance criteria and these rules) before merge.
- **Documentation as a first-class deliverable.** Keep `README.md` and module docs current; a new reader should be able to set up and understand any layer from the docs alone.
- **Determinism and reproducibility.** Seed all RNGs; version data, features, and models; any run can be reproduced from its config + versions.
- **Performance where it matters, simplicity everywhere else.** Optimize the hot paths (feature computation, backtest vectorization) with evidence; keep everything else simple.
- **Fail loudly and early.** Validate inputs at boundaries; raise clear, specific exceptions; never let a bad state propagate silently.

## 8. Proper Logging

Comprehensive, structured, useful logging across the whole system.

- **Structured logging** (JSON or key-value), not bare prints. Use the standard `logging` module configured once in `core/`.
- **Appropriate levels:** DEBUG (development detail), INFO (lifecycle events, decisions), WARNING (recoverable anomalies, retries, drift watch), ERROR (failures needing attention), CRITICAL (limit breach, kill-switch, naked-position risk).
- **Log every event that matters:** each trading decision, signal, order placement/modification/fill/rejection, every risk-limit evaluation and breach, every reconciliation action, data-feed gaps, latency, auth/session events, retrain runs, model promotions.
- **Correlation IDs** to trace a decision → order → fill → P&L across modules.
- **Never log secrets** (keys, tokens, credentials, the `api_secret`).
- **The audit trail is append-only and immutable** — it is both a debugging substrate and the SEBI traceability record. Logging feeds the monitoring and alerting layer (Phase 5); CRITICAL events trigger alerts.
- Logs are timestamped (IST), queryable, and retained.

## Project-Specific Inviolable Rules (a professional building *this* system must encode these)

These are domain safety rules. They override convenience and "just make it work."

1. **The kill-gate is sacred.** No strategy receives capital — not even paper-to-live promotion — without passing **all seven** kill-gate criteria (Part III, Layer 2). No tweaking-until-it-passes; that is overfitting and inflates the trial count the Deflated Sharpe will punish. Most ideas should die here. That is success, not failure.
2. **Point-in-time correctness, always.** No feature may use data unavailable at decision time. Decisions on bar *t*'s close execute at bar *t+1*'s open — identically in backtest and live. All normalization uses trailing/expanding windows only. Leakage tests run in CI.
3. **Hard risk limits sit above every model.** The risk-limit engine (per-trade stop, daily-loss halt, drawdown circuit breaker, exposure caps, kill-switch) can veto or flatten anything and cannot be overridden by a model or by a human mid-session. The kill-switch must always work and is tested.
4. **Costs are always modeled.** No gross-only backtests. The full Indian cost model (brokerage, STT, exchange charges, GST, stamp duty) plus realistic slippage applies to every simulation.
5. **The phone is a remote control, never the brain.** Broker secrets live only on the server; orders originate only from the static-IP server; the app sends bounded, server-clamped intents whose most powerful action is fail-safe (flatten/stop). Control API behind a VPN.
6. **SEBI compliance is non-negotiable.** Stay a sub-10-OPS white-box personal user: ≤10 orders/second (self-throttled), static-IP order placement, daily manual auth seed, market protection on market/SL-M orders, every order strategy-tagged. Exclude ESM/T2T names (no intraday trading).
7. **Honesty about outcomes.** "High stable profit" is not a goal and is not promised. Over 90% of retail F&O traders lose money — that is the operating reality. The achievable target is a positive-expectancy, risk-controlled system with a small, decaying edge that is continuously re-mined. The system must be able to fail and to stop.
8. **Build in dependency order; respect the gates.** Do not proceed past a failed gate.

---

# PART II — SYSTEM OVERVIEW & LOCKED DECISIONS

## What we are building

An automated system that trades **liquid Indian cash equities intraday (MIS)** on a **15-minute decision clock** (square-off by ~15:20), using gradient-boosted models on point-in-time features, validated against overfitting with rigorous cross-validation, sized conservatively under hard risk limits, executed faithfully via the Zerodha Kite Connect API, monitored for drift, and controllable from a secure mobile master-control app.

## Realistic-expectations frame (keep this visible)

- Base rate: **>90% of retail F&O traders lose money** (SEBI FY25; net losses ₹1.05 lakh crore, +41% YoY).
- Correcting lookahead bias alone cut average ML-strategy Sharpe from **2.1 → 0.8** in a 2024 study — most "profitable" backtests are bias artifacts.
- Realistic sustainable net Sharpe is **1.0–2.0**; a backtest Sharpe **>3 is a red flag**, not a trophy. Max-drawdown budget **15–20%**.
- The disciplines that decide the outcome are the boring ones: not fooling yourself in validation, sizing small, enforcing un-overridable limits, and stopping when the edge dies.

## The pipeline

```
 DATA → FEATURES → LABELING → MODEL → VALIDATION → SIGNAL/PORTFOLIO → RISK/SIZING → EXECUTION/OMS → MONITORING/DRIFT
   │        │          │         │         │              │               │              │               │
   └─ broker adapter, storage, hygiene (L1) │              └────────── capital layer (L3) ┘   │   operations (L5)
                       └──── research layer (L2: labels, models, anti-overfitting) ┘          └ execution (L4) ┘
                                                                          + mobile master control (L6) over all
```

## Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Instrument | Liquid cash equities, intraday MIS | Simplest first system; no options greeks; shortable |
| Decision frequency | 15-minute bars (features from finer data) | Cost arithmetic: round-trip ~0.12–0.20%; 15-min targets 0.3–1%+ moves; lower overfit; <10 OPS |
| Broker | Zerodha Kite Connect | Bundled 10-yr history + live; same API for data and orders |
| Market data envelope | Minute bars + **5-level** depth | 20-depth not redistributable via API; design to 5 levels |
| Research store | ArcticDB (+ Parquet raw archive + Redis live) | Python-native, versioned dataframes; versioning fights leakage |
| Alpha model | Gradient boosting (LightGBM/XGBoost) | Dominates on tabular, low-SNR financial data |
| RL | Execution/sizing only, phase 2+ | Fragile for alpha; bounded use is safe |
| Portfolio | Inverse-vol → HRP (never MVO) | Robust > optimal; MVO error-maximizes |
| Sizing | Fractional Kelly (¼) + risk-per-trade cap + vol target | Under-bet; survive estimation error |
| Leverage (v1) | None (gross ≤ 1x) | Leverage magnifies a small, uncertain edge into ruin |
| App stack | PWA → APK (Bubblewrap/TWA); Flutter later | Single codebase, fastest; native push later |
| Language/tooling | Python; ruff+black, mypy, pytest, pre-commit, CI | Standard, proven |

---

# PART III — TECHNICAL REFERENCE (distilled from the six deep dives)

*Enough to build from. Full detail in `docs/deep_dives/01..06`.*

## Layer 1 — Data & Feature

**Goal:** a versioned, point-in-time, clean dataset and a leakage-proof feature library, behind swappable interfaces.

**Three silent killers to prevent structurally:** lookahead leakage, survivorship bias, train/serve skew.

**Connectivity (Kite):** WebSocket modes `ltp`/`quote`/`full` (full = 5-level depth + timestamp); ≤3000 instruments/connection, 3 connections/key; REST ~3 req/s data, ~10 req/s orders; ~2000 MIS orders/day; **static IP mandatory for orders**; daily session reset; the paid Connect plan is required for market data (free Personal API has none). All access behind a `BrokerAdapter` protocol — nothing else imports the SDK.

**Storage (tiered):** Redis Streams (hot/live) → ArcticDB (warm/research, versioned) → Parquet on object storage (cold/immutable raw, partitioned by symbol/date). All behind a `Repository` interface (swappable to QuestDB later). Raw archives are immutable; corrections become new versions.

**Hygiene jobs (each idempotent, tested, logged):** NSE calendar + IST timestamps + pre-open/close tagging; corporate-action adjustment (store raw *and* adjusted); survivorship control via point-in-time index constituents (include delisted/renamed); bad-tick filtering (log every correction, never silently mutate); gap detection; liquidity screen (high ADV, tight spread); exclude ESM/T2T.

**Feature families (all point-in-time pure functions):** microstructure (Order Flow Imbalance from 5-depth — empirically the top feature; bid-ask spread; depth imbalance; VWAP-to-mid deviation; signed trade flow); price/return transforms; volatility (realized, ATR, range estimators, GARCH); momentum/mean-reversion (TA-Lib — never hand-rolled); time-of-day/seasonality (cyclical encoding); cross-sectional ranks (sector-neutral); regime features.

**Normalization:** trailing/rolling or cross-sectional only; robust scaling; winsorize.

**Feature store contract:** `compute_features(symbol, asof) → versioned vector`, identical code path in backtest and live, with a CI test asserting vectorized==incremental output (the skew tripwire) and leakage tests.

## Layer 2 — Research

**Goal:** honest labels, a calibrated model, and a validation engine that determines whether any edge is real. *Build the validation engine before the models.*

**Labeling:** CUSUM event sampling (label when something happens); **triple-barrier** (volatility-scaled upper/lower barriers + vertical barrier = session square-off; path-dependent so stops are honest); **meta-labeling** (primary model → side, tuned for recall; secondary model → bet/no-bet + size — the natural home for the ~0.15% cost hurdle); calibrated probabilities (isotonic/Platt) for sizing.

**Sample weighting (labels are NOT IID):** concurrency/uniqueness weighting (`1/c_t`, average uniqueness), sequential bootstrap for bagging, time-decay, return-attribution weighting.

**Stationarity:** fractional differentiation — minimum `d` (via ADF) that achieves stationarity while preserving memory.

**Model stack (build order):** LightGBM baseline first (if a clean cost-aware baseline isn't profitable, stop) → LightGBM+XGBoost ensemble (uniqueness-aware bagging) → cross-family stack (rank-averaging/stacking) → HMM/GMM regime gate → meta-model. Use permutation/SHAP importance (NOT MDI); tune under purged CV; MLflow tracking + model registry; deep learning and RL deferred.

**Validation (two questions, two tools):**
- *Is the edge real?* → **purged k-fold + embargo**, **CPCV** (combinatorial purged CV: N groups, k test → C(N,k) splits → φ = C(N,k)·k/N paths; judge the *distribution* of path-Sharpes — narrow & positive = robust, wild variance = fragile regardless of mean), **Deflated Sharpe Ratio** (corrects for trial count, skew, kurtosis, length — track honest trial count), **PBO via CSCV**, t-stat hurdle ~3.0.
- *What would live feel like?* → **walk-forward** with the **full Indian cost model** (brokerage lower of ~0.03%/₹20 per order; STT ~0.025% sell-side; exchange ~0.003%/side; stamp ~0.003% buy; GST 18% on brokerage+txn; ~0.12–0.20% round trip) + slippage (0.05–0.20%, size/depth-aware) + **next-bar-open fills** + latency.

**Robustness battery:** parameter sensitivity, Monte Carlo trade shuffle, noise injection, cross-symbol, synthetic-data backtest, two-engine reconciliation (VectorBT screen vs Backtrader/Nautilus).

**THE KILL-GATE (all seven, set thresholds before running):** (1) CPCV median path-Sharpe >1.0 after costs; (2) Deflated Sharpe positive & significant; (3) PBO below ~0.2–0.5; (4) narrow positive CPCV path distribution (no deeply negative paths); (5) P&L not concentrated in a few trades; (6) survives robustness battery; (7) edge stable across regimes. Fail → it dies.

## Layer 3 — Capital

**Goal:** turn calibrated signals into positions, robustly, under un-overridable limits. *Build the risk-limit engine first.*

**Signal combination:** rank-averaging (default) → IC-weighting → stacking (only under purged CV). Cross-sectional selection (top/bottom-N), with eligibility filters (liquidity, spread/cost, ESM/T2T exclusion, optional event filter).

**Portfolio construction:** equal-weight (baseline) → **inverse-volatility (v1 default)** → HRP (when universe grows — clustering + quasi-diagonalization + recursive bisection; no matrix inversion, no expected-return vector). **Never MVO** (error-maximization). Constraints: max weight/name, sector caps, gross/net targets, max positions, **no-trade band / turnover control** (only trade when the target moves enough to clear costs).

**Sizing:** portfolio-level **volatility targeting** (scale exposure by σ_target/σ_realized, capped) + **fractional Kelly** from the meta-probability (`f* = p − (1−p)/b`, use ¼–½) + a fixed **risk-per-trade cap** (~0.25–1% of equity), clamped to weight caps. The cap matters more than the cleverness.

**India leverage reality:** max 5x MIS (20% margin); peak-margin regime (margin on max intraday exposure); Bracket/Cover Orders discontinued (system owns stops); auto-square-off ~15:20. **v1: no leverage.**

**Hard risk limits (coded, automatic, non-overridable, above all models):** per-trade stop (triple-barrier lower; system-enforced); **daily loss limit → flatten + halt for the day**; max drawdown circuit breaker → halt for review; max position / max gross exposure; consecutive-loss throttle; **global kill-switch** (manual + automatic triggers: feed loss, abnormal latency, reconciliation mismatch). Every limit logged; tested with breach scenarios.

## Layer 4 — Execution

**Goal:** faithful, compliant, cheap fills with a guarantee that no position is ever unprotected. *Core truth: placement ≠ execution.*

**Order lifecycle:** a state machine (`PUT ORDER REQ RECEIVED → VALIDATION PENDING → OPEN PENDING → OPEN → COMPLETE/CANCELLED/REJECTED`, `TRIGGER PENDING` for SL). The placement response gives an `order_id`, not a fill. Learn outcomes via **two channels together**: postback webhooks (+ WebSocket order updates) and order-history polling. Documented failure: status can stick at "PUT ORDER REQUEST RECEIVED" though executed — so safety must not depend on a single callback.

**Order types:** product MIS; LIMIT-near-touch entries (cancel-replace) preferred over MARKET; **SL-M** protective stops; **market protection mandatory** for MARKET/SL-M (`market_protection=0` rejected); tag every order with its strategy. SL-M blocked for index options (n/a here).

**Compliance gates (hard rejections):** static IP (or rejected); **≤10 OPS** (429 if exceeded — self-throttle with a token bucket); market protection; ~25 modifications/order cap. Sub-10-OPS personal user → no exchange strategy-ID registration.

**Smart execution:** for liquid large-caps at retail size, impact is negligible — limit-near-touch + occasional TWAP slicing suffices; **slice ≤10**; iceberg (min ₹1,00,000); handle auto-slicing children for freeze limits. Almgren-Chriss/RL execution only when size grows relative to depth (phase 2+).

**Implementation shortfall:** measure realized slippage per trade vs the backtest's slippage assumption (decision-vs-fill, spread/delay/impact/opportunity) — feed monitoring; if live slippage exceeds the model, the edge was partly fictional.

**Idempotency & reliability:** never blind-retry on timeout (reconcile first — a timeout may mean success); local order key recorded before the call; persist OMS state before/after each call for crash recovery.

**Reconciliation loop (continuous + on restart):** align intended ↔ broker order book ↔ actual positions; the loop **guarantees a stop exists for every open position** (this is the fix for the stuck-status bug); repairs discrepancies.

**Failure handling:** partial fills (stop/target to filled qty), entry-filled-but-stop-failed (reconciliation + system-side stop monitor), rejects (specific handlers), WebSocket/postback disconnect (reconnect + poll fallback; persistent loss → kill-switch), 429 backoff, **self-square-off ~15:15** (before broker auto-square-off), margin-shortfall forced square-off.

**Adversarial test requirement:** kill the WebSocket mid-trade, time out a placement, force a partial fill → the system must never end up naked or doubled.

## Layer 5 — Operations

**Goal:** keep the system alive and *honest*; detect when the edge dies.

**Daily lifecycle state machine** (calendar-aware): PRE-OPEN (auth + checks) → MARKET OPEN (trade loop) → SELF-SQUARE-OFF (~15:15) → POST-CLOSE (reconcile, attribute, archive, drift/retrain checks, report).

**Morning auth (India-specific):** access token expires ~5:00–7:30 AM; flow = login endpoint → `request_token` at redirect URL → POST with SHA-256 checksum → `access_token`. **Exchange mandates manual login once/day** → clean design is a 30-second manual TOTP seed at ~7:30 AM, then automated for the session. One active session per key; avoid Kite-web login while the bot runs.

**Pre-open gate:** token valid, feed fresh, margin sufficient (+buffer), universe refreshed (ESM/T2T excluded), limits armed, kill-switch responsive, yesterday flat. Fail → don't trade today.

**Monitoring:** a live gauge for every hard limit and every backtest assumption — P&L (realized/unrealized vs daily limit), exposure/margin vs caps, **realized slippage vs model**, fill rates, reject counts, latency, drawdown vs breaker, feed/connection/token health.

**P&L attribution:** by strategy/name (via order tags); **signal-vs-execution decomposition** (if execution eats the edge, fix execution; if signal underdelivers, it's drift).

**Drift detection (three detectors, three responses, pre-set thresholds):** performance (live Sharpe/hit-rate/expectancy vs CPCV distribution → throttle band / halt band); data (PSI/KS/KL on feature distributions → retrain trigger); concept (decaying IC, meta-model decalibration, ADWIN/Page-Hinkley → distinguish gradual decay (retrain) from regime break (halt)). Responses are pre-defined, not improvised in a drawdown.

**MLOps:** scheduled walk-forward retraining (purged, embargoed, cost-aware) + drift-triggered retraining; **champion/challenger** (new model runs in shadow, promoted only after clearing the kill-gate); model registry + versioning + **instant rollback**; continuous research for new signals (edges decay to zero).

**Platform:** structured immutable audit log (debugging + SEBI traceability); tiered alerting (Telegram/email/PagerDuty) with CRITICAL on any limit breach, halt, kill-switch, reconciliation mismatch, feed loss, reject spike, drift trip, failed auth; secrets manager; config-as-code; containerization; **state durability + crash recovery**; **DR: panic-flatten path + exchange-resident SL-M stops that survive engine death** (test by killing the engine mid-session); backups.

**Runbook & kill criteria:** daily checklist, incident procedures, and pre-defined criteria for *stopping a strategy* (halt-band breach confirmed as decay, drawdown breach from regime break, repeated operational failures, persistent slippage excess). The hardest discipline is actually stopping a broken strategy.

## Layer 6 — Control (Mobile Master Control)

**Goal:** monitor and control everything from a phone, safely. *The phone is a remote control, never the brain.*

**Security model (the heart):** phone never holds broker secrets/tokens and never places orders directly; all phone↔system traffic goes through a hardened **control API on the VPS**, which is **behind a VPN/WireGuard/Tailscale** (not public). TLS (ideally mTLS); device-bound, short-lived, server-revocable tokens; biometric app lock; **read vs control scopes**; **2FA on risk-increasing actions** (flatten/stop fast-pathed since fail-safe); **bounded intents only** (no arbitrary order entry) with every parameter **clamped to hard bounds server-side** (can tighten freely, loosen only within ceilings); every action audit-logged; API rate-limited. Designed blast radius if phone stolen: an attacker can only *turn the bot off*.

**Architecture:** App ↔ (HTTPS commands + WSS telemetry) ↔ Control API gateway (thin, hardened; translates intents; clamps) ↔ Engine (single authority; same hard limits) ↔ Broker (only the VPS). Read path = subscribe to existing telemetry; control path = authenticated/2FA/clamped/audited commands.

**Control API contract:** read scope (telemetry stream + GET status/positions/pnl/limits/strategies/alerts); control scope (POST flatten-all, engine pause/stop [fail-safe], engine start ★, strategy pause/enable ★, limits ★ [clamped], alerts ack, model rollback / promote ★). ★ = 2FA/re-auth.

**App stack:** PWA dashboard served by the VPS, wrapped to an APK via Bubblewrap (TWA) or Capacitor (v1); Flutter later for native push. The operator generates and holds the signing key; the operator runs the build tooling and deploys the API + VPN. Claude writes the source/build config but cannot compile/sign the production APK or hold secrets.

**Security checklist (before real money):** API VPN-only; TLS/mTLS; secrets only on VPS; biometric lock + revocable token; read/control scopes; 2FA on risk-increasing actions; server-side clamping; phone cannot place arbitrary orders or exceed limits; all actions audited; stolen-phone test; flatten/kill path verified end-to-end.

---

# PART IV — THE BUILD PROGRAM (session-sized subtasks)

The program is a single ordered path of phases; each phase is a set of subtasks; **each subtask is sized to complete in one focused session** and ends in a mergeable PR with passing tests. Do not skip phase gates.

**Subtask template:** each has a Goal, Depends-on, Deliverable, Done-when (acceptance criteria), and Reference.

---

## PHASE 0 — Foundation & Scaffolding

#### P0.1 — Repository & tooling
- **Goal:** stand up the project skeleton and quality gates.
- **Depends on:** —
- **Deliverable:** repo with the Part-I folder structure, `pyproject.toml` (deps + ruff/black/mypy/pytest config), `.pre-commit-config.yaml`, `.gitignore` (secrets/, data/, models/, .env), `.github/workflows/ci.yml` (lint + type-check + test), `README.md`.
- **Done when:** `pre-commit` runs clean; CI passes on an empty test; `mypy` and `ruff` configured and green; folder structure matches Part I.
- **Reference:** Part I (3, 6, 7).

#### P0.2 — Configuration & secrets system
- **Goal:** layered config loader + secrets interface; zero hard-coding.
- **Depends on:** P0.1
- **Deliverable:** `core/config.py` (load `default.yaml` ← env override ← env vars), `core/secrets.py` (single interface to env/secret store), example `config/default.yaml`, `config/universe.yaml`, `config/env/*.yaml`.
- **Done when:** config loads and merges by environment with tests; secrets are never read from code/config files; a missing secret raises a clear error; no literals in business logic.
- **Reference:** Part I (2); Layer 5 platform.

#### P0.3 — Logging & audit foundation
- **Goal:** structured logging configured once; append-only audit log interface.
- **Depends on:** P0.1
- **Deliverable:** `core/logging.py` (structured logger, levels, correlation IDs, IST timestamps, secret redaction), `core/audit.py` (append-only audit interface).
- **Done when:** logs are structured with levels and correlation IDs; secrets are redacted; audit entries are append-only; tested.
- **Reference:** Part I (8); Layer 5 platform.

#### P0.4 — NSE calendar utility
- **Goal:** authoritative trading-calendar/session utility used everywhere.
- **Depends on:** P0.1
- **Deliverable:** `core/calendar.py` — is-trading-day, session bounds (09:15–15:30 IST), pre-open, holidays, square-off time; all in IST.
- **Done when:** correctly classifies trading/holiday days and session phases for sample dates; tested.
- **Reference:** Layer 1 hygiene; Layer 5 scheduler.

#### P0.5 — Domain types & interfaces (contracts)
- **Goal:** the shared data models and the Protocols every layer implements.
- **Depends on:** P0.1
- **Deliverable:** `core/types.py` (Bar, Tick, DepthSnapshot, OrderRequest, Order, Position, Signal, etc.) and `core/interfaces.py` (`BrokerAdapter`, `Repository`, `Model`, `PortfolioConstructor`, `Sizer`, `RiskEngine` Protocols).
- **Done when:** types are fully typed and documented; interfaces compile and are importable; a trivial fake implementation of each Protocol type-checks.
- **Reference:** Part I (1); all layers' contracts.

**GATE 0:** project scaffolding, config/secrets, logging/audit, calendar, and the core contracts exist, typed and tested; CI green. Tag `gate-0-foundation`.

---

## PHASE 1 — Data & Feature Layer

#### P1.1 — Broker adapter (market data) + auth/session
- **Goal:** `KiteAdapter` for market data behind `BrokerAdapter`, with daily session handling.
- **Depends on:** P0.5
- **Deliverable:** `data/brokers/` — `BrokerAdapter` use + `KiteAdapter` (historical fetch, OAuth/token flow with manual-seed pattern, static-IP awareness), rate-limit-aware REST client.
- **Done when:** historical candles fetch behind the interface (against sandbox/recorded fixtures in tests); token flow documented; no SDK import outside this package; tested with a fake.
- **Reference:** Layer 1 connectivity; Layer 5 auth.

#### P1.2 — Live stream consumer
- **Goal:** robust WebSocket consumer for ticks + 5-level depth.
- **Depends on:** P1.1
- **Deliverable:** `data/ingest/stream.py` — subscribe (`full` mode), reconnect/backoff, resubscribe, heartbeat, push to a queue.
- **Done when:** simulated disconnects auto-recover and resubscribe; depth parsed to `DepthSnapshot`; tested with a fake socket.
- **Reference:** Layer 1 connectivity.

#### P1.3 — Storage layer
- **Goal:** `Repository` interface + tiered implementations.
- **Depends on:** P0.5
- **Deliverable:** `data/store/` — `Repository` + `ParquetArchive` (immutable raw, symbol/date partitions) + `ArcticRepository` (versioned research) + `RedisLiveStore`.
- **Done when:** write/read round-trips for each tier; versioning works in Arctic; raw archive is immutable; swappable behind the interface; tested.
- **Reference:** Layer 1 storage.

#### P1.4 — Historical backfill job
- **Goal:** paginated, resumable multi-year backfill into storage.
- **Depends on:** P1.1, P1.3
- **Deliverable:** `data/ingest/backfill.py` + `scripts/run_backfill.py`.
- **Done when:** backfills a small universe; resumes after interruption without duplication; writes versioned data; tested.
- **Reference:** Layer 1 ingestion.

#### P1.5 — Data hygiene jobs
- **Goal:** corporate actions, survivorship, bad-tick, gaps, liquidity screen.
- **Depends on:** P1.3
- **Deliverable:** `data/hygiene/` — corp-action adjustment (raw + adjusted stored), point-in-time constituents/survivorship, bad-tick filter (logged, never silent), gap detection, liquidity screen, ESM/T2T exclusion.
- **Done when:** a split is correctly adjusted; delisted names included historically; corrections logged; ESM/T2T excluded; each job idempotent and tested.
- **Reference:** Layer 1 hygiene.

#### P1.6 — Feature library: core families + dual-path harness
- **Goal:** point-in-time pure feature functions (returns, vol, VWAP-deviation) + the backtest/live dual-path harness.
- **Depends on:** P1.3
- **Deliverable:** `data/features/` — core feature functions + `compute_features(symbol, asof)` harness used by both paths.
- **Done when:** features are pure and point-in-time; vectorized output equals incremental output bar-by-bar (skew test); tested.
- **Reference:** Layer 1 features.

#### P1.7 — Feature library: microstructure + technical + cross-sectional + regime
- **Goal:** the remaining families.
- **Depends on:** P1.6
- **Deliverable:** OFI (5-depth), spread, depth imbalance, signed trade flow; TA-Lib technicals; cyclical time-of-day; cross-sectional ranks (sector-neutral); regime features.
- **Done when:** each family computed point-in-time with trailing/cross-sectional normalization and winsorization; tested.
- **Reference:** Layer 1 features.

#### P1.8 — Leakage & skew test suite (CI)
- **Goal:** structural anti-leakage guarantees in CI.
- **Depends on:** P1.6, P1.7
- **Deliverable:** `tests/adversarial/` — forward-shift invariance, trailing-only normalization checks, no-suspicious-future-correlation, train/serve skew.
- **Done when:** the suite runs in CI and fails on an intentionally leaky feature.
- **Reference:** Layer 1 features; Part I rule 2.

#### P1.9 — Data-quality dashboard
- **Goal:** visibility into data health.
- **Depends on:** P1.5
- **Deliverable:** gaps, bad-tick counts, coverage, feed latency report/dashboard.
- **Done when:** surfaces issues on sample data; tested.
- **Reference:** Layer 1.

**GATE 1:** reproduce a point-in-time, corporate-action-adjusted, survivorship-correct, leakage-tested dataset and feature set on demand. Tag `gate-1-data`.

---

## PHASE 2 — Research Layer

#### P2.1 — Validation harness core (purged CV + cost backtester)
- **Goal:** the judge, before any contestant — purged k-fold + embargo + realistic backtester with the Indian cost model.
- **Depends on:** GATE 1
- **Deliverable:** `research/validation/` — purged k-fold + embargo splitter; event-driven backtest core (next-bar-open); full Indian cost model; slippage model (size/depth-aware); latency.
- **Done when:** purge/embargo verified to remove overlap; costs/slippage/next-bar fills applied; tested against hand-computed cases.
- **Reference:** Layer 2 validation.

#### P2.2 — CPCV + DSR + PBO
- **Goal:** the "is the edge real?" toolkit.
- **Depends on:** P2.1
- **Deliverable:** CPCV with path reconstruction (φ = C(N,k)·k/N), Deflated Sharpe Ratio, PBO via CSCV, trial-count tracking.
- **Done when:** CPCV produces the correct number of paths and a path-Sharpe distribution; DSR/PBO match reference formulas; tested.
- **Reference:** Layer 2 validation.

#### P2.3 — Labeling: CUSUM + triple-barrier
- **Goal:** honest, event-sampled, volatility-scaled labels.
- **Depends on:** GATE 1
- **Deliverable:** `research/labeling/` — CUSUM event sampler + triple-barrier labeler (vol-scaled barriers, vertical = square-off).
- **Done when:** labels match expected on synthetic price paths; vertical barrier respects session end; tested.
- **Reference:** Layer 2 labeling.

#### P2.4 — Sample weighting
- **Goal:** correct for non-IID labels.
- **Depends on:** P2.3
- **Deliverable:** concurrency/uniqueness weights, sequential bootstrap, time-decay, return-attribution.
- **Done when:** uniqueness computed correctly on overlapping labels; sequential bootstrap samples by uniqueness; tested.
- **Reference:** Layer 2 weighting.

#### P2.5 — Meta-labeling + fractional differentiation
- **Goal:** side/size split + stationary memory-preserving features.
- **Depends on:** P2.3, P1.7
- **Deliverable:** primary-side + meta bet/no-bet label generation; fractional differentiation (min-`d` via ADF).
- **Done when:** meta-labels generated from a primary signal; frac-diff series passes ADF while retaining memory; tested.
- **Reference:** Layer 2 labeling/stationarity.

#### P2.6 — Model: baseline + tracking + calibration
- **Goal:** the LightGBM baseline under proper discipline.
- **Depends on:** P2.1, P2.5
- **Deliverable:** `research/models/` — LightGBM baseline; MLflow tracking; purged-CV hyperparameter tuning; permutation/SHAP importance; isotonic calibration.
- **Done when:** baseline trains and is evaluated only under purged CV; importances use permutation/SHAP (not MDI); probabilities calibrated; runs logged to MLflow; tested.
- **Reference:** Layer 2 models.

#### P2.7 — Ensemble + regime gate + registry
- **Goal:** the production model stack.
- **Depends on:** P2.6
- **Deliverable:** LightGBM+XGBoost+linear ensemble (rank-averaging/stacking), HMM/GMM regime gate, model registry with data/feature/label version tags.
- **Done when:** ensemble + regime gate evaluated under CPCV; models versioned in registry; tested.
- **Reference:** Layer 2 models.

#### P2.8 — Robustness battery + two-engine reconciliation
- **Goal:** stress the edge.
- **Depends on:** P2.2, P2.7
- **Deliverable:** parameter sensitivity, Monte Carlo shuffle, noise injection, cross-symbol, synthetic-data backtest; reconciliation against a second engine (VectorBT vs Backtrader/Nautilus).
- **Done when:** each test runs and reports; two engines reconcile within tolerance on a sample strategy; tested.
- **Reference:** Layer 2 robustness.

#### P2.9 — Validation report + kill-gate emitter
- **Goal:** one report that decides trade/don't-trade.
- **Depends on:** P2.2, P2.8
- **Deliverable:** `research/reports/` — automated report (CPCV distribution, DSR, PBO, trial count, walk-forward equity, robustness) + QuantStats tearsheet + the **seven-point kill-gate** as pass/fail.
- **Done when:** report generates end-to-end and emits the kill-gate verdict; tested.
- **Reference:** Layer 2 kill-gate.

**GATE 2 — THE KILL-GATE:** no strategy proceeds toward capital without passing all seven criteria on honest, cost-inclusive, point-in-time data. Most ideas die here. Tag `gate-2-research`.

---

## PHASE 3 — Capital Layer

#### P3.1 — Risk-limit engine (first)
- **Goal:** the un-overridable safety harness.
- **Depends on:** GATE 2
- **Deliverable:** `capital/risk/` — per-trade stop manager, daily-loss halt, drawdown circuit breaker, exposure/position caps, consecutive-loss throttle, **kill-switch** (manual + auto triggers). Authority to veto/flatten.
- **Done when:** each limit fires correctly under simulated breach scenarios in `tests/adversarial/`; kill-switch flattens; limits cannot be bypassed by a model.
- **Reference:** Layer 3 risk.

#### P3.2 — Signal combination + selection
- **Goal:** many signals → one ranked candidate set.
- **Depends on:** GATE 2
- **Deliverable:** `capital/combine/` — rank-averaging (default), IC-weighting; cross-sectional selection; eligibility filters (liquidity, spread/cost, ESM/T2T, event).
- **Done when:** combination + selection produce a candidate set with filters applied; tested.
- **Reference:** Layer 3 combination.

#### P3.3 — Portfolio construction + constraints
- **Goal:** weight the selected names robustly.
- **Depends on:** P3.2
- **Deliverable:** `capital/portfolio/` — equal-weight, inverse-vol (default), HRP; constraints (name/sector caps, gross/net, max positions, no-trade band/turnover).
- **Done when:** each weighting honors constraints; no-trade band suppresses cost-losing churn; HRP runs on a singular covariance without error; tested.
- **Reference:** Layer 3 portfolio.

#### P3.4 — Position sizing
- **Goal:** convert conviction to size, conservatively.
- **Depends on:** P3.3
- **Deliverable:** `capital/sizing/` — volatility-target scalar + fractional-Kelly from meta-probability + fixed risk-per-trade cap + clamps.
- **Done when:** sizes respect the risk-per-trade cap and weight caps; fractional-Kelly uses calibrated `p`; vol-target scaling capped; tested.
- **Reference:** Layer 3 sizing.

#### P3.5 — Capital pipeline integration
- **Goal:** signal → portfolio → sizing → risk-check, end to end.
- **Depends on:** P3.1, P3.4
- **Deliverable:** integrated pipeline producing risk-checked target orders; backtest run with limits active.
- **Done when:** the pipeline emits orders inside every hard limit; limits provably fire in a backtested stress scenario; tested.
- **Reference:** Layer 3.

**GATE 3:** hard limits provably fire in simulation; portfolio + sizing validated end-to-end. Tag `gate-3-capital`.

---

## PHASE 4 — Execution Layer

#### P4.1 — OMS state machine + durable store
- **Goal:** model orders as a recoverable state machine.
- **Depends on:** P0.5
- **Deliverable:** `execution/oms/` — order state machine; durable store (local key ↔ broker `order_id` ↔ state), persisted before/after each call.
- **Done when:** state transitions correct; a simulated crash recovers state from the store; tested.
- **Reference:** Layer 4 lifecycle/idempotency.

#### P4.2 — Order-update ingestion (single source of truth)
- **Goal:** reconcile postbacks + WebSocket updates + polling.
- **Depends on:** P4.1
- **Deliverable:** postback receiver + WebSocket order-update consumer + order-history poller → one consistent order state.
- **Done when:** a missed postback is recovered by polling; the stuck-status case is handled; tested.
- **Reference:** Layer 4 lifecycle.

#### P4.3 — Order router + ≤10-OPS throttle
- **Goal:** choose and place the right order, compliantly.
- **Depends on:** P4.1, P1.1
- **Deliverable:** `execution/router/` — order-type selection (limit-near-touch, market+protection, SL-M), cancel-replace with modification budgeting, **token-bucket ≤10-OPS throttle**, market-protection enforcement.
- **Done when:** never exceeds 10 OPS; rejects without market protection are avoided; 429 handled with backoff; tested.
- **Reference:** Layer 4 order types/compliance.

#### P4.4 — Slicer
- **Goal:** work larger orders without impact or OPS breach.
- **Depends on:** P4.3
- **Deliverable:** slicer (≤10 slices, TWAP spacing, freeze-limit child handling, iceberg threshold).
- **Done when:** large orders split correctly (≤10), children tracked; tested.
- **Reference:** Layer 4 execution.

#### P4.5 — Reconciliation loop + stop-existence guarantee
- **Goal:** keep reality and intent aligned; never leave a position unprotected.
- **Depends on:** P4.2, P3.1
- **Deliverable:** `execution/reconcile/` — continuous + on-restart reconciliation of intended↔broker↔positions; **guarantees a stop exists for every open position**; repairs discrepancies.
- **Done when:** an open position without a stop is detected and a stop placed; discrepancies repaired; tested.
- **Reference:** Layer 4 reconciliation.

#### P4.6 — Execution safety
- **Goal:** the backstops.
- **Depends on:** P4.5
- **Deliverable:** `execution/safety/` — system-side stop monitor; end-of-day **self-square-off (~15:15)**; disconnect/feed-loss → kill-switch escalation; 429 backoff.
- **Done when:** system-side stop fires if no exchange stop confirmed; self-square-off flattens before auto-square-off; feed loss escalates; tested.
- **Reference:** Layer 4 failure handling.

#### P4.7 — Implementation-shortfall measurement
- **Goal:** measure execution quality vs the backtest assumption.
- **Depends on:** P4.2
- **Deliverable:** `execution/shortfall/` — per-trade realized slippage + shortfall decomposition, emitted to monitoring.
- **Done when:** shortfall computed per trade and compared to the model; tested.
- **Reference:** Layer 4 shortfall.

#### P4.8 — Adversarial execution tests
- **Goal:** prove safety under failure.
- **Depends on:** P4.6
- **Deliverable:** `tests/adversarial/` — kill WebSocket mid-trade, time out placement, force partial fill, duplicate-prevention.
- **Done when:** under every injected failure the system never ends naked or doubled, and always has a stop per position.
- **Reference:** Layer 4.

**GATE 4:** adversarial execution tests pass; no naked/doubled positions under injected failures. Tag `gate-4-execution`.

---

## PHASE 5 — Operations Layer

#### P5.1 — Daily lifecycle scheduler
- **Goal:** the calendar-aware daily state machine.
- **Depends on:** P0.4, GATE 4
- **Deliverable:** `ops/scheduler/` — PRE-OPEN → OPEN → SELF-SQUARE-OFF → POST-CLOSE state machine; pre-open gate; end-of-day routine.
- **Done when:** runs the full cycle on a simulated day; pre-open gate blocks on any failed check; tested.
- **Reference:** Layer 5 lifecycle.

#### P5.2 — Morning auth/token routine
- **Goal:** compliant daily session seeding.
- **Depends on:** P1.1, P5.1
- **Deliverable:** manual-seed + automated-session routine; one-session-per-key handling; token persistence.
- **Done when:** seeds a token via the documented flow and serves it to all components; handles expiry; tested (with fakes).
- **Reference:** Layer 5 auth.

#### P5.3 — Monitoring metrics + dashboard
- **Goal:** a live gauge for every limit and assumption.
- **Depends on:** GATE 4
- **Deliverable:** `ops/monitor/` — metrics emission + dashboard (P&L, exposure/margin, slippage-vs-model, latency, reject rates, drawdown, feed/connection/token health).
- **Done when:** all key metrics surfaced live; tested on simulated streams.
- **Reference:** Layer 5 monitoring.

#### P5.4 — P&L attribution
- **Goal:** know what's working.
- **Depends on:** P5.3, P4.7
- **Deliverable:** `ops/attribution/` — per-strategy/name P&L (via tags) + signal-vs-execution decomposition.
- **Done when:** attribution reconciles to total P&L; decomposition isolates execution drag; tested.
- **Reference:** Layer 5 attribution.

#### P5.5 — Drift detection (observe-only first)
- **Goal:** detect when the edge dies.
- **Depends on:** P2.2, P5.3
- **Deliverable:** `ops/drift/` — performance (vs CPCV distribution), data (PSI/KS), concept (IC decay, calibration, ADWIN/Page-Hinkley); throttle/halt/retrain triggers with pre-set thresholds; runs observe-only initially.
- **Done when:** detectors fire on injected drift; thresholds configurable; tested.
- **Reference:** Layer 5 drift.

#### P5.6 — MLOps: retraining + champion/challenger
- **Goal:** manage a decaying edge.
- **Depends on:** P2.7, P5.5
- **Deliverable:** `ops/mlops/` — scheduled + drift-triggered walk-forward retrain; champion/challenger shadow harness; **kill-gate re-run on every candidate**; registry + instant rollback.
- **Done when:** a challenger trains, shadows, and is promoted only after passing the kill-gate; rollback works; tested.
- **Reference:** Layer 5 MLOps.

#### P5.7 — Platform: audit, alerting, secrets, config
- **Goal:** production plumbing.
- **Depends on:** P0.2, P0.3
- **Deliverable:** `ops/platform/` — append-only audit log; tiered alerting (Telegram/email) with CRITICAL triggers; secrets manager wiring; config-as-code finalized.
- **Done when:** CRITICAL events alert; audit immutable; no secrets in logs; tested.
- **Reference:** Layer 5 platform.

#### P5.8 — Infra & disaster recovery
- **Goal:** survive crashes with positions safe.
- **Depends on:** P4.5, P5.7
- **Deliverable:** containerization; state durability/recovery; **panic-flatten path + exchange-resident SL-M stops**; backups; process supervision; DR docs.
- **Done when:** killing the engine mid-session in a test leaves positions protected (exchange stops) and the panic-flatten path works; recovery reconciles cleanly; tested.
- **Reference:** Layer 5 DR.

**GATE 5:** the daily cycle runs hands-off (after manual seed); DR validated. Tag `gate-5-operations`.

---

## PHASE 6 — Paper Trading

#### P6.1 — End-to-end paper trading
- **Goal:** run the full system against live data with the real execution path, no real capital.
- **Depends on:** GATE 5
- **Deliverable:** paper/sim trading wired through the real OMS/router/reconciliation against live data (real latency, rate limits, session resets).
- **Done when:** the system trades a full day on paper with correct lifecycle, attribution, and zero operational failures; tested over multiple days.
- **Reference:** Project plan Phase 3; Layers 4–5.

#### P6.2 — Live-vs-backtest validation
- **Goal:** confirm paper tracks backtest and slippage matches the model.
- **Depends on:** P6.1
- **Deliverable:** comparison reports (paper P&L vs backtest expectation; realized vs modeled slippage); operational hardening fixes.
- **Done when:** paper performance falls within the backtest's plausible range; slippage model validated or corrected.
- **Reference:** Layer 5 drift/monitoring.

**GATE 6:** paper P&L tracks backtest within tolerance; slippage model validated; zero operational failures over a sustained period. Tag `gate-6-paper`.

---

## PHASE 7 — Control Layer (Mobile Master Control)

#### P7.1 — Control API gateway (auth + scopes)
- **Goal:** the hardened backend the app talks to.
- **Depends on:** GATE 5
- **Deliverable:** `control/` — control API with device-bound, short-lived, revocable tokens; TLS; read vs control scopes; rate limiting; against a stubbed engine first.
- **Done when:** auth + scope enforcement tested; tokens revocable; no broker secrets exposed; tested.
- **Reference:** Layer 6 security/API.

#### P7.2 — Bounded command handlers + clamping + 2FA
- **Goal:** safe control actions only.
- **Depends on:** P7.1, P3.1
- **Deliverable:** handlers (flatten/pause/stop/start/limits/strategy/model) with **server-side clamping to hard bounds**, 2FA on risk-increasing actions, audit logging.
- **Done when:** limits cannot be loosened past ceilings; risk-increasing actions require 2FA; flatten/stop are fail-safe and fast; every action audited; tested.
- **Reference:** Layer 6 API/security.

#### P7.3 — Telemetry stream
- **Goal:** live read path to clients.
- **Depends on:** P7.1, P5.3
- **Deliverable:** WSS/SSE stream of metrics/positions/P&L/health/alerts.
- **Done when:** clients receive live telemetry; reconnects handled; tested.
- **Reference:** Layer 6 architecture.

#### P7.4 — Private-network setup
- **Goal:** keep the API off the public internet.
- **Depends on:** P7.1
- **Deliverable:** VPN/WireGuard/Tailscale configuration + docs (operator runs it).
- **Done when:** the API is reachable only over the private network in the documented setup.
- **Reference:** Layer 6 security.

#### P7.5 — PWA dashboard
- **Goal:** the master-control app UI (the real version of the prototype).
- **Depends on:** P7.2, P7.3
- **Deliverable:** `app/` — responsive PWA (dashboard, positions, risk/limits, strategies, health/drift, alerts, models, activity log) against the control API; works against the stubbed engine.
- **Done when:** all screens function against the API; control actions go through scopes/2FA/clamping; tested.
- **Reference:** Layer 6 features/stack.

#### P7.6 — APK wrapping (operator-signed)
- **Goal:** an installable APK.
- **Depends on:** P7.5
- **Deliverable:** Bubblewrap/TWA (or Capacitor) wrapper config + Digital Asset Links + signing-key generation docs (**operator generates and holds the key**).
- **Done when:** build config produces an APK locally; signing documented; *the operator performs the signed build* (Claude does not).
- **Reference:** Layer 6 stack; Part I working method.

#### P7.7 — Security validation
- **Goal:** prove the control surface is safe.
- **Depends on:** P7.2, P7.4
- **Deliverable:** run the Layer-6 security checklist; stolen-phone scenario test; end-to-end flatten/kill verification.
- **Done when:** every checklist item passes; stolen-phone blast radius confirmed bounded to "turn the bot off"; flatten/kill verified end-to-end.
- **Reference:** Layer 6 checklist.

**GATE 7:** security checklist fully passes; flatten/kill works end-to-end. Tag `gate-7-control`.

---

## PHASE 8 — Live, Micro Size *(operator-driven; Claude assists, never acts alone)*

#### P8.1 — Go live, trivially small
- **Goal:** validate live ≈ paper, not to make money.
- **Depends on:** GATE 6, GATE 7
- **Deliverable:** live deployment with trivial capital; full monitoring/drift/limits/alerts/panic-flatten active. **Operator confirms and executes; Claude does not place real orders.**
- **Done when:** live behaves like paper; all safety systems verified live; daily reports clean.
- **Reference:** Project plan Phase 4.

#### P8.2 — Sustained live validation
- **Goal:** earn the right to scale.
- **Depends on:** P8.1
- **Deliverable:** months of live track record vs expectations; honest performance audit.
- **Done when:** sustained live performance is consistent with the backtest distribution before any capital increase.
- **Reference:** Project plan Phase 4.

**GATE 8:** sustained live consistency before scaling capital — and even then, scale slowly (edge is capacity-limited). Tag `gate-8-live`.

---

## PHASE 9 — Operate, Re-mine, Decay-manage *(ongoing)*

- Automated walk-forward retraining; continuous research for new signals (edges decay to zero — replace them); periodic SEBI-compliance review; quarterly honest performance audit with pre-defined kill criteria for dying strategies. The program never "finishes"; it is maintained.

---

# PART V — PROGRESS LOG

*Claude updates this at the end of every session.* **The authoritative, full log now lives at [`docs/PROGRESS.md`](docs/PROGRESS.md)** — the snapshot below mirrors its top-level status.

| Date | Subtask | Status | PR / commit | Tests | Notes / decisions / follow-ups |
|---|---|---|---|---|---|
| 2026-06-17 | P0.1 | ☑ done | `feat/p0.1-repo-tooling` (merged) | 2 passing | uv toolchain; ruff/black/mypy/pytest/pre-commit all green. Details in `docs/PROGRESS.md`. |
| 2026-06-17 | P0.2 | ☑ done | `feat/p0.2-config-secrets` (merged) | 34 passing | Layered typed config (pydantic) + env-var overrides + secrets interface; 99% cov. |
| 2026-06-17 | P0.3 | ☑ done | `feat/p0.3-logging-audit` (merged) | 58 passing | Structured logging (IST, correlation IDs, redaction) + hash-chained append-only audit log; 100% cov. |
| 2026-06-17 | P0.4 | ☑ done | `feat/p0.4-nse-calendar` | 87 passing | IST trading-calendar/session utility (trading days, holidays, session phases); 100% cov. |
| | P0.5 | ☐ todo | | | next |
| | … | | | | |

**Gate status:** Gate 0 ☐ · Gate 1 ☐ · Gate 2 ☐ · Gate 3 ☐ · Gate 4 ☐ · Gate 5 ☐ · Gate 6 ☐ · Gate 7 ☐ · Gate 8 ☐

---

# PART VI — REFERENCE FILES

The six detailed deep-dive documents (full rationale, formulas, and grounded sources) live in `docs/deep_dives/`:
1. `01_DeepDive_Data_and_Feature_Layer.md`
2. `02_DeepDive_Research_Layer.md`
3. `03_DeepDive_Capital_Layer.md`
4. `04_DeepDive_Execution_Layer.md`
5. `05_DeepDive_Operations_Layer.md`
6. `06_DeepDive_Control_Layer_Mobile_App.md`

Part III above is a faithful distillation of these; consult them when a subtask needs deeper detail.

---

*This is an engineering and research reference, not financial advice. The author/operator is not a licensed financial advisor. Over 90% of retail F&O traders lose money; "high stable profit" is not promised by this system. Trading carries substantial risk of loss, and nothing here is a recommendation to trade, to use leverage, or to take any particular position. Treat the safety rules and security checklist as mandatory.*
