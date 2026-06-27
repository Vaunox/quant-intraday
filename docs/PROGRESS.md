# Progress Log

The living build log for the quant-intraday system. This is the authoritative
tracker referenced by Part V of `MASTER_BLUEPRINT_Claude_Build_Handoff.md`.
Updated at the end of every session.

**Status:** ◐ in-progress / ☑ done / ☐ todo

**Gates:** Gate 0 ☑ · Gate 1 ☑ · Gate 2 ☐ (kill-gate KILL) · Gate 2A ☐ · Gate 2R (loop — **STOPPED at cycle 4**; research phase complete) ⊘ · Gate 3 ☐ · Gate 4 ☐ · Gate 5 ☐ · Gate 5A ☐ · Gate 6 ☐ · Gate 7 ☐ · Gate 7A ☐ · Gate 8A ☐ · Gate 8 ☐

> **⊘ RESEARCH ARC CLOSED.** No strategy cleared the seven-point kill-gate net of costs. Phase 2R STOPPED at cycle 4 (tag `research-phase-stop-cycle-4`); the operator-directed **Cycle-5** re-open (daily/CNC, 56 survivorship-aware names, validated Kite data, honest CNC 0.22% / N=23) closed out at an honest **+0.148** annualised CPCV path-Sharpe (META; DIRECT −0.156) — real but economically negligible, fails the kill-gate (criteria 1 & 5). The pre-committed +0.3 stop band engaged and was honored. Phases 3–8 deferred indefinitely (not deleted). **No live trading.**
>
> **→ The authoritative close-out is [`docs/FINDINGS.md`](FINDINGS.md)** — what we built, what we found, why the kill-gate was never passed, and the honest ceiling of the edge, with MLflow run-IDs and exact numbers. See also `docs/iteration_log/closeout.md` (Phase 2R stop) and `docs/iteration_log/cycle-5_closeout.md` (Cycle-5 seal).

---

## Phase 0 — Foundation & Scaffolding

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| 2026-06-17 | P0.1 Repository & tooling | ☑ done | `feat/p0.1-repo-tooling` (pushed to origin) | 2 passing (`tests/unit/test_smoke.py`) | uv toolchain; all gates verified green. See session notes below. |
| 2026-06-17 | P0.2 Configuration & secrets | ☑ done | `feat/p0.2-config-secrets` | 34 passing (config + secrets) | Layered typed config (pydantic) + `QUANT__*` overrides + secrets interface; 99% cov. See notes. |
| 2026-06-17 | P0.3 Logging & audit foundation | ☑ done | `feat/p0.3-logging-audit` (merged) | 58 passing (incl. logging + audit) | Structured JSON/text logging (IST, correlation IDs, redaction) + hash-chained append-only audit log; 100% cov both. See notes. |
| 2026-06-17 | P0.4 NSE calendar utility | ☑ done | `feat/p0.4-nse-calendar` (merged) | 87 passing (incl. calendar) | IST trading-calendar/session utility (trading days, holidays, session phases); 100% cov. See notes. |
| 2026-06-17 | P0.5 Domain types & interfaces | ☑ done | `feat/p0.5-types-interfaces` | 98 passing (incl. types + interfaces) | Frozen domain types + 6 runtime-checkable Protocols; fakes type-check; 100% cov both. See notes. |
| 2026-06-17 | **GATE 0** | ☑ **passed** | tag `gate-0-foundation` | whole-package 99% cov | Scaffolding, config/secrets, logging/audit, calendar, contracts — typed, tested, CI green. |

## Phase 1 — Data & Feature Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| 2026-06-19 | P1.1 Broker adapter + auth/session | ☑ done | `feat/p1.1-broker-adapter` | 54 new (158 total) | `KiteAdapter` behind `BrokerAdapter` (historical market data + daily session seam); `kiteconnect` SDK confined to `data/brokers/`; token-bucket rate limiter; 100% cov on the package. See notes. |
| 2026-06-19 | P1.2 Live stream consumer | ☑ done | `feat/p1.2-live-stream` | 27 new (185 total) | `TickStreamConsumer` (full-mode ticks + 5-depth → `MarketUpdate` queue; resubscribe-on-reconnect; staleness heartbeat) behind a `TickerTransport` Protocol; `KiteTickerTransport` (SDK) confined to `data/brokers/`; 100% cov on new modules. See notes. |
| 2026-06-20 | P1.3 Storage layer | ☑ done | `feat/p1.3-storage-layer` | 82 new (267 total) | Three tiers behind `Repository`: `ParquetArchive` (immutable raw, symbol/date partitions; real+tested), `ArcticRepository` (versioned research; time-travel reads), `RedisLiveStore` (bounded recent-bars hot store). Optional clients (`arcticdb`/`redis`) confined to `data/store/` + lazy; arcticdb pins pandas<3 → not a declared dep. 100% cov on new modules. See notes. |
| 2026-06-20 | P1.4 Historical backfill job | ☑ done | `feat/p1.4-historical-backfill` | 40 new (307 total) | `BackfillJob` (paginated, resumable) + `run_backfill.py` CLI, writing through `Repository`. Per-symbol accumulate-then-write-once (the only tier-agnostic, idempotent write — Arctic `write_bars` snapshots, not appends); resume skips completed symbols via a `JsonBackfillCheckpoint`; one Arctic version per symbol. 100% cov on new modules. See notes. |
| 2026-06-20 | P1.5 Data hygiene jobs | ☑ done | `feat/p1.5-data-hygiene` | 50 new (357 total) | `data/hygiene/`: corporate-action back-adjustment (split/bonus/dividend, raw untouched), point-in-time `ConstituentRegistry` (delisted names included), bad-tick filter (point-in-time, logs every correction), calendar-aware gap detection, liquidity screen + ESM/T2T exclusion. Each idempotent/pure + tested; 100% cov on new modules. See notes. |
| 2026-06-20 | P1.6 Feature library: core + dual-path harness | ☑ done | `feat/p1.6-feature-core` | 27 new (384 total) | `data/features/`: pure causal feature functions (multi-horizon log returns, realized-vol/ATR/Parkinson, intraday VWAP-deviation) + `compute_feature_frame` (vectorized) / `compute_features_asof` (incremental) harness. **Skew test: incremental == vectorized bar-by-bar** + prefix-invariance (no lookahead). 100% cov on new modules. See notes. |
| 2026-06-20 | P1.7 Feature library: microstructure/technical/x-sec/regime | ☑ done | `feat/p1.7-features-extended` | 45 new (429 total) | `data/features/`: microstructure (OFI 5-depth, spread, depth imbalance, signed flow), TA-Lib technicals (RSI/MACD/Bollinger %B), cyclical time-of-day, cross-sectional sector-neutral ranks/z-scores, regime (vol/trend) + trailing winsorize/robust-scale (§2.3). All causal/point-in-time; `ta-lib` added (prebuilt wheels). 100% cov on new modules. See notes. |
| 2026-06-20 | P1.8 Leakage & skew test suite (CI) | ☑ done | `feat/p1.8-leakage-suite` | 38 new (467 total) | `tests/adversarial/`: reusable structural checks (forward-shift invariance, train/serve skew, trailing-only normalization, no-future-correlation) run across every feature family + **tripwires that fire on intentionally-leaky features**. Marked `adversarial`; runs in CI. See notes. |
| 2026-06-20 | P1.9 Data-quality dashboard | ☑ done | `feat/p1.9-data-quality` | 14 new (481 total) | `data/quality/`: `DataQualityDashboard` composes coverage (session-level vs NSE calendar) + gaps + bad-tick counts (P1.5) + feed-latency stats into a `DataQualityReport` with a text `render()`; surfaces issues per symbol. 100% cov on new modules. See notes. |
| 2026-06-20 | **GATE 1** | ☑ **passed** (tag `gate-1-data`) | | 481 passing | Point-in-time, corp-action-adjusted, survivorship-correct, leakage-tested dataset + feature set reproducible on demand. Phase 1 complete. |

## Phase 2 — Research Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| 2026-06-21 | P2.1 Validation harness core (purged CV + cost backtester) | ☑ done | `feat/p2.1-validation-harness` | 72 new (553 total) | `research/validation/`: `PurgedKFold` (purge + embargo, strict no-overlap), `IndianCostModel` (itemised per-order brokerage/STT/exchange/SEBI/stamp/GST), `DepthAwareSlippage` (size-vs-liquidity participation curve), `Backtester` (event-driven, next-bar-open, intraday square-off, costs+slippage, latency). 100% cov on new modules. See notes. |
| 2026-06-21 | P2.2 CPCV + DSR + PBO | ☑ done | `feat/p2.2-cpcv-dsr-pbo` | 61 new (614 total) | `research/validation/`: `CombinatorialPurgedCV` (φ=C(N,k)·k/N path reconstruction + path-Sharpe distribution), Deflated/Probabilistic Sharpe (`metrics.py`, stdlib `NormalDist` — no SciPy), PBO via CSCV (`pbo.py`), `TrialTracker`. Refactored the purge primitive (`purged_train_mask`) out of `PurgedKFold` for reuse across non-adjacent test groups. 100% cov on new modules. See notes. |
| 2026-06-21 | P2.3 Labeling: CUSUM + triple-barrier | ☑ done | `feat/p2.3-labeling` | 38 new (652 total) | `research/labeling/`: symmetric `cusum_events` sampler + `TripleBarrierLabeler` (vol-scaled barriers floored at the cost hurdle, high/low first-touch with conservative same-bar stop, vertical = IST session end). `LabelSet.label_times` (t0→t1) feeds the purged CV/CPCV splitters; `.sides` is the primary label. 100% cov on new modules. See notes. |
| 2026-06-21 | P2.4 Sample weighting | ☑ done | `feat/p2.4-sample-weighting` | 36 new (688 total) | `research/labeling/`: `SampleWeights` (indicator matrix → concurrency, average-uniqueness, return-attribution) + `time_decay_weights`; uniqueness-aware `sequential_bootstrap` (+ `average_uniqueness_of_sample` diagnostic, seeded RNG). Corrects non-IID overlapping labels (AFML ch. 4). 100% cov on new modules. See notes. |
| 2026-06-21 | P2.5 Meta-labeling + fractional differentiation | ☑ done | `feat/p2.5-meta-fracdiff` | 40 new (728 total) | `research/labeling/`: `momentum_side`/`mean_reversion_side` primary rules + `MetaLabeler` (side-aware bet/no-bet via a shared `barriers.first_touch`); `research/features_research/`: `frac_diff` (binomial FFD) + `adf_test` (statsmodels) + `min_ffd` (min-d stationary, retains memory). Added `statsmodels` dep (resolves with pandas 3.x). 100% cov on new modules. See notes. |
| 2026-06-21 | P2.6 Model: baseline + tracking + calibration | ☑ done | `feat/p2.6-model-baseline` | 58 new (786 total) | `research/models/`: LightGBM baseline (native API) evaluated only under purged CV (pooled OOS predictions); permutation/MDA importance computed within the CV (not MDI); isotonic probability calibration (hand-rolled PAVA, no sklearn); purged-CV `HyperparameterTuner`; `ExperimentTracker` (in-memory default + lazy, confined `MLflowExperimentTracker` — operator-installed, pandas<3). `LightGBMBaseline` implements the live `Model`. Added `lightgbm`; mlflow not a declared dep. 100% cov on new modules. See notes. |
| 2026-06-22 | P2.7 Ensemble + regime gate + registry | ☑ done | `feat/p2.7-ensemble-regime-registry` | 98 new (884 total) | `research/models/`: cross-family ensemble (LightGBM+XGBoost+logistic; rank-average/stack, OOF combiner+calibrator), GMM regime gate, `FileModelRegistry` (data/feature/label/model version tags + fingerprint), `evaluate_ensemble_under_cpcv`. Added `xgboost`. **Final registry-promotable run on real data was deferred to P2A.6 — now done** (run `e24c0cd6…`, artifact `ensemble-regime-v1-0001`). 100% cov on new modules. See notes. |
| 2026-06-25 | P2.8 Robustness battery + two-engine reconciliation | ☑ done | `feat/p2.8-robustness-battery` | 69 new (1016 total) | `research/validation/{robustness,reconcile}.py` (5 stress tests + independent vectorised engine) + `research/pipeline/robustness{,_cli}.py` orchestration; ran vs the real P2A.6 artifact (MLflow exp `p2.8-robustness` id 3, 14 runs), **engines reconcile exactly** (max money diff 0.0); edge weak (~0.04 per-obs path-Sharpe). 100% cov on new modules. See notes. |
| 2026-06-25 | P2.9 Validation report + kill-gate emitter | ☑ done | `feat/p2.9-killgate-emitter` | 38 new (1054 total) | `research/reports/` (seven-point kill-gate, validation report + renderer, QuantStats tearsheet) + `research/pipeline/validation{,_cli}.py`; **net-of-cost** CPCV + DSR + PBO + walk-forward + robustness → verdict. Ran vs the real candidate (MLflow exp `p2.9-killgate` id 4, run `cdf5dd8f…`): **VERDICT KILL** (6/7 failed; net CPCV median −0.977, walk-forward −9.8%). 100% cov on new modules. See notes + `docs/iteration_log/cycle-1_verdict.md`. |
| | **GATE 2 — THE KILL-GATE** | ☐ not passed (machinery built; candidate KILLed → Phase 2R) | | | Tag `gate-2-research` only when a candidate clears all seven. Current candidate routed to Phase 2R (Cycle 2). |

## Phase 2R — Research Iteration Loop

| Date | Cycle / subtask | Status | Branch / commit | Artifact | Notes |
|---|---|---|---|---|---|
| 2026-06-25 | Cycle 1 · P2R.1 Diagnostic | ☑ done | `docs/cycle-1-diagnostic` (#43) | `docs/iteration_log/cycle-1_diagnostic.md` | Binding-constraint ranking: feature signal (primary) + label/barrier calibration (cheapest first); model capacity NOT the bottleneck. |
| 2026-06-25 | Cycle 1 · P2R.3 Verdict | ☑ done | (P2.9 run) | `docs/iteration_log/cycle-1_verdict.md` | **KILL** → CONTINUE. Net-of-cost CPCV median −0.977; costs flip the gross edge negative, exactly as the diagnostic predicted. |
| 2026-06-24 | P2R.4 Iteration budget (operator) | ☑ done | `docs/p2r-iteration-budget` (#45) | `docs/iteration_log/budget.md` | 6-cycle cap; 50-trial cap; STOP if best smoke path-Sharpe <+0.3 after cycle 4; PIVOT freq if <+0.5; tighten-only. |
| 2026-06-25 | Cycle 2 · label sanity | ☑ done | `docs/cycle-2-finding` (#46) | `docs/iteration_log/cycle-2_finding.md` | Label SOUND — vertical only 16.4%, positive rate stable ~0.45. Hypothesis (b) refuted; labeling closed. 0 trials. |
| 2026-06-25 | Cycle 3 · feature signal (3a + 3b decision) | ☑ done | `docs/cycle-3-plan` (#47), `feat/iteration-cycle3a-features-finer` (#48), `docs/cycle-3a-finding` (#49) | `cycle-3_plan.md` / `cycle-3a_finding.md` / `cycle-3b_decision.md` | **3a:** finer OHLCV (5/1-min) adds no signal (gross/obs +0.012/+0.015 vs +0.042 baseline) — closed. **3b:** depth deferred (no retail historical depth) → pivot. 2 trials. |
| 2026-06-26 | Cycle 4 · frequency pivot to 60-min | ☑ done | `docs/cycle-4-finding` (#51), `docs/research-phase-closeout` | `cycle-4_finding.md` / `cycle-4_verdict.md` / `closeout.md` | 60-min **no lift** (gross flat +0.047; net −0.90 ann). Best smoke path-Sharpe far below +0.3 → **STOP criterion engaged**. Operator decision: **STOP** (honor the budget; daily-close/instrument pivots would be loosening). |
| 2026-06-26 | **Phase 2R — STOPPED** | ⊘ research phase complete | tag `research-phase-stop-cycle-4` | `docs/iteration_log/closeout.md` | No edge survives costs at this configuration (intraday cash equity, 8 names, bar-data, retail costs). Apparatus + blueprint preserved; Phases 3–8 deferred indefinitely; no live trading. A successful Rule-7 outcome. |
| 2026-06-26 | Cycle 5 · prev-project config under honest harness (diagnostic) | ☑ done | uncommitted — `scripts/run_cycle5_diagnostic.py` (hold for go) | `docs/iteration_log/cycle-5_finding.md`; MLflow exp `p2r-cycle5` | Operator-directed post-STOP probe of the uploaded RL-ensemble's **49-stock / daily-close / CNC-0.14%** config (materially different scope from the 8-name/15-min/MIS arc that STOPPED). Net ann **+0.556** (smoke 6×2/80); DSR 1.000, PBO 0.412. **MARGINAL** (>+0.3 stop, <+1.0 gate). Prev "60%" ~4–5× inflated (GAN val-period leakage + best-of-42 w/o DSR + cost understatement) but real underlying signal confirmed. 1 trial → N=5 cum / 45 remaining. |
| 2026-06-27 | Cycle 5 · **P2.8 full robustness battery** | ☑ done | uncommitted — `scripts/run_cycle5_robustness.py` (hold for go) | MLflow exp `p2r-cycle5-p28-battery` (id 8) run **`08b4213b50f0481cb9682b6ac931618b`** (FINISHED) | Full battery on daily/CNC/49-stock. Baseline 8×2/300-rds net ann **+0.662** (+0.0417/obs), 0/φ negative paths. **6/6 green:** param-sens CV 0.140 (no knife-edge/flip) · MC order-robust (rank 1.000) · noise edge-persists (graceful 0.035→0.017→0.012→0.007) · cross-symbol LOO(20) median +0.063, 60% positive · synthetic GBM −0.054 (no leak) · two-engine reconcile max_diff 2.4e-11. **Cost: $0 — ran LOCAL (14.7 min, 16 GB threshold met); cloud `c7i.8xlarge` deferred (Part II requires committed code; commits held). No instance launched → none to terminate.** Edge **robust but MARGINAL** (<+1.0 gate); kill-gate verdict remains P2.9's. |
| 2026-06-27 | Cycle 5 · **complete gated pipeline — Stage 1** (8-name validated, honest inputs) | ☑ done | uncommitted — `scripts/run_complete_pipeline.py` + new CNC labeler in `barriers.py`/`triple_barrier.py`/`meta.py`/`config.py` (hold for go) | MLflow exp `p2r-cycle5-complete-pipeline` run **`dcd93454c75e462299030a6cfc65905b`** | Brought the daily/CNC strategy onto the **gated path** + wired all four dormant components. **New: gated labeler CNC mode** (`holding_mode: mis\|cnc`; MIS unchanged, +3 unit tests) — the gated P2.3/P2.5 labelers were MIS-session-clamped (0 labels on daily); CNC unblocks multi-day holds. Features via P1.7 harness + 8 new TA-Lib indicators (leakage suite **53 green** on the actual 21-feature matrix); MetaLabeler bet/no-bet 2nd stage; cross-sectional rank+sector-z; frac-diff (min_ffd, bounded grid) on 5 price-level cols; **honest DSR N=22** (live MLflow count, not 5); **honest CNC cost 0.22%** (0.1% STT ×2 + stamp/exch/GST, not 0.14%). CI **1077 passed**, mypy clean. **RESULT (8 names, ~2.6k obs): DIRECT net ann −0.222 (validated) / −0.206 (yfinance); META −0.285 / −0.024; DSR ≈ 0 — does NOT survive honest inputs.** ① **Data source is NOT the cause:** validated − yfinance = **−0.016 ann** (noise) → the +0.662 was **not a yfinance hygiene/survivorship artifact**. ② Collapse vs +0.662 driven by honest cost + honest N + gated labeler + the **8-name universe** (guts cross-sectional power) — this is the honest-input/gated result, **not** the cross-sectional headline (needs 49 names). Stage 2 (CNC in backtester/reconciliation/cost-model) held pending the 49-name smoke. |
| 2026-06-27 | Cycle 5 · complete gated pipeline — **49-name (56) honest smoke** (cross-sectional headline) | ☑ done | uncommitted — `scripts/run_complete_pipeline.py` (58-name universe; hold for go) | MLflow exp `p2r-cycle5-complete-pipeline` run **`7397d1cee4c944acb18ac01d36b7e6df`** | Survivorship-aware Nifty-50 union 2021–2026 backfilled via **own Kite→hygiene→Parquet path** (live token seeded; 50 new names daily-native + 8 minute-resampled; **56 usable** — HDFC/TATAMOTORS/LTIM unavailable, all merger/demerger/restructuring cases empirically confirmed, **none collapses** → survivorship intact). Honest CNC **0.22%**, honest **N=23**, gated CNC labeler, all 4 components, ~31.8k pooled events. **RESULT: DIRECT (2p−1) ann −0.156 (val) / −0.196 (yf), DSR 0 — still negative at scale. META (meta-label+cross-sectional) ann +0.148 (val) / +0.154 (yf), all 5 CPCV paths positive, DSR(N=23)=0.967, t=3.71, profit-factor 1.047.** ① **Data source irrelevant again** (val−yf = +0.040 DIRECT / −0.006 META) → +0.662 was never a yfinance hygiene/survivorship artifact. ② **Cross-sectional scale + meta-labeling produces a REAL but ECONOMICALLY NEGLIGIBLE edge**: META −0.285 (8-name) → +0.148 (56-name), statistically significant (DSR pass, all paths +) but **fails kill-gate criterion 1 (Sharpe ≥1.0) by ~7× and criterion 5 (PF ≥1.2)**. Honest ceiling is ~+0.15 Sharpe, not +0.662 (~4.5× inflation = cost 0.14→0.22% + N 5→23 + off-gated inline labeler + selection). DSR caveat: 0.967 on the cycle-5-comparable path-concatenated basis (n×5); de-dup t≈1.66 (marginal). **VERDICT: real signal, far below the bar → close-out per pre-committed bands (+0.148 < +0.3 stop). Stage 2 NOT justified** (realistic execution can only shrink +0.15, never clear +1.0). |

## Phase 3X — Cross-Sectional Multi-Factor Equity (Nifty 500, Monthly)

New alpha source re-pointing the apparatus per [`FINDINGS.md`](FINDINGS.md): attack the Phase-2R
binding constraint via the other Grinold–Kahn axes — frequency (monthly), alpha (cross-sectional
factors), breadth (Nifty 500, sector-neutral). **Long-only, benchmark-relative; success metric =
active IR vs Nifty 500 TRI, gate ≥ 0.75.** Spec: [`iteration_log/p3x_spec.md`](iteration_log/p3x_spec.md).
Pre-committed gate + budget: [`config/factor_default.yaml`](../config/factor_default.yaml).

> **Two facts that shape the plan** (verified against the repo, not the handoff's assumptions):
> **(i)** Portfolio construction is a **build, not a reuse** — `src/quant/capital/` is empty
> scaffolding (Phase 3 below is ☐ todo); P3X.7 builds it. **(ii)** The **survivorship data
> decision is the validity-critical blocker** and runs as a parallel track from day one — Kite
> cannot serve delisted names and Nifty 500 (unlike Nifty 50) has real collapses; see
> [`iteration_log/p3x_data_sourcing.md`](iteration_log/p3x_data_sourcing.md). No backtest number
> is trustworthy until it's settled.

| Date | Subtask | Status | Branch / commit | Notes |
|---|---|---|---|---|
| 2026-06-27 | P3X · gate config locked + scaffold | ◐ in-progress | `feat/p3x-cross-sectional-factors` | `config/factor_default.yaml` (§4 seven-point benchmark-relative gate + §2 contract + §5 budget, fixed before any run — Rule 1) + spec + data-track doc. |
| | P3X.1 Nifty-500 point-in-time universe + backfill | ☐ blocked | | **Gated on the survivorship data decision** (vendor / accept-and-quantify / restricted sub-universe) + operator-provided PIT membership + fresh Kite token. |
| 2026-06-27 | P3X.2 Price-only factor library + leakage tests | ☑ done | `feat/p3x-cross-sectional-factors` | `research/factors/price_factors.py`: momentum 12-1, short-term reversal, low-vol, residual momentum (rolling market-model), Amihud illiquidity — all causal per-symbol transforms; P1.8 leakage-covered (no-lookahead + no-future-correlation) on synthetic panels + hand-computed correctness tests. **1092 tests green**, mypy strict + ruff + black clean. Built on synthetic panels — no market data dependency. |
| | P3X.3 Cross-sectional forward-return labeling | ☐ todo | | 21-session fwd return + decile rank; replaces triple-barrier. |
| | P3X.4 Signal combination | ☐ todo | | Baseline = sector-neutral z-score equal-weight (0 params); ML = trial-charged. |
| | P3X.5 Validation harness adaptation | ☐ todo | | Purge/embargo ≥ 21 sessions; metrics on active return; honest N; de-dup t-stat. |
| | P3X.6 CNC cost model + monthly backtester | ☐ todo | | CNC 0.22% RT; monthly rebalance, no square-off; two-engine reconcile. |
| | P3X.7 Portfolio construction + sizing (**build Capital Layer**) | ☐ todo | | Top-quintile → sector caps → inverse-vol/HRP → no-trade band → vol-target. |
| | P3X.8 Pre-committed gate run (baseline composite) | ☐ todo | | Zero-parameter baseline through the §4 gate on honest CNC cost; verdict → MLflow. |

## Phase 3 — Capital Layer

> Note: P3X.7 builds the portfolio-construction / risk / sizing modules this phase specifies
> (the Capital Layer was scaffolded but never implemented). Tracked there for the factor product.

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P3.1 Risk-limit engine (first) | ☐ todo | | | |
| | P3.2 Signal combination + selection | ☐ todo | | | |
| | P3.3 Portfolio construction + constraints | ☐ todo | | | |
| | P3.4 Position sizing | ☐ todo | | | |
| | P3.5 Capital pipeline integration | ☐ todo | | | |
| | **GATE 3** | ☐ | | | Tag `gate-3-capital`. |

## Phase 4 — Execution Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P4.1 OMS state machine + durable store | ☐ todo | | | |
| | P4.2 Order-update ingestion | ☐ todo | | | |
| | P4.3 Order router + ≤10-OPS throttle | ☐ todo | | | |
| | P4.4 Slicer | ☐ todo | | | |
| | P4.5 Reconciliation loop + stop-existence guarantee | ☐ todo | | | |
| | P4.6 Execution safety | ☐ todo | | | |
| | P4.7 Implementation-shortfall measurement | ☐ todo | | | |
| | P4.8 Adversarial execution tests | ☐ todo | | | |
| | **GATE 4** | ☐ | | | Tag `gate-4-execution`. |

## Phase 5 — Operations Layer

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P5.1 Daily lifecycle scheduler | ☐ todo | | | |
| | P5.2 Morning auth/token routine | ☐ todo | | | |
| | P5.3 Monitoring metrics + dashboard | ☐ todo | | | |
| | P5.4 P&L attribution | ☐ todo | | | |
| | P5.5 Drift detection (observe-only first) | ☐ todo | | | |
| | P5.6 MLOps: retraining + champion/challenger | ☐ todo | | | |
| | P5.7 Platform: audit, alerting, secrets, config | ☐ todo | | | |
| | P5.8 Infra & disaster recovery | ☐ todo | | | |
| | **GATE 5** | ☐ | | | Tag `gate-5-operations`. |

## Phase 6 — Paper Trading

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P6.1 End-to-end paper trading | ☐ todo | | | |
| | P6.2 Live-vs-backtest validation | ☐ todo | | | |
| | **GATE 6** | ☐ | | | Tag `gate-6-paper`. |

## Phase 7 — Control Layer (Mobile Master Control)

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P7.1 Control API gateway (auth + scopes) | ☐ todo | | | |
| | P7.2 Bounded command handlers + clamping + 2FA | ☐ todo | | | |
| | P7.3 Telemetry stream | ☐ todo | | | |
| | P7.4 Private-network setup | ☐ todo | | | |
| | P7.5 PWA dashboard | ☐ todo | | | |
| | P7.6 APK wrapping (operator-signed) | ☐ todo | | | |
| | P7.7 Security validation | ☐ todo | | | |
| | **GATE 7** | ☐ | | | Tag `gate-7-control`. |

## Phase 8 — Live, Micro Size

| Date | Subtask | Status | Branch / commit | Tests | Notes |
|---|---|---|---|---|---|
| | P8.1 Go live, trivially small | ☐ todo | | | Operator-driven; Claude never places real orders. |
| | P8.2 Sustained live validation | ☐ todo | | | |
| | **GATE 8** | ☐ | | | Tag `gate-8-live`. |

---

## Session notes

### 2026-06-17 — P0.1 Repository & tooling ☑

**Goal:** stand up the project skeleton and quality gates.

**Delivered**
- Full Part-I folder structure under `src/quant/` (six layers, all subpackages),
  `tests/{unit,integration,adversarial}`, `config/{,env}`, `app/`, `scripts/`,
  `notebooks/`, `data/`. Every Python package has a one-line module docstring.
- `pyproject.toml` — `hatchling` build (src layout, package `quant`); dev tools in a
  PEP 735 `dependency-groups.dev`; configs for ruff (lint + isort + pydocstyle),
  black, mypy (`strict`), and pytest. Runtime deps intentionally empty (added per layer).
- `.pre-commit-config.yaml` — generic file-hygiene hooks + **local** ruff/black/mypy
  hooks run via `uv run`, so hook versions equal the project's pinned versions (one
  source of truth, no drift between local/CI).
- `.gitignore` — secrets/data/models/.env/caches.
- `.gitattributes` — repo-wide LF normalization (`* text=auto eol=lf`).
- `.github/workflows/ci.yml` — lint + type-check + test on every push/PR via uv, using
  the committed `uv.lock` for reproducible installs.
- `.python-version` (3.12) + committed `uv.lock`.
- `README.md` rewritten with setup/run instructions.
- `tests/unit/test_smoke.py` — 2 tests (package imports; all layer subpackages import).

**Verification (all green, Python 3.12.12 via uv):**
- `uv run ruff check .` → All checks passed
- `uv run black --check .` → 38 files unchanged
- `uv run mypy` → no issues in 38 source files
- `uv run pytest` → 2 passed
- `uv run pre-commit run --all-files` → all 12 hooks Passed

**Decisions**
- **Toolchain = uv** (operator-approved). Single binary, reproducible lockfile; CI uses
  the same. Python pinned to **3.12** to match CI exactly.
- **black formats, ruff lints** (Ground Rule 7 names both). Same line length (100); ruff's
  formatter is left off so the two never conflict. Typing is enforced by mypy `strict`, so
  ruff's `ANN` rules are intentionally **not** enabled (avoids double-reporting); docstrings
  (`D`, google convention) **are** enabled per Ground Rule 5.
- **Local pre-commit hooks via `uv run`** rather than mirror repos, so versions track
  `uv.lock` exactly.

**Bug caught & fixed (root cause, not band-aid — Ground Rule 4)**
- Initial `.gitignore` used unanchored `data/` and `models/`, which also matched the
  **source** packages `src/quant/data/` (6 files) and `src/quant/research/models/` (1 file),
  plus `env/` matched `config/env/`. Because ruff/black/git honor `.gitignore`, those source
  packages would have been silently un-linted **and excluded from commits** — a serious
  defect for a data-centric system. Fixed by anchoring the root-only dirs (`/data/`,
  `/models/`, `/secrets/`, …) and dropping the colliding `env/` pattern. Verified that the
  source packages are now tracked while the root `data/` cache stays ignored.

**Follow-ups / notes for next sessions**
- `config/*.yaml` are intentionally absent (only `config/env/.gitkeep`); their contents are
  **P0.2**'s deliverable.
- Repo is git-initialised on `main`; P0.1 is **committed** on branch `feat/p0.1-repo-tooling`.
  No remote exists yet and nothing has been pushed.
- `gate-0-foundation` tag is **not** applied yet; it comes after P0.5.
- **Next subtask: P0.2 — Configuration & secrets system.**

### 2026-06-17 — P0.2 Configuration & secrets ☑

**Goal:** layered config loader + secrets interface; zero hard-coding.

**Delivered**
- `core/config.py` — layered loader: `default.yaml` ← `config/env/<env>.yaml` ←
  `QUANT__<section>__<key>` env-var overrides; deep-merged and validated into an
  **immutable, typed pydantic `Config`** (`extra="forbid"` → unknown keys fail loud).
  Section models seed the blueprint's locked decisions (15-min clock, broker limits,
  Indian cost model, risk limits, ¼-Kelly, inverse-vol, storage URIs, logging). Plus
  `load_universe()` → typed `Universe`. Loader is fully DI (`config_dir`, `environ`).
- `core/secrets.py` — `Secrets` Protocol + `EnvSecrets` (env-backed, `QUANT_SECRET_`
  prefix). Missing/empty secret raises `MissingSecretError` naming the env var (never
  the value); `environ` excluded from `repr` so values can't leak.
- `config/default.yaml`, `config/env/{dev,paper,live}.yaml`, `config/universe.yaml`.
- Deps: `pydantic`, `pyyaml` (+ `types-PyYAML` dev).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 42 files), pre-commit;
**34 tests pass**; coverage 99% config (only an unreachable defensive raise) / 100% secrets.

**Decisions**
- **pydantic v2** for the schema: typed access, fail-loud validation, immutability.
- Safety/compliance invariants encoded as schema constraints: OPS ≤ 10 (SEBI),
  `max_slices` ≤ 10, `kelly_fraction` ∈ (0,1], `max_gross_exposure` ≤ 5 (default 1.0 =
  no leverage), slippage `min_bps ≤ max_bps`.
- Override convention: `QUANT__section__key` (double-underscore nesting, highest
  precedence); `QUANT_ENV` selects env; `QUANT_CONFIG_DIR` overrides config location.
- A test asserts **no secret-like keys** in any committed config file (keys parsed,
  comments ignored) — enforcing "secrets never in config files".

**Follow-ups / notes**
- Execution/risk/sizing/portfolio config is seeded now (anti-hard-coding) and will be
  *consumed* by its layer (P3/P4); fields extend per subtask.
- The logger that reads `logging.*` is **P0.3**.
- **Next subtask: P0.3 — Logging & audit foundation.**

### 2026-06-17 — P0.3 Logging & audit foundation ☑

**Goal:** structured logging configured once; append-only audit log interface.

**Delivered**
- `core/logging.py` — `configure_logging(config)` sets up the root logger once
  (idempotent) from `config.logging` (level/format/timezone). JSON or text output;
  **IST timestamps** (zoneinfo + tzdata); **correlation IDs** via a `ContextVar` +
  `correlation_id_context()` + `CorrelationIdFilter`; **secret redaction** (`Redactor`
  masks sensitive-named fields and inline token patterns) applied in both formatters.
  `get_logger(__name__)` everywhere else.
- `core/audit.py` — `AuditLog` Protocol + `FileAuditLog`: append-only JSONL with a
  **SHA-256 hash chain** (each entry links to the prior), per-entry seq + IST timestamp
  + correlation id; secrets redacted on write; `verify()` detects tampering/reordering;
  chain continues across restarts; thread-safe.
- Dep: `tzdata` (zoneinfo resolves Asia/Kolkata on any OS).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 46 files), pre-commit;
**58 tests pass**; **100% coverage** on both new modules.

**Decisions**
- Root logger configured (all modules' logs become structured); idempotent so
  "configure once" is safe to call again.
- Redaction is key-name + inline-pattern based (no need to hold secret literals);
  reused by the audit log.
- Audit log is hash-chained for tamper-evidence (immutable / SEBI traceability),
  beyond a plain append-only file; `verify()` tested against data-tamper and seq-break.
- IST via `zoneinfo` (config-driven), not a hard-coded offset.

**Follow-ups / notes**
- Alerting on CRITICAL events + secrets-manager wiring are **P5.7** (platform); this is
  the logging/audit substrate they build on.
- **Next subtask: P0.4 — NSE calendar utility.**

### 2026-06-17 — P0.4 NSE calendar utility ☑

**Goal:** authoritative trading-calendar/session utility used everywhere.

**Delivered**
- `core/calendar.py` — `NSECalendar` (frozen): `is_trading_day` / `is_holiday` /
  `is_weekend`, `session_open` / `session_close` / `session_bounds`, `phase_at`
  (CLOSED / PRE_OPEN / REGULAR via the `SessionPhase` enum), `is_open`,
  `next_` / `previous_trading_day` — all in IST. `phase_at` fails loud on naive
  datetimes and converts aware ones to IST. Exchange session times (09:00 pre-open,
  09:15 open, 15:30 close) are named constants (Ground Rule 2). `load_nse_calendar()`
  loads holidays from `config/nse_holidays.yaml` (DI-friendly).
- `config/nse_holidays.yaml` — **partial seed** (fixed-date national holidays, 2025–26)
  with a prominent warning that movable festival holidays MUST be added from the
  official NSE list before trading.
- Small refactor: exposed `config.discover_config_dir` (was private) so the calendar
  reuses config-dir discovery (DRY).

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 48 files), pre-commit;
**87 tests pass**; **100% coverage** on calendar.

**Decisions**
- Calendar is **data-driven** (holidays injected/loaded), keeping `core/` light — no heavy
  market-calendar library in the foundation; the holiday list is reference data like the
  universe.
- **Honesty:** only fixed-date holidays are seeded (no fabricated movable festival dates);
  the engine is fully tested with injected holidays regardless of seed completeness.
- Self-square-off (~15:15) stays in config (`execution.self_square_off_time`); this module
  models exchange session phases only.

**Follow-ups / notes**
- ⚠️ Before paper/live: complete `config/nse_holidays.yaml` with the official NSE holiday
  list (festival holidays move yearly); the live universe/hygiene (P1.5) or operator owns this.
- **Next subtask: P0.5 — Domain types & interfaces (contracts).** Last one before Gate 0.

### 2026-06-17 — P0.5 Domain types & interfaces ☑ (completes Gate 0)

**Goal:** the shared data models and the Protocols every layer implements.

**Delivered**
- `core/types.py` — immutable, slotted value objects: `Bar`, `Tick`, `DepthLevel`,
  `DepthSnapshot` (+ `best_bid`/`best_ask`), `OrderRequest`, `Order`
  (+ `is_complete`/`remaining_quantity`), `Position` (+ `side`/`is_flat`), `Signal`,
  `RiskDecision`; enums `Side`, `OrderType`, `Product`, `OrderStatus`. Pure carriers
  (business invariants enforced by the constructing layer; documented).
- `core/interfaces.py` — `runtime_checkable` Protocols: `BrokerAdapter`, `Repository`,
  `Model`, `PortfolioConstructor`, `Sizer`, `RiskEngine`.
- Coverage config: exclude Protocol/type-only stubs (`...`) from reports.

**Verification (all green, Py 3.12):** ruff, black, mypy (strict, 52 files), pre-commit;
**98 tests pass**; types/interfaces 100% cov; whole-package **99%** (only the one
unreachable defensive `raise` in config). A trivial fake of each Protocol is statically
checked (typed assignment → mypy) and runtime-checked (`isinstance`).

**Decisions**
- Domain types are **frozen + slotted dataclasses** (immutable, hot-path-cheap), not
  pydantic — market data streams fast and these are pure carriers.
- All six core Protocols are `runtime_checkable` for fakes; mypy is the authoritative
  conformance check.

---

## GATE 0 — Foundation: ✅ PASSED (2026-06-17)

Project scaffolding, layered config + secrets, structured logging + append-only audit,
the NSE calendar, and the core domain types/Protocols all exist — typed, tested, and
green in CI. Tagged **`gate-0-foundation`**.

**Next: Phase 1 — Data & Feature Layer** (P1.1 — broker adapter + auth/session).

---

### 2026-06-17 — Post-Gate-0 audit + hybrid data contracts (amends P0.5)

**Why:** before starting P1.1, audited all of Phase 0 against deep dives 01–05 and
amended the P0.5 data contracts to the deep-dive "hybrid" shape.

**Audit result (P0.1–P0.5 vs deep dives):** verified correct — cost-model rates
([02 §4b.6]), risk/sizing limits + Kelly ([03 §6]), the order state machine and order
types/product, which correctly exclude the discontinued CO/BO ([04 §7.1–7.2]), session
times/IST ([01 §1.3]), and the secrets/audit/logging discipline ([05]). Two contract
gaps found (below).

**Amendment delivered (`refactor/p0.5-hybrid-data-contracts`):**
- **Hybrid bar representation:** bulk time-series cross boundaries as a pandas
  `DataFrame`; single events stay typed. `BrokerAdapter.fetch_historical` and
  `Repository.read_bars`/`write_bars` now return/accept `pd.DataFrame`; `core/frames.py`
  is the single bridge (`bars_to_frame`/`frame_to_bars` + `BAR_COLUMNS` derived from
  `Bar` so the schema can't drift). Keeps the money/event path typed; gives research the
  pandas it wants.
- Added typed **`Margins`** + `BrokerAdapter.margins()` (pre-open gate + sizing; matches
  the deep-dive `BrokerAdapter`).
- `pandas` is now a `core` dependency (deliberate — foundational for a quant system).

**Verification:** ruff, black, mypy strict (54 files), pre-commit; **103 tests**;
frames/types/interfaces 100% cov.

**Still open (flagged):**
- **Signal direction:** ✓ resolved — `SignalDirection` (LONG/SHORT/FLAT) added, distinct
  from order `Side` (see entry below).
- Deferred to their own layer (not P0 errors): `OrderRequest` `validity`/`variety`/
  `market_protection` → P4.3; `stream()` on the adapter vs a separate port → P1.1/P1.2;
  `Model` primary/meta split → P2.

---

### 2026-06-17 — SignalDirection (long/short/flat), distinct from order Side

`core/types.py`: added **`SignalDirection`** (LONG / SHORT / FLAT) with `to_target_sign()`
(+1 / 0 / -1) as the *only* pure mapping off direction. `Signal` now carries
`direction: SignalDirection` — a `FLAT` signal is a first-class "model ran, no edge"
prediction, kept distinct from the *absence* of a signal. Order `Side` (BUY/SELL) is
unchanged and stays on `OrderRequest`; the **position-aware** direction → (Side, quantity)
translation (target − current position; a future `Side.from_delta`) is deferred to the
capital/execution layer (**P3/P4**) — no `Signal`→`Side` mapping exists in core.

**Verification:** ruff, black, mypy strict (54 files), pre-commit; **104 tests**; types 100% cov.

**Next:** **P1.1** (broker adapter + auth/session) — awaiting operator go.

---

## Phase 1 — Data & Feature Layer

### 2026-06-19 — P1.1 Broker adapter (market data) + auth/session ☑

**Goal:** a `KiteAdapter` for historical market data behind the `BrokerAdapter`
Protocol, with the daily session/token seam — nothing outside `data/brokers/`
importing the SDK.

**Reference (Ground Rule 9):** Deep Dive #1 §0.2 (Kite mechanics: ~3 req/s data
limit, static-IP-for-orders, daily session reset), §0.3 ("never let the rest of the
system import `kiteconnect`"); Deep Dive #5 (morning auth/token routine: login URL →
`request_token` → `SHA-256(api_key+request_token+api_secret)` → `access_token`,
manual-seed-then-automate). Transport decision (official SDK vs custom httpx)
**confirmed by the operator at session start: official `kiteconnect` SDK.**

**Delivered (`src/quant/data/brokers/`):**
- `client.py` — `KiteClient` Protocol (the narrow SDK surface we use) + interval
  normalization (`normalize_interval` / `KITE_INTERVALS`) + `create_kite_client`,
  the **single, lazy** `kiteconnect` import site (keeps the SDK — and its heavy
  twisted/autobahn deps — out of every import path until a live client is built).
- `kite.py` — `KiteAdapter` (implements `BrokerAdapter`): `fetch_historical`
  resolves symbol→token, ensures the session is seeded, throttles, calls the SDK,
  and maps candles to the canonical bars schema **via `core.frames.bars_to_frame`**
  (one schema source of truth). Trading/account methods raise `NotImplementedError`
  naming their subtask (orders → P4.3, order reads → P4.2, positions → P4.5,
  margins → P5.1) — tracked deferral, not a buried TODO (Ground Rule 4).
- `auth.py` — `TokenStore` Protocol + `InMemoryTokenStore` (P1.1 default) +
  `KiteAuthenticator` (`login_url` / `seed_session` / `access_token`); the
  `api_secret` is read only via `core.secrets` and never logged.
- `instruments.py` — `InstrumentRegistry` (`(exchange, tradingsymbol)`→token, from
  the instruments dump; `from_client` builder).
- `rate_limit.py` — `RateLimiter` Protocol + thread-safe `TokenBucketRateLimiter`
  (config-driven, injectable clock/sleep).
- `errors.py` — `BrokerError` + `SessionNotSeededError` / `InstrumentNotFoundError`
  / `UnsupportedIntervalError`.
- `docs/runbooks/kite_session.md` — the daily auth flow, secrets, wiring, caveats.
- `pyproject.toml` — `kiteconnect>=4.2,<6` runtime dep (resolved 5.2.0; v5 signatures
  verified) + a mypy override marking the untyped SDK `ignore_missing_imports`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (67 files),
pre-commit (12 hooks); **158 tests pass** (54 new); **100% coverage** on every
`data/brokers/` module. A `test_brokers_confinement.py` scans the whole `quant`
tree and fails CI on any `kiteconnect` reference outside `data/brokers/`.

**Decisions**
- **Official SDK, confined + wrapped.** Operator-confirmed. The SDK is fronted by our
  own `KiteClient` Protocol and `TokenBucketRateLimiter`, and imported lazily in one
  place, so tests run with fakes (no SDK, no network, no credentials).
- **Symbol-based interface, token resolution inside the adapter.** Our
  `BrokerAdapter.fetch_historical` is symbol-based (P0.5); Kite is token-based, so
  the adapter resolves via `InstrumentRegistry` — the rest of the system never sees
  instrument tokens.
- **Candle → DataFrame via the existing `core.frames` bridge** (not a hand-rolled
  frame) so the bars schema can't drift.
- **`stream()` stays off `BrokerAdapter`.** The live WebSocket consumer is its own
  ingest module (P1.2), matching the existing interface; not added here.

**Bug caught & fixed (root cause, not the test — Ground Rule 4)**
- The token-bucket's refill loop could spin forever: FP rounding left `tokens` a few
  ULPs below 1.0, making the computed wait so small it fell below the clock's ULP, so
  time stopped advancing (a unit test surfaced it as a `MemoryError`). Fixed with a
  `1e-9` epsilon on the token comparison (grant ≈ sub-nanosecond early; loop now
  provably terminates).

**Follow-ups / notes (deferred, tracked)**
- Token **persistence + automated morning seed → P5.2** (`InMemoryTokenStore` is
  behind the `TokenStore` Protocol; a persistent store drops in with no other change).
- **Orders/positions/margins → P4.2/P4.3/P4.5/P5.1** (currently `NotImplementedError`).
- **Live tick/depth stream → P1.2**; **multi-year paginated/resumable backfill → P1.4.**
- **Static IP** matters only for order placement (Phase 4); data endpoints are exempt.
- ⚠️ Operator live-run prerequisites (none needed to build/test): paid Kite Connect
  plan, `QUANT_SECRET_KITE_API_KEY` / `QUANT_SECRET_KITE_API_SECRET`, daily TOTP seed.

**Next subtask: P1.2 — Live stream consumer.**

### 2026-06-19 — P1.2 Live stream consumer ☑

**Goal:** a robust live WebSocket consumer for ticks + 5-level depth, behind a
swappable transport so nothing in `data/ingest` imports the broker SDK.

**Reference (Ground Rule 9):** Deep Dive #1 §0.2 (WebSocket modes — `full` = 5-depth
+ timestamp; 3000 instruments/conn, 3 conns/key) and the `brokers/` module note
("WebSocket lifecycle: reconnect, heartbeat, resubscribe"). KiteTicker v5 API + full-
mode tick shape verified via context7 and SDK introspection.

**Delivered:**
- `core/interfaces.py` — `TickerTransport` (the live-socket port) + `StreamListener`
  (the callback sink) Protocols; `core/types.py` — `MarketUpdate` (a `Tick` + optional
  `DepthSnapshot`).
- `data/ingest/stream.py` — `TickStreamConsumer` (implements `StreamListener`):
  resubscribes its full token set on **every (re)connect** (the testable
  auto-recovery), parses each raw tick to a `MarketUpdate` (tz-aware IST), pushes to a
  `queue.Queue` off the socket thread (a full queue **drops with a WARNING**, never
  blocks the feed), and tracks a **staleness heartbeat**. Pure `parse_market_update`
  for the tick/5-depth mapping. SDK-free.
- `data/brokers/ticker.py` — `KiteTickerTransport` wrapping `kiteconnect.KiteTicker`
  (the **only** ticker import site, lazy via `create_kite_ticker_transport`);
  translates the SDK's `(ws, …)` callbacks to `StreamListener`. Confinement test still
  green.
- `config` — `broker.websocket` gains `reconnect_max_tries` / `reconnect_max_delay_seconds`
  / `connect_timeout_seconds` / `stale_timeout_seconds` (schema + `default.yaml`),
  so reconnect/backoff is config-driven (handed to the SDK's exponential backoff).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (72 files),
pre-commit (12 hooks); **185 tests pass** (27 new); **100% coverage** on
`stream.py`, `ticker.py`, and `MarketUpdate`.

**Decisions**
- **Reconnect/backoff = the SDK's** (KiteTicker's exponential backoff, configured by
  us); duplicating it would fight the library (Ground Rule 4). Our consumer owns the
  **resubscribe-on-connect** and **staleness** logic — the parts worth testing — and
  those are driven by a `FakeTickerTransport` (the "fake socket").
- **Backpressure drops loudly, never blocks.** `on_ticks` runs on the SDK's reactor
  thread; blocking it would stall the feed, so a full queue increments a counter and
  WARNs. Escalation of persistent staleness/feed-loss to the kill-switch is Layer 4/5.
- **SDK confinement holds for streaming too:** the WebSocket lives behind
  `TickerTransport`; `data/ingest` imports no SDK.

**Follow-ups / notes (deferred, tracked)**
- Consumer pushes to a `queue.Queue`; wiring it to the **Redis live store → P1.3**.
- Multi-connection sharding (≤3000 tokens/conn, ≤3 conns) is config-aware but a
  single-connection consumer suffices for a Nifty-100 universe; shard in a later pass
  if the universe grows.
- Feed-staleness → kill-switch escalation lands with execution safety (**P4.6**) /
  monitoring (**P5.3**); P1.2 detects + warns only.

**Next subtask: P1.3 — Storage layer.**

### 2026-06-20 — P1.3 Storage layer ☑

**Goal:** the `Repository` interface + the three tiered implementations, all swappable
behind the one interface so the rest of the system never sees a concrete store.

**Reference (Ground Rule 9):** Deep Dive #1 §1.2 (the three-tier design — Redis hot →
ArcticDB warm/versioned → Parquet cold/immutable; "partition raw archives by
`symbol/date` and keep them immutable and versioned … corrections become new versions";
"storage is behind a repository interface", swappable to QuestDB later) and the §"What
I'd build" `store/` spec (`Repository` + `ParquetArchive` + `ArcticRepository` +
`RedisLiveStore`). ArcticDB `Library` API (`Arctic(uri)` → `get_library(create_if_missing)`
→ `write(prune_previous_versions=False)` / `read(as_of=…)` → `VersionedItem.data/.version`
/ `list_versions` / `has_symbol`) verified via context7.

**Delivered (`src/quant/data/store/`):**
- `serde.py` — the one place that validates the canonical bars schema
  (`ensure_bars_schema`), orders/sorts/range-filters (`sort_bars`,
  `restrict_to_range`, inclusive), (de)serializes via Parquet bytes
  (`to_parquet_bytes`/`from_parquet_bytes` — verified dtype-exact round-trip, reused by
  both the Parquet and Redis tiers), and compares content order-insensitively
  (`frames_equal`). Schema source of truth stays `core.frames.BAR_COLUMNS`.
- `parquet.py` — `ParquetArchive` (a `Repository`): immutable raw archive,
  Hive-partitioned `symbol=<S>/date=<YYYY-MM-DD>/bars.parquet` by **IST** trading day;
  atomic temp-then-replace writes; **idempotent** identical re-write, **immutable**
  conflicting overwrite → `ImmutableArchiveError`; range reads prune partitions then
  filter precisely. Real (pyarrow), fully round-trip tested. `create_parquet_archive`.
- `arctic.py` — `ArcticRepository` (a `Repository`) over a narrow `ArcticLibrary`
  Protocol: every changed write is a new version; identical re-write is a no-op (no
  version bloat); `read_bars_version` + `list_versions` + `latest_version` give
  point-in-time time travel. `open_arctic_library`/`create_arctic_repository` are the
  single, lazy `arcticdb` import site.
- `redis_store.py` — `RedisLiveStore` (a `Repository`) over a narrow `RedisClient`
  Protocol: a bounded rolling window (newest `live_max_bars_per_symbol`) per symbol,
  de-duped by timestamp (incoming wins), optional Redis TTL; `create_redis_client`/
  `create_redis_live_store` are the single, lazy `redis` import site.
- `errors.py` — `StorageError` + `SchemaError` / `ImmutableArchiveError` /
  `VersionNotFoundError` / `OptionalDependencyError` (Ground Rule 7).
- `core/config.py` + `config/default.yaml` — `StorageConfig` gains `arctic_library`,
  `redis_key_prefix`, `live_max_bars_per_symbol` (>0), `live_ttl_seconds` (≥0), all
  config-driven (Ground Rule 2).
- `pyproject.toml` — `pyarrow` runtime dep (Parquet engine); `redis` optional extra;
  `arcticdb`/`redis` added to mypy `ignore_missing_imports` (absent in CI).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (84 files),
pre-commit (12 hooks); **267 tests pass (82 new)**; **100% coverage** on all five
`data/store/` modules. `uv lock --check` + `uv sync --frozen` clean (pandas stays 3.0.3).
A `test_store_confinement.py` (AST-based) fails CI on any `arcticdb`/`redis` import
outside `data/store/`; a parametrized `test_store_repository_contract.py` runs the same
`Repository` contract across all three tiers (the swappability proof).

**Decisions**
- **All three tiers implement the existing `Repository`** (bars). The hot tier keeps a
  bounded recent-bars window (the "live" flavor); tick-level buffering / wiring the P1.2
  consumer→store is deferred (needs tick→bar aggregation, a later pass).
- **`arcticdb` is NOT a declared dependency.** It pins `pandas<3` and would drag the
  whole project's locked pandas down from 3.x (verified: `uv pip install --dry-run
  arcticdb` ⇒ pandas 3.0.3 → 2.3.3). It is operator-installed in a pandas<3 environment
  (or swap the warm tier for QuestDB — the `Repository` interface makes that clean).
  `redis` is a safe optional extra (no pandas constraint). Parquet (pyarrow) is the
  always-installed baseline — Deep Dive #1: "Parquet … perfectly adequate to start."
- **Optional clients confined + lazy + faked**, exactly like the P1.1 `kiteconnect`
  pattern: narrow Protocols (`ArcticLibrary`, `RedisClient`), one lazy `create_*` import
  site each, repository logic fully tested against fakes (no install, no server). Only
  the post-import construction lines are `# pragma: no cover`; the missing-dependency
  path (→ `OptionalDependencyError`) **is** tested (it is reachable in CI, where the
  clients are absent), skipping only where a client happens to be installed.
- **One serializer for Parquet files and Redis values** (Parquet bytes via pyarrow),
  so dtypes round-trip identically across tiers and the archive immutability check
  compares apples to apples.

**Bug caught & fixed (root cause, not a workaround — Ground Rule 4)**
- A method named `set` (to match `redis.Redis.set`) shadowed the builtin `set` inside
  the class body, so a sibling annotation `set[bytes]` evaluated the *method* and raised
  `TypeError: 'function' object is not subscriptable` at import. Fixed by typing those
  returns as the abstract `collections.abc.Set[bytes]` (the codebase's idiom for abc
  types), which resolves to the module global, not the shadowing method.

**Follow-ups / notes (deferred, tracked)**
- **Multi-year paginated/resumable backfill → P1.4** writes through these tiers.
- **Wiring the live consumer → `RedisLiveStore`** (tick→bar aggregation) lands with the
  feature/ingest path (P1.6-ish); P1.3 provides the store, not the aggregation.
- ⚠️ Operator, to use the optional tiers: `uv sync --extra redis` for the hot store;
  `pip install "arcticdb>=5,<7"` in a **pandas<3** env for the versioned research store.
- Parquet range reads prune by IST date then filter precisely; if a single symbol grows
  to many years of partitions, a future optimization is a DatetimeIndex + arcticdb-native
  `date_range` (perf only, with evidence — Ground Rule 7).

**Next subtask: P1.4 — Historical backfill job.**

### 2026-06-20 — P1.4 Historical backfill job ☑

**Goal:** a paginated, resumable multi-year historical backfill that writes through the
`Repository` interface — `data/ingest/backfill.py` + `scripts/run_backfill.py`.

**Reference (Ground Rule 9):** Deep Dive #1 §1.1/§1.2 + the "What I'd build" `ingest/`
spec ("historical backfill jobs (paginated, resumable) … writing through a `Repository`
interface"); §0.2 (Kite caps a single historical request — ~60 days for minute candles —
which is *why* pagination exists). Build order (§"What I'd build"): adapter → **historical
backfill** → storage → hygiene.

**Delivered:**
- `data/ingest/backfill.py` — `BackfillJob` (programs against `BrokerAdapter` + `Repository`
  + a `BackfillCheckpoint`, all injected): paginates `[start, end]` into day-aligned,
  non-overlapping `chunk_days` windows (`iter_chunks`), accumulates a symbol's chunks, and
  writes **once per symbol**. Per-symbol failures are isolated (logged ERROR + recorded in
  the `BackfillReport`, run continues); naive bounds / `start>end` / `chunk_days<=0` fail
  loud. `JsonBackfillCheckpoint` (atomic temp-then-replace JSON, keyed `symbol:interval`)
  is the durable resume state; `BackfillCheckpoint` Protocol + in-memory fake for tests.
- `data/ingest/backfill_cli.py` — importable CLI wiring (arg/date parsing, universe
  fallback, tier selection `parquet|arctic|redis`, `build_adapter`, `main`); `main` takes
  an injected `environ` + `adapter_factory` so the whole orchestration is unit-tested with
  a fake adapter. `scripts/run_backfill.py` is a thin shim (Ground Rule 3).
- `core/config.py` + `config/default.yaml` — new `IngestConfig` (`backfill_chunk_days` (>0),
  `backfill_interval`, `backfill_checkpoint_file`); the chunk window is config, not a magic
  number (Ground Rule 2), since the cap is a per-interval broker constraint.
- `data/ingest/errors.py` — `IngestError` + `BackfillCheckpointError`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (90 files), pre-commit
(12 hooks); **307 tests pass (40 new)**; **100% coverage** on all new `data/ingest`
modules (`backfill`, `backfill_cli`, `errors`, `__init__`). Coverage on this Windows env
needs path-based `--cov=src/quant/data/ingest` (the module-name form trips a numpy-2.x
"load module more than once" import guard under pytest-cov).

**Decisions**
- **Accumulate-then-write-once per symbol** (the key design call). `Repository.write_bars`
  is *not* a guaranteed append across tiers: Parquet appends day-partitions, but **Arctic
  `write_bars` writes the frame as a whole new version (snapshot, replacing prior data)**
  and Redis merges a bounded window (P1.3). The only behaviour the interface guarantees
  everywhere is "persist this frame as the symbol's data, idempotently, readable by range".
  So the job concatenates a symbol's paginated chunks and writes the full series in one
  call — correct on *every* tier, and it yields exactly one Arctic version per symbol per
  run (= "writes versioned data"). Writing per-chunk would silently corrupt the Arctic tier
  (each chunk would overwrite the last) — a latent bug Ground Rule 4 forbids.
- **Resume granularity is one symbol.** The checkpoint records "completed through date D"
  per `(symbol, interval)`; a re-run skips any symbol already complete through the requested
  `end` and re-fetches the rest in full. No duplication: completed symbols aren't re-fetched,
  and the single re-write of an unfinished symbol is idempotent (and even with the checkpoint
  deleted, idempotent writes prevent dups). Finer **per-chunk durable** resume would need an
  explicit `append`-style method on `Repository` — deferred, tracked (it would also let a
  multi-year symbol resume mid-stream instead of re-fetching from `start`).
- **Broker- and store-agnostic.** The job imports no SDK and no concrete store; the CLI's
  live `build_adapter` is the only operator/network path (`# pragma: no cover`). The
  `kiteconnect`-confinement scanner still passes (the CLI only *imports from* `data/brokers`).

**Follow-ups / notes (deferred, tracked)**
- **Per-chunk durable resume** ⇒ a `Repository.append_bars` (or an ingest-side staging
  area); only matters once single-symbol histories are large enough that re-fetching a
  whole symbol on resume is costly.
- **Hygiene (corp-actions/survivorship/bad-tick/gaps/liquidity) → P1.5** runs over what
  this backfill lands in the raw archive.
- ⚠️ Operator live-run prerequisites (none needed to build/test): paid Kite plan,
  `QUANT_SECRET_KITE_API_KEY`/`_SECRET`, today's `--request-token` (daily manual seed),
  static IP not required for data endpoints. Tune `backfill_chunk_days` down if a coarser
  interval hits its own Kite cap.

**Next subtask: P1.5 — Data hygiene jobs.**

### 2026-06-20 — P1.5 Data hygiene jobs ☑

**Goal:** the idempotent, tested, logged hygiene jobs that decide whether anything
downstream is real — `data/hygiene/`: corporate actions, survivorship, bad ticks,
gaps, liquidity/ESM-T2T.

**Reference (Ground Rule 9):** Deep Dive #1 §1.3 (the six hygiene jobs): §1.3.2
corp-action adjustment ("store both raw and adjusted … a 1:5 split misread as a -80%
return will poison a model"), §1.3.3 point-in-time constituents ("include
delisted/merged/renamed"), §1.3.4 bad-tick filtering ("log every correction, never
silently mutate" + a filter using future info is itself lookahead), §1.3.5 gap
detection, §1.3.6 liquidity screen; Inviolable Rule 6 (exclude ESM/T2T).

**Delivered (`src/quant/data/hygiene/`):**
- `corporate_actions.py` — `CorporateAction` (split/bonus by `ratio`, dividend by
  `amount`) + `CorporateActionAdjuster.adjust`: pure back-adjustment of bars *strictly
  before* each ex-date by compounded price/volume factors (split/bonus: price ×1/ratio,
  volume ×ratio; dividend: price ×(C−amt)/C off the raw reference close, volume
  unchanged). Raw is never mutated (it stays the immutable archive); the adjusted frame
  is the derived output. Fails loud on bad ratio/amount and a dividend ≥ reference close.
- `survivorship.py` — `Membership` + `ConstituentRegistry` (`constituents_asof`,
  `is_member`, `all_symbols` — the survivorship-correct universe that *includes*
  since-delisted names). `from_records` accepts date objects or ISO strings.
- `bad_ticks.py` — `BadTickFilter.filter` → `BadTickResult` (clean frame + a
  `TickCorrection` per removed bar, each logged WARNING). Checks: non-positive price,
  negative volume, OHLC inconsistency, and a **point-in-time** spike test vs the
  *previous valid* close (config `hygiene.bad_tick_max_move_pct`). Idempotent
  (re-filtering clean data removes nothing).
- `gaps.py` — `GapDetector` (calendar-aware): intraday spacing gaps within a trading
  day + missing trading days in the data span; overnight/weekend/holiday closures are
  never flagged. Convention-agnostic (checks spacing, not a fixed grid).
- `liquidity.py` — `LiquidityScreen` over `UniverseEligibility` (min ADV, max spread,
  ESM/T2T toggle) → eligible + reasoned `Rejection`s; `average_daily_value(bars)`
  computes ADV (Σ close×volume per day, averaged).
- `core/config.py` + `config/default.yaml` — `HygieneConfig.bad_tick_max_move_pct`
  (20%, the widest circuit band; config not a literal — Ground Rule 2).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (102 files), pre-commit
(12 hooks); **357 tests pass (50 new)**; **100% coverage** on all seven new
`data/hygiene` modules (path-based `--cov=src/quant/data/hygiene` on Windows).

**Decisions**
- **Jobs are pure transforms/queries over the canonical bars schema**, depending only on
  `core` (calendar, config) + `store.serde` — no broker SDK, no concrete store — so they
  run identically in research and live (the deep dive's Module-1 output contract). Each
  is idempotent in the sense that matters: a pure function of its inputs.
- **Raw stays immutable; adjusted is derived.** The corp-action job returns adjusted
  bars (for returns/features); raw (for fills) is the P1.4 Parquet archive, untouched —
  matching "store both raw and adjusted." Materializing the adjusted series to a store is
  pipeline orchestration (P1.6+), not this job.
- **Bad-tick decisions are point-in-time only** (spike vs *previous valid* close, never a
  future bar) — a filter that peeked forward would itself be lookahead (§1.3.4).
- **Spread is depth-derived, passed in.** Bars carry no spread; `LiquidityMetrics` takes
  `median_spread_bps` (from the 5-level book, a later pass), keeping the screen pure.
  ADV is computed from bars now.

**Follow-ups / notes (deferred, tracked)**
- **Operator reference data** (like the holiday calendar): point-in-time index
  constituents and the live ESM/T2T list. The registries/screen are DI-first with
  `from_records`; YAML loaders (mirroring `load_nse_calendar`) are trivial to add when
  the operator supplies the data.
- **Median spread** comes from depth snapshots — computed in the microstructure feature
  pass (**P1.7**) and fed to the liquidity screen there.
- Session pre-open/close *bar tagging* (§1.3.1) is deferred to the time-of-day features
  (**P1.7**); the calendar (P0.4) already classifies session phases.

**Next subtask: P1.6 — Feature library: core families + dual-path harness.**

### 2026-06-20 — P1.6 Feature library: core families + dual-path harness ☑

**Goal:** point-in-time pure feature functions (returns, vol, VWAP-deviation) + the
backtest/live dual-path harness — `data/features/`.

**Reference (Ground Rule 9):** Deep Dive #1 §2.1 (point-in-time correctness: features are
`f(history≤t)`, normalization trailing-only), §2.2.A/B/C (the core families: price/return
transforms, volatility, VWAP-to-mid deviation), §2.4 (the feature store — "compute once,
serve identically"; one library, two callers; the skew tripwire: vectorized == incremental;
output contract `compute_features(symbol, asof) → versioned vector`).

**Delivered (`src/quant/data/features/`):**
- `returns.py` — `log_return(bars, horizon)` (causal, `shift`-based; NaN warmup).
- `volatility.py` — `realized_volatility` (rolling std of 1-bar log returns), `atr`
  (Wilder true range, SMA), `parkinson_volatility` (high-low range estimator).
- `vwap.py` — `intraday_vwap` (cumulative **within each IST session**, resets daily;
  divide-by-zero → NaN) + `vwap_deviation = (close-vwap)/vwap`.
- `harness.py` — `compute_feature_frame(bars, config)` (vectorized/backtest, indexed by
  timestamp) + `compute_features_asof(bars, asof, config)` (incremental/live, via history
  truncation through the *same* code path) + `feature_names(config)` (kept in lock-step
  with the frame columns). `errors.py` — `FeatureError`.
- `core/config.py` + `config/default.yaml` — `FeaturesConfig` (return_horizons,
  vol/atr/parkinson windows, `feature_set_version`); horizons/windows are config, not
  literals (Ground Rule 2). `pyproject.toml` — `numpy` promoted to a direct dep (used for
  the vectorised feature math; already present transitively, lock unchanged at 2.4.6).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (111 files), pre-commit
(12 hooks), `uv lock --check`; **384 tests pass (27 new)**; **100% coverage** on all six
new `data/features` modules.

**Decisions**
- **Skew is eliminated structurally, not just tested.** Every feature is a *causal* pure
  transform (trailing `shift`/`rolling`/intraday-`cumsum` only), and the incremental path
  is literally "truncate history to ≤ asof, run the vectorized path, take the last row".
  So `compute_features_asof(bars, t) == compute_feature_frame(bars).loc[t]` holds by
  construction; the headline test asserts it bar-by-bar, and a prefix-invariance test
  asserts no future bar changes a past feature (point-in-time). The full CI leakage/skew
  suite is **P1.8**; this subtask ships the core tripwire.
- **Features assume hygiene-clean, corp-action *adjusted* bars** (§1.3.2: adjusted for
  returns/features, raw for fills). The harness does not adjust — that is P1.5's job.
- **Intraday VWAP groups by IST date, no calendar dependency** (one IST date = one
  intraday session); cumulative-within-day is causal.
- **Harness operates on bars frames (one symbol), not a Repository.** The `(symbol, asof)`
  contract is satisfied at the pipeline layer (read `repo.read_bars(symbol, …, asof)` then
  call `compute_features_asof`); keeping the harness bars-based keeps it pure and testable.

**Follow-ups / notes (deferred, tracked)**
- **Remaining feature families → P1.7**: microstructure/OFI (5-depth), spread, depth
  imbalance, signed trade flow, TA-Lib technicals, cyclical time-of-day, cross-sectional
  ranks, regime. Robust scaling/winsorization (§2.3) lands with them.
- **Leakage & skew CI suite → P1.8** (forward-shift invariance, trailing-only
  normalization, no-future-correlation) — generalises this subtask's skew test and must
  fail on an intentionally leaky feature.
- **Feature materialization/versioning** (ArcticDB symbol per feature-set version, §2.4):
  `feature_set_version` + `feature_names` are in place; persisting the frames is pipeline
  orchestration (later).

**Next subtask: P1.7 — Feature library: microstructure + technical + cross-sectional + regime.**

### 2026-06-20 — P1.7 Feature library: microstructure + technical + x-sec + regime ☑

**Goal:** the remaining feature families — `data/features/` microstructure, TA-Lib
technicals, cyclical time-of-day, cross-sectional (sector-neutral), regime, plus the
§2.3 normalization/winsorization utilities.

**Reference (Ground Rule 9):** Deep Dive #1 §2.2.A (microstructure/OFI — "the single most
informative family"; OFI/spread/depth-imbalance/signed-flow from 5-depth + trades),
§2.2.D (technicals via **TA-Lib**, "never hand-rolled"), §2.2.E (cyclical time-of-day),
§2.2.F (cross-sectional sector-neutral ranks), §2.2.G (regime), §2.3 (trailing/robust
normalization + winsorization). Inviolable Rule 6 informs the ESM/T2T-aware universe (P1.5).

**Delivered (`src/quant/data/features/`):**
- `microstructure.py` — depth/trade frames (`depth_to_frame`/`trades_to_frame`) + `bid_ask_spread`,
  `relative_spread`, `depth_imbalance` (5-level), `order_flow_imbalance` (Cont-Kukanov-Stoikov,
  multi-level), `signed_volume` (Lee-Ready tick rule). Operate on the order book / trade tape.
- `technical.py` — TA-Lib wrappers `rsi`, `macd_histogram`, `bollinger_percent_b` (typed
  Series; `talib` confined here).
- `temporal.py` — `time_of_day_features`: cyclical sin/cos of minute-of-day & day-of-week +
  within-session `time_since_open`/`time_to_close` (from NSE session bounds).
- `cross_sectional.py` — `cross_sectional_rank` (centred percentile) + `sector_neutral_zscore`
  (standardize within sector, per timestamp; fails loud on an unmapped symbol).
- `regime.py` — `volatility_regime` (vol vs trailing median) + `trend_strength` (close-vs-mean z).
- `normalize.py` — `winsorize` (trailing rolling quantile clip), `rolling_zscore`,
  `robust_zscore` (median/IQR), all trailing-window only.
- `core/config.py` + `config/default.yaml` — `FeaturesConfig` gains technical/regime/winsor
  params (config, not literals — Ground Rule 2). `pyproject.toml` — `ta-lib>=0.6.8` (core dep;
  prebuilt wheels incl. `manylinux_2_28_x86_64`, so CI's frozen sync needs no C toolchain) +
  `talib` mypy override.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (123 files), pre-commit
(12 hooks), `uv lock --check`; **429 tests pass (45 new)**; **100% coverage** on all
`data/features` modules (path-based `--cov=src/quant/data/features` on Windows).

**Decisions**
- **TA-Lib is usable in CI.** It mandates the C library, but `ta-lib` 0.6.8 ships prebuilt
  wheels (incl. manylinux), so `uv sync --frozen` on ubuntu installs a binary — no compile.
  Verified the lock carries the linux wheel before declaring it. "Never hand-rolled" honoured.
- **Microstructure operates on the book/tape, not bars.** OFI/spread/imbalance use a depth
  frame (5 levels, missing levels → NaN price/0 qty); signed flow uses a trades frame. These
  are causal (per-snapshot, or current-vs-previous for OFI/tick-rule). Aggregating them to the
  bar clock and joining into the model matrix is pipeline integration (later).
- **Cross-sectional uses contemporaneous (time-t) data across names** — not lookahead; it is
  the cross-sectional normalizer (§2.3). Sector-neutral z-score removes market/sector moves.
- **Families stay standalone functions** (different inputs: bars / book / tape / panel); the
  P1.6 `compute_feature_frame` skew harness is unchanged. Each new family is independently
  causal/point-in-time (prefix-invariance tested where bar-based).
- **`feature_set_version` stays `core-v1`** (the harness output is unchanged; the new families
  are additive functions). Bump it when they are wired into the materialized feature matrix.

**Follow-ups / notes (deferred, tracked)**
- **Leakage & skew CI suite → P1.8**: generalize the P1.6 skew test across all families and
  fail on an intentionally leaky feature (forward-shift invariance, trailing-only norm,
  no-future-correlation).
- **Feature-matrix assembly/materialization**: aggregate microstructure to the bar clock, join
  cross-sectional across the universe, version per `feature_set_version` (pipeline, later).
- **Median spread for the P1.5 liquidity screen** now has a source: `relative_spread` over the
  book (wire in the universe-refresh pass).

**Next subtask: P1.8 — Leakage & skew test suite (CI).**

### 2026-06-20 — P1.8 Leakage & skew test suite (CI) ☑

**Goal:** structural anti-leakage guarantees in CI — `tests/adversarial/`: forward-shift
invariance, trailing-only normalization, no-suspicious-future-correlation, train/serve skew;
the suite must **fail on an intentionally leaky feature**.

**Reference (Ground Rule 9):** Deep Dive #1 §2.4 (leakage tests in CI: "(a) shift inputs
forward and assert features don't change retroactively, (b) no feature correlates suspiciously
with the future label, (c) normalization uses only trailing data") + the dual-path skew
tripwire; Part I Rule 2 (point-in-time correctness; leakage tests run in CI).

**Delivered (`tests/adversarial/`):**
- `leakage.py` — the reusable assertion API (raises `AssertionError` on a leak):
  `assert_no_lookahead` (prefix == full's prefix), `assert_skew_free` (incremental ==
  vectorized per bar), `assert_trailing_only` (perturbing the last value leaves earlier
  outputs unchanged), `assert_no_future_correlation` / `max_abs_future_correlation`.
- `sample_data.py` — seeded bars / 5-level depth book / trade tape / cross-sectional panel +
  `forward_return` label. `leaky_features.py` — the known-bad inputs (`lookahead_return`
  shift(-1), `centered_volatility` centred window, `full_sample_zscore`).
- `test_no_lookahead.py` — forward-shift invariance across **every** family (returns, vol,
  VWAP, RSI/MACD/Bollinger, regime, time-of-day, the assembled `compute_feature_frame`,
  microstructure spread/imbalance/OFI, signed flow, cross-sectional rank/z-score) +
  tripwires (lookahead & centred-window caught).
- `test_train_serve_skew.py` — harness `compute_feature_frame` == `compute_features_asof`
  for every bar + a full-sample-feature skew tripwire.
- `test_trailing_normalization.py` — `rolling_zscore`/`robust_zscore`/`winsorize` are
  trailing-only + a full-sample-zscore tripwire.
- `test_future_correlation.py` — real features have |corr| with the forward return well
  below 0.99 + a tripwire on a feature that *is* the forward return (|corr| == 1).
- All modules marked `pytest.mark.adversarial` (registered marker; selectable with
  `-m adversarial`), and run in the default CI `uv run pytest`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (130 files), pre-commit
(12 hooks); **467 tests pass (38 new)**; `-m adversarial` selects exactly the 38 leakage
tests. No new `src/quant` modules — the suite is the deliverable and exercises the existing
feature library.

**Decisions**
- **The checks are reusable assertions, applied two ways**: (a) over the *real* feature
  library so CI fails if any feature becomes leaky, and (b) wrapped in `pytest.raises` over
  *deliberately-leaky* features so the tripwire itself is proven to fire — satisfying
  "fails on an intentionally leaky feature" while keeping CI green.
- **Forward-shift invariance is the unifying primitive.** "Trailing-only normalization" is
  just forward-shift invariance applied to the normalizers; "skew-free" is the same property
  read as vectorized==incremental. Each named check is a distinct, documented entry point.
- **Future-correlation threshold is high (0.99)** — it flags mechanical lookahead (a feature
  that contains the future → |corr| ~ 1), not genuine edge; verified across families on a
  200-bar seeded fixture.

**Follow-ups / notes**
- New features added later should be registered in `test_no_lookahead.py` /
  `test_future_correlation.py` so the guarantees extend automatically.

**Next subtask: P1.9 — Data-quality dashboard** (last before Gate 1).

### 2026-06-20 — P1.9 Data-quality dashboard ☑ (completes Gate 1)

**Goal:** visibility into data health — `data/quality/`: gaps, bad-tick counts, coverage,
feed-latency report/dashboard.

**Reference (Ground Rule 9):** Deep Dive #1 ("a data-quality dashboard — gaps, bad-tick
counts, feed latency, coverage") + the Module-1 output contract (a clean, point-in-time
dataset retrievable on demand); composes the P1.5 hygiene jobs.

**Delivered (`src/quant/data/quality/`):**
- `report.py` — immutable carriers: `CoverageStats` (session-level: observed vs expected
  trading days), `SymbolQuality` (coverage + gap/bad-tick counts; `has_issues`),
  `FeedLatencyStats`, `DataQualityReport` (aggregates + `render()` text dashboard).
- `dashboard.py` — `DataQualityDashboard.assess(bars_by_symbol, start, end, latency_samples)`
  composes session coverage (NSE calendar) + `GapDetector` + `BadTickFilter` (P1.5) per
  symbol; `summarize_feed_latency` (mean/p50/p95/max, seconds); `create_data_quality_dashboard`
  factory (interval + bad-tick threshold from config — Ground Rule 2). Naive bounds /
  start>end fail loud.
- No new config/deps (composes existing hygiene jobs; numpy for percentiles).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (134 files), pre-commit
(12 hooks); **481 tests pass (14 new)**; **100% coverage** on all three new modules.

**Decisions**
- **Two complementary lenses:** *coverage* is session-level (trading days present vs the
  calendar's expected days over the requested window — catches edge/whole-day gaps);
  *gaps* (P1.5 GapDetector) are bar-level holes within the observed span. Together they give
  the full "how much do we have / where are the holes" picture without a brittle
  bars-per-session convention.
- **Composes, doesn't duplicate:** the dashboard reuses the P1.5 `GapDetector`/`BadTickFilter`
  (injected; config-driven) over the raw bars, so it reports the same definitions the
  pipeline enforces. Feed-latency samples come from the live stream (P1.2); the dashboard
  only summarizes them.
- **Library + text render, not a web UI.** The live trading dashboard is P5.3; this is the
  Layer-1 *data*-quality report (consumed by the daily lifecycle / monitoring later).

**Follow-ups / notes**
- Wiring the dashboard into a scheduled post-backfill / daily-close job (and recording
  per-tick feed latency in the P1.2 consumer) is ops orchestration (Phase 5).

---

## GATE 1 — Data & Feature Layer: ✅ PASSED (2026-06-20)

All Phase-1 subtasks (P1.1–P1.9) complete and merged. The layer can **reproduce a
point-in-time, corporate-action-adjusted, survivorship-correct, leakage-tested dataset and
feature set on demand**:
- **Dataset:** `KiteAdapter` market data (P1.1) → live stream (P1.2) → tiered `Repository`
  storage (P1.3) → paginated/resumable backfill (P1.4) → hygiene: corp-action adjustment,
  point-in-time survivorship, bad-tick filtering, gap detection, liquidity/ESM-T2T (P1.5).
- **Features:** causal core families + dual-path harness (P1.6) and the extended families —
  microstructure/OFI, TA-Lib technicals, time-of-day, cross-sectional, regime + §2.3
  normalization (P1.7).
- **Leakage-tested:** the adversarial CI suite (P1.8) enforces forward-shift invariance,
  trailing-only normalization, no-future-correlation, and train/serve skew, and fails on an
  intentionally leaky feature.
- **Visibility:** the data-quality dashboard (P1.9).

481 tests, all gates green. Tagged **`gate-1-data`**.

**Next: Phase 2 — Research Layer** (P2.1 — validation harness core: purged CV + cost
backtester; "build the validation engine before the models").

---

## Phase 2 — Research Layer

### 2026-06-21 — P2.1 Validation harness core (purged CV + cost backtester) ☑

**Goal:** *the judge before any contestant* — a purged k-fold + embargo splitter and a
realistic, next-bar-open backtester with the full Indian cost model and size/depth-aware
slippage. (CPCV/DSR/PBO are P2.2; labels are P2.3 — this subtask builds only the
splitter + backtest core, per the deliverable.)

**Reference (Ground Rule 9):** Deep Dive #2 §4b.1 (purging — "remove from training any
observation whose label window overlaps the test set's span"; embargo — forward-only
buffer ≈ label horizon; "without these every number is optimistic fiction"; technique
from AFML ch. 7), §4b.6 (the realistic backtester: **next-bar-open** fills, the itemised
Indian MIS cost model with the per-order ₹20 brokerage cap / sell-side STT / buy-side
stamp / 18% GST on brokerage+exchange+SEBI, size-vs-depth slippage 0.05–0.20%, latency).
Inviolable Rules 2 (point-in-time; next-bar-open identical in research and live) and 4
(costs always modelled). Build order (§"What I'd build"): purged-CV + cost model **first**.

**Delivered (`src/quant/research/validation/`):**
- `splits.py` — `PurgedKFold(n_splits, embargo_pct).split(label_times) → Fold(train, test)`.
  Contiguous time-blocks as test sets; training purged of any observation whose label
  window `[t0, t1]` overlaps the block's span, plus a forward embargo. **Strict**
  non-overlap (drops the boundary instant AFML's `<=` keeps). `embargo_size` exposed +
  tested. Fails loud on unsorted/naive/duplicate index, non-datetime values, `t1 < t0`,
  too-few observations.
- `costs.py` — `IndianCostModel.cost_for_fill(side, price, qty) → CostBreakdown` (itemised:
  brokerage `min(rate·turnover, cap)`, STT sell-side, exchange per-side, SEBI, stamp
  buy-side, GST on brokerage+exchange+SEBI). Pure; every rate from `CostConfig`.
- `slippage.py` — `DepthAwareSlippage`: participation = `qty / available_liquidity`
  (clamped), slippage interpolates `min_bps → max_bps`; no-liquidity → ceiling
  (conservative). `adjusted_fill_price` moves a buy up / sell down. The backtest passes the
  fill bar's **volume** as the liquidity proxy in the bars-only path (true 5-depth
  substitutes later).
- `backtest.py` — `Backtester(cost_model, slippage_model, *, initial_capital,
  execution_delay_bars).run(bars, target_positions) → BacktestResult` (fills, MtM equity
  curve, per-bar returns, net aggregates). Event-driven loop: a target decided on bar *t*'s
  close fills at bar *t+delay*'s **open**; no fill bridges a session; **square-off at each
  session's last-bar open** (no overnight MIS carry; lines up with self-square-off ~15:15).
  `create_backtester(config)` wires the real models. Handles long/short uniformly.
- `core/config.py` + `config/default.yaml` — new `BacktestConfig` (`initial_capital_inr`,
  `execution_delay_bars` = next-bar-open default), config not literals (Ground Rule 2).
  Corrected the `costs.gst_rate` comment to include SEBI charges (matches §4b.6 and the code).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (144 files), pre-commit
(12 hooks); **553 tests pass (72 new)**; **100% coverage** on all five new
`research/validation` modules. Hand-computed cases throughout: cost breakdowns vs the NSE
schedule (cap on both sides of the `min`), slippage participation curve, P&L =
`qty·(exit_open − entry_open)` for long & short, costs/slippage reducing net P&L by exactly
the modelled amount, latency shifting the fill bar, and the **purge no-overlap invariant**
asserted directly on overlapping label windows.

**Decisions**
- **P2.1 is the splitter + backtest core only.** CPCV path-reconstruction, DSR, PBO
  (§4b.2–4) are P2.2 and consume this backtester's `returns`; the empty
  `research/validation/__init__` docstring already scoped them there. Walk-forward (§4b.5)
  also builds on these primitives in P2.2. Kept this subtask to its deliverable.
- **Strict purge over AFML's `<=` boundary.** A label resolving at the exact instant the
  test block begins/ends is dropped, not kept — a hair more conservative, zero leakage.
  The reusable per-block keep-logic is the primitive CPCV will reuse for arbitrary test
  groups (P2.2).
- **Square-off at the last bar's *open*, uniformly.** Every fill — entries and the forced
  end-of-session flatten — happens at a bar open, so there is one execution rule and no
  open/close asymmetry. Flattening at the final 15-min bar's open ≈ 15:15 = the configured
  self-square-off. No position is ever carried overnight (asserted).
- **Bar volume as the liquidity proxy.** Bars carry no order book, so the size/depth-aware
  slippage uses the fill bar's volume as available liquidity — data we have, conservative
  for large orders, and swappable for true 5-depth on the live/feature path.
- **Within-layer concrete models, injected (DI).** Cost/slippage are concrete classes
  injected into the backtester (tests pass zero/flat-config instances to isolate
  mechanics); a Protocol is deferred until a second slippage model (volatility/time-of-day
  widening) actually appears (YAGNI; Ground Rule 1 reserves interfaces for real swaps).

**Follow-ups / notes (deferred, tracked)**
- **CPCV + DSR + PBO + walk-forward → P2.2** reconstruct paths over `PurgedKFold`'s blocks
  and compute path-Sharpe from `BacktestResult.returns`.
- **Triple-barrier labels → P2.3** produce the `label_times` (`t0 → t1`) the splitter
  consumes and the `target_positions` the backtester executes; today's tests synthesise both.
- **Volatility/time-of-day slippage widening** (§4b.6 "wider near the open / in volatile
  windows") multiplies the participation base once the vol input is wired — `slippage_bps`
  is shaped to extend.
- **Multi-asset / portfolio backtests** compose per-symbol single-symbol runs; the core is
  single-symbol by design (fails loud on multi-symbol bars).
- ⚠️ Cost rates are the documented defaults — *"pull exact numbers from a current brokerage
  calculator; these change"* (§4b.6). They live in `config.costs` for exactly that reason.

**Next subtask: P2.2 — CPCV + DSR + PBO.**

### 2026-06-21 — P2.2 CPCV + DSR + PBO ☑

**Goal:** the "is the edge real?" toolkit — Combinatorial Purged CV with path
reconstruction, the Deflated Sharpe Ratio, and the Probability of Backtest Overfitting,
plus honest trial-count tracking. Builds on P2.1's purged-CV + backtester.

**Reference (Ground Rule 9):** Deep Dive #2 §4b.2 (CPCV: N groups, k test → C(N,k)
splits → **φ = C(N,k)·k/N = C(N-1,k-1)** complete paths; judge the *distribution* of
path-Sharpes — narrow & positive = robust, wild variance = fragile), §4b.3 (Deflated
Sharpe: corrects an observed Sharpe for trial count, skew, kurtosis, sample length;
"honestly track your trial count"), §4b.4 (PBO via CSCV: probability the IS-best config
underperforms the OOS median; "> ~0.2-0.5 is a serious warning"; t-stat hurdle ~3.0).
Methodology from López de Prado *Advances in Financial ML* ch. 7-8 and Bailey-López de
Prado (DSR/PSR) / Bailey-Borwein-LdP-Zhu (PBO/CSCV).

**Delivered (`src/quant/research/validation/`):**
- `cpcv.py` — `CombinatorialPurgedCV(n_groups, n_test_groups, embargo_pct)`:
  `num_splits`=C(N,k), `num_paths`=C(N-1,k-1); `split()` yields `CombinatorialSplit`
  (purged+embargoed train, k-group test); `reconstruct_paths()` tiles per-split OOS
  returns into φ full-timeline paths (each group drawn from a distinct split);
  `path_distribution()` → `PathDistribution` (median / minimum / std / fraction_negative —
  the kill-gate read surface); `run(label_times, backtest_fn)` does split→backtest→paths
  end-to-end.
- `metrics.py` — `sharpe_ratio` (per-obs or annualised), `return_moments`,
  `probabilistic_sharpe_ratio`, `expected_maximum_sharpe_ratio` (the DSR deflation
  benchmark), `deflated_sharpe_ratio` (+ `_from_returns`). Uses stdlib
  `statistics.NormalDist` for the normal CDF/quantile — **no SciPy dependency added**.
- `pbo.py` — `probability_of_backtest_overfitting(performance, n_partitions)`: the full
  CSCV algorithm over C(S, S/2) IS/OOS partitions → `PBOResult` (pbo + per-combination
  logits).
- `trials.py` — `TrialTracker`: de-duplicated-by-name trial log providing the DSR's
  `count` (N) and `sharpe_variance` (V), in per-observation Sharpe units.
- `splits.py` (refactor) — extracted `purged_train_mask(starts, ends, test_mask, embargo)`
  + `_contiguous_runs`; `PurgedKFold` now composes it, and CPCV reuses it for test sets
  that span several (possibly non-adjacent) groups. `_validate_label_times` shared too.
- `errors.py` — `MetricError`, `PBOError` (CPCV reuses `SplitError`).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (152 files), pre-commit
(12 hooks); **614 tests pass (61 new)**; **100% coverage** on every `research/validation`
module (whole package). DSR/PSR/expected-max checked against an **independent assembly of
the reference formulas** via `NormalDist`; CPCV path counts verified for five (N,k) plus
the φ=C(N-1,k-1) identity across all valid (N,k); path reconstruction proven to **tile the
timeline once** (marker==position) and **draw each group from a distinct split**
(marker==split-index); PBO behaviourally validated (dominant strategy → ≈0, pure noise →
≈0.5, engineered overfit → high) plus structural/fail-loud checks.

**Decisions**
- **stdlib `NormalDist`, not SciPy.** PSR/DSR need only the normal CDF and quantile, both
  on `statistics.NormalDist` (Py 3.8+, ~1e-14 accurate). Avoids adding SciPy to the engine
  env (Part II environment policy: keep runtime deps lean) while honouring "understand the
  math, don't black-box it" (§4b.8).
- **Path reconstruction is decoupled from the backtest.** CPCV gives the splits + the
  path-assignment grid; the caller supplies per-split OOS returns (its P2.1 `Backtester`
  output). This keeps P2.2 the pure *math* (testable with synthetic returns) and lets P2.6
  / P2.9 wire the real model+backtester through `run()`.
- **DSR uses per-observation (non-annualised) Sharpes.** The formula's √(T-1) carries the
  sample-length scaling, so the observed Sharpe and the trial variance V must share those
  units — `TrialTracker.record_returns` defaults to non-annualised for exactly that
  consistency. Annualised Sharpes are for the CPCV path distribution / kill-gate threshold.
- **Refactor over duplicate.** Rather than reimplement purge+embargo for CPCV's multi-group
  test sets, extracted the P2.1 logic into `purged_train_mask` (composes per contiguous
  run, AND across runs) — one audited no-overlap primitive, used by both splitters
  (Ground Rule 4). PurgedKFold's existing tests still pass unchanged.
- **PBO uses Sharpe as the CSCV metric** (the BBLZ default), relative rank with ties
  averaged so the logit is always finite; `PBO = mean(logit <= 0)` (matches the mlfinlab
  reference convention, counting the exact-median boundary as overfit).

**Follow-ups / notes (deferred, tracked)**
- **Triple-barrier labels → P2.3** produce the real `label_times` (t0→t1) these splitters
  consume; today's tests synthesise them.
- **Kill-gate emitter → P2.9** reads `PathDistribution.median`/`minimum`/`fraction_negative`
  (criteria 1 & 4), the DSR (criterion 2), and PBO (criterion 3) into the seven-point
  pass/fail verdict.
- **MLflow trial logging → P2.6** replaces/augments the in-memory `TrialTracker` for the
  honest, persisted trial count (§4b.8); the interface (count + variance) stays the same.
- **Annualisation factor** for intraday path-Sharpes (periods-per-year for a 15-min,
  intraday-only clock) is a kill-gate calibration detail for P2.9; `sharpe_ratio` /
  `path_distribution` already take `periods_per_year`.

**Next subtask: P2.3 — Labeling: CUSUM + triple-barrier.**

### 2026-06-21 — P2.3 Labeling: CUSUM + triple-barrier ☑

**Goal:** honest, event-sampled, volatility-scaled labels — a CUSUM event sampler and a
triple-barrier labeler whose `label_times` (event `t0` → resolution `t1`) feed the P2.1/P2.2
purged-CV / CPCV splitters and whose `label` is the primary side. (Meta-labeling is P2.5,
sample weighting P2.4, frac-diff P2.5 — this subtask is the primary label only.)

**Reference (Ground Rule 9):** Deep Dive #2 §3.2 (triple-barrier: label by the first of
three barriers touched — path-dependence is the point; **vol-scaled** `k_up·σ` / `k_dn·σ`
with asymmetric multiples; the profit-take must **clear the cost hurdle** so a +1 is a
tradeable win; **vertical barrier = session end** since MIS auto-squares-off), §3.3 (CUSUM
event sampling — "sample when something is happening", removes dead bars, more balanced
labels). Methodology from López de Prado *Advances in Financial ML* ch. 2-3.

**Delivered (`src/quant/research/labeling/`):**
- `cusum.py` — `cusum_events(prices, threshold)`: the symmetric CUSUM filter (AFML
  §2.5.2.1) over per-bar log returns; two zero-floored accumulators, an event + reset when
  either reaches `h`; scalar **or** per-bar Series threshold (dynamic/vol-scaled). Single
  causal pass; returns the event `DatetimeIndex`.
- `triple_barrier.py` — `TripleBarrierLabeler(config).label(bars, events, volatility) →
  LabelSet`. Reference = event-bar close; barriers `max(k·σ, min_return)` (cost-hurdle
  floor); forward path scanned via **high/low first-touch** (honest intrabar stops); a
  same-bar breach of *both* resolves to the **stop** (conservative — order unknown);
  vertical barrier = **IST session end** (no overnight), optionally capped by
  `max_hold_bars`, labeled by the sign of the return. `LabelSet.label_times` (t0→t1) and
  `.sides` (+1/-1/0) are the typed accessors for downstream.
- `errors.py` — `LabelingError` / `LabelingInputError`.
- `core/config.py` + `config/default.yaml` — `LabelingConfig` (cusum_threshold,
  barrier_upper/lower_multiple, barrier_min_return, vertical_max_hold_bars); config not
  literals (Ground Rule 2), seeded +2σ/-1.5σ, 0.2% floor, session-end vertical.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (157 files), pre-commit
(12 hooks); **652 tests pass (38 new)**; **100% coverage** on all new `research/labeling`
modules. Outcomes hand-computed on synthetic OHLC paths (upper/lower at the exact barrier
return; vertical by sign; same-bar tie → stop; first-touch ordering; vol scaling; the
0.2% floor; session-end vertical never carries into the next day; max-hold cap; warm-up /
last-bar skips). `LabelSet.label_times` is fed through `PurgedKFold` (the contract proof).

**Decisions**
- **Barriers from the event bar's close; volatility injected.** The reference is `close[t0]`
  (the decision price) and the barrier *widths* use only `σ` at `t0` (point-in-time — no
  future data leaks into the barrier). `σ` is an injected return-unit trailing volatility
  (e.g. `realized_volatility`), reusing the leakage-tested feature rather than recomputing.
  The label's *resolution* legitimately reads the future path — the leakage rule constrains
  features, not a label's own outcome.
- **High/low first-touch, conservative same-bar tie.** Stops are honest (a bar's low
  breaching the stop is a stop, even if it later recovers). When one bar gaps through both
  barriers the intrabar order is unknown, so the **stop wins** — this slightly under-counts
  +1, the safe direction (we'd rather underestimate edge). Documented.
- **Vertical = IST session end, by sign.** One IST date = one session (same convention as
  the VWAP feature and the P2.1 backtester), so a position never carries overnight; the
  vertical label is the sign of the close-to-close return (§3.2's "sign of the return at
  expiry"). The cost-hurdle/no-bet decision is the meta-model's job (P2.5); here the
  *barrier widths* already encode the cost floor.
- **Labels ≠ backtest P&L (separation of concerns).** The labeler answers "does an up- or
  down-move materialise from this decision price?"; the P2.1 backtester (next-bar-open +
  costs + slippage) measures tradeable P&L. They share the session/no-overnight rule but
  not the exact entry price, by design.
- **DataFrame-centric `LabelSet`.** Matches the codebase's result-object style
  (BacktestResult/GapReport); `label_times`/`sides` are tz-aware and drop straight into the
  splitter contract (`_validate_label_times` accepts them — verified).

**Follow-ups / notes (deferred, tracked)**
- **Sample weighting → P2.4** (concurrency/uniqueness, time-decay, return-attribution)
  consumes `LabelSet.label_times` (overlap) and `ret` (attribution).
- **Meta-labeling → P2.5** uses a primary side (a simple rule or model) + these barriers to
  generate bet/no-bet labels; frac-diff features land there too.
- **CUSUM dynamic threshold** can be wired to a trailing-vol Series (the `threshold: Series`
  path exists); the default is the configured scalar.
- **σ source**: callers pass `realized_volatility(bars, features.volatility_window)`
  re-indexed by timestamp; the labeler stays vol-source-agnostic (ATR/EWMA also fit, in
  return units).

**Next subtask: P2.4 — Sample weighting.**

### 2026-06-21 — P2.4 Sample weighting ☑

**Goal:** correct for non-IID labels — overlapping triple-barrier windows share returns, so
two "samples" can be largely the same information; train naively and the model overfits.
Builds on P2.3's `LabelSet.label_times`.

**Reference (Ground Rule 9):** Deep Dive #2 §3.5 (the four corrections, all AFML ch. 4):
**concurrency / average uniqueness** (`c_t` active labels per bar; a label's weight = mean
of `1/c_t` over its window — "the single most important correction"), **sequential
bootstrap** (draw by uniqueness so each bag carries more independent info), **time-decay**
(older relationships fade), **return-attribution** (weight by the move's magnitude).

**Delivered (`src/quant/research/labeling/`):**
- `weights.py` — `SampleWeights(bar_times, label_times)`: builds the (bars × labels)
  indicator matrix once, then `concurrency()` (per bar), `average_uniqueness()` (per label,
  the primary weight), `return_attribution(prices, normalize=)` (`|Σ r_t/c_t|`, AFML §4.4),
  and exposes `indicator_matrix` for the bootstrap. `time_decay_weights(uniqueness,
  last_weight)` — piecewise-linear decay over *cumulative uniqueness* (newest = 1, oldest =
  `last_weight`; negative zeroes the oldest fraction).
- `bootstrap.py` — `sequential_bootstrap(indicator_matrix, n_samples, *, rng)`: draws by
  each candidate's average uniqueness *given the running sample* (vectorized matrix-vector
  update per draw), **seeded `np.random.Generator` injected** (Ground Rule 7).
  `average_uniqueness_of_sample` is the AFML diagnostic proving the draw quality.
- `errors.py` — reuses `LabelingInputError`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (161 files), pre-commit
(12 hooks); **688 tests pass (36 new)**; **100% coverage** on the new modules (whole
`research/labeling` package at 100%). Uniqueness hand-computed (overlap → 2/3, nested →
0.5, disjoint → 1.0, isolated → 1.0); concurrency `[1,2,2,1,0,0]`; return-attribution
splits shared bars and normalizes to mean 1; time-decay identities (last_weight 1 → no
decay, 0 → newest 1, negative → oldest 0); the **sequential bootstrap beats uniform on
average uniqueness** over 40 seeds (§4.5.3's promise) and is deterministic per seed.

**Decisions**
- **Indicator-matrix foundation, built once.** Concurrency, uniqueness, return-attribution,
  and the bootstrap all derive from one (bars × labels) `int8` matrix on a `SampleWeights`
  object (like `Backtester` holding its config) — no recomputation, and the matrix is the
  bootstrap's input. Concurrency is counted over the **full bar timeline** (not just event
  bars), so `bar_times` is required alongside `label_times`.
- **Labeling stays independent of validation.** The label-times contract is re-validated
  locally here rather than importing `validation.splits._validate_label_times` — labels are
  *upstream* of cross-validation in the pipeline, so the dependency must not point that way
  (Ground Rule 1). The small duplication is the right trade.
- **Vectorized sequential bootstrap.** Each draw updates a running per-bar concurrency and
  computes every candidate's average uniqueness as a single `mat.T @ (1/(conc+1))` — O(bars
  × labels) per draw, not the naive triple loop. Correct *and* fast enough for research-scale
  event sets (Ground Rule 7).
- **RNG injected, never global.** `sequential_bootstrap` takes a required keyword-only
  seeded `Generator`, so every bag is reproducible (determinism, Ground Rule 7) — no hidden
  global RNG.
- **Return-attribution matches AFML's window** (`[t0, t1]` inclusive, including the entry
  bar's return) for internal consistency with the concurrency it divides by; the
  economically-exact realized return already lives on `LabelSet.ret` if a caller wants it.

**Follow-ups / notes (deferred, tracked)**
- **Meta-labeling + frac-diff → P2.5** (primary side + bet/no-bet; min-`d` via ADF).
- **Model training → P2.6** consumes these as `sample_weight` (uniqueness × time-decay, or
  return-attribution) and the sequential-bootstrap indices for uniqueness-aware bagging.
- **σ / prices sourcing** stays the caller's job (return-attribution takes close prices
  indexed by the bar timeline); the module is data-source-agnostic.

**Next subtask: P2.5 — Meta-labeling + fractional differentiation.**

### 2026-06-21 — P2.5 Meta-labeling + fractional differentiation ☑

**Goal:** the side/size split (meta-labeling) + stationary-but-memory-preserving features
(fractional differentiation). Builds on P2.3 (triple barrier) and P1.7 (features).

**Reference (Ground Rule 9):** Deep Dive #2 §3.4 (meta-labeling: primary → SIDE tuned for
recall; secondary → BET/NO-BET, "the natural home for the cost hurdle"; the primary can be
a simple rule), §3.6 (fractional differentiation: the dimmer switch between raw (d=0,
memory, non-stationary) and returns (d=1, stationary, memoryless); find the **minimum d**
that passes ADF, preserving maximum memory). Methodology from López de Prado *Advances in
Financial ML* ch. 3 (meta-labels) and ch. 5 (frac-diff, fixed-width-window §5.5).

**Delivered:**
- `research/labeling/meta.py` — `momentum_side` / `mean_reversion_side` (simple primary
  rules: sign of the trailing move) + `MetaLabeler(config).label(bars, events, sides,
  volatility) → MetaLabelSet`. **Side-aware** barriers (a long takes profit above / stops
  below; a short mirrors it), labeled **1 = bet won** (profit-take, or profitable at the
  vertical) / **0 = no-bet** (stop, or unprofitable); `ret` is **side-adjusted** (a
  profitable short is positive). Flat sides are skipped. `label_times` / `meta_labels` /
  `sides` accessors.
- `research/labeling/barriers.py` — extracted the shared first-touch scan (with the
  conservative same-bar **stop-wins** tie, parameterized by which side is the stop) plus the
  event-position / volatility-alignment / session-end helpers. **Refactored P2.3's
  `TripleBarrierLabeler` to use it** — one implementation of the correctness-critical
  invariant for both the primary and meta labelers (Ground Rule 4). P2.3 tests unchanged.
- `research/features_research/frac_diff.py` — `frac_diff_weights` (binomial
  `w_k = -w_{k-1}(d-k+1)/k`), `frac_diff` (fixed-width-window, **causal** via `np.convolve`),
  `adf_test` (statsmodels `adfuller` wrapper → `ADFResult.is_stationary`), and `min_ffd`
  (searches the d-grid for the smallest stationary order; skips candidates whose window
  exceeds a short series).
- `pyproject.toml` — added **`statsmodels>=0.14`** (+ scipy, patsy) for the ADF test; mypy
  override for the partial stubs.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (167 files), pre-commit
(12 hooks); `uv lock --check` clean (pandas stays 3.0.3); **728 tests pass (40 new)**;
**100% coverage** on all new modules. Meta labels hand-computed for long & short
profit/stop/vertical (+ the short same-bar conservative stop, exercising the `tie_to_low`
flip); frac-diff weights (d=0 → [1], d=1 → [1,-1]), d=1 == first difference; **min_ffd finds
a fractional d that passes ADF while a random walk's raw series does not, and the
differenced series keeps materially more correlation with the level than returns do** (the
§3.6 memory-retention property).

**Decisions**
- **statsmodels for ADF, not hand-rolled.** Checked first that `statsmodels` resolves with
  the project's pinned **pandas 3.0.3** — it does (adds scipy + patsy, no pandas downgrade),
  so the environment policy (don't force a project-wide pin) is satisfied. Reimplementing a
  unit-root test with correct critical values is exactly the kind of well-tested routine
  Ground Rule 4 says not to reinvent; §4b.8 references statsmodels. (This does *not* reverse
  P2.2's "no SciPy just for a normal CDF" — there stdlib sufficed; ADF genuinely needs it.)
  Import confined to `frac_diff.py`.
- **Refactor over duplicate for the barrier scan.** The conservative same-bar tie is a
  correctness-critical invariant; rather than copy it into the meta labeler, extracted
  `barriers.first_touch` (parameterized by which side is the stop) and pointed both labelers
  at it. P2.3's behavior and tests are unchanged (verified).
- **Meta-labeling is a side-aware triple barrier.** Given the primary's side, the profit-take
  is in the side's direction and the stop against it; a short's barriers mirror a long's, and
  the realized return is side-adjusted. The meta label is the natural bet/no-bet target a
  secondary classifier learns (P2.6), and `label_times` feeds the purged CV/CPCV (verified).
- **Frac-diff is causal (fixed-width window).** The value at *t* uses only `y_{t-k}` (a
  `np.convolve` of the trailing window with the truncated weights), so it is point-in-time
  correct like the Layer-1 features; the first `W` bars are NaN warm-up. `min_ffd` skips a
  small-d candidate whose window is wider than the series (too few points to ADF-test) rather
  than crashing.

**Follow-ups / notes (deferred, tracked)**
- **Model stack → P2.6** trains the LightGBM baseline on the primary-side label *or* the
  meta bet/no-bet label, with the P2.4 sample weights, under purged CV; isotonic calibration
  of the meta-probability for sizing (Deep Dive #3).
- **Frac-diff as a feature** is wired into the feature matrix at materialization (apply
  `min_ffd` to the log-price series; the `d` and threshold become feature-set version params).
- **Primary-rule lookback** is an explicit arg (no hard-coded default); the operator/research
  sweeps it. A model primary (not just a rule) also fits the `sides` contract.

**Next subtask: P2.6 — Model: baseline + tracking + calibration.**

### 2026-06-21 — P2.6 Model: baseline + tracking + calibration ☑

**Goal:** the LightGBM baseline *under proper discipline* — *"do this first, always; if a
clean, cost-aware baseline isn't profitable in honest validation, no deeper model will save
it."* Builds on P2.1 (purged CV) and P2.5 (the meta/primary labels it trains on).

**Reference (Ground Rule 9):** Deep Dive #2 §4.1 Step 1 (LightGBM baseline first), §4.2 (the
four "things people get wrong": **MDA/SHAP not MDI**, **calibration mandatory**, **tuning
under purged CV**, **modest capacity**), §4b.5 (MLflow experiment tracking → honest trial
count). Part II environment policy (optional backends that pin `pandas<3` stay
operator-installed behind an interface — the arcticdb precedent, P1.3). LightGBM native-API
(`Dataset`/`train`/`Booster.predict`) verified at the version resolved (4.6.0).

**Delivered (`src/quant/research/models/`):**
- `baseline.py` — `BaselineTrainer(config).train(...)`: runs `PurgedKFold`, pools the
  **out-of-fold** predictions (every event predicted by a model that never saw it), fits the
  calibrator on those leak-free OOS preds, then trains the deliverable booster on all data.
  `LightGBMBaseline` (booster + calibrator) implements the live `core.interfaces.Model`
  (`predict(features) -> calibrated P(y=1)`), so research and live share one object;
  `BaselineResult` carries OOS preds, fold scores, importances, and the logged metrics. The
  single LightGBM import site (confinement, like kiteconnect/arcticdb).
- `calibration.py` — `fit_isotonic` (weighted **PAVA**) → `IsotonicCalibrator`; monotone by
  construction, interpolates between knots, flat-extrapolates at the ends. Hand-rolled (no
  sklearn), the same lean call as P2.2's stdlib `NormalDist` over SciPy.
- `importance.py` — `permutation_importance` (MDA): shuffle a column on the **held-out** fold,
  measure the score drop; seeded RNG injected; computed within the CV (§4.2).
- `scoring.py` — dependency-free `accuracy`/`log_loss`/`neg_log_loss`/`brier_score`/`roc_auc`
  (rank/Mann-Whitney AUC) under one higher-is-better `Scorer` contract.
- `tracking.py` — `ExperimentTracker` Protocol + `InMemoryExperimentTracker` (default) +
  `MLflowExperimentTracker` (thin translation to MLflow's API) + lazy `create_mlflow_tracker`.
- `tuning.py` — `HyperparameterTuner`: each grid config scored by mean **purged-CV** score,
  every candidate logged as a trial (the honest DSR count); capacity-modest `default_param_grid`.
- `core/config.py` + `config/default.yaml` — `ModelConfig` (LightGBM capacity/regularization
  + purged-CV + calibration/importance + seed + `model_version`); `max_depth > 0` and
  `num_leaves > 1` encode the §4.2 "shallow, modest capacity" discipline in the schema.
- `pyproject.toml` — added **`lightgbm>=4.4`** (no pandas pin); mypy overrides for the untyped
  `lightgbm`/`mlflow`.

**Verification (all green, Py 3.12):** ruff, black, mypy strict (183 files), pre-commit (12
hooks); `uv lock --check` clean (pandas stays 3.0.3); **786 tests pass (58 new)**; **100%
coverage** on all eight new modules. Headline asserts on a synthetic *known-signal* dataset:
OOS AUC > 0.8 computed only on purged out-of-fold predictions; permutation importance ranks
the true `signal` above `noise`; **calibrated Brier ≤ raw Brier** on the fit set (the isotonic
guarantee — identity is a feasible monotone fit); the run is logged (params/metrics/
importances/version tags); the fitted model satisfies the `Model` Protocol; training is
deterministic per seed. The MLflow adapter is exercised against a faithful fake module, and
`create_mlflow_tracker`'s missing-dependency path is asserted (reachable in CI).

**Decisions**
- **MLflow is operator-installed, not a declared dep — exactly the arcticdb call (P1.3).**
  `uv pip install --dry-run mlflow` would downgrade **pandas 3.0.3 → 2.3.3**, so per the Part
  II environment policy it must not be a project dependency. It lives behind the
  `ExperimentTracker` interface, lazily imported and confined to `tracking.py`, with the
  in-memory tracker as the always-available default. "Runs logged to MLflow" is satisfied by a
  real adapter, proven against a fake (the same pattern that tests `ArcticRepository` with no
  arcticdb install). A `test_models_confinement.py` (AST scan) fails CI on any
  `lightgbm`/`mlflow` import outside `research/models/`.
- **LightGBM native API (not the sklearn wrapper)** so scikit-learn is *not* dragged in.
  Combined with hand-rolled PAVA/scoring/MDA, the model stack's only new third-party
  dependency is `lightgbm` itself — the minimal, auditable surface the project favours.
- **Isotonic (PAVA) hand-rolled, not sklearn.** A clean, exact algorithm; following the
  NormalDist-over-SciPy precedent. The calibration set is the pooled purged OOS predictions —
  leak-free by construction (§4.2's "held-out (purged) set").
- **Baseline target is binary `{0, 1}`** — the calibratable form the meta bet/no-bet label
  (§3.4) and a binarized primary side both take. Isotonic calibration of a 3-class side is
  ill-defined; the binary baseline is what conviction-sizing (Deep Dive #3) actually consumes.
- **Importance computed within the CV on the test fold, not on training data** (§4.2 — "so the
  importance isn't itself leaking"); MDA, never MDI (`feature_importances_` is deliberately
  never read).
- **Early stopping deferred (not half-built).** Capacity is controlled by the modest config +
  the purged-CV tuner (which searches `num_leaves`/`min_child_samples`); OOS eval uses a fixed
  `num_boost_round` so it stays leak-free and deterministic. Early-stopping-on-a-purged-fold
  is a tracked refinement, not a buried TODO (Ground Rule 4).

**Follow-ups / notes (deferred, tracked)**
- **Ensemble + regime gate + registry → P2.7** consumes this baseline (LightGBM+XGBoost+linear
  rank-average/stack, HMM/GMM gate); the `model_version` tag + `ExperimentTracker` are the
  registry seam. P2.7 final runs are cloud-by-default (Part II compute policy).
- **DSR honest trial count:** each `RunRecord` (baseline + every tuning trial) is one trial;
  wiring the tracker's runs into P2.2's `TrialTracker` lands when the kill-gate report (P2.9)
  assembles the deflation.
- **Frac-diff / full feature matrix:** the trainer takes a prepared `X`; materializing the
  P1.6/P1.7 features + P2.5 frac-diff into the training matrix is pipeline orchestration (P2.9).
- ⚠️ Operator, to use MLflow tracking: `pip install mlflow` in a **pandas<3** environment (it
  is optional, like arcticdb); the in-memory tracker needs no install.

**Next subtask: P2.7 — Ensemble + regime gate + registry.**

### 2026-06-22 — P2.7 Ensemble + regime gate + registry ☑

**Goal:** the **production model stack** — a calibrated LightGBM + XGBoost + linear ensemble
(rank-averaging / stacking), an HMM/GMM regime gate, and a versioned model registry — built on
the P2.6 baseline and evaluated under the P2.2 CPCV path distribution.

**Reference (Ground Rule 9):** Deep Dive #2 §4.1 Step 2 (LightGBM **+ XGBoost** as the core),
Step 3 (cross-family blend via **rank-averaging or stacking** — *"diversity across model
families is more robust than one big tuned model; diversity is a free lunch"*), Step 4 (an
**HMM/GMM** regime gate that switches models on/off or sizes them down by volatility/trend
regime — non-stationarity), §4 output contract (*"every artifact tagged with the data +
feature + label versions it was trained on"* → the registry). §4b.2 for the CPCV path-Sharpe
distribution the gate is judged on. Inviolable Rule 2 (point-in-time: combiner/calibrator fit
OOF; regime model fit on train, applied to test; gate selection from train returns only).

**Delivered (`src/quant/research/models/`):**
- `estimators.py` — one tiny `Estimator` (`fit → FittedEstimator`) / `FittedEstimator`
  (`predict_proba`) contract so the ensemble blends *prediction vectors*, not library
  internals. `LightGBMEstimator` (reuses the P2.6 `fit_booster`), `XGBoostEstimator` (second
  GBM family, native API, confined), `LogisticEstimator` (hand-rolled L2 logistic, standardized,
  zero-init full-batch GD → deterministic without an RNG). `xgb_params_from_config` maps the
  shared `ModelConfig` capacity/regularization knobs onto XGBoost's names (one config, both
  boosters). All three deterministic for a fixed seed (single-thread boosters; convex logistic).
- `ensemble.py` — `RankAverageCombiner` (mean of each member's empirical-quantile rank against
  its own OOF reference — scale/calibration-neutral, and well-defined for one live row) and
  `StackCombiner` (a logistic meta-learner over the members' **OOF** probabilities). Both feed
  isotonic calibration. `EnsembleTrainer.train` pools per-member OOF predictions under
  `PurgedKFold`, fits the combiner + calibrator on those leak-free OOF preds, then re-fits the
  members on all data; `EnsembleModel` implements the live `Model` contract. `build_ensemble`
  is the per-split helper for CPCV.
- `regime.py` — `GaussianMixtureModel` (diagonal-covariance EM, log-sum-exp E-step, seeded
  init → deterministic; components sorted by first-feature mean so labels are stable and
  interpretable) + `RegimeGate` (per-regime position multiplier: 0 = off, fraction = sized
  down, 1 = full). `select_regime_multipliers` switches off regimes whose train return is
  non-positive (the operational form of kill-gate criterion 7, "edge stable across regimes").
- `registry.py` — `ModelCard` (the four version tags + metrics/params/importances + assigned
  `model_id`/`version`/`created_at`/SHA-256 `fingerprint`), `ModelRegistry` Protocol +
  `InMemoryModelRegistry` (default) + `FileModelRegistry` (JSON card + pickled artifact under a
  `pathlib` directory tree, append-only versioning, fingerprint integrity check on load,
  durable across sessions for Layer-5 rollback). Imports no model library — storage stays
  decoupled from the GBMs.
- `evaluation.py` — `evaluate_ensemble_under_cpcv`: per CPCV split, fit the ensemble + a
  train-return-driven regime gate on the purged train rows, predict on the held-out test rows,
  turn calibrated `P(y=1)` into a position (`2·p - 1`), gate it, multiply by the realized
  forward return → the per-observation OOS strategy return CPCV stitches into φ path-Sharpes.
- `pyproject.toml` — added **`xgboost>=2.0`** (no pandas pin, like lightgbm); mypy override for
  untyped `xgboost`; `test_models_confinement.py` now also guards `xgboost` (AST scan fails CI
  on any `lightgbm`/`xgboost`/`mlflow` import outside `research/models/`).

**Verification (all green, Py 3.12):** ruff, black, mypy strict (193 files); `uv lock` clean
(pandas stays 3.x — xgboost 3.3.0 resolved with no pin); **884 tests pass (98 new)**; **100%
coverage** on all five new modules. Headline asserts on synthetic *known-signal* data: each
family learns the signal (AUC > 0.8) and is column-order-invariant + deterministic; the
ensemble's combined OOS AUC > 0.8 with every member attributable; the fitted ensemble satisfies
the live `Model` contract; the GMM recovers two well-separated regimes (>99% accuracy) with
stable labels; **the regime gate recovers an edge that cancels out ungated** — in a scenario
where the signal is profitable in one regime and loss-making in another, ungated CPCV median
path-Sharpe ≈ 0 while gated ≈ 0.47 (and a clean-edge dataset gives median path-Sharpe > 0.5,
the kill-gate-relevant magnitude); the registry round-trips through disk and detects a tampered
artifact via the fingerprint.

**Decisions**
- **XGBoost is a real declared dependency (like LightGBM), not hand-rolled or operator-only.**
  A *different* GBM implementation is the whole point of family diversity (§4.1 Step 2); it
  does **not** pin `pandas<3` (`uv lock` keeps pandas 3.x), so unlike mlflow/arcticdb it
  belongs in the engine env, confined to `research/models/`. The linear member, by contrast,
  *is* hand-rolled (a small convex algorithm, the isotonic/NormalDist precedent) so the stack
  adds no scikit-learn.
- **GMM over HMM** for the regime gate (the deep dive allows either). For an unordered
  point-in-time regime label a mixture is sufficient and is hand-rollable as a clean EM — no
  `hmmlearn`/sklearn dependency, fully deterministic and testable. An HMM (temporal transition
  matrix) is a tracked future refinement, not half-built here (Ground Rule 4).
- **Rank-averaging uses a stored per-member reference distribution, not in-batch ranks.** That
  makes the blend point-in-time — a single live row ranks against history, not against its
  unknowable contemporaries — while preserving the spirit (neutralize cross-family scale).
- **Combiner + calibrator fit on OOF; final members re-fit on all data** — the exact P2.6
  baseline discipline (a stack trained on OOF base preds cannot leak). `build_ensemble` fits
  in-sample for the per-split CPCV path because the test block is still strictly purged.
- **Registry stores via pickle behind a generic `object` artifact** — no GBM import in
  `registry.py`, so storage and modelling stay decoupled and the registry is testable with a
  trivial fake model. The fingerprint is integrity, the version tags are the §4 contract.

**Follow-ups / notes (deferred, tracked)**
- ✅ **Persistent MLflow tracking + final run — DONE in P2A.6 (deferral closed 2026-06-24).**
  P2.7 delivered and unit-tested the *code* (the `ExperimentTracker` seam +
  `create_mlflow_tracker`). The **final** registry-promotable run on the real backfilled,
  labeled dataset was executed in **P2A.6** (local, per the cloud policy): the
  `quant.research.pipeline` orchestration pooled the 8-symbol universe (14,150 events) and
  trained the ensemble + GMM regime gate, logged to **persistent MLflow** (experiment
  `p2a6-final-run`, run-ID `e24c0cd6354f40e7bae024ce9f6b16c1`, status FINISHED — *not* the
  in-memory tracker) and registered as **`ensemble-regime-v1-0001`** in `FileModelRegistry`
  (round-trip exact). That artifact is the input P2.8 will validate. See the P2A.6 section below
  and `docs/operator_runbooks/P2A.6_final_run.md`.
- **Meta-model (§4.1 Step 5) → its natural home is the existing P2.5 `MetaLabeler` + this
  ensemble as the primary**; wiring the bet/no-bet meta-model on top of the gated ensemble lands
  with the kill-gate report assembly (P2.9), alongside the DSR honest trial count.
- **Robustness battery + two-engine reconciliation → P2.8** stresses this stack; the kill-gate
  verdict (all seven criteria) is emitted in P2.9.

**Next subtask: P2.8 — Robustness battery + two-engine reconciliation.**

### 2026-06-23 — Blueprint correction: P2A.1 `api_key` location

Corrected the P2A.1 "Done when" (and the AI-guidance-deliverable wording + Part V row) in the
blueprint: the Kite `api_key` is recorded via the **secrets interface**
(`QUANT_SECRET_KITE_API_KEY`), the same as `api_secret` (`QUANT_SECRET_KITE_API_SECRET`) —
**not** in `config/env/dev.yaml` as the drifted text had said. This matches the canonical,
merged P1.1 implementation (`backfill_cli.py` reads `api_key` via `secrets.get(...)`) per Ground
Rule 4 (don't refactor working, tested code to chase a less-correct doc choice). Docs-only; no
code changed; P2A.1 itself not yet started.

### 2026-06-23 — P2A.1 Kite Connect: subscription + developer app creation ☑

**Goal:** an active Kite Connect subscription + registered developer app yielding `api_key` /
`api_secret`, recorded via the secrets interface and confirmed with a read-only call. First
operator-action subtask (Phase 2A); the AI authored the walkthrough, guided execution, and
verified — it never held the credentials.

**Operator actions (completed):** created the Kite Connect app on `developers.kite.trade`,
subscribed (**₹500/month, historical data included** — confirmed on the official site/signup;
Zerodha repriced down from the ₹2000 the blueprint assumed), and recorded `api_key` /
`api_secret` via the secrets interface — both as **persistent** env vars (`setx
QUANT_SECRET_KITE_API_KEY` / `QUANT_SECRET_KITE_API_SECRET`), neither in any config file or git.

**Delivered (AI):**
- `docs/operator_runbooks/P2A.1_kite_signup.md` — the screen-by-screen walkthrough (console
  fields, local-dev redirect URL, secrets-interface storage, once-only-secret recovery,
  verification, last-4-char key fingerprint).
- `src/quant/data/brokers/verify.py` (logic) + `scripts/verify_kite_credentials.py` (thin shim,
  Ground Rule 3): reads both credentials via the secrets interface (presence-checked, never
  printed), builds the Kite client, makes **one read-only** `instruments` call, and logs only
  the api_key's **last 4 chars** + the instrument count.
- `tests/unit/test_brokers_verify.py` — 5 tests (fake client; no SDK/network); 100% on `verify.py`.

**Verification (operator machine):** `uv run python scripts/verify_kite_credentials.py` →
`PASSED — api_key ending <last 4>, fetched 9,853 NSE instruments` (HTTP 200 from
`api.kite.trade`). The `api_secret` is end-to-end validated later by P2A.2's session checksum.

**Done-when:** ☑ `api_key` via `QUANT_SECRET_KITE_API_KEY`; ☑ `api_secret` via
`QUANT_SECRET_KITE_API_SECRET` (neither committed); ☑ one read-only call succeeds; ☑ recorded
here with the date (no credential values).

**Decisions / notes**
- **Price correction:** the blueprint's ₹2000/month was stale; the real, verified figure is
  **₹500/month incl. historical data**. Corrected in the blueprint (P2A.1) and the walkthrough.
- **api_key location:** secrets interface (not config) — see the prior correction note and PR #30.
- **Historical data** is included in the ₹500 plan, so **P2A.3's backfill is unblocked** (no
  separate add-on needed).
- **Operator credential handling stays local:** session/persistent env vars on the dev box now;
  AWS Secrets Manager on the live host (Phase 8 / P5A).
- **Deferred follow-up:** the engine-startup last-4-chars `api_key` log line is deferred to the
  subtask that introduces engine-startup wiring (likely the Phase-3/4 boundary) — no speculative
  plumbing now (Ground Rule 4). Compensating control: the P2A.1 verifier already logs the
  last-4-chars on credential load.

### 2026-06-23 — P2A.2 Daily-auth flow: the manual TOTP seed ☑

**Goal:** a repeatable morning routine turning one manual login into a fresh `access_token`,
persisted to the secrets interface for the engine/research to read. Second operator-action
subtask; the AI authored the runbook + helper and verified, never holding the token.

**Operator action (completed, live):** ran `uv run python scripts/kite_morning_auth.py`, logged
in to Kite (client ID + password + TOTP), pasted the one-time `request_token` from the redirect;
the exchange returned `POST /session/token → 200` (the `SHA-256(api_key + request_token +
api_secret)` checksum succeeded — **the `api_secret` is now end-to-end proven**, complementing
P2A.1's key check). The fresh token persisted to the file-backed secret store; a separate process
read it back via `default_secrets()` (32 chars). No TOTP automation (compliant).

**Delivered:**
- `core/secrets.py` — file-backed fallback (`FileSecretStore` at `~/.quant-intraday/secrets.json`,
  `0600` on POSIX, atomic write) behind the existing `Secrets` interface: **env-then-file**
  precedence (env always wins → prod/AWS Secrets Manager/CI keep injecting via env), a new
  `set()` method, and a `default_secrets()` factory. Repository pattern — the Phase-5.2 / Phase-8
  swap to AWS Secrets Manager is a backend change, not a caller change. Cross-platform (no
  Windows-only `setx` branch, Ground Rule 2). 100% cov.
- `data/brokers/morning_auth.py` (logic) + `scripts/kite_morning_auth.py` (thin shim): reuse
  `KiteAuthenticator.seed_session`, persist via `secrets.set(KITE_ACCESS_TOKEN_SECRET, …)`, log
  only the access_token's **last 4 chars**. `KITE_ACCESS_TOKEN_SECRET` added to `auth.py`.
- `docs/operator_runbooks/P2A.2_daily_auth.md` — the walkthrough.
- Tests: `test_secrets.py` (+15, file-backed fallback + precedence + perms + malformed) and
  `test_brokers_morning_auth.py` (+4). 905 pass (1 skipped: POSIX perms → CI Ubuntu).

**Done-when:** ☑ manual login → token exchange succeeds (proves `api_secret`); ☑ token persisted
to the secrets interface (file store, `kite_access_token`); ☑ a new process reads it back; ☑ one
successful daily login end-to-end; recorded here (date only, no token value).

**Decisions / notes**
- **File-backed store over `setx`** (operator's refinement): cross-platform from day one,
  repository-pattern parity with the future AWS Secrets Manager backend, no env-var refresh
  footgun, inspectable/wipeable file.
- **Daily ritual:** the seed must be re-run each trading morning (token flushed ~05:00–07:30
  IST); scheduling it + a richer cross-restart token store are **P5.2**; the live-host backend is
  **Phase 8**.

**Next subtask: P2A.3 — Real-data backfill: first historical pull.**

### 2026-06-24 — P2A.3 Real-data backfill: first historical pull ☑

**Goal:** the first real historical dataset — ~5 years of minute bars for the seed universe, via
the P1.4 backfill → Parquet, then checked with P1.5 gap detection + the P1.9 data-quality
dashboard. Runbook authored: `docs/operator_runbooks/P2A.3_backfill.md`.

**Parameters (set with the operator):** the 8 seed large-caps in `config/universe.yaml`; minute
interval; 2021-06-24 → 2026-06-23 (~5 years); Parquet tier; the daily access token read from the
secrets interface (`kite_access_token`, seeded by the P2A.2 helper) rather than a per-run
`--request-token`.

**Deferred follow-up (tracked):** universe expansion to a survivorship-correct **Nifty-50/100**
is deferred to a follow-up subtask before P2.8. Requires sourcing point-in-time index
constituents including delisted/renamed names per P1.5 hygiene. The current P2A.3 backfill uses
the 8 seed large-caps from `config/universe.yaml`.

**Executed (operator, live):** `run_backfill.py` pulled all 8 names (reading today's token from
the secrets interface — no `--request-token`); `check_backfill.py` verified the pull. Result —
**every symbol has data** over **2021-06-24 09:15 → 2026-06-23 15:29** (the full requested range):

| metric | value |
|---|---|
| symbols | 8 (all populated) |
| minute bars | ~462k per symbol (~3.70M total; e.g. RELIANCE 462,436) |
| sessions covered | 1,239 per symbol |
| bad ticks removed | 2 total (across 8 names × ~5y) |
| intraday gaps | 117 total (~15/symbol — micro-gaps, ~0.5% of minutes) |

The first bar lands exactly on the requested start (2021-06-24), and 1,239 observed sessions ≈
all real NSE trading days in the window — coverage is effectively complete.

**Done-when:** ☑ Parquet store holds the 8-symbol minute universe over the configured period;
☑ P1.5 gap detection run + reviewed (micro-gaps, within tolerance); ☑ P1.9 dashboard reports
every symbol with data; ☑ dataset span + counts recorded here.

**Follow-up (tracked):** the P1.9 check reports **expected = 1,300** sessions vs **1,239** observed
and `missing_days = 67` (identical across all 8 names) — these are **NSE holidays absent from the
P0.4 `NSECalendar` holiday set**, not missing data (the first bar is exactly 2021-06-24). Complete
the holiday calendar (a P0.4 follow-up) before relying on session-level coverage / drift metrics;
it would also clear the spurious "ISSUES" flags in the coverage report.

**Next subtask: P2A.4 — Research environment stand-up (`.venv-research` + persistent MLflow).**

### 2026-06-24 — P2A.4 Research environment stand-up ☑

**Goal:** a separate `.venv-research` env (`pandas<3` + MLflow + ArcticDB) with a persistent MLflow
tracking server, so the auto-trigger research runs (P2A.6 final P2.7, then P2.8/P2.9) record to a
durable store. Runbook: `docs/operator_runbooks/P2A.4_research_env.md`.

**Stood up & verified (on the dev box, via the AI's shell — pure local tooling, no credentials):**
- `.venv-research` created (`uv venv --python 3.12`); installed **pandas 2.3.3 + mlflow 3.14.0 +
  arcticdb 6.18.3** (arcticdb installs fine on Windows). Engine env untouched (stays pandas 3.x).
- MLflow tracking server reachable at **http://127.0.0.1:5000**; a smoke run logged to the
  `p2a4-smoke` experiment and **persisted** (sqlite `mlruns/mlflow.db`); server then stopped.
- Config: `.gitignore` now ignores `.venv-research/` (`mlruns/` already ignored); ruff
  `extend-exclude` adds `.venv-research` (mypy already scoped to `src`/`tests`).

**Done-when:** ☑ `mlflow --version` in `.venv-research`; ☑ pandas 2.x there; ☑ UI reachable on
127.0.0.1:5000; ☑ a test run appears + persists.

**Findings (corrected in the runbook + Part II):**
- **MLflow 3.x deprecated the file store** (`--backend-store-uri ./mlruns`) — `mlflow server` now
  refuses it. Switched to a **sqlite** backend (`sqlite:///mlruns/mlflow.db` + `--default-artifact-root
  ./mlruns/mlartifacts`), both under the gitignored `mlruns/`. Part II's runbook command updated.
- **Windows needs `PYTHONUTF8=1`** for MLflow-logging scripts: MLflow prints a 🏃 emoji in the
  run-URL line that crashes the default cp1252 console. Noted in the runbook + Part II.

**Note:** installing the quant project + model stack (LightGBM/XGBoost) *into* `.venv-research` is
**P2A.6**'s setup, when the final P2.7 run actually executes in this env (P2A.4 proves MLflow only).

**Next subtask: P2A.5 — AWS account preparation (one-time; no resources launched).**

### 2026-06-24 — P2A.5 AWS account preparation ☑

**Goal:** an AWS account prepared (hygiene + guardrails) for the P2.8 cloud run and the Phase-8
engine VPS — with **zero resources launched**. Account hygiene only. Runbook:
`docs/operator_runbooks/P2A.5_aws_setup.md`.

**Operator actions (completed, existing account, account-ID tail …9719):** root MFA on + no root
access keys; **$150 promotional credits** present (≈$50 already used of the $200 grant); created
IAM user **`quant-intraday-ops`** (console + programmatic) with **MFA**; attached the
least-privilege customer-managed policy **`quant-intraday-ops-policy`** (spot EC2 + project S3 +
CloudWatch, **`ap-south-1`-only**, with an explicit out-of-region deny); AWS **Budgets** cost
alerts at 50/80/100% of a $25/mo tripwire; installed AWS CLI 2.35.11 and `aws configure` (key in
`~/.aws/`, never the repo).

**Verified (AI, on the dev box):** `aws sts get-caller-identity` → the IAM user ARN (auth works,
not root); `ec2 describe-instances --region us-east-1` → **explicit deny** (least-privilege
proven); `--region ap-south-1` → allowed and **empty** (`Reservations: []` — nothing launched).

**Delivered:** `aws/config.yaml` — non-secret identifiers only (region, account ID, IAM ARN,
policy name); no credentials.

**Done-when:** ☑ IAM auth works; ☑ least-privilege (out-of-region denied); ☑ Budgets armed;
☑ credits visible; ☑ MFA on root + IAM user; ☑ recorded (date + account-ID-tail, no keys);
☑ no EC2/S3/NAT/EIP created.

**Note:** S3 bucket + first spot run are **P2.8**; engine VPS + EIP are **P5A.1 / Phase 8**; NAT
is never used (public subnet + EIP per the cloud policy).

**Next subtask: P2A.6 — Final P2.7 registry-promotable run on real data (local).**

### 2026-06-24 — P2A.6 Final P2.7 registry-promotable run on real data ☑

**Goal:** retroactively complete the deferred final P2.7 run now that real data exists — train the
production stack (cross-family **ensemble** + **GMM regime gate**) on the real backfilled universe,
log it to **persistent MLflow**, and write the artifact + model card into `FileModelRegistry`,
ready for P2.8/P2.9. Runbook: `docs/operator_runbooks/P2A.6_final_run.md`.

**Reference (Ground Rule 9):** Deep Dive #2 §4.1 (the cross-sectional ensemble + regime gate),
§4 output contract (every artifact tagged with its data/feature/label/model versions → the
registry), Inviolable Rule 2 (point-in-time: purged CV, OOF combiner/calibrator, train-only gate
selection), Part II research-env/MLflow runbook + cloud policy (final P2.7 runs **local**).

**Design decision — cross-sectional pooling (operator-approved Option 1, Ground Rule 9).** The
blueprint's model is cross-sectional (one model across the universe), but `PurgedKFold` needs a
**sorted, unique** timeline and the 8 symbols share 15-min timestamps. The pipeline pools all
symbols onto **one synthetic timeline**, concatenating each symbol's events with an inter-symbol
gap **strictly larger than the max label horizon** (`pipeline.pool_gap_days=5`; the vertical
barrier caps a label at one session). Intra-symbol time deltas are preserved exactly (purge/embargo
stay correct) and a label window can never span two symbols (asserted in the tests). Uses the
merged P2.7 `EnsembleTrainer` unmodified. Options 2/3 (single-symbol / per-symbol-pick-best) were
rejected: they break the cross-sectional architecture and (Option 3) inflate the P2.9 trial count.

**Delivered (`src/quant/research/pipeline/`, orchestration only — no model maths):**
- `dataset.py` — `resample_bars` (minute → 15-min, session-safe), `build_symbol_dataset`
  (P1.6 core features + P1.7 regime descriptors → CUSUM events → triple-barrier labels →
  average-uniqueness × time-decay weights), `pool_datasets` (the gapped synthetic timeline +
  `PoolSegment` audit), `build_pooled_dataset`, deterministic `data_version`/`label_version`.
- `model.py` — `GatedEnsembleModel` (the registry artifact: `EnsembleModel` + `RegimeGate`,
  picklable, satisfies the live `Model` contract; `gated_position` applies the regime gate).
- `final_run.py` — `train_final_model`: pool → `EnsembleTrainer.train` (MLflow-logged) → fit the
  regime gate on full-sample strategy returns → register → **round-trip verify** (reloaded
  artifact predicts identically, else exit 1).
- `cli.py` + `scripts/run_final_training.py` — one narrated command; `--tracker mlflow` default
  (selecting it without mlflow fails loudly — no silent in-memory fallback, a P2.9 correctness
  requirement). None of the pipeline imports lightgbm/xgboost/mlflow directly (confinement test).
- `core/config.py` + `config/default.yaml` — a `pipeline` config section (`pool_gap_days`,
  `n_regimes`, `ensemble_method`, `registry_model_version`, `registry_dir`); gap is config, not a
  literal (Ground Rule 2).
- `.venv-research` gained the project + model stack (`uv pip install -e .`; LightGBM/XGBoost/
  TA-Lib/statsmodels) — the install deferred from P2A.4; pandas stays 2.3.3.

**Executed (AI, local, persistent MLflow → sqlite):** full backfill `2021-06-24 → 2026-06-23`,
default 8-symbol universe. **Exit 0, round-trip exact** (≈2 min wall-clock):

| item | value |
|---|---|
| MLflow | experiment `p2a6-final-run` (id **2**), run-ID **`e24c0cd6354f40e7bae024ce9f6b16c1`**, status **FINISHED** |
| registry artifact | **`ensemble-regime-v1-0001`** (`models/registry/ensemble-regime-v1/0001/`; fingerprint `9031451e…`) |
| data / feature / label versions | `15min-8sym-20210624-20260623-1bba6975` / `core-v1` / `tb-cusum0.01-u2.0-d1.5-min0.002-vmax0` |
| pooled observations | **14,150** events across all 8 symbols (positive rate 0.450) |
| members / gate | `lightgbm, xgboost, logistic` (rank-average, isotonic) / 3 regimes, multipliers `(1,1,1)` |
| OOS (purged CV) | combined AUC 0.520 (lgbm 0.529 / xgb 0.527 / logistic 0.488); calibrated logloss 0.687, Brier 0.247 |

**Done-when:** ☑ MLflow run-ID exists (FINISHED); ☑ `FileModelRegistry` artifact exists; ☑ both
recorded here + under P2.7 (deferral closed above); ☑ reloaded artifact deserializes + predicts
identically (independently re-verified in a fresh process, fingerprint checked); ☑ artifact is the
input P2.8 will validate.

**Verification (all green, engine env, Py 3.12):** ruff, black, mypy strict (210 files);
**947 tests pass (36 new), 1 skipped** (POSIX-only); **100% coverage** on all new pipeline modules.

**Honesty note (Inviolable Rule 7).** The edge is **weak** — combined OOS AUC ≈ 0.52, barely above
chance on this 8-name seed universe. That is the expected reality, not a failure: P2A.6's job is to
produce the registry-promotable artifact; whether it survives **costs + the seven-point kill-gate**
is P2.8 (robustness) and P2.9's (DSR/PBO/CPCV) verdict, not this run's.

**Follow-ups / notes (deferred, tracked):**
- **Universe expansion to survivorship-correct Nifty-50/100** (already tracked in P2A.3) remains
  the right next data step before P2.8 leans on this artifact's generality.
- **"Features from finer data" (Part II locked decision).** This run computes features on the
  resampled 15-min bars; pulling minute-level microstructure (OFI/depth, P1.7) into the 15-min
  decision rows is a tracked refinement, not built here (Ground Rule 4) — the depth book isn't in
  the minute archive yet.
- **P2A gate (`gate-2a-real-data-path`) is ready to tag:** Kite creds + daily auth + real data +
  research env + AWS prep + the final P2.7 artifact all exist. Tagging is the operator's call.

**Next subtask: P2.8 — Robustness battery + two-engine reconciliation (against this artifact).**

### 2026-06-25 — P2.8 Robustness battery + two-engine reconciliation ☑

**Goal:** stress the registered ensemble + regime-gate edge from the five §4b.7 angles and
reconcile a sample strategy across two independent backtest engines — the inputs to kill-gate
criterion 6 (P2.9 emits the verdict). Runbook: `docs/operator_runbooks/P2.8_robustness.md`.

**Reference (Ground Rule 9):** Deep Dive #2 §4b.7 (the robustness battery: parameter sensitivity,
Monte Carlo trade shuffle, noise injection, cross-symbol, synthetic-data; the implementation-risk
two-engine check), §4b.8 (tooling — *"implement the math directly … don't black-box it"*), the
kill-gate (criterion 6), Inviolable Rule 7 (honesty about a weak edge), Part II cloud policy
(P2.8 is cloud-by-default; local smoke on the same code path before any cloud run) + the
research-env/MLflow auto-trigger (persistent tracking required).

**Design decision — independent in-house second engine, not VectorBT/Backtrader (Ground Rule 9,
surfaced to the operator).** §4b.8 names those libraries as *examples* of the fast-vectorised vs
event-driven pair but equally sanctions implementing the math directly — which is the whole
codebase's ethos (no sklearn/SciPy; hand-rolled PAVA/GMM/logistic/`NormalDist`) to keep the engine
env lean (Part II Environment Policy). VectorBT pins numpy/numba and Backtrader is unmaintained;
more decisively, a third-party engine knows nothing of our Indian cost model or next-bar-open +
intraday-square-off rules, so it could never reconcile *within tolerance* without re-implementing
those semantics inside it anyway. So `VectorizedBacktester` is an independent, fully **vectorised**
reimplementation that shares the *injected* cost/slippage models but differs entirely in
simulation structure (whole-array `diff`/`cumsum` vs the P2.1 per-bar loop) — the property the
reconciliation isolates. The simpler/more-robust/more-testable option per the blueprint preamble.

**Delivered (`research/validation/`, model-agnostic — the battery imports no model library, so
confinement + clean layering hold):**
- `robustness.py` — `StrategyDataset` + the five stress primitives, each taking an injected
  `EvaluateFn`/score/builder (Ground Rule 1) so they're pure validation utilities testable with
  fakes: `parameter_sensitivity` (knife-edge via CV / sign-flip), `monte_carlo_shuffle`
  (order-dependent max-drawdown distribution), `noise_injection` (per-feature-std Gaussian decay),
  `cross_symbol_validation` (leave-one-symbol-out held-out Sharpe), `synthetic_data_backtest`
  (driftless GBM, edge must centre ~0) + a vectorised `geometric_brownian_bars` generator.
- `reconcile.py` — `VectorizedBacktester` (independent vectorised engine, same contract as the
  P2.1 `Backtester`) + `reconcile_engines` → `ReconciliationReport` (per-metric money diffs,
  pass/fail within tolerance).

**Delivered (`research/pipeline/`, the layer that wires the real model in — as `final_run` does):**
- `robustness.py` — `run_robustness_battery`: rebuild the pooled real dataset, run all five tests
  against the recipe (the `cross_family_estimators` stack + gate, re-fit OOS per CPCV split under
  perturbation), load the registered artifact and reconcile its own signal through both engines,
  and log every variant as its own tracker run (the honest trial count for P2.9). Promoted the
  shared estimator stack to `models/estimators.cross_family_estimators` (DRY with `final_run`).
- `robustness_cli.py` + `scripts/run_robustness.py` — one narrated command; `--tracker mlflow`
  default (no silent in-memory fallback); exit 1 only if the engines disagree (an implementation
  bug), never for a weak edge.
- `core/config.py` + `config/default.yaml` — a `robustness` config section (CPCV scheme, noise
  levels/repeats, MC shuffles, synthetic universes/sessions, knife-edge CV threshold, reconcile
  tolerance, seed); every knob is config, not a literal (Ground Rule 2).

**Executed (AI, local smoke vs the real P2A.6 artifact, persistent MLflow → sqlite, research env):**
full backfill `2021-06-24 → 2026-06-23`, 8-symbol universe, reduced battery knobs (a fast smoke on
the same code path — the Part II prerequisite before any cloud run). **Exit 0, engines reconcile
exactly.**

| item | value |
|---|---|
| MLflow | experiment `p2.8-robustness` (id **3**), **14 runs** logged (one per stress variant) |
| reconciliation | `max_money_diff` **0.0** — the vectorised engine is bit-identical to the event-driven `Backtester` on the artifact's sample strategy |
| parameter sensitivity | baseline median path-Sharpe ≈ 0.040; all variants 0.040–0.049 (no knife-edge, no sign flip) |
| noise injection | median ≈ 0.036 → 0.032 → 0.037 across levels 0.05–0.5 (graceful, stays positive) |
| monte carlo | drawdown percentile-rank 0.965 (observed ordering not anomalously benign) |
| cross-symbol | leave-one-out median held-out Sharpe ≈ 0.044 |
| synthetic (no-luck) | mean median ≈ 0.031 (near zero → no spurious edge / leak) |

**Done-when:** ☑ each of the five tests runs and reports; ☑ two engines reconcile within tolerance
on a sample strategy (exactly, 0.0); ☑ persistent MLflow records every variant (run-IDs above);
☑ tested.

**Verification (all green, engine env, Py 3.12):** ruff, black, mypy strict (218 files), pre-commit
(12 hooks); **1016 tests pass (69 new), 1 skipped** (POSIX-only); **100% coverage** on all four new
modules (`robustness`, `reconcile`, `pipeline/robustness`, `pipeline/robustness_cli`).

**Honesty note (Inviolable Rule 7).** The edge is **weak** — per-observation CPCV path-Sharpes
cluster around 0.04, consistent with P2A.6's OOS AUC ≈ 0.52. The battery's job is to *measure and
report* (which it did, cleanly, on real data); whether the edge clears the **seven-point kill-gate**
(annualised CPCV median > 1.0, DSR, PBO, etc.) is **P2.9's** verdict, not this subtask's. On this
seed universe it almost certainly will not — and failing on a laptop is the system working.

**Follow-ups / notes (deferred, tracked):**
- **Full-fidelity cloud run.** This was a reduced local smoke. The default-knob battery (1000 MC
  shuffles, 4 noise levels × 3 repeats, 8 synthetic universes × 60 sessions, `num_boost_round=300`)
  is the heaviest single research run — cloud-by-default per Part II (spot `c7i.8xlarge`,
  `ap-south-1`, ≈3–6 h). It's operator-approved/triggered; the runbook documents it. Not required
  to satisfy P2.8's acceptance criteria (the smoke did), but it is the input P2.9 should consume.
- **Battery evaluates unweighted.** The CPCV re-evaluation drops the P2.4 sample weights (the
  battery stresses the signal's robustness; unweighted is the more conservative read). Threading
  weights through is a tracked refinement, not built here.
- **Sample-strategy sizing is a placeholder.** The reconciliation derives integer share targets
  from the gated signal via a crude `round(gated · capital / price)` (full conviction ≈ 1× capital
  in the name) — enough to drive identical fills. Real sizing is **P3.4** (vol-target + ¼-Kelly).

**Next subtask: P2.9 — Validation report + kill-gate emitter.**

### 2026-06-25 — P2.9 Validation report + kill-gate emitter ☑

**Goal:** one report that decides trade/don't-trade — the §4b.8 output contract bundled with the
**seven-point kill-gate** as PASS/KILL. Runbook: `docs/operator_runbooks/P2.9_killgate.md`.

**Reference (Ground Rule 9):** Deep Dive #2 "The kill-gate" (the seven criteria), §4b.8 (the
output contract: CPCV distribution, DSR, PBO, trial count, walk-forward equity, robustness),
§4b.2/§4b.3/§4b.4 (CPCV/DSR/PBO), §4b.6 (the realistic, cost-inclusive backtester), Inviolable
Rule 1 (thresholds set before running), Inviolable Rule 7 (most candidates die here).

**Delivered (`research/reports/`, pure — fed primitive evidence, no model/pipeline imports):**
- `killgate.py` — `KillGateEvidence` → `evaluate_kill_gate` → `KillGateVerdict` (the seven criteria
  as an AND, each with observed-vs-threshold detail + a rendered decision block).
- `report.py` — `ValidationReport` (the §4b.8 bundle) + text renderer + the cost/concentration/
  regime stat primitives: `round_trip_cost_fraction` (Indian cost model + slippage → fraction of
  notional), `net_event_returns` (gross − position-scaled round-trip cost, one round trip per
  event), `profit_factor`, `trade_concentration`, `regime_breakdown`.
- `tearsheet.py` — `write_quantstats_tearsheet` (confined, lazy QuantStats; research-env only,
  injected writer in tests). `errors.py` — `ReportError`/`ReportDependencyError`.

**Delivered (`research/pipeline/`, the orchestration that runs model + validation engine):**
- `validation.py` — `build_validation_report`: rebuild the pooled dataset, compute the
  **net-of-cost, annualised** CPCV path distribution (criterion 1 is *"after costs"* — the gross
  ~0.04 from P2.8 is **not** the input), the DSR vs an honest candidate-config panel (PBO + trial
  count from the same panel, computed once), the per-regime net returns (criterion 7), the
  full-cost walk-forward equity (P2.1 backtester), and the robustness battery (P2.8) → assemble
  the report, evaluate the gate, log to MLflow.
- `validation_cli.py` + `scripts/run_validation_report.py` — one narrated command; `--output`
  writes the rendered verdict; exit 0 once the report generates (a KILL is a *successful* report).
- `core/config.py` + `config/default.yaml` — a `kill_gate` section (the seven thresholds, set
  before running, Ground Rule 2 / Inviolable Rule 1).
- `models/evaluation.py` — a backward-compatible `round_trip_cost` param on
  `evaluate_ensemble_under_cpcv` (default 0.0 = the gross P2.7/P2.8 behaviour; P2.9 passes the
  representative cost so the CPCV is net, with the regime-gate's train selection netted too).

**Executed (AI, real candidate, persistent MLflow → sqlite, research env, reduced-knob smoke):**
8-symbol universe, `2021-06-24 → 2026-06-23`. **VERDICT: KILL** (6 of 7 criteria failed).

| item | value |
|---|---|
| MLflow | experiment `p2.9-killgate` (id **4**), kill-gate run **`cdf5dd8ff72c4555bde22050436eb042`** (`verdict=KILL`) |
| (1) CPCV median path-Sharpe (annualised, **net**) | **−0.977** (all 5 paths negative; worst −1.288) — FAIL |
| (2) Deflated Sharpe Ratio | 0.001 — FAIL · (3) PBO 0.265 — FAIL · (5) profit factor 0.826 — FAIL |
| (6) robustness battery | **PASS** (robustly weak — not a knife-edge, generalises, reconciles) |
| (7) regime stability | all 3 regimes loss-making net — FAIL |
| walk-forward (full-cost) | net P&L **−₹98,471** (−9.8%), max DD 10.85%, 2568 fills |

**Done-when:** ☑ the report generates end-to-end; ☑ it emits the seven-point verdict; ☑ tested.

**Verification (all green, engine env, Py 3.12):** ruff, black, mypy strict (229 files), pre-commit
(12 hooks); **1054 tests pass (38 new), 1 skipped** (POSIX-only); **100% coverage** on all six new
modules (`killgate`, `report`, `tearsheet`, `errors`, `validation`, `validation_cli`).

**Honesty note (Inviolable Rule 7).** KILL is the correct, expected outcome — and the verdict
confirms the cycle-1 diagnostic exactly: the gross ~0.04 per-obs edge, netted of the representative
~0.17% round-trip cost per event, **flips negative** (−0.977 annualised; profit factor 0.826;
walk-forward −9.8%). Criterion 6 (robustness) *passing* while 1/2/4/5/7 fail is the gate working as
designed — a signal can be *robustly* weak yet unprofitable after costs; robustness alone is not
profitability. This run also doubles as P2.9's acceptance test (the gate correctly emits KILL on a
known-failing input). **Gate 2 is NOT passed** — the candidate routes to **Phase 2R** (the verdict
is recorded in `docs/iteration_log/cycle-1_verdict.md`).

**Design decisions (Ground Rule 9, surfaced):**
- **Net-of-cost CPCV via a per-event round-trip cost.** Criterion 1 demands cost-inclusive returns.
  The CPCV operates on triple-barrier events (one round trip each: enter at t0, exit at the
  barrier), so a representative round-trip cost from the real Indian cost + slippage models is
  charged once per event, scaled by position size. The bar-level next-bar-open Backtester (P2.1)
  is the complementary "walk-forward equity" deliverable. (Refinement: bar-level cost in the CPCV
  itself; tracked.)
- **PBO over a candidate-config panel.** The textbook CSCV PBO measures overfitting in *config
  selection*, so the (T×N) matrix columns are a small panel of distinct model configs (tree
  capacity, learning rate, blend), each one full-timeline net OOS series; the same panel feeds the
  honest DSR trial count + variance. (Refinement: fold the cross-cycle MLflow trial budget into N;
  tracked.)
- **Reduced-knob local run, not the full-fidelity cloud battery.** Per the operator's steer + Part
  II iteration discipline: a known-failing candidate is confirmed cheaply; the full-fidelity report
  + cloud earn their spend only when a candidate's smoke path-Sharpe is meaningfully above zero.

**Follow-ups / notes (deferred, tracked):**
- **Phase 2R Cycle 2 (label sanity)** is the next action — dump the triple-barrier touch
  distribution (the cheapest lever from the diagnostic). One input family per cycle.
- **Operator: set the P2R.4 iteration budget** (`docs/iteration_log/budget.md`) before Cycle 2.

**Next subtask: Phase 2R Cycle 2 — label sanity (triple-barrier touch distribution).**
