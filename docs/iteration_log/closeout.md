# Research-phase close-out

**Status:** the research phase is **complete and stopped at Phase 2R, Cycle 4** (tag
`research-phase-stop-cycle-4`). Gate 2 (the seven-point kill-gate) was **never passed**. **No
strategy proceeds toward capital. No live trading.** Phases 3–8 are deferred **indefinitely**, not
deleted — the apparatus and blueprint remain in place for a future research program if one is
defined.

> **The honest one-line verdict:** for a sub-10-OPS retail bot, **liquid Indian intraday cash
> equity (15-min/60-min, an 8-name large-cap universe, bar-data features) does not carry a
> predictive edge that survives realistic Indian transaction costs.** The system was built to be
> able to discover this cheaply and to stop — and it did.

---

## What was built (the apparatus — Phases 0–2, all gates 0/1 green)

A complete, tested, point-in-time research stack — **the durable output of this phase**:

- **Layer 1 (data & feature):** broker adapter (Kite, SDK-confined), live stream consumer, tiered
  storage behind a `Repository` interface, paginated/resumable backfill, hygiene jobs
  (corp-actions, survivorship, bad-tick, gaps, liquidity), a leakage-proof feature library +
  dual-path skew harness, a data-quality dashboard. Gate 1 green.
- **Layer 2 (research):** purged k-fold + embargo, **CPCV** with path reconstruction, **Deflated
  Sharpe**, **PBO/CSCV**, an honest trial tracker, the full **Indian cost model** + depth-aware
  slippage + a next-bar-open event backtester; CUSUM + **triple-barrier** labels, sample weighting,
  meta-labeling, fractional differentiation; a LightGBM baseline, a cross-family ensemble + GMM
  regime gate + model registry; the **robustness battery** + an independent second engine; and the
  **seven-point kill-gate emitter**. 1,000+ tests, 100% coverage on new modules throughout.
- **Real-data path (Phase 2A):** live Kite credentials + daily auth, a real 5-year minute backfill
  (8 symbols, 462k bars/symbol), the research env + persistent MLflow, AWS account prep.

## What was tried, and what each step concluded

| step | result |
|---|---|
| **P2A.6** — final ensemble + regime-gate artifact on real data | Edge weak: OOS AUC ≈ 0.52, calibrated logloss ≈ ln 2 |
| **P2.8** — robustness battery vs the artifact | Engines reconcile exactly; edge "robustly weak" (passes robustness, gross ~0.04 per-obs) |
| **P2.9** — kill-gate verdict (cost-inclusive) | **KILL** (6/7 fail). Net CPCV median **−0.98** annualised; costs flip the gross edge negative |
| **2R cycle 1** — diagnostic | Binding constraint ranked: feature signal (primary); model capacity *not* the bottleneck |
| **2R cycle 2** — label sanity (free) | Labels **sound** (vertical 16.4%, positive rate stable ~0.45). Axis (b) closed |
| **2R cycle 3a** — features from finer bars | Finer OHLCV (5-/1-min) **adds no signal** — slightly worse. Closed |
| **2R cycle 3b** — depth microstructure | **Data-gated:** no historical 5-level depth at retail budget. Deferred, pivot instead |
| **2R cycle 4** — 60-min frequency pivot | **No lift.** Gross flat, net still −0.90 annualised. **Stop criterion engaged** |

## What was learned (the honest, transferable findings)

1. **"Robustness is not profitability."** A signal can pass the parameter-sensitivity /
   noise / cross-symbol / synthetic battery yet be unprofitable after costs — it was *robustly*
   weak. The seven-point gate, judged **net of costs**, is what caught it; gross numbers are
   fantasy.
2. **Costs dominate the edge at this scale.** A ~0.12–0.20% round-trip against 15-min/60-min target
   moves leaves no margin once the gross edge is ≈ chance. This is structural, not a tuning miss.
3. **The constraint was correctly localised by cheap tests.** Label sanity (free), finer features
   (cheap), and a frequency pivot (cheap) each falsified a hypothesis without spending the trial
   budget or any capital — the iteration loop and budget worked exactly as designed.
4. **The DSR/trial-budget discipline never bound** — single-digit trials used of 50. The scarce
   resource was *signal*, not search.

## Inventory — what the apparatus can be re-pointed at later (future options, none committed now)

The entire stack is instrument- and frequency-agnostic behind its interfaces. If a **new** research
program is ever defined, candidates that change the cost-to-edge arithmetic the most:

- **Index / stock futures (NIFTY/BANKNIFTY, single-stock F&O):** lower effective cost per unit
  notional, deeper liquidity, native shorting — a structurally friendlier cost-to-edge regime than
  cash equity. (Would re-open the options-greeks scope the blueprint deliberately closed for v1.)
- **A different / larger universe:** survivorship-correct Nifty-100/500 or a different liquidity
  tier (the universe-expansion deferral) — more cross-sectional signal + a better DSR denominator.
- **A different decision frequency, properly:** daily-close / swing (overnight) — but this leaves
  intraday MIS and its no-gap-risk guarantees; treat as a *new* project, not a knob.
- **Depth microstructure (cycle 3b), via Phase-5 forward capture:** record live 5-level depth
  forward during the live-ingest work (₹0 data cost via Kite, weeks–months of accumulation) and
  retry depth-augmented features — the architecturally clean way, not a Phase-2R side-quest.

These are **logged, not chosen.** Re-entering any of them is a fresh research program with its own
diagnostic, budget, and kill-gate.

## What is preserved

- All code, tests, the blueprint, the iteration log, the registered artifact, and the MLflow run
  history remain in the repo. Nothing is deleted.
- The kill-gate, the cost model, the validation engine, and the data/feature pipeline are reusable
  as-is.
- The git tag `research-phase-stop-cycle-4` marks this conclusion.

## Final word

Over 90% of retail F&O traders lose money; most "edges" are bias artifacts. This project set out to
build a system that could tell the difference **honestly** and **stop when the edge isn't there** —
and that is precisely what it did, before a single rupee of real capital was risked. That is the
disciplined, successful outcome (Inviolable Rule 7), not a failed one.
