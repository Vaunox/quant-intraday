# P2A.4 — Research environment stand-up (operator walkthrough)

**Subtask:** P2A.4 (Phase 2A — Operator Actions). See the master blueprint, Part IV, and Part II
**"Research environment setup (operator runbook)"** (the authoritative recipe this points to).
**Depends on:** none (can run any time).
**Audience:** the operator. This is pure local tooling — no credentials, no money, no network
beyond PyPI — so the AI can stand it up on your machine and verify it; this doc records the recipe
so it's reproducible (e.g. on the live host or a fresh laptop).

---

## 0. Goal and scope

**Goal:** a separate **`.venv-research`** environment (pinned **`pandas<3`**, with **MLflow** and
**ArcticDB**) and a **persistent MLflow** tracking server, so research runs (the final P2.7 run in
P2A.6, then P2.8/P2.9) record to a durable store — the honest trial count the Deflated Sharpe needs.

**Why a *separate* env (the environment policy, Part II).** MLflow and ArcticDB pin `pandas<3`,
while the engine env tracks current pandas (3.x). Mixing them would drag the whole project's pandas
down. So research deps live in their own venv, **never imported by the engine**; the engine env is
untouched. Storage/tracking backends sit behind interfaces (the `Repository`, the
`ExperimentTracker`), so this split costs the engine nothing.

**Out of scope here:** installing the *quant project itself* + the model stack
(LightGBM/XGBoost) into `.venv-research` — that's **P2A.6**'s setup, when the final P2.7 run
actually executes in this env. P2A.4 just stands up the env and proves MLflow persists.

---

## 1. The recipe (Windows; one-time)

No activation needed — target the venv's interpreter directly (sidesteps PowerShell
execution-policy snags with `Activate.ps1`):

```powershell
cd C:\Users\vinay\Documents\quant-intraday

# 1) create the research venv (separate from the engine .venv)
uv venv .venv-research --python 3.12

# 2) install the research-only deps into it (pandas pinned < 3)
uv pip install --python .venv-research\Scripts\python.exe "pandas<3" mlflow arcticdb

# 3) verify
.venv-research\Scripts\mlflow.exe --version
.venv-research\Scripts\python.exe -c "import mlflow, arcticdb, pandas; print('pandas', pandas.__version__)"
#   expected: an mlflow version, and pandas reports a 2.x version (engine env stays 3.x)
```

*(Activation alternative, if you prefer: `.venv-research\Scripts\Activate.ps1` — but if PowerShell
blocks it, `Set-ExecutionPolicy -Scope Process RemoteSigned` for that session, or just use the
direct-path commands above.)*

---

## 2. Persistent MLflow tracking

> **MLflow 3.x note (verified 2026-06-24):** the file store (`--backend-store-uri ./mlruns`) is
> deprecated and `mlflow server` now **refuses** it — use a **sqlite** backend. We keep the db and
> artifacts under the already-gitignored `mlruns/`.

```powershell
# Terminal A — start the tracking server (sqlite backend), bound to localhost:
mkdir mlruns -Force | Out-Null
.venv-research\Scripts\mlflow.exe server --backend-store-uri "sqlite:///mlruns/mlflow.db" `
    --default-artifact-root "./mlruns/mlartifacts" --host 127.0.0.1 --port 5000
#   leave this running; open http://127.0.0.1:5000 in a browser. ('server' and 'ui' are aliases.)

# Terminal B — point a run at it and log a one-line smoke run.
# PYTHONUTF8=1 is required on Windows: MLflow prints a 🏃 emoji in the run-URL line, which crashes
# the default cp1252 console without it.
$env:MLFLOW_TRACKING_URI = "http://127.0.0.1:5000"
$env:PYTHONUTF8 = "1"
.venv-research\Scripts\python.exe -c "import mlflow; mlflow.set_experiment('p2a4-smoke'); r = mlflow.start_run(); mlflow.log_metric('ok', 1.0); mlflow.end_run(); print('logged run', r.info.run_id)"
```

The run appears in the UI under the **`p2a4-smoke`** experiment and persists in
**`mlruns/mlflow.db`** (it survives a server restart — that's the "persistent" part).
`--host 127.0.0.1` keeps the server on localhost only; never expose it publicly.

---

## 3. Acceptance checklist (subtask "Done when")

- [ ] `mlflow --version` runs inside `.venv-research`.
- [ ] `pandas` reports a **2.x** version inside `.venv-research` (the engine env stays 3.x).
- [ ] The MLflow UI is reachable at **http://127.0.0.1:5000**.
- [ ] A one-line test run appears in the UI and **persists** in `mlruns/mlflow.db`.

---

## 4. Notes (auditable)

- **Gitignored:** `.venv-research/` and `mlruns/` are in `.gitignore` — run history is local
  artifact, never committed. Ruff also excludes `.venv-research/` so static analysis never
  traverses research deps (mypy is already scoped to `src`/`tests`).
- **One-way isolation:** the engine never imports anything from `.venv-research`; the research env
  exists so the operator can use `mlflow`/`arcticdb` without leaking them into the engine. The CI
  confinement test (P2.6) still fails the build if `mlflow`/`lightgbm`/`xgboost` are imported
  outside `research/models/`.
- **Persistence is the point:** for the auto-trigger subtasks (P2.7 final run, P2.8, P2.9), the
  in-memory tracker is **not** acceptable — the MLflow server set up here is what makes the trial
  count (and so P2.9's Deflated Sharpe) honest.
- **Live host (Phase 8):** the same MLflow server runs on the VPS in `ap-south-1`, bound to
  localhost / behind the VPN — same recipe, different host.

---

## 5. References (Ground Rule 9)

- Master blueprint, Part IV — **P2A.4**; Part II — **"Research environment setup (operator
  runbook)"** (the recipe + the MLflow auto-trigger rules) and the **Environment policy**.
- Code: the `ExperimentTracker` / `create_mlflow_tracker` seam in
  [`research/models/tracking.py`](../../src/quant/research/models/tracking.py) (P2.6) is what logs
  to this server in P2A.6+.
- Prior: **P2A.3** (`docs/operator_runbooks/P2A.3_backfill.md`). Next: **P2A.5** (AWS account prep).
