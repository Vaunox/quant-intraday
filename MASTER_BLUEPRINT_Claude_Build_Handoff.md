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
- Before each subtask, **read its referenced deep dive and cite it** per Ground Rule 9.
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
- **OS-portable code, always.** All path handling must use `pathlib.Path` (or `os.path` equivalents) — never hardcode `\` or `/` separators or platform-specific path strings. Subprocess and shell invocations must work on both Windows (dev) and Linux (deployment); when OS-specific commands are unavoidable (e.g., venv activation), document both variants. No imports of platform-only stdlib modules (`fcntl`, `winreg`, etc.) in shared business logic. A test for OS-portability is: would this code path run identically inside the CI Ubuntu container and on the operator's Windows dev box? If not, it must be refactored.

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

1. **The kill-gate is sacred.** No strategy receives capital — not even paper-to-live promotion — without passing **all seven** kill-gate criteria (Part III, Layer 2). No tweaking-until-it-passes; that is overfitting and inflates the trial count the Deflated Sharpe will punish. Most ideas should die here. That is success, not failure. A failed kill-gate is not a project failure — it is a routing signal. A failed kill-gate diverts the build into Phase 2R (research iteration loop), not forward into Phase 3. The agent must never proceed from a failing P2.9 verdict into Phase 3 work. Phase 3 (Capital Layer) and beyond are gated on a passing P2.9 — not on having merely completed P2.9. Treat "P2.9 emits a kill verdict" as a fork in the road, not a milestone behind you.
2. **Point-in-time correctness, always.** No feature may use data unavailable at decision time. Decisions on bar *t*'s close execute at bar *t+1*'s open — identically in backtest and live. All normalization uses trailing/expanding windows only. Leakage tests run in CI.
3. **Hard risk limits sit above every model.** The risk-limit engine (per-trade stop, daily-loss halt, drawdown circuit breaker, exposure caps, kill-switch) can veto or flatten anything and cannot be overridden by a model or by a human mid-session. The kill-switch must always work and is tested.
4. **Costs are always modeled.** No gross-only backtests. The full Indian cost model (brokerage, STT, exchange charges, GST, stamp duty) plus realistic slippage applies to every simulation.
5. **The phone is a remote control, never the brain.** Broker secrets live only on the server; orders originate only from the static-IP server; the app sends bounded, server-clamped intents whose most powerful action is fail-safe (flatten/stop). Control API behind a VPN.
6. **SEBI compliance is non-negotiable.** Stay a sub-10-OPS white-box personal user: ≤10 orders/second (self-throttled), static-IP order placement, daily manual auth seed, market protection on market/SL-M orders, every order strategy-tagged. Exclude ESM/T2T names (no intraday trading).
7. **Honesty about outcomes.** "High stable profit" is not a goal and is not promised. Over 90% of retail F&O traders lose money — that is the operating reality. The achievable target is a positive-expectancy, risk-controlled system with a small, decaying edge that is continuously re-mined. The system must be able to fail and to stop.
8. **Build in dependency order; respect the gates.** Do not proceed past a failed gate.
9. **Ground every decision in the reference docs, and cite them.** Before building a subtask, read its Reference pointer — the relevant Part III section and the corresponding docs/deep_dives/NN document — and treat those as the source of truth. Ground every non-trivial design decision in the deep dives, Part III, and these Ground Rules rather than in general knowledge, and cite the specific section it is based on (e.g. "Deep Dive #2 §3.4") in your notes and PR so the reasoning is auditable. If the docs are silent on a decision, or conflict with the blueprint or the existing code, STOP and surface it to the operator with options — do not guess, and do not patch around it.

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
| Production deployment OS | Linux (Ubuntu LTS) in AWS ap-south-1 | ~50–60% cost saving vs Windows for the same instance class; native fit for systemd, Docker, SSM Session Manager, CloudWatch agent; matches the Phase-8 runbook in Part II's Cloud compute policy. Windows server deployment is explicitly out of scope. Dev machine OS (operator) is unconstrained — Windows, Linux, or macOS all work; CI runs Ubuntu to guarantee Linux parity on every push. |

## Environment policy (research vs engine)

The project uses **two separate Python environments, by design** — to keep the production
engine's dependencies clean while letting the research/notebook side pin differently when
an optional backend (e.g. ArcticDB, which currently requires `pandas<3`) demands it:

- **Engine environment** (the default uv env for `src/quant/`): tracks current pandas
  (3.x) and the minimum runtime deps for live operation. Optional backends are **not**
  installed here. This is what runs the daily lifecycle, OMS, monitoring, control API.
- **Research environment** (a separate uv env, e.g. `.venv-research/`, used for
  `notebooks/` and the `research/labeling/validation` packages): may pin `pandas<3` and
  install optional backends like `arcticdb` for versioned dataset workflows. Never
  imported by the engine.

**Rule:** storage backends live behind the `Repository` interface (Deep Dive #1 §1.2).
The engine never depends on an optional backend; the research env may. If a backend's
constraints would force a project-wide pin (e.g. `pandas<3` everywhere), **do not apply
it** — either keep the backend operator-installed in the research env, or swap to a
compatible alternative behind the same interface (e.g. QuestDB) per the deep dive.
Repository abstractions exist precisely so storage choices don't dictate to the rest of
the codebase.

This policy is referenced by the dependency choices in **P1.3** (Parquet + Redis in the
base engine deps; ArcticDB operator-installed in research) and should guide every future
"should I add this dep?" decision.

## Research environment setup (operator runbook)

The Environment Policy says optional backends (ArcticDB, MLflow) live in a separate research env, never in the engine env. This is the standard, cross-platform runbook for standing that env up. The recipe assumes `uv` as the toolchain and is correct on Windows, Linux, and macOS.

### Standing it up (one time, ~15 minutes)

```bash
# from the repo root — works the same on Windows / Linux / macOS

# 1) create the research venv (separate from the engine env)
uv venv .venv-research --python 3.12

# 2) activate it (the activation command is the only platform-specific line)
#    Windows (PowerShell): .venv-research\Scripts\Activate.ps1
#    Windows (cmd.exe):    .venv-research\Scripts\activate.bat
#    Linux / macOS:        source .venv-research/bin/activate

# 3) install research-only packages into the now-active env
uv pip install "pandas<3"
uv pip install mlflow arcticdb
# (add other research-only packages here as future subtasks introduce them)

# 4) verify
mlflow --version
python -c "import mlflow, arcticdb, pandas; print(pandas.__version__)"
# expected: pandas reports a 2.x version inside this env (the engine env stays 3.x)

# 5) deactivate when finished (`deactivate` on all platforms)
```

Before exiting this subsection, also ensure the repo's `.gitignore` covers `.venv-research/` and `mlruns/`. If it does not, that's a one-line fix tracked as part of the first subtask that needs persistent tracking — not part of this docs PR.

### Running MLflow tracking for a research run

```bash
# Terminal A — start a local MLflow server bound to localhost only.
# NOTE (MLflow 3.x, verified 2026-06-24 in P2A.4): the file store (./mlruns) is deprecated and
# `mlflow server` refuses it — use a sqlite backend. Keep the db + artifacts under mlruns/ (gitignored).
#   Windows:       .venv-research\Scripts\mlflow.exe server --backend-store-uri "sqlite:///mlruns/mlflow.db" --default-artifact-root "./mlruns/mlartifacts" --host 127.0.0.1 --port 5000
#   Linux / macOS: .venv-research/bin/mlflow     server --backend-store-uri "sqlite:///mlruns/mlflow.db" --default-artifact-root "./mlruns/mlartifacts" --host 127.0.0.1 --port 5000

# Terminal B — activate the research env, then run training with the URI set
#   (activate per the platform line above)
#   then:
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000     # Linux / macOS
$env:MLFLOW_TRACKING_URI = "http://127.0.0.1:5000"    # Windows PowerShell
set MLFLOW_TRACKING_URI=http://127.0.0.1:5000         # Windows cmd.exe
$env:PYTHONUTF8 = "1"   # Windows only: MLflow prints a 🏃 emoji that crashes the cp1252 console without it

python -m quant.research.<your_entry_point>
```

The training code path does not change. `MLflowExperimentTracker` (built in P2.6) lazy-loads when `mlflow` is importable; the in-memory tracker is used otherwise. Setting `MLFLOW_TRACKING_URI` is what activates persistence. `--host 127.0.0.1` keeps the MLflow UI bound to localhost — do not expose the MLflow server to a public interface.

### When the research env is REQUIRED (auto-trigger)

Stand up the research env (if not already standing) before starting any subtask that meets either condition:

1. The subtask produces artifacts that will be promoted to the model registry, fed into the kill-gate report (P2.9), used in champion/challenger promotion, or otherwise persisted across sessions.
2. The subtask runs hyperparameter tuning, multi-configuration comparison, or any process whose honest trial count must survive across sessions for the Deflated Sharpe computation in P2.9.

By the current blueprint, this trigger fires for at least: P2.7 (ensemble + regime gate + registry), P2.8 (CPCV + robustness battery), P2.9 (validation report + kill-gate emitter), P5.6 (scheduled + drift-triggered retraining, champion/challenger), and any subsequent model-promotion or retrain run.

Mandatory start-of-subtask procedure for any subtask the trigger fires for (this is acceptance-criterion-grade, not advisory):

1. Verify the research env exists and is healthy (`mlflow --version` inside it). If it does not exist, stand it up using the recipe above before any other work on the subtask — do not fall back to the in-memory tracker.
2. Start a local MLflow server (or confirm one is running), bound to `127.0.0.1`, with a persistent backend store at `./mlruns`.
3. Ensure `MLFLOW_TRACKING_URI` is set in the training process's environment.
4. Log every configuration tried as a separate MLflow run (the trial-count rule — this is what makes P2.9's Deflated Sharpe honest).
5. Record in `docs/PROGRESS.md` that persistent MLflow tracking is in use for this subtask, including the MLflow run-IDs or experiment-ID(s) produced. Failing to record this is a missed acceptance criterion for the subtask.

Falling back to the in-memory tracker silently for an auto-trigger subtask is a silent correctness violation of P2.9's Deflated Sharpe contract — treat it the same way the codebase treats a CI lint failure: do not merge.

### Tooling integration

- The repo's `mypy`/`ruff` configuration must exclude `.venv-research/` so static analysis does not traverse research dependencies. If not already excluded, fixing the exclusion is part of the first subtask that creates the research env, not part of this docs PR.
- The CI confinement test introduced in P2.6 (which fails the build if `mlflow` or `lightgbm` leak outside `src/quant/research/models/`) remains in force regardless — the research env exists to let the operator use these packages, not to let them leak into the engine.

### Rules (always apply)

- Engine env never installs `mlflow`, `arcticdb`, or anything else that would force pandas < 3. The CI confinement test enforces this.
- Research env is for research scripts and notebooks only. It must never be imported by the engine.
- `.venv-research/` and `mlruns/` are gitignored. Run history is local artifact, not source.
- Persistence is not optional for runs that meet the auto-trigger conditions above — it is a correctness requirement (honest trial count → honest DSR in P2.9).
- Bind MLflow UI to `127.0.0.1` only. Never expose it on a public interface.
- When MLflow eventually relaxes the pandas pin, this whole subsection becomes optional and `mlflow` may move to the engine env. Until then, this is the standard.

This runbook is referenced by every subtask in the auto-trigger list and supersedes any subtask-local instruction about how/when to set up persistent experiment tracking.

## Cloud compute policy (AWS)

**Default: local.** Training, research, and validation run on the operator's machine. The cloud is rented only when a specific, justified need exists — never as the default for compute.

**Two legitimate cloud uses, and only these:**

1. **Heavy one-shot research runs** — final P2.7 stack runs and the full P2.8 CPCV + robustness battery; periodic walk-forward retrains in Phase 5. Spin up → run → fetch artifacts → terminate. **Always spot, always time-bounded.**
2. **The live engine + supporting services in Phase 8** — fixed-IP VPS in `ap-south-1` (Mumbai) hosting the engine, control API, and MLflow tracking server. This is **required by SEBI's static-IP rule**, not optional.

### One-time setup (do once, before first cloud use)

**Account hygiene:**
- **Region: `ap-south-1` (Mumbai)** — non-negotiable for the live engine (latency to NSE); use it for research runs too so data transfer to/from the engine is free.
- **Never use the root account** for project work. Create a dedicated IAM user, enable MFA on both root and the IAM user, lock root credentials away, and operate via the IAM user only.
- Programmatic access keys live only in the secrets interface (`core/secrets.py`) or AWS Secrets Manager — never in code, config files, environment files in git, or the repo.
- **IMDSv2 required** on every EC2 instance launched (`HttpTokens=required`) — prevents SSRF metadata theft.

**Cost guardrails (do these on Day 1 — they pay for themselves the first time something is misconfigured):**
- AWS Budgets: a monthly **hard budget alert** at 50%, 80%, and 100% of the available credit balance, with email notifications.
- A **CloudWatch billing alarm** independent of Budgets as a backup.
- **A "kill-all" runbook in `docs/`** — exact CLI commands to terminate every project EC2 instance and release unused EIPs if cost ever spikes unexpectedly. Test it once.
- **Free-tier awareness:** before introducing a new service, check whether a free-tier alternative exists; document the choice in `docs/PROGRESS.md` if you pick the paid one.
- **Mandatory tags on every resource:** `project=quant-intraday`, `purpose={research|engine|mlflow|...}`, `lifecycle={ephemeral|persistent}`. Set a tag policy so untagged resources are flagged.

**Networking — read this before launching anything, because mistakes here are how credits evaporate:**
- **NAT Gateway is the #1 silent cost.** ~$0.045/hour + per-GB egress. If the live engine sits in a private subnet pulling market data through a NAT, that's ~$33/month minimum + data transfer. For Phase 8 engine: put it in a **public subnet with an Elastic IP** (the EIP is required anyway for the static-IP whitelist) and a **strict security group** — no NAT needed, and no extra cost. Document this choice in the runbook so no one "improves" it later.
- **Outbound data transfer costs money** (~$0.09/GB out of `ap-south-1`). Keep S3, EC2, and MLflow all in `ap-south-1` so intra-region transfer is free. Never transfer raw market data to another region.
- **VPC Endpoints for S3** (Gateway endpoint — *free*) so EC2 → S3 traffic never traverses the public internet or NAT. Enable this in the default VPC for the project.

**Storage:**
- One project S3 bucket, versioning **on**, default encryption **on** (SSE-S3 minimum).
- **S3 Lifecycle rules:** transition raw archive to Glacier after 90 days; expire incomplete multipart uploads after 7 days (silent storage leak otherwise); expire old `runs/` artifacts older than 1 year unless tagged `keep=true`.
- **Block all public access** at the account and bucket level.

### Standard runbook — heavy research run (e.g. final P2.7, P2.8)

**Pre-launch checklist — verify each item before clicking Launch:**
- [ ] Region is `ap-south-1`.
- [ ] Instance type is a **spot request**, not on-demand (confirm in the request).
- [ ] AMI is the project's pinned base image (or Ubuntu LTS with the env Docker pulled at boot).
- [ ] **No public IPv4** unless strictly needed; access via **AWS Systems Manager Session Manager (SSM)** instead of SSH keys (no inbound port required, audit-logged, no key management).
- [ ] Security group: outbound to S3/internet only; **no inbound from `0.0.0.0/0`**.
- [ ] IAM instance profile attached with **least-privilege** — read project S3 prefix, write runs prefix, nothing else.
- [ ] **IMDSv2 enforced**.
- [ ] Root volume encrypted; tags applied; `lifecycle=ephemeral`.
- [ ] CloudWatch agent configured to ship logs.

**Run:**
1. Build a Docker image with the engine env pinned to the same versions as local (reproducibility).
2. Launch the spot instance per the checklist.
3. Pull data + code from the private S3 prefix; never embed credentials in the AMI — use the IAM instance profile.
4. Run the job; stream logs to CloudWatch; write artifacts (MLflow runs, validation reports, model files) **directly to S3 as they're produced**, not only at the end — spot instances can be reclaimed with 2 minutes' notice, and unsaved work is gone.
5. Implement **graceful shutdown handling**: trap SIGTERM, flush current artifacts to S3, log the partial state, exit cleanly. Jobs must be safe to interrupt and resume.

**Pre-termination checklist — verify each item before clicking Terminate:**
- [ ] Final artifacts confirmed in S3 (`aws s3 ls` against the runs prefix).
- [ ] CloudWatch logs flushed and visible in the console.
- [ ] MLflow run is closed with status set (`FINISHED` / `FAILED`), not left `RUNNING`.
- [ ] Cost recorded in `docs/PROGRESS.md` for the subtask.
- [ ] Any attached EBS volumes set to delete-on-termination (otherwise they persist and silently charge).
- [ ] Elastic IP (if any) released — an unattached EIP charges ~$3.60/month.
- [ ] No other resources from this run still running (a stray Lambda, ECR push job, etc.).

**Terminate the instance.** Spot does not auto-stop on idle; an unmonitored instance is a credit leak. Most credit-loss stories start with "I forgot it was running."

### Standard runbook — Phase-8 live engine VPS

- **Sizing:** smallest instance that meets engine CPU/RAM needs (`t3.small` or `t3.medium` usually suffices — engine is I/O-bound). Use `t4g` (ARM) if all dependencies are ARM-compatible — meaningfully cheaper.
- **Public subnet, Elastic IP attached** — saves NAT cost and provides the static IP needed for the SEBI register-with-broker step. **Once registered with Kite, the EIP must not change** (losing it means re-registering, lost trading days).
- **Register the EIP with Kite Connect** in the broker developer console as the static IP for order placement (Layer 5 morning auth routine assumes this is done).
- Engine runs under **systemd** with `Restart=always`; logs ship to CloudWatch; metrics flow to the operations layer's dashboard (Layer 5).
- **EBS root encrypted at rest; daily AWS Backup snapshots; restore tested once per quarter** (an untested backup is not a backup).
- Secrets (broker API key/secret, daily access token, Telegram bot token, etc.) injected via environment from **AWS Secrets Manager** — never baked into the AMI, never in git. Rotate as appropriate.
- **Security group:** inbound only the ports the control API needs, and only from the VPN/private network (per Layer 6 security model). Kite API and broker traffic are outbound only.
- **Control API reachable only over the VPN** — never publicly routed. Per Layer 6.
- **Daily auth flow** (Layer 5 morning routine): the manual TOTP seed at ~7:30 AM IST writes the fresh access token into Secrets Manager; the engine reads from there. Document the runbook in `docs/`.
- **IMDSv2 enforced; no SSH key pair** — use SSM Session Manager.
- **CloudTrail enabled** on the account for audit (SEBI traceability).

### Iteration discipline (the rule that protects the credit budget)

For research subtasks the policy marks as cloud-by-default (currently P2.7 and P2.8): **only *final* runs go to cloud**. Iterative development — tweaking features, hyperparameters, label/weight schemes, debugging a fold — stays local.

A run qualifies as a "final" cloud run only if **all** of the following hold:
- The code, config, data version, and feature version are pinned and committed to git.
- A short local smoke run (small universe or fold subset) has completed successfully on the same code path within the last 24 hours.
- The artifacts produced will be promoted to the model registry or fed into the kill-gate report — not thrown away as exploratory.
- The operator has been notified of the planned cloud run, its expected duration, and its expected cost in `docs/PROGRESS.md`.

Counter-examples — these stay **local**, regardless of the subtask's default:
- "Let me try one more feature subset and see if Sharpe improves" — local.
- "Re-run with a different regime-component count" — local.
- "Debug a fold that crashed" — local on the offending fold only.
- "I changed one hyperparameter and want to re-test" — local.

The cost of cloud isn't the per-run charge — it's the *frequency* of casual re-runs at cloud rates. Spending $3 once on a real final run is sensible; spending $3 × 20 on iterative tweaks is how a credit budget evaporates without anything to show for it. Default cloud + this discipline gives you the speed where it matters and the thrift where it doesn't.

### Rules of the policy (always apply)

- **Cost discipline:** every cloud invocation is justified in writing in `docs/PROGRESS.md` with the reason, expected spend, and actual spend after the run. The credits are finite and **reserved primarily for Phase 8**; research runs are a secondary use.
- **No persistent training infrastructure.** Spot → run → fetch → terminate. A standing training instance is an anti-pattern at this scale.
- **Reproducibility first.** Every cloud run is reproducible from a local config + Docker image + versioned data. If a run can't be reproduced locally given enough time, it shouldn't run in cloud either.
- **Idempotency and resumability.** Cloud jobs must be safe to interrupt and resume — spot instances can be reclaimed with 2 minutes' notice.
- **No production data on research instances** unless strictly needed; research reads from the immutable raw archive in S3, never from the live engine's state.
- **Stop, don't terminate, only when you'll resume within 24 hours.** Otherwise terminate. Stopped instances don't bill compute but still bill EBS.

### What an AI agent must NOT do without explicit operator approval

- Launch **on-demand** instances (must be spot unless explicitly approved).
- Launch instances **outside `ap-south-1`**.
- Create or attach a **NAT Gateway**.
- Open a security group inbound to **`0.0.0.0/0`**.
- Create resources without the mandatory tags.
- Create **public S3 buckets** or disable Block Public Access.
- Provision a **standing training instance** of any kind.
- Use the **root account** for anything.
- Hard-code credentials anywhere, including in user-data scripts, AMIs, or environment files in git.
- Touch the **registered static IP** (EIP attached to the live engine) — once registered with the broker, it must not change.

If any of the above is genuinely needed for a subtask, **STOP and surface it to the operator with the rationale, expected cost, and alternatives** — per Ground Rule 9. Do not proceed unilaterally.

This policy is referenced by P2.7, P2.8, and Phase 8; future subtasks proposing cloud use must justify it against the two legitimate uses above and follow the runbooks here.

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

> **Portability note:** the development workflow must work on Windows, Linux, and macOS. CI already runs on Ubuntu, providing automatic Linux parity verification on every push. The production deployment target is Linux per Part II's locked-decisions table. All code must satisfy Ground Rule 2's OS-portability bullet.

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

> **Compute note:** the ensemble + regime gate + meta-model stack is the second-heaviest research run. **Final P2.7 runs (whose artifacts feed P2.9 / the kill-gate) execute on cloud by default** — spot `c7i.8xlarge` in `ap-south-1`, ≈2–4 hrs, ≈$2–3. **Iterative development runs** (feature subset tweaks, HMM component-count sweeps, meta-model threshold tuning, anything you expect to re-run within hours) **stay local** — sequential per-model training with float32 features fits in 16 GB. The agent must distinguish the two; cloud is reserved for runs whose artifacts go into the registry. See the "Cloud compute policy" subsection in Part II for the standard runbook and the iteration-discipline rule.

> **Tracking note:** this subtask meets the auto-trigger in Part II's "Research environment setup (operator runbook)" — persistent MLflow tracking is required, not optional. Stand up the research env per the runbook before starting work, and record persistent-tracking confirmation (run-IDs/experiment-IDs) in `docs/PROGRESS.md` for this subtask. Falling back to the in-memory tracker is a missed acceptance criterion.

> **Real-data final run:** deferred to P2A.6; complete the deferral note in `docs/PROGRESS.md` against both P2.7 and P2A.6 when that run lands.

#### P2.8 — Robustness battery + two-engine reconciliation
- **Depends on:** the P2A gate (`gate-2a-real-data-path`) — real backfilled data, persistent MLflow, and the final P2.7 artifact must exist before P2.8 can validate anything.
- **Goal:** stress the edge.
- **Depends on:** P2.2, P2.7
- **Deliverable:** parameter sensitivity, Monte Carlo shuffle, noise injection, cross-symbol, synthetic-data backtest; reconciliation against a second engine (VectorBT vs Backtrader/Nautilus).
- **Done when:** each test runs and reports; two engines reconcile within tolerance on a sample strategy; tested.
- **Reference:** Layer 2 robustness.

> **Compute note:** the full CPCV path reconstruction + robustness battery is the heaviest single run in the research phase. Recommended execution: rent a spot `c7i.8xlarge` (32 vCPU) in `ap-south-1` for the one-shot run (≈3–6 hrs, ≈$3–5), fetch artifacts to S3, terminate the instance. Follow the standard runbook in Part II's "Cloud compute policy" subsection. Local execution is acceptable if RAM and time allow; treat 16 GB local RAM as the threshold above which P2.8 should move to cloud.

> **Tracking note:** this subtask meets the auto-trigger in Part II's "Research environment setup (operator runbook)" — persistent MLflow tracking is required, not optional. Stand up the research env per the runbook before starting work, and record persistent-tracking confirmation (run-IDs/experiment-IDs) in `docs/PROGRESS.md` for this subtask. Falling back to the in-memory tracker is a missed acceptance criterion.

#### P2.9 — Validation report + kill-gate emitter
- **Goal:** one report that decides trade/don't-trade.
- **Depends on:** P2.2, P2.8
- **Deliverable:** `research/reports/` — automated report (CPCV distribution, DSR, PBO, trial count, walk-forward equity, robustness) + QuantStats tearsheet + the **seven-point kill-gate** as pass/fail.
- **Done when:** report generates end-to-end and emits the kill-gate verdict; tested.
- **Reference:** Layer 2 kill-gate.

> **Tracking note:** this subtask meets the auto-trigger in Part II's "Research environment setup (operator runbook)" — persistent MLflow tracking is required, not optional. Stand up the research env per the runbook before starting work, and record persistent-tracking confirmation (run-IDs/experiment-IDs) in `docs/PROGRESS.md` for this subtask. Falling back to the in-memory tracker is a missed acceptance criterion.

**GATE 2 — THE KILL-GATE:** no strategy proceeds toward capital without passing all seven criteria on honest, cost-inclusive, point-in-time data. Most ideas die here. Tag `gate-2-research`.

---

## PHASE 2A — Operator Actions: Broker, Credentials, Real-Data Path

This subphase exists because the project has reached the transition from synthetic-data research to real-data research, and that transition requires actions the AI agent cannot perform on the operator's behalf — paid third-party signups, credentials that must live with the operator, regulatory steps the exchange/broker requires from the account holder. Without this subphase the "final P2.7 run" (deferred to P2.9) and everything from P2.8 onward is silently blocked.

**Operating principle:** every subtask in 2A pairs an operator action with explicit AI guidance. The AI produces a written walkthrough first (screen-by-screen, field-by-field), then sits with the operator while they execute it, verifies the result, and updates `docs/PROGRESS.md`. The agent never holds the operator's broker credentials, payment methods, or 2FA secrets — those flow only into the project's secrets interface (`core/secrets.py`) or AWS Secrets Manager (Phase 8).

**Gating:** P2A must complete before P2.8 begins. (P2.7's code work is already complete on synthetic data; the final registry-promotable P2.7 run is deferred to P2.9 and depends on P2A.)

#### P2A.1 — Kite Connect: subscription + developer app creation
- **Goal:** an active Kite Connect subscription with a registered developer app, yielding `api_key` and `api_secret` for this project.
- **Depends on:** the operator has an active Zerodha trading account.
- **Operator action (cannot be delegated):** sign in to the Zerodha account, subscribe to Kite Connect (₹500/month incl. historical data, verified 2026-06-23 — repriced down from ₹2000; paid by the operator), create a developer app, configure the redirect URL, and copy the `api_key` and `api_secret` exactly once at app-creation time.
- **AI guidance deliverable:** a step-by-step walkthrough document at `docs/operator_runbooks/P2A.1_kite_signup.md` written before the operator begins, covering: every screen and field on developers.kite.trade, what the redirect URL should be for a local-development setup, that both `api_key` and `api_secret` are recorded only via the secrets interface (neither is in any config file or in git), what to do if the `api_secret` is closed without copying (it's irrecoverable; the app must be regenerated), and a verification step that confirms the credentials work via a single read-only API call (e.g. fetch the instrument list).
- **Done when:** `api_key` is set via the secrets interface (`QUANT_SECRET_KITE_API_KEY` env var or secret store) and `api_secret` likewise (`QUANT_SECRET_KITE_API_SECRET`) — neither is committed to git; a verification script makes one read-only call successfully; and the act of obtaining credentials is recorded in `docs/PROGRESS.md` with the date (not the credentials themselves).
- **Reference:** Part III Layer 1 §0.2; Ground Rule 2 (no hard-coded secrets).

#### P2A.2 — Daily-auth flow: the manual TOTP seed
- **Goal:** a working daily login routine that produces a fresh `access_token` from the `api_key` / `api_secret` / `request_token` flow, persisted to the secrets interface, ready for the engine to read.
- **Depends on:** P2A.1.
- **Operator action (cannot be delegated):** perform the once-per-day manual login (Zerodha credentials + TOTP), per SEBI's manual-login mandate.
- **AI guidance deliverable:** a runbook at `docs/operator_runbooks/P2A.2_daily_auth.md` covering the OAuth dance, where to paste the `request_token`, how the SHA-256 checksum is computed (the AI generates the checksum), where the resulting `access_token` lands, and what to do when the token expires (next morning). The AI provides a small CLI helper script in `scripts/` that the operator runs in the morning and which writes the token to the secrets interface. Do not automate the TOTP itself — manual entry by the operator is the compliant path.
- **Done when:** running the helper script in the morning yields a valid `access_token`, the engine and research code can read it via the secrets interface, and the runbook is verified by the operator completing one successful daily login end-to-end.
- **Reference:** Part III Layer 5 §8.1 (morning auth/token routine); Project-specific Inviolable Rule 6.

#### P2A.3 — Real-data backfill: first historical pull
- **Goal:** the project's first real historical dataset in the storage layer — a defined liquid Nifty-50 / Nifty-100 universe, several years of 15-min bars (and finer intervals for feature computation per Part III Layer 1), backfilled through P1.4's job into P1.3's repository, with P1.5 hygiene applied.
- **Depends on:** P2A.1 (credentials), P2A.2 (token), P1.4–P1.7 (code already exists).
- **Operator action (cannot be delegated):** run the backfill (the data is pulled under the operator's Kite subscription and lands in the operator's local data store). Backfill runs locally — not AWS — at this stage; the dataset is a few GB of Parquet and the laptop is the right environment.
- **AI guidance deliverable:** a runbook at `docs/operator_runbooks/P2A.3_backfill.md` defining the exact universe (config-driven, in `config/universe.yaml`), the date range, the intervals, the expected size on disk, the expected wall-clock time, and what success looks like (row counts per symbol; gap reports under tolerance; survivorship coverage including delisted names if applicable). The AI provides the run command and reads back the resulting Parquet to verify counts. Resumable on interruption per P1.4's design.
- **Done when:** the data store contains the configured universe over the configured period, P1.5 hygiene checks pass on the pull, the data-quality dashboard (P1.9) reports green, and the dataset version is recorded in `docs/PROGRESS.md` alongside row/symbol counts.
- **Reference:** Part III Layer 1; subtasks P1.4–P1.7, P1.9.

#### P2A.4 — Research environment stand-up
- **Goal:** the `.venv-research` env exists and is healthy, with persistent MLflow ready to record runs that will feed P2.8/P2.9.
- **Depends on:** none (can run in parallel with P2A.1–P2A.3).
- **Operator action (cannot be delegated):** run the recipe from Part II's "Research environment setup (operator runbook)" — three commands on the operator's machine.
- **AI guidance deliverable:** the AI walks the operator through the recipe live, runs the verification line, starts the local MLflow server bound to 127.0.0.1, and confirms an end-to-end test run logs to it persistently.
- **Done when:** `mlflow --version` runs inside `.venv-research`, the MLflow UI is reachable at http://127.0.0.1:5000, and a one-line test run from a research script appears in the UI as a persistent record.
- **Reference:** Part II "Research environment setup (operator runbook)".

#### P2A.5 — AWS account preparation (one-time, low effort, no resources yet)
- **Goal:** an AWS account exists and is prepared for Phase 8 and the cloud-default research runs in P2.8 — but no compute resources are launched in this subtask. This is account hygiene only.
- **Depends on:** none. Can run any time before P2.8.
- **Operator action (cannot be delegated):** create the AWS account (or use an existing personal account), attach the operator's payment method, apply the $150 credits, enable MFA on the root account, create a dedicated IAM user for project access (programmatic + console), enable MFA on that IAM user, configure AWS Budgets per Part II's "Cost guardrails" subsection. Root credentials get locked away after the IAM user is created and never used again.
- **AI guidance deliverable:** a runbook at `docs/operator_runbooks/P2A.5_aws_setup.md` covering every console click, exactly which IAM policies the project user needs (least-privilege — read project S3, manage spot EC2 in ap-south-1, write CloudWatch logs; nothing else), the Budgets configuration (50/80/100% alerts on the credit balance), how to apply the credits, and the verification that the IAM user can authenticate via `aws sts get-caller-identity` and nothing more permissive can be done (least-privilege check). The AI writes a single `aws/` config file in the repo containing the non-secret parts (region, account ID, IAM user ARN); the credentials go to the secrets interface, never the repo.
- **Done when:** the IAM user can run `aws sts get-caller-identity` from the operator's machine via the secrets interface, the Budgets alerts are configured, the credits are applied and visible, root MFA is on, the IAM user has MFA, and `docs/PROGRESS.md` records that account preparation is complete (date and account-ID-tail only — never the credentials themselves).
- **Important:** no EC2 instance is launched in this subtask, no S3 bucket is created, no NAT Gateway is created — those are deliberately deferred to the actual subtask that needs them (P2.8 for the bucket + first spot run, Phase 8 for the engine VPS). This subtask only prepares the account so those moves are friction-free when they come.
- **Reference:** Part II "Cloud compute policy (AWS)".

#### P2A.6 — Final P2.7 registry-promotable run on real data (operator-triggered)
- **Goal:** retroactively complete the deferred final P2.7 run now that real data exists — produce the ensemble + regime-gate model artifact in `FileModelRegistry`, logged to persistent MLflow, ready to be judged by P2.8/P2.9.
- **Depends on:** P2A.1, P2A.2, P2A.3, P2A.4. (Not P2A.5 — final P2.7 runs locally; cloud is for P2.8.)
- **Operator action:** initiate the run; the AI executes the training using the code already merged from P2.7's PR, against the real backfilled data, against the persistent MLflow server, and writes the model card + artifact into the registry.
- **AI guidance deliverable:** a single command, narrated; verification that the MLflow run is FINISHED, the registry artifact deserializes and predicts identically to the in-memory model, and the run-IDs are captured.
- **Done when:** an MLflow run-ID exists, a `FileModelRegistry` artifact exists, both are recorded in `docs/PROGRESS.md` under P2A.6 and P2.7 (closing the deferral note), and the artifact is the input P2.8 will validate.
- **Reference:** Part III Layer 2 §4.1; the P2.7 deferral note.

**P2A gate:** the real-data path is live. Kite credentials work, daily auth works, real data is in the store, the research env is up, the AWS account is ready (no spend yet), and the final P2.7 artifact exists and is registry-promotable. Tag `gate-2a-real-data-path`. P2.8 (Robustness battery + two-engine reconciliation) can now begin against real data and a real model.

---

## PHASE 2R — Research Iteration Loop

This subphase exists because most candidate strategies will fail the kill-gate (Inviolable Rule 7), and the path forward from a failing P2.9 verdict is iteration on inputs, not progression to Phase 3. Phase 2R is a loop, not a sequential phase: a candidate enters at P2R.1, exits either back to P2.9 (with new inputs, re-validated) or out of the project (a deliberate stop). Phase 3 is unreachable until P2.9 emits a passing verdict.

**Operating principle:** iteration is hypothesis-driven, not tweak-driven. Each cycle changes one input family with a stated reason grounded in the deep dives, the candidate is re-validated under the same honest harness, and the result is logged. Deflated Sharpe Ratio in P2.9 punishes blind search — every trial counts toward the trial budget, even the ones discarded silently. So iteration discipline is correctness, not aesthetics.

**Gating:** Phase 3 (Capital Layer) is reachable only when P2.9 emits a passing verdict (all seven kill-gate criteria green) on a candidate that has been through Phase 2R at least once or passed P2.9 on first attempt. The "passed on first attempt" outcome is statistically unlikely and should be inspected for leakage before being trusted.

#### P2R.1 — Diagnostic: where is the binding constraint?
- **Goal:** a written, evidence-grounded assessment of why the current candidate failed P2.9, ranking the most likely binding constraints from a fixed list.
- **Depends on:** P2.9 emitting a kill verdict on the current candidate.
- **Deliverable:** `docs/iteration_log/<cycle-N>_diagnostic.md` containing a ranked assessment of: (a) feature signal strength (especially missing OFI / microstructure from Layer 1 §2.2), (b) triple-barrier upper/lower/vertical calibration vs realized intraday volatility, (c) universe size and survivorship coverage, (d) decision frequency, (e) sample weighting / labeling discipline, (f) model capacity, (g) something else. Each candidate cites the deep-dive sections that inform it and the diagnostic evidence (AUC, Brier, path-Sharpe, feature importances, fold-by-fold metrics) that points to it being binding.
- **Done when:** the diagnostic exists, the top one or two candidates are explicitly recommended for the next iteration cycle, and the diagnostic is reviewed by the operator before any code changes are made.
- **Reference:** Inviolable Rule 7; Layer 1 §2.2; Layer 2 throughout.

#### P2R.2 — Hypothesis-driven iteration: change one input family
- **Goal:** modify one input family — features, labels, universe, frequency, or sample weighting — per the diagnostic's recommendation, and re-validate.
- **Depends on:** P2R.1.
- **Operator action required:** approve the chosen input change before code is written (this prevents tweak-spiral).
- **Deliverable:** the focused change to the relevant Layer-1 or Layer-2 module under a `feat/iteration-<cycle-N>-<input-family>` branch, accompanied by an updated entry in `docs/iteration_log/<cycle-N>_changelog.md` describing the change, the hypothesis, and the expected effect.
- **Done when:** the change is merged behind the same engineering ground rules as any other subtask (CI green, tests cover the new code path, etc.), and the iteration log entry is complete.
- **Important guardrails:**
  - One input family per cycle. Changing features and labels and universe at once destroys causality — you can't tell what helped.
  - Local execution per the cloud-compute policy. Iterative re-runs stay on the operator's machine; cloud is for the final-run-after-smoke-passes only.
  - Every variant tried is logged to MLflow (the persistent research env), so the Deflated Sharpe trial count remains honest for the eventual passing-verdict run. Including variants that were quickly discarded. The penalty for cheating on trial count is invisible until P2.9 reports a deflated number that doesn't match expectations.
- **Reference:** Cloud-compute policy "Iteration discipline" subsection; Layer 2 §4b.

#### P2R.3 — Re-run P2.9 against the iterated candidate
- **Goal:** the same kill-gate report emitted against the iterated candidate.
- **Depends on:** P2R.2.
- **Deliverable:** a re-run of P2.9's report; outcome appended to `docs/iteration_log/<cycle-N>_verdict.md`.
- **Done when:** the report exists and the verdict is one of: PASS (route to Phase 3), CONTINUE (route back to P2R.1 with the next cycle number), or STOP (operator decision: enough cycles without sufficient progress; the project either pivots or ends — see P2R.4).

#### P2R.4 — Iteration budget and stop discipline (operator-only)
- **Goal:** prevent the iteration loop from becoming infinite or degenerating into overfitting.
- **Deliverable:** a written iteration budget in `docs/iteration_log/budget.md`, set by the operator before P2R.1 of cycle 1, stating: (a) maximum number of cycles before a hard reassessment, (b) maximum cumulative MLflow trial count before Deflated Sharpe becomes punitive enough that no realistic raw Sharpe can clear it, and (c) the operator's pre-committed pivot/stop criteria (e.g., "if after N cycles smoke path-Sharpe has not exceeded 0.3, the project pivots to a different decision frequency or stops entirely").
- **Done when:** the budget is committed to git before iteration begins, and is consulted at the end of each cycle.
- **Important:** this is an operator decision, not an agent decision. The agent surfaces the trial count and cycle count; the operator decides whether to continue. Stopping a project that is honestly not converging is the disciplined choice (Layer 5 §8.9, kill criteria) and is genuinely a successful outcome — you have built a reusable research apparatus and avoided losing money.

Phase 2R is a loop, not a phase with a single gate. The exit condition is a passing P2.9 verdict (route to Phase 3) or an operator-decided stop/pivot (P2R.4). The blueprint does not auto-advance past a failing P2.9. Tag each cycle's exit as `iteration-cycle-N-{pass|continue|stop}`.

---

## PHASE 3 — Capital Layer

**Phase 3 prerequisite (re-checked at every session start in this phase):** the most recent P2.9 verdict in `docs/iteration_log/` must be PASS. If the most recent verdict is CONTINUE or no PASS verdict exists, the agent must route to Phase 2R, not proceed with Phase 3 work. This is enforced as a session-start check, per Ground Rule 9.

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

> **Tracking note:** this subtask meets the auto-trigger in Part II's "Research environment setup (operator runbook)" — persistent MLflow tracking is required, not optional. Stand up the research env per the runbook before starting work, and record persistent-tracking confirmation (run-IDs/experiment-IDs) in `docs/PROGRESS.md` for this subtask. Falling back to the in-memory tracker is a missed acceptance criterion.

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

## PHASE 5A — Operator Actions: Live Infrastructure & Monitoring

**Subphase principle:** Phase 5 built the operations code (scheduler, monitoring, drift detection, MLOps, platform plumbing). Phase 5A configures and authorizes the operator-only infrastructure that operations code expects to find — the things only the operator can stand up, pay for, or authenticate.

#### P5A.1 — AWS engine VPS provisioning (Phase 8 prep, no live trading yet)
- **Goal:** the Phase-8 Linux engine VPS exists in ap-south-1, with an Elastic IP attached, configured per Part II's Phase-8 runbook — but not yet registered with Kite as the static IP, and not yet running the engine. This is infrastructure standup only.
- **Depends on:** P2A.5 (AWS account ready).
- **Operator action (cannot be delegated):** launch the EC2 instance (smallest viable size per the runbook), attach an Elastic IP, configure the security group (inbound only from VPN/operator IP), enable IMDSv2, attach the least-privilege IAM instance profile, enable EBS encryption, set up daily AWS Backup, install the CloudWatch agent.
- **AI guidance deliverable:** a walkthrough at `docs/operator_runbooks/P5A.1_engine_vps.md` with screen-by-screen instructions, the exact `aws` CLI commands (which the operator runs), verification that SSM Session Manager works (no SSH key needed), CloudTrail confirmation, and a smoke test that a Docker container can run on the host.
- **Done when:** SSM Session Manager opens a shell, `docker run hello-world` succeeds, the Elastic IP is recorded in `docs/PROGRESS.md` (IP value redacted in git; the IP value lives in the secrets interface), and the instance's monthly burn matches expectations.
- **Reference:** Part II "Standard runbook — Phase-8 live engine VPS"; Part III Layer 5 §8.8.

#### P5A.2 — VPN / private network for the control surface
- **Goal:** the control API (Layer 6) is reachable only from operator devices over a private network. Per Layer 6 security model.
- **Depends on:** P5A.1.
- **Operator action (cannot be delegated):** stand up the VPN solution (WireGuard self-hosted on the VPS, or Tailscale free tier — the AI walkthrough recommends one with the trade-offs); enroll the operator's laptop + phone as VPN clients; lock the control-API security-group inbound to the VPN's address range only.
- **AI guidance deliverable:** `docs/operator_runbooks/P5A.2_vpn.md` covering choice of VPN (with reasons), every config step, MTU/firewall gotchas, how to revoke a client (the device-loss scenario), and verification that the control-API port is unreachable from the public internet (`nmap` from an external host).
- **Done when:** the operator's laptop reaches the control-API over the VPN, an external scan confirms the port is closed publicly, and the device-revocation procedure is tested once.
- **Reference:** Part III Layer 6 security model.

#### P5A.3 — Alerting channels (Telegram/email + PagerDuty optional)
- **Goal:** CRITICAL alerts from the platform layer (Part III Layer 5 §8.6) reach the operator within seconds, on a channel that will be seen.
- **Depends on:** P5A.1.
- **Operator action (cannot be delegated):** create the Telegram bot (the operator owns it), get the bot token, identify the chat ID, register both with the secrets interface; optionally set up a PagerDuty trial for harder-to-ignore criticals; configure email-on-CRITICAL fallback.
- **AI guidance deliverable:** `docs/operator_runbooks/P5A.3_alerting.md` with BotFather steps, how to capture the chat ID, where the bot token lives (never in git), how the alerting code reads the credentials, and an end-to-end test that fires a fake CRITICAL on each channel and confirms receipt on the operator's phone.
- **Done when:** a manually-triggered CRITICAL fires and arrives on the operator's phone within seconds on at least Telegram + email; the tested-fire is recorded in `docs/PROGRESS.md`.
- **Reference:** Part III Layer 5 §8.6.

#### P5A.4 — Backup verification (the restore that proves the backup)
- **Goal:** the daily AWS Backup snapshots configured in P5A.1 are provably restorable. An untested backup is not a backup (Part III Layer 5 §8.8).
- **Depends on:** P5A.1, at least 7 days of automated snapshots.
- **Operator action (cannot be delegated):** trigger a restore drill — restore a snapshot to a fresh test instance, verify the data and config come back intact, then terminate the test instance.
- **AI guidance deliverable:** `docs/operator_runbooks/P5A.4_restore_drill.md` covering the exact AWS Backup restore steps, what to verify on the restored instance, expected duration, expected cost (~$0 for a brief test instance on the existing volume class), and the schedule for repeating the drill (quarterly).
- **Done when:** a snapshot restored to a fresh instance opens via SSM with intact data and config; the test instance is terminated; the drill is recorded in `docs/PROGRESS.md` with a calendar reminder for the next quarterly drill.
- **Reference:** Part III Layer 5 §8.8.

**P5A gate:** the operator-owned live infrastructure exists, is reachable only over VPN, alerts reach the operator, and backups are provably restorable. Tag `gate-5a-live-infra`. Phase 6 (paper trading) can now run against real infrastructure.

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

## PHASE 7A — Operator Actions: Mobile App Build & Signing

**Subphase principle:** Phase 7 produced the control-API source, the PWA dashboard source, and the APK build configuration. Phase 7A is the operator-only signing, installation, and authentication setup — none of which the AI can or should do.

#### P7A.1 — APK signing keystore generation
- **Goal:** a signing keystore exists, held only by the operator, used to sign all APK builds for this project. Anyone who holds this key can publish updates as the operator — irreplaceable if lost, catastrophic if leaked.
- **Depends on:** P7.6 (build config exists).
- **Operator action (cannot be delegated):** generate the keystore (`keytool`), set a strong passphrase, back up the keystore to two offline locations (e.g., encrypted USB stick + encrypted cloud archive), record the SHA-256 fingerprint, configure the build to sign with it.
- **AI guidance deliverable:** `docs/operator_runbooks/P7A.1_keystore.md` with the exact `keytool` command, passphrase requirements, the two-backup discipline (and why), how to record the fingerprint without recording the key, what to do if the key is lost (you cannot recover — you would publish a new app under a new identity), and the build configuration line that references the local keystore path.
- **Done when:** the keystore exists locally, two offline backups are confirmed, the fingerprint is recorded in `docs/PROGRESS.md`, and a test APK builds and signs successfully. The keystore itself is never committed to git (verify `.gitignore` covers `*.keystore` and `*.jks`).
- **Reference:** Part III Layer 6 stack section.

#### P7A.2 — Signed APK build and sideload
- **Goal:** a signed APK is installed on the operator's phone, opening as a real installed app (not a browser tab), authenticating cleanly to the control API over the VPN.
- **Depends on:** P7A.1, P5A.2 (VPN), P7.5 (PWA dashboard live), P7.7 (security validation complete).
- **Operator action (cannot be delegated):** run the local build to produce a signed APK; sideload it to the operator's phone (developer mode + USB transfer, or a private Play Console internal track); install; enroll the device with biometric lock; complete the device-registration flow with the control API to receive a short-lived, revocable device token.
- **AI guidance deliverable:** `docs/operator_runbooks/P7A.2_apk_install.md` covering the build command, sideload paths (Windows + Android), enabling developer mode without compromising the phone's security posture, the device-registration handshake with the API, the biometric setup, the stolen-phone revocation test (revoke the device token from the VPS and confirm the app loses access within the session).
- **Done when:** the installed app authenticates to the control API over VPN, biometric lock is on, a deliberate stolen-phone revocation test passes (operator revokes from VPS → app reaches the API → access denied), and the install + tested-revocation is recorded in `docs/PROGRESS.md`.
- **Reference:** Part III Layer 6 security checklist.

**P7A gate:** the operator holds the signing key, the signed APK is installed on the operator's phone with verified revocation, and the full Layer-6 security checklist has been walked end-to-end. Tag `gate-7a-app-installed`. Phase 8 micro-live can now begin with the panic-flatten path tested and reachable from the operator's pocket.

---

## PHASE 8A — Operator Actions: Going Live (the no-going-back subphase)

**Subphase principle:** every action here moves the system one step closer to real money in motion. Each subtask is small, gated, and reversible (until the final one). The operator initiates each; the AI verifies. The operator may pause at any subtask boundary and remain there indefinitely — there is no obligation to proceed once a subtask is complete.

#### P8A.1 — Static-IP registration with the broker
- **Goal:** the engine's Elastic IP is registered with Zerodha Kite Connect as the static IP for order placement, satisfying SEBI's static-IP-whitelist mandate. After this step, the EIP must never change (losing it means re-registering, lost trading days).
- **Depends on:** P5A.1 (EIP exists), P2A.1 (Kite Connect account).
- **Operator action (cannot be delegated):** log in to the Kite developer console, paste the engine's EIP into the static-IP whitelist, save, verify acceptance.
- **AI guidance deliverable:** `docs/operator_runbooks/P8A.1_static_ip.md` with screen captures of the developer console section, the verification step (a real order-endpoint call from the EIP returns success rather than rejected-IP), explicit "do not change the EIP after this point" warning, and the documented procedure for re-registering if the EIP ever does change (and the lost trading time it implies).
- **Done when:** a verification order-endpoint call from the EIP is accepted, and the registered IP value is recorded in the secrets interface plus a redacted note in `docs/PROGRESS.md`.
- **Reference:** Part II Phase-8 runbook; Project-specific Inviolable Rule 6.

#### P8A.2 — Funding the live account (operator decision + transfer)
- **Goal:** the live Zerodha account holds the agreed micro-live capital (~₹40k per the project plan's micro-live decision) — money the operator is willing to lose for the validation purpose Phase 8 exists for.
- **Depends on:** the operator's own readiness; the kill-gate (Gate 2/Gate 2A.6) passed.
- **Operator action (cannot be delegated):** transfer funds into the Zerodha account from the operator's bank.
- **AI guidance deliverable:** `docs/operator_runbooks/P8A.2_funding.md` is a single short page reiterating: this is validation capital, not income capital; >90% of retail F&O traders lose money; the only purpose at this stage is "does live behave like paper" not "make money"; the kill-criteria for stopping live entirely (Part III Layer 5 §8.9) are pre-committed before funds are transferred.
- **Done when:** funds visible in the Zerodha account; the date and amount recorded in `docs/PROGRESS.md` (private notes; not committed publicly if the repo is ever shared).
- **Reference:** Part II's honesty frame; Part III Layer 5 §8.9 (kill criteria).

#### P8A.3 — First live session: micro-live trading begins (operator-gated, daily for first week)
- **Goal:** the engine begins trading the live account at micro-size, with the operator present and ready to invoke the panic-flatten path from their phone if anything looks wrong. The first week is manually re-authorized each morning — the operator decides each day whether to trade.
- **Depends on:** P8A.1, P8A.2, every previous gate passed.
- **Operator action (cannot be delegated):** each morning of week 1 — complete the daily TOTP login (P2A.2 routine), review the pre-open gate output, explicitly authorize the engine to begin trading for that day (a manual confirmation, not an automatic resume), and monitor through the session.
- **AI guidance deliverable:** `docs/operator_runbooks/P8A.3_first_week.md` covers the morning routine, what "looks normal" looks like during the day, when to invoke the panic-flatten path (immediate, no second-guessing — Layer 6's superpower is the off switch), the end-of-day reconcile review, and the criteria for proceeding to P8.B1 (after-week-one automated micro-live).
- **Done when:** five consecutive trading days complete with operator authorization each morning, no unhandled incidents, end-of-day reconcile clean each day, and the operator personally signs off on transitioning to the automated micro-live regime (P8.B1) — or pauses indefinitely.
- **Reference:** Part III Layer 5 lifecycle; Part III Layer 6 security; the project plan's Phase 4 / blueprint Phase 8 honesty.

**P8A gate:** static IP registered, account funded, the first authorized live trading week completed without incident, the operator signs off. Tag `gate-8a-first-week-live`. P8.B1 (the existing "Go live, trivially small" subtask, now post-renumber) can proceed.

---

## PHASE 8 — Live, Micro Size *(operator-driven; Claude assists, never acts alone)*

Phase 8 begins with the operator subphase P8A above; the engineering subtasks below assume `gate-8a-first-week-live` has passed.

#### P8.B1 — Go live, trivially small
- **Goal:** validate live ≈ paper, not to make money.
- **Depends on:** GATE 6, GATE 7
- **Deliverable:** live deployment with trivial capital; full monitoring/drift/limits/alerts/panic-flatten active. **Operator confirms and executes; Claude does not place real orders.**
- **Done when:** live behaves like paper; all safety systems verified live; daily reports clean.
- **Reference:** Project plan Phase 4.

#### P8.B2 — Sustained live validation
- **Goal:** earn the right to scale.
- **Depends on:** P8.B1
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
| 2026-06-17 | P0.4 | ☑ done | `feat/p0.4-nse-calendar` (merged) | 87 passing | IST trading-calendar/session utility (trading days, holidays, session phases); 100% cov. |
| 2026-06-17 | P0.5 | ☑ done | `feat/p0.5-types-interfaces` | 98 passing | Frozen domain types + 6 runtime-checkable Protocols; fakes type-check; 100% cov. |
| 2026-06-17 | **GATE 0** | ☑ **passed** (tag `gate-0-foundation`) | | 99% cov | Foundation complete; CI green. Next: P1.1. |
| 2026-06-19 | P1.1 | ☑ done | `feat/p1.1-broker-adapter` | 158 passing | `KiteAdapter` (historical market data + daily session) behind `BrokerAdapter`; `kiteconnect` SDK confined to `data/brokers/`; 100% cov. Details in `docs/PROGRESS.md`. |
| 2026-06-19 | P1.2 | ☑ done | `feat/p1.2-live-stream` | 185 passing | `TickStreamConsumer` (full-mode ticks + 5-depth, resubscribe-on-reconnect, staleness heartbeat) behind a `TickerTransport` Protocol; Kite WebSocket confined to `data/brokers/`; 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.3 | ☑ done | `feat/p1.3-storage-layer` | 267 passing | Storage tiers behind `Repository`: `ParquetArchive` (immutable raw, symbol/date partitions), `ArcticRepository` (versioned, time-travel), `RedisLiveStore` (bounded hot window). Optional `arcticdb`/`redis` confined to `data/store/` + lazy (arcticdb pins pandas<3 → operator-installed); 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.4 | ☑ done | `feat/p1.4-historical-backfill` | 307 passing | `BackfillJob` (paginated, resumable) + `scripts/run_backfill.py`, writing through `Repository`. Accumulate-then-write-once per symbol (the only tier-agnostic, idempotent write — Arctic `write_bars` snapshots, not appends); per-symbol resume via `JsonBackfillCheckpoint`; one Arctic version per symbol. 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.5 | ☑ done | `feat/p1.5-data-hygiene` | 357 passing | `data/hygiene/`: corp-action back-adjustment (split/bonus/dividend; raw kept), point-in-time `ConstituentRegistry` (delisted included), bad-tick filter (point-in-time, every correction logged), calendar-aware gap detection, liquidity screen + ESM/T2T exclusion. Each pure/idempotent + tested; 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.6 | ☑ done | `feat/p1.6-feature-core` | 384 passing | `data/features/`: pure causal core features (multi-horizon log returns, realized-vol/ATR/Parkinson, intraday VWAP-deviation) + dual-path harness (`compute_feature_frame` vectorized / `compute_features_asof` incremental). Skew test asserts incremental == vectorized bar-by-bar; prefix-invariance proves no lookahead. 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.7 | ☑ done | `feat/p1.7-features-extended` | 429 passing | `data/features/`: microstructure (OFI 5-depth, spread, depth imbalance, signed flow), TA-Lib technicals (RSI/MACD/Bollinger %B), cyclical time-of-day, cross-sectional sector-neutral ranks/z-scores, regime (vol/trend) + trailing winsorize/robust-scale (§2.3). All causal/point-in-time; `ta-lib` added (prebuilt manylinux wheels). 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.8 | ☑ done | `feat/p1.8-leakage-suite` | 467 passing | `tests/adversarial/`: reusable structural anti-leakage checks (forward-shift invariance, train/serve skew, trailing-only normalization, no-future-correlation) run across every feature family + tripwires proving the suite fails on intentionally-leaky features. Runs in CI (`adversarial` marker). Details in `docs/PROGRESS.md`. |
| 2026-06-20 | P1.9 | ☑ done | `feat/p1.9-data-quality` | 481 passing | `data/quality/`: `DataQualityDashboard` composes coverage (session-level vs NSE calendar) + gaps + bad-tick counts + feed-latency into a rendered `DataQualityReport`; surfaces issues per symbol. 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-20 | **GATE 1** | ☑ **passed** (tag `gate-1-data`) | | whole-suite green | Point-in-time, corp-action-adjusted, survivorship-correct, leakage-tested dataset + feature set reproducible on demand. Phase 1 complete; next is Phase 2 (Research). |
| 2026-06-21 | P2.1 | ☑ done | `feat/p2.1-validation-harness` | 553 passing (72 new) | `research/validation/`: `PurgedKFold` (purge + embargo, strict no-overlap), `IndianCostModel` (itemised per-order costs), `DepthAwareSlippage` (size/depth participation curve), `Backtester` (event-driven, next-bar-open, intraday square-off, costs+slippage+latency). The judge before the contestants; 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-21 | P2.2 | ☑ done | `feat/p2.2-cpcv-dsr-pbo` | 614 passing (61 new) | `research/validation/`: `CombinatorialPurgedCV` (φ=C(N,k)·k/N path reconstruction + path-Sharpe distribution), Deflated/Probabilistic Sharpe (stdlib `NormalDist`, no SciPy), PBO via CSCV, `TrialTracker`. Shared `purged_train_mask` primitive. The "is the edge real?" toolkit; 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-21 | P2.3 | ☑ done | `feat/p2.3-labeling` | 652 passing (38 new) | `research/labeling/`: symmetric `cusum_events` sampler + `TripleBarrierLabeler` (vol-scaled barriers floored at the cost hurdle, high/low first-touch with conservative same-bar stop, vertical = IST session end). `LabelSet.label_times` (t0→t1) feeds the purged CV/CPCV splitters; `.sides` is the primary label. 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-21 | P2.4 | ☑ done | `feat/p2.4-sample-weighting` | 688 passing (36 new) | `research/labeling/`: `SampleWeights` (indicator matrix → concurrency, average-uniqueness, return-attribution) + `time_decay_weights`; uniqueness-aware `sequential_bootstrap` (seeded RNG, beats uniform on avg uniqueness). Corrects non-IID overlapping labels (AFML ch. 4). 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-21 | P2.5 | ☑ done | `feat/p2.5-meta-fracdiff` | 728 passing (40 new) | `research/labeling/`: momentum/mean-reversion primary + `MetaLabeler` (side-aware bet/no-bet via shared `barriers.first_touch`); `research/features_research/`: `frac_diff` (binomial FFD, causal) + `adf_test` + `min_ffd` (min-d stationary, retains memory). Added `statsmodels` (resolves with pandas 3.x). 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-21 | P2.6 | ☑ done | `feat/p2.6-model-baseline` | 786 passing (58 new) | `research/models/`: LightGBM baseline (native API) evaluated **only under purged CV** (pooled OOS preds), permutation/MDA importance (not MDI), **isotonic calibration** (hand-rolled PAVA), purged-CV hyperparameter tuning, and experiment tracking (`ExperimentTracker` → in-memory default + lazy, confined **MLflow** adapter — operator-installed like arcticdb, since mlflow pins pandas<3). `LightGBMBaseline` implements the live `Model`. Added `lightgbm`; mlflow not a declared dep. 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-22 | P2.7 | ☑ done | `feat/p2.7-ensemble-regime-registry` | 884 passing (98 new) | `research/models/`: cross-family **ensemble** (LightGBM+XGBoost+hand-rolled-logistic behind one `Estimator` contract; **rank-average / stacking**, OOF-fit combiner+calibrator, live `Model`), **GMM regime gate** (diagonal-cov EM, deterministic; per-regime on/off/size-down; data-driven selection = kill-gate crit. 7), **model registry** (`ModelCard` w/ data/feature/label/model version tags + fingerprint; in-memory + `FileModelRegistry`), and `evaluate_ensemble_under_cpcv` (path-Sharpe distribution; gated recovers an edge that cancels ungated). Added `xgboost` (no pandas pin; confinement guard extended). ⚠️ persistent-MLflow **final run is operator action** (see PROGRESS). 100% cov on new modules. Details in `docs/PROGRESS.md`. |
| 2026-06-23 | P2A.1 | ☑ done | `feat/p2a.1-kite-credentials` | 5 new (verify) | Kite Connect app created & subscribed (₹500/mo incl. historical data); `api_key`/`api_secret` recorded only via the secrets interface (`QUANT_SECRET_KITE_*`), never git; read-only `verify_kite_credentials` passed (9,853 NSE instruments). Walkthrough `docs/operator_runbooks/P2A.1_kite_signup.md`. |
| 2026-06-23 | P2A.2 | ☑ done | `feat/p2a.2-daily-auth` | 19 new (secrets+auth) | Daily manual-TOTP login → fresh `access_token` persisted to the secrets interface via a **file-backed store** (`~/.quant-intraday/secrets.json`, env-then-file precedence; repository-pattern parity with future AWS Secrets Manager); morning CLI helper `scripts/kite_morning_auth.py`. Live seed verified end-to-end (`POST /session/token → 200`, proving the `api_secret`; 32-char read-back). Runbook `docs/operator_runbooks/P2A.2_daily_auth.md`. |
| 2026-06-24 | P2A.3 | ☑ done | `feat/p2a.3-backfill` | 7 new (token+verifier) | First real backfill: 8 seed large-caps, ~5y minute bars (2021-06-24 → 2026-06-23; ~462k bars/symbol, ~3.70M rows, 1,239 sessions) via P1.4 → Parquet; backfill reads the daily token from the secrets interface; `check_backfill` (P1.5 gaps + P1.9 dashboard) green — every symbol has data, 2 bad ticks removed. The 67 "missing days" = NSE holidays absent from the P0.4 calendar (tracked follow-up). Runbook `docs/operator_runbooks/P2A.3_backfill.md`. |
| 2026-06-24 | P2A.4 | ☑ done | `feat/p2a.4-research-env` | (docs/config) | `.venv-research` stood up (pandas 2.3.3 + mlflow 3.14.0 + arcticdb 6.18.3); persistent MLflow on 127.0.0.1:5000 verified (smoke run persisted to sqlite `mlruns/mlflow.db`). Findings folded into the runbook + Part II: MLflow 3.x needs a sqlite backend (file store deprecated) and Windows needs `PYTHONUTF8=1`. `.venv-research/` gitignored + ruff-excluded. Runbook `docs/operator_runbooks/P2A.4_research_env.md`. |
| 2026-06-24 | P2A.5 | ☑ done | `feat/p2a.5-aws-prep` | (docs/config) | AWS account hygiene (existing account …9719): root+user MFA, IAM user `quant-intraday-ops` + least-privilege `ap-south-1`-only policy (verified: out-of-region denied, Mumbai empty), Budgets 50/80/100%, $150 credits; **no resources launched**. `aws/config.yaml` (non-secret IDs); key in `~/.aws/`. Runbook `docs/operator_runbooks/P2A.5_aws_setup.md`. |
| 2026-06-24 | P2A.6 | ☑ done | `feat/p2a.6-final-run` | 36 new (947 total) | Final registry-promotable P2.7 run on real data (local). New `research/pipeline/` orchestration pools the 8-symbol universe onto one gapped synthetic timeline (operator-approved Option 1), trains the ensemble + GMM regime gate → **MLflow run `e24c0cd6…` (FINISHED)** + **`FileModelRegistry` artifact `ensemble-regime-v1-0001`** (14,150 events; round-trip exact). Closes the P2.7 deferral. Edge weak (OOS AUC ≈0.52) — P2.8/P2.9 judge it. Runbook `docs/operator_runbooks/P2A.6_final_run.md`. |
| | … | | | | |
| | P5A.1 | ☐ todo | | | AWS engine VPS standup in ap-south-1 (EIP, IMDSv2, least-priv IAM profile, EBS encryption, daily AWS Backup, CloudWatch agent) — not Kite-registered, engine not running. Runbook `docs/operator_runbooks/P5A.1_engine_vps.md`. |
| | P5A.2 | ☐ todo | | | VPN / private network (WireGuard or Tailscale) for the control API; SG locked to the VPN range; public-port-closed verified; device revocation tested. Runbook `docs/operator_runbooks/P5A.2_vpn.md`. |
| | P5A.3 | ☐ todo | | | Alerting channels — operator-owned Telegram bot + email (PagerDuty optional); credentials to the secrets interface; CRITICAL test-fire to phone. Runbook `docs/operator_runbooks/P5A.3_alerting.md`. |
| | P5A.4 | ☐ todo | | | Backup restore drill — restore a snapshot to a fresh instance, verify, terminate; quarterly cadence. Runbook `docs/operator_runbooks/P5A.4_restore_drill.md`. |
| | P7A.1 | ☐ todo | | | APK signing keystore generation — operator-held, two offline backups, SHA-256 fingerprint recorded; `*.keystore`/`*.jks` gitignored. Runbook `docs/operator_runbooks/P7A.1_keystore.md`. |
| | P7A.2 | ☐ todo | | | Signed APK build + sideload to operator phone; device registration over VPN + biometric lock; stolen-phone revocation test. Runbook `docs/operator_runbooks/P7A.2_apk_install.md`. |
| | P8A.1 | ☐ todo | | | Static-IP (EIP) registration with Kite (SEBI mandate); EIP must never change after. Runbook `docs/operator_runbooks/P8A.1_static_ip.md`. |
| | P8A.2 | ☐ todo | | | Fund the live account (~₹40k validation capital); kill-criteria pre-committed. Runbook `docs/operator_runbooks/P8A.2_funding.md`. |
| | P8A.3 | ☐ todo | | | First live week — daily operator-authorized micro-live, panic-flatten ready; 5 clean days → sign off (or pause). Runbook `docs/operator_runbooks/P8A.3_first_week.md`. |

**Gate status:** Gate 0 ☑ · Gate 1 ☑ · Gate 2 ☐ (**kill-gate KILL**; never passed) · Gate 2A ☐ · Gate 2R (loop — **STOPPED at cycle 4**: no edge survives costs; research phase complete) ⊘ · Gate 3 ☐ · Gate 4 ☐ · Gate 5 ☐ · Gate 5A ☐ · Gate 6 ☐ · Gate 7 ☐ · Gate 7A ☐ · Gate 8A ☐ · Gate 8 ☐

> **RESEARCH PHASE STOPPED (Phase 2R, cycle 4; tag `research-phase-stop-cycle-4`).** No strategy
> cleared the seven-point kill-gate on honest, cost-inclusive data; the iteration budget's stop
> criterion engaged and was honored. Phases 3–8 are deferred **indefinitely** (not deleted). **No
> live trading.** See `docs/iteration_log/closeout.md` for the full conclusion and the inventory of
> what the apparatus can be re-pointed at if a future research program is defined.

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
