# Phase 2R · Cycle 3 — Plan: the feature-signal split (3a / 3b)

**Subtask:** P2R.2 cycle 3, planning artifact (authored *before* any 3a code). See the
[cycle-1 diagnostic](cycle-1_diagnostic.md) (binding constraint **(a)**, feature signal), the
[cycle-2 finding](cycle-2_finding.md) (labeling closed), and the [iteration budget](budget.md).
**Status:** plan committed; 3a **ran and was closed** (no lift — see [cycle-3a finding](cycle-3a_finding.md)); 3b **deferred** (see [cycle-3b decision](cycle-3b_decision.md)).

> **Permanent structural fact (surfaced for future-us):** historical 5-level depth is **not
> available at a retail budget** — it exists only at institutional tiers (₹tens-of-thousands+/month,
> quote-based, redistribution-licensed). The **only** viable retail path to depth-augmented
> features is **forward-recording via Kite's existing free WebSocket** (which costs calendar time +
> Phase-5 live-capture infrastructure, not data fees). See §2 for the full cost-tier breakdown.

The cycle-1 diagnostic's primary binding constraint is **feature signal (a)**, and it named two
*distinct* feature gaps with very different costs. This plan records the data reality behind each,
the operator-cost analysis for the expensive one, and the cheap-test-first sequencing.

---

## 1. Current depth-book data state

| question | finding |
|---|---|
| Historical 5-level depth in the store? | **None.** The `Repository` is bars-only (`read_bars`/`write_bars`); there is no depth tier and no `DepthSnapshot` is ever persisted. |
| Has live ingest captured any depth? | **No.** P1.2's `TickStreamConsumer` *parses* `full`-mode 5-depth into an in-memory queue, but the queue→store wiring was **deferred** (P1.2 notes), and the live consumer is **not running** (we are in Phase 2; the live engine is Phase 6/8). |
| Can depth be backfilled? | **No.** Kite's historical API serves **OHLCV candles only** — the minute archive (`backfill_interval: minute`, 462k rows/symbol, 2021→2026) is the most granular history obtainable. 5-level depth exists **only** in the live WebSocket. |
| What *is* available today? | The **minute OHLCV archive** for all 8 symbols — the substrate 3a uses. |

**Gap:** depth-derived microstructure features (OFI, depth imbalance, signed flow — Deep Dive #1
§2.2, "empirically the top feature") cannot be computed from any data we currently hold.

## 2. Operator-cost analysis for 3b (depth microstructure)

Two distinctions decide everything: **L2 = 5-level depth** (what we designed to) vs **L3 = 20-level**
(not retail-redistributable); and **live vs historical** — which is the crux. The full cost-tier
breakdown (vendor pricing verified June 2026 to the extent it is public; depth tiers are
quote-based, so treat the upper tiers as order-of-magnitude):

| path | data cost | what you get / the catch |
|---|---|---|
| **(A) Record forward** via Kite's existing WebSocket | **₹0 marginal** (live 5-level depth is already included in the ₹500/mo Kite Connect plan, just not wired/run) | the *only* retail-viable path; cost is **calendar time** (weeks–months to accumulate usable history across regimes) + engineering (wire P1.2 → a depth store, run daily) — which **front-runs Phase-5 live-capture infrastructure** into Phase 2R |
| **(B) Retail real-time vendor** (TrueData, Global Datafeeds) | ~**₹990–a few-₹1,000s/month** | largely **duplicates** the live depth Kite already gives free; standard historical products are trades/OHLCV/L1, **not** historical depth-of-book — so it does **not** close the historical gap |
| **(C) Institutional historical L2 depth** (NSE Data & Analytics / LSEG / TickData) | **₹tens-of-thousands to ₹lakhs/month**, quote-based + redistribution-licensed | the only source of *historical* 5-level depth-of-book at scale; not a retail-budget purchase |
| (D) Weak proxy from minute OHLCV | ₹0 | signed-volume tick-rule / intrabar range ≈ microstructure-*flavoured*, but **not** 5-level OFI; overlaps with 3a, not a substitute |

**Bottom line:** historical 5-level depth is not buyable at a retail budget; **forward-recording
via Kite (path A) is the only viable route**, and its true cost is time + Phase-5 infra, not data
fees. A ~₹1k/mo vendor buys live depth we already have free and does not supply history. **Deferred
to operator** — resolved in the [cycle-3b decision](cycle-3b_decision.md): 3b deferred, pivot first.

## 3. Sequencing — 3a first (cheap test), then 3b (data-gated)

- **Cycle 3a — features from finer data.** Compute the **existing** feature families on finer bars
  (1-min / 5-min from the minute archive) and align to the 15-min decision rows. Tests Part II's
  "15-min decision bars; **features from finer data**." **Hypothesis:** the model is signal-starved
  because resampling to 15-min *before* featurising discards sub-15-min structure. **Reveals:**
  whether usable signal exists at sub-15-min resolution.
- **Cycle 3b — depth microstructure.** Only after the 3b data decision (§2). **Hypothesis:**
  OFI/depth/signed-flow add genuine predictive microstructure the bar-only set cannot. **Reveals:**
  whether true depth is the binding answer.

**Why 3a first:** it is the cheapest possible feature test (existing data, no backfill, no new
deps), and its result **sharpens 3b's question**:
- If 3a lifts the smoke CPCV path-Sharpe meaningfully (budget reference **>+0.2**), the model was
  signal-starved in a way finer bars partly solve — and 3b would then be *amplifying* a working
  signal.
- If 3a does **not** lift it, that argues 3b's depth features are more likely *creating* signal,
  not amplifying — a stronger case for paying 3b's data cost — and the labeling question is by then
  fully settled, so the feature question is isolated.

## 4. Cost / trial-budget impact

| cycle | compute | data cost | trial-budget impact (of 50) |
|---|---|---|---|
| **3a** | local, reduced-knob smoke (existing minute archive) | none | a small number of feature-frequency variants (each one CPCV evaluation = one trial); reported in the 3a finding |
| **3b** | (if activated) local research once data exists | **high** — forward recording (weeks–months) or a paid vendor | not spent until the data exists; planning only here |

3a stays **local** per the cloud-compute policy (iterative development never goes to cloud). Every
3a variant — including discarded ones — is logged to MLflow toward the 50-trial cap, and the
trial-count consumed is reported in the cycle-3a finding (the DSR-honest discipline).

**Decision:** proceed with **3a**; hold **3b** pending the operator's data decision.
