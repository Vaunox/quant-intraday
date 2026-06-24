# P2A.6 — Final P2.7 registry-promotable run on real data (operator walkthrough)

**Subtask:** P2A.6 (Phase 2A — Operator Actions). See the master blueprint, Part IV (P2A.6), the
P2.7 deferral note, and Part II **"Research environment setup (operator runbook)"** (the MLflow
recipe this builds on).
**Depends on:** P2A.1 (Kite credentials), P2A.2 (daily auth), P2A.3 (real backfill), P2A.4
(research env + persistent MLflow). **Not** P2A.5 — this run is **local**; cloud is for P2.8.
**Audience:** the operator. The run reads the local Parquet archive and writes a local model
artifact + MLflow record — no money, no orders, no network beyond MLflow's own telemetry (which you
can disable, below). The AI can execute and verify it on your machine; this doc records the recipe.

---

## 0. Goal and scope

**Goal:** retroactively complete the deferred final P2.7 run now that real data exists — train the
production stack (the cross-family **ensemble** + the **GMM regime gate**) on the **real backfilled
universe**, log the run to **persistent MLflow**, and write the artifact + model card into the
**`FileModelRegistry`**, ready for P2.8/P2.9 to judge.

**What "done" means (acceptance criteria):** an MLflow run-ID exists, a `FileModelRegistry`
artifact exists, both are recorded in `docs/PROGRESS.md` under P2A.6 and P2.7 (closing the
deferral), and the reloaded artifact predicts **identically** to the in-memory model (the
round-trip check) — that artifact is the input P2.8 will validate.

**The one design decision (cross-sectional pooling).** The blueprint's model is cross-sectional
(one model across the universe), but `PurgedKFold` needs a **sorted, unique** timeline and the 8
symbols share 15-minute timestamps. The pipeline therefore pools all symbols onto **one synthetic
timeline**, concatenating each symbol's events with an inter-symbol **gap larger than the maximum
label horizon** (`pipeline.pool_gap_days`, default 5; the vertical barrier caps a label at one
session). Intra-symbol time deltas are preserved exactly (so the purge/embargo stay correct) and a
label window can never span two symbols (asserted in the tests). One model, all the data, no
modification to the merged P2.7 code.

---

## 1. Pre-flight checklist

- [ ] **Real data present.** `data/parquet/` holds the 8-symbol minute archive (P2A.3). Confirm
      with `uv run python scripts/check_backfill.py --start 2021-06-24 --end 2026-06-23`.
- [ ] **Research env ready (P2A.4)** and **the project installed into it** (this is P2A.6's setup
      step, deferred from P2A.4):

  ```powershell
  cd C:\Users\vinay\Documents\quant-intraday
  uv pip install --python .venv-research\Scripts\python.exe -e .
  ```

  This adds the `quant` package + the model stack (LightGBM, XGBoost, TA-Lib, statsmodels,
  kiteconnect) into `.venv-research` **without** disturbing its `pandas 2.3.3` (the project only
  requires `pandas>=2.2`). Verify:

  ```powershell
  .venv-research\Scripts\python.exe -c "import pandas, mlflow, lightgbm, xgboost, talib, quant.research.pipeline; print(pandas.__version__)"
  # expected: 2.3.3 (research env stays pandas 2.x; the engine env is untouched at 3.x)
  ```

- [ ] **Persistent MLflow store** under the gitignored `mlruns/` (from P2A.4).

---

## 2. The command (narrated)

Run from the **research env**, with persistent MLflow tracking. Two ways to point at the store:

- **Direct sqlite (no server)** — simplest for a one-shot run; logs straight to the DB file:

  ```powershell
  cd C:\Users\vinay\Documents\quant-intraday
  $env:MLFLOW_TRACKING_URI = "sqlite:///mlruns/mlflow.db"
  $env:PYTHONUTF8 = "1"               # MLflow prints a 🏃 emoji that crashes the cp1252 console
  $env:MLFLOW_DISABLE_TELEMETRY = "true"   # optional: stop MLflow's anonymous usage ping
  .venv-research\Scripts\python.exe scripts\run_final_training.py `
      --start 2021-06-24 --end 2026-06-23 --tracker mlflow --experiment p2a6-final-run
  ```

- **Tracking server** — if you want the UI live while it runs, start the server per Part II's
  runbook (`mlflow server --backend-store-uri sqlite:///mlruns/mlflow.db ... --host 127.0.0.1`)
  and set `MLFLOW_TRACKING_URI=http://127.0.0.1:5000` instead. Both write the same `mlruns/`.

What the single command does, end to end (all in `quant.research.pipeline`):

1. **Reads** the 8-symbol minute archive (the universe in `config/universe.yaml`; `--symbols`
   overrides) over `[--start, --end]`.
2. **Builds** the pooled cross-sectional training matrix — resample → P1.6 core features + P1.7
   regime descriptors → CUSUM events → triple-barrier labels → average-uniqueness × time-decay
   weights → gapped synthetic timeline.
3. **Trains** the ensemble (LightGBM + XGBoost + logistic, rank-average blend, isotonic-calibrated)
   under purged CV, **logging the run to MLflow** (the auto-trigger requirement — *not* the
   in-memory tracker).
4. **Fits** the GMM regime gate on the full-sample strategy returns and **bundles** it with the
   ensemble into the `GatedEnsembleModel` artifact.
5. **Registers** the artifact + model card (data/feature/label/model version tags) into
   `FileModelRegistry` under `models/registry/` (gitignored).
6. **Verifies** the reloaded artifact predicts identically to the in-memory model (exit code 1 if
   not).

`--tracker mlflow` is the default; selecting it without `mlflow` installed fails loudly rather than
silently falling back to the in-memory tracker (a P2.9 Deflated-Sharpe correctness requirement).

---

## 3. Verification (what the AI checks after the run)

- **Exit code 0** and the log line `final run PASSED — registered <model_id>; round-trip exact`.
- **MLflow run is FINISHED** with the version tags, queried from the store:

  ```powershell
  .venv-research\Scripts\python.exe -c "import mlflow; mlflow.set_tracking_uri('sqlite:///mlruns/mlflow.db'); import pandas as pd; r = mlflow.search_runs(experiment_names=['p2a6-final-run']); print(r[['run_id','status','tags.model_version','tags.data_version']].to_string())"
  ```

- **Registry artifact exists and deserializes**: `models/registry/ensemble-regime-v1/0001/`
  holds `card.json` + `model.pkl`; loading it and predicting matches the in-memory model
  (the run's own round-trip check already asserts this to within 1e-9).

---

## 4. Executed result (2026-06-24)

Run executed locally from `.venv-research`, persistent MLflow → `sqlite:///mlruns/mlflow.db`,
over the full backfill `2021-06-24 → 2026-06-23`, default universe (8 symbols). **Exit 0,
round-trip exact.** Wall-clock ≈ 2 min.

| Item | Value |
|---|---|
| MLflow experiment | `p2a6-final-run` (experiment_id **2**) |
| MLflow run-ID | **`e24c0cd6354f40e7bae024ce9f6b16c1`** — status **FINISHED** |
| Registry artifact | **`ensemble-regime-v1-0001`** → `models/registry/ensemble-regime-v1/0001/` (`card.json` + `model.pkl`) |
| Fingerprint (SHA-256) | `9031451e30dfb27eff327235902e042f38381b9474239ead55add8e697ffc593` |
| `data_version` | `15min-8sym-20210624-20260623-1bba6975` |
| `feature_set_version` | `core-v1` |
| `label_version` | `tb-cusum0.01-u2.0-d1.5-min0.002-vmax0` |
| Pooled observations | **14,150** events across all 8 symbols (positive rate 0.450) |
| Members / blend | `lightgbm, xgboost, logistic` / rank-average, isotonic-calibrated |
| Regime gate | 3 regimes, multipliers `(1.0, 1.0, 1.0)` — all active in-sample |
| OOS metrics (purged CV) | combined AUC 0.520 (lgbm 0.529 / xgb 0.527 / logistic 0.488); calibrated logloss 0.687, Brier 0.247 |
| Round-trip | reloaded artifact predicts identically (diff ≤ 1e-9); fingerprint re-verified on a fresh load |

The edge is **weak** (combined OOS AUC ≈ 0.52, barely above chance) on this 8-name seed universe —
which is the honest, expected reality, and exactly what P2.8's robustness battery and P2.9's
seven-point kill-gate (cost-inclusive) exist to judge. P2A.6's job is to produce the
registry-promotable artifact, not to clear the gate; that verdict is P2.9's.

---

## 5. Notes / gotchas

- **Local, by policy.** Final P2.7 runs are local (Part II cloud policy); cloud is reserved for
  P2.8's heavier CPCV + robustness battery. No AWS resources are used here.
- **Artifacts are gitignored.** `models/`, `mlruns/`, and `*.pkl` are never committed (Ground Rule
  6); the artifact is a regenerable local deliverable, reproducible from config + the versioned
  data. Re-running registers a new version (`0002`, …) — append-only.
- **Re-running is safe and deterministic.** Seeds are fixed (`model.random_seed`), so the same
  data + config reproduce the same model and metrics.
