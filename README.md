# Quant Intraday — Indian Cash-Equity Intraday Trading System

An automated system that trades **liquid Indian cash equities intraday (MIS)** on a
**15-minute decision clock**, using gradient-boosted models on point-in-time features,
validated rigorously against overfitting, sized conservatively under hard, un-overridable
risk limits, executed via the Zerodha Kite Connect API, monitored for drift, and
controllable from a secure mobile master-control app.

> **Status: PROJECT CLOSED — no live trading, $0 of capital risked.** The data + feature + model +
> validation apparatus is built, gated, and sound (Gate 0 ✅, Gate 1 ✅). **Three research arcs were
> each tested to an honest end and none cleared the seven-point kill-gate net of realistic costs:**
>
> | Arc | Thesis | Verdict | Strongest honest result |
> |---|---|---|---|
> | **I. MIS-directional** (Parts I–V) | ML-predicted intraday direction from bar features | **KILL** | +0.148 ann CPCV path-Sharpe — real but too small |
> | **II. Mechanical-edge** (Part VI) | non-directional flow / stat-arb / event mechanics | **GATE 7 honest stop** | cointegration pairs **+0.425** net Sharpe — strongest edge found, still < +1.0 bar & insignificant; index-rebalance + PEAD data-gated |
> | **III. Cross-sectional factors** (Phase 3X) | monthly multi-factor, benchmark-relative IR | **KILL** | composite IC +0.051; active IR −0.82; K-Means cluster A/B **marginal +0.09**, still KILL |
>
> Across directional prediction, three non-directional mechanics, **and** cross-sectional factors,
> **no strategy is tradeable at retail scale** — the strongest edge anywhere (pairs, +0.42 Sharpe)
> is real but economically negligible and statistically marginal. Every arc closed on a
> pre-committed budget; the kill-gate held; nothing fooled itself. A successful
> intellectual-honesty outcome, not a failure.
>
> **→ Read [`docs/FINDINGS.md`](docs/FINDINGS.md)** — the authoritative close-out for all three arcs
> (with MLflow run-IDs and exact numbers). Part-VI detail: [`docs/mechanisms/gate7_closeout.md`](docs/mechanisms/gate7_closeout.md).
> Factor A/B: [`docs/iteration_log/p3x_cycle2_cluster_combiner.md`](docs/iteration_log/p3x_cycle2_cluster_combiner.md).
> Full build log: [`docs/PROGRESS.md`](docs/PROGRESS.md).
>
> **Post-close-out pivots — both also NO-GO.** The program briefly reopened to attack the
> "untradeable at retail scale" finding from two new angles: leveraged **gold F&O** (Mini/Petal)
> and an **ETF portfolio manager** (ML rotation + a risk-managed allocator). Both reached honest
> negatives. The full per-experiment record — every arc, cycle, mechanism, gold variant, and ETF
> step — is the **Research scoreboard** below.

> **Reality check.** Over 90% of retail F&O traders lose money. "High stable profit" is
> not a goal and is not promised. The achievable target is a positive-expectancy,
> risk-controlled system with a small, decaying edge — one that can fail, and stop itself.
> This is engineering/research, **not financial advice**.

---

## Research scoreboard — everything tested, every result

The full record across **all** research: the intraday equity program (Arcs I–III) and the
post-close-out pivots (gold F&O, ETF portfolio manager). Every arc reached an **honest negative**
— a real-but-sub-threshold edge, or a structural infeasibility at retail scale. Nothing cleared
the gates; **no capital was ever risked.** The recurring root cause is the **two-gates split**:
most failures are **Gate 1 (is the edge real *and strong enough*?)**, which is Sharpe-based and
therefore **invariant to capital and leverage**; the gold case is **Gate 2 (economic viability)**,
the one capital actually moves, which couldn't be tested for lack of data.

Columns: **Result · Conclusion · Why it failed · How it could be fixed · Why we couldn't fix it here.**

### Arc I — Intraday cash-equity, directional (the original program · [`docs/FINDINGS.md`](docs/FINDINGS.md))
| Tested | Result | Conclusion | Why it failed | Possible fix | Why not fixed |
|---|---|---|---|---|---|
| Final model artifact (P2A.6): 3 families on bar features | OOS AUC **0.520** (lgbm .529 / xgb .527 / logit .488) | Ceiling set by **data**, not the algorithm | Weak directional signal in bar-data features | Richer data (depth/microstructure) | Depth data inaccessible at retail (Cycle 3b) |
| Kill-gate on 15-min MIS design | **KILL**, net CPCV Sharpe **−0.977**, 6/7 criteria fail | Real gross edge, flipped negative by cost | ~0.17–0.21% MIS round-trip cost > the edge | Lower-cost venue / frequency | No tested frequency survived (below) |
| Cycle 1 — binding-constraint diagnostic | Edge dies on **feature signal + cost**, not model | Stop tuning the model | (diagnostic) | — | — |
| Cycle 2 — label-sanity (mislabeling?) | **Labels SOUND** (vertical-barrier 16.4%) | Ruled out a false lead | (clean negative) | — | — |
| Cycle 3a — finer-grid OHLCV (5/1-min) features | **No lift** (+0.012/+0.015 vs +0.042 base) | Finer bars add no signal | Information ceiling, not resolution | — | Structural, external to code |
| Cycle 3b — 5-level depth / microstructure | **DATA-GATED** — untestable | The richest remaining family can't be populated | Historical depth data inaccessible at retail budget | Buy institutional depth data | Out of budget/scope |
| Cycle 4 — coarser 60-min frequency | net **−0.90** → **STOP** | Cutting cost drag doesn't save it | Gross edge flat, still < cost | — | Pre-committed stop engaged |
| Cycle 5 — daily/CNC, 56-name cross-sectional META | net **+0.148** (all paths +, DSR 0.967†); DIRECT −0.156 | Real but **economically negligible** → KILL | ~7× below the +1.0 gate; PF 1.047 | More capital / scale | Gate-1 weakness is **capital-invariant** |
| Audit of external "60% / +0.662 Sharpe" claim | **Debunked** → true value +0.148 (~4.5× inflated) | Honest apparatus walked a hype number to truth | cost 0.14→0.22%, N=5→23, off-gated labeler, selection | — | — (the point *was* to deflate it) |
| Ruled out: data source; survivorship | Kite ≈ yfinance (Δ −0.016..+0.040); survivorship corrected | Neither was the problem | — | — | — |

### Arc II — Mechanical / event edge (Part VI)
| Tested | Result | Conclusion | Why it failed | Possible fix | Why not fixed |
|---|---|---|---|---|---|
| **Cointegration pairs** (equity, real data) | **+0.425** net Sharpe — *strongest edge the project ever found* | Real but sub-threshold + insignificant → GATE-7 honest stop | Too few independent pairs; weak/insignificant after cost | More pairs, better entry/exit timing | Edge still below the bar; t-stat insignificant |
| **Index-rebalance flow** | **DATA-GATED** | Couldn't test the flow signal | Needs constituent-change + flow data | Buy index-event data | Data out of scope |
| **PEAD** (post-earnings drift) | **DATA-GATED** | Couldn't test the event signal | Needs clean earnings-date + estimate data | Buy earnings/event data | Data out of scope |

### Arc III — Cross-sectional factors (Phase 3X)
| Tested | Result | Conclusion | Why it failed | Possible fix | Why not fixed |
|---|---|---|---|---|---|
| Multi-factor composite, survivorship-free 2,695-name NSE panel (2016–24) | composite **IC +0.051**, active **IR −0.82** vs EW | Signal real, far too weak → **KILL** | Factor edge decays below cost after turnover | Stronger/orthogonal factors, lower turnover | Same Gate-1 weakness |
| K-Means cluster-selection A/B | **MARGINAL** (IR −0.82 → **+0.09**, all paths flip +) | Beats baseline but still KILLs (~8× below bar) | Still sub-threshold; confounded with dropping weak factors | A genuinely stronger factor set | Edge ceiling too low |

### Gold pivot — MCX futures (F&O) ([`GOLD_MINI_CHARTER.md`](GOLD_MINI_CHARTER.md))
| Tested | Result | Conclusion | Why it failed | Possible fix | Why not fixed |
|---|---|---|---|---|---|
| **Gold Mini** futures (100g) @ ₹1L, 3× cap | **INFEASIBLE** | Not tradeable within the committed risk caps | 1 contract ≈ **₹7.25L ≈ 7.25×** on ₹1L; indivisible | Raise capital to ≥ ~₹2.4L; or use Gold Petal | ₹1L below minimum lot economics → pivoted |
| **Gold Petal** futures (1g ≈ ₹14k) liquidity | **BLOCKED (incomplete)** | Couldn't measure tradeable liquidity/history | No MCX data in-env (MCX/NSE 403; Kite token daily-expired; no TradingView lib) | Export TradingView CSV, or build an MCX-bhavcopy ingester | Data access unresolved → **parked** |
| **Gold ETF** (GOLDBEES) leverage-free path | **DEFERRED**; later tested as an ETF *leg* (below) | No leverage; STT question (since resolved) | — | — | Superseded by the ETF track |
| **Gold–Silver cointegration pairs** (Phase-2 fallback) | **PRE-REGISTERED, NOT RUN** | Committed as fallback only if Phase 1 cleared Gate 1 | — | Run it if a directional gold path revives | Phase 1 never cleared (parked) |

### ETF portfolio manager ([`SPEC_MultiETF_Rotation.md`](SPEC_MultiETF_Rotation.md) · [`docs/etf_rotation/`](docs/etf_rotation/))
| Tested | Result | Conclusion | Why it failed | Possible fix | Why not fixed |
|---|---|---|---|---|---|
| Step 1 — universe liquidity gate @ ₹1L | All 12 candidates clear ₹5 cr/day | Turnover non-binding; froze 5 risk + cash | — (information) | — | — |
| Step 2 — cost model + STT-on-ETF | STT ≤0.1 bps; **flat DP fee dominates** (~15–32 bps round-trip) | The flat ₹15.9/scrip/sell is the real small-capital cost | — (information) | More capital shrinks the flat DP in bps | — |
| Step 3 — fixed-weight benchmark | **Sharpe 1.53** (2022–26), **1.54** (10y clean) | A strong, robust baseline = the line to beat | — (it *is* the bar) | — | — |
| Step 4–5 — **ML cross-sectional rotation** vs benchmark | Excess Sharpe **negative in every config** (best −0.116) → **NO-GO** | ML loses to dumb rebalancing | Cross-section too thin (~3–4 independent drivers); benchmark holds the winners; turnover drag | Broader, genuinely independent universe; more capital | Liquid ETFs give too few independent drivers; correlated equity ETFs (tested) don't help |
| Universe robustness — 3 variants (drop gold/silver; add MID150+ITBEES; 3-ETF) | All **NO-GO**; one 3-ETF "PASS" **rejected as best-of-N** | NO-GO is structural, not asset-specific | Same thin cross-section; apparent pass was selection bias (honest-N → ~0.2) | (none that survives honest N) | Only independent liquid drivers are {Ind eq, US eq, gold, silver, cash} |
| **Risk-managed PM** (vol-target risk-parity, no ML) | **NO-GO** | Fails Gate 2 | maxDD **−28.75% > 20%** cap; *dominated* by equal-weight on Sharpe & DD | Leverage to de-risk; broader universe; revise DD mandate | Long-only, no-leverage ETF book can't hold ≤20% DD over a cycle (COVID ≈ −22%) |
| Meta: "would a Nifty-100 **stock** PM be broad enough?" | Answered from Arcs I/III — **not re-run** | Breadth is fine, but it *is* the closed equity arc | Edge is Gate-1 weak (+0.148 / IC +0.051); stock STT (~0.2% round-trip) *worse* than ETF | More capital helps only flat DP — not STT, not Sharpe | Capital is the Gate-2 lever; this failure is **Gate 1** |

† **DSR caveat** (Cycle 5): 0.967 is on the path-concatenated basis; on de-duplicated events the
t-stat is ~1.66 (marginal). Doesn't change the verdict — criterion 1 fails ~7× regardless.

**Data-quality note:** Yahoo `range=10y` adjusted-close carries isolated ~90% one-day glitches
(2019-12, 2021-06) that fake huge drawdowns; a centered-median bad-tick filter is in
`scripts/etf_portfolio.py`. `>2022`-window figures predating that fix are flagged in the docs.

---

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — the package/environment manager (single binary).
  - Windows (PowerShell): `irm https://astral.sh/uv/install.ps1 | iex`
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Ensure uv is on your `PATH` (Windows installs to `%USERPROFILE%\.local\bin`).
- **Python 3.12** — provisioned automatically by uv (pinned via [`.python-version`](.python-version));
  you do not need to install it yourself.

## Setup

```bash
uv sync                      # create .venv, install dev tools + the editable `quant` package
uv run pre-commit install    # enable the git pre-commit hooks
```

`uv sync` is reproducible: it installs the exact versions from [`uv.lock`](uv.lock).

### Optional storage backends

The storage layer has three tiers behind one `Repository` interface. The **Parquet**
raw archive (cold) works out of the box (`pyarrow` is a base dependency). The richer
tiers are optional:

```bash
uv sync --extra redis                 # hot/live store (RedisLiveStore)
pip install "arcticdb>=5,<7"          # versioned research store — REQUIRES a pandas<3 env
```

`arcticdb` pins `pandas<3`, so it is intentionally **not** a declared dependency (it
would pull the whole project's pandas back to 2.x); install it ad hoc in a dedicated
environment, or swap the warm tier for QuestDB later — the `Repository` interface makes
that a clean swap. All three tiers are fully unit-tested without either backend installed.

## Quality gates

The same four gates run locally, in pre-commit, and in CI — "green" means the same thing
everywhere.

```bash
uv run ruff check .          # lint + import order
uv run black --check .       # formatting
uv run mypy                  # strict static typing
uv run pytest                # tests
```

Or run the whole pre-commit suite (file hygiene + the above) in one shot:

```bash
uv run pre-commit run --all-files
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint + type-check + tests
on every push and pull request.

---

## Project structure

```
quant-intraday/
├── config/             # versioned configuration (contents land in P0.2)
│   └── env/            #   dev / paper / live overrides
├── src/quant/          # the system, organised by layer:
│   ├── core/           #   shared domain types, interfaces, config, logging, calendar
│   ├── data/           #   Layer 1 — brokers, ingest, store, hygiene, features, recorders (P9)
│   ├── research/       #   Layer 2 — labeling, models, validation, reports,
│   │                   #     factors (Phase 3X), mechanisms (Part VI mechanical-edge harness)
│   ├── capital/        #   Layer 3 — combine, portfolio, sizing, risk
│   ├── execution/      #   Layer 4 — oms, router, reconcile, safety, shortfall
│   ├── ops/            #   Layer 5 — scheduler, monitor, attribution, drift, mlops, platform
│   └── control/        #   Layer 6 — control API gateway (backend for the app)
├── app/                # mobile master-control app (PWA → APK)
├── tests/              # unit / integration / adversarial (mirrors src/)
├── scripts/            # runnable ops scripts
├── notebooks/          # exploration only — never production logic
├── docs/               # blueprint reference + deep dives + PROGRESS log
└── data/               # local data cache (gitignored)
```

The authoritative build specification is
[`MASTER_BLUEPRINT_Claude_Build_Handoff.md`](MASTER_BLUEPRINT_Claude_Build_Handoff.md):
engineering ground rules (Part I), locked decisions (Part II), the technical reference
(Part III), and the phased, session-sized build program with its safety gates (Part IV).
Detailed design lives in [`docs/deep_dives/`](docs/deep_dives/).

## Development workflow

- **One subtask per session**, finished to its acceptance criteria, on a branch
  (`feat/p0.1-repo-tooling`, …). Never commit straight to `main`.
- **Every commit leaves the tree green** — pre-commit enforces lint/format/type locally;
  CI re-checks on push.
- **Update [`docs/PROGRESS.md`](docs/PROGRESS.md)** at the end of each session.
- **Respect the phase gates.** Do not start a phase until the previous gate passes.
- **Secrets never enter git** — they come only from environment / a secrets manager.
