# Quant Intraday — Indian Cash-Equity Intraday Trading System

An automated system that trades **liquid Indian cash equities intraday (MIS)** on a
**15-minute decision clock**, using gradient-boosted models on point-in-time features,
validated rigorously against overfitting, sized conservatively under hard, un-overridable
risk limits, executed via the Zerodha Kite Connect API, monitored for drift, and
controllable from a secure mobile master-control app.

> **Status:** Phase 1 (Data & Feature Layer) in progress — Gate 0 ✅ passed.
> See [`docs/PROGRESS.md`](docs/PROGRESS.md) for the live build log.

> **Reality check.** Over 90% of retail F&O traders lose money. "High stable profit" is
> not a goal and is not promised. The achievable target is a positive-expectancy,
> risk-controlled system with a small, decaying edge — one that can fail, and stop itself.
> This is engineering/research, **not financial advice**.

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
│   ├── data/           #   Layer 1 — brokers, ingest, store, hygiene, features
│   ├── research/       #   Layer 2 — labeling, models, validation, reports
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
