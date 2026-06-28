# Step 1 — Universe liquidity gate (multi-ETF rotation)

**Track:** `etf-rotation` (separate from `gold-mini`). Spec: `SPEC_MultiETF_Rotation.md` §7 Step 1.
**Status:** DONE. Tradeable universe frozen (client-ratified). No scoring/benchmark/backtest yet.
**Code:** `src/quant/research/etf/liquidity.py` (pure, unit-tested) + `scripts/etf_liquidity_gate.py` (thin Yahoo I/O shim). Reproduce: `uv run python scripts/etf_liquidity_gate.py`.

## Pre-registered gate (committed before viewing results)

- **Source:** Yahoo Finance daily OHLCV, `.NS` symbols, trailing **252 genuine sessions**.
  A coarse **turnover/continuity screen only** — the real bid-ask **spread** is the live
  Step 2 measurement (§6), and is the cost that actually bites at ₹1 lakh scale.
- **Metric:** daily traded value = `close × volume` (₹); report the **median** (robust to spikes).
- **PASS:** median 1Y traded value **≥ ₹5 cr/day** AND continuity **≥ 99%**.
- **Rationale for ₹5 cr:** at ₹1 lakh a single leg's monthly rebalance turnover is a few
  thousand rupees — ~1000× headroom even at the floor. Generous on absorption (we are a
  rounding error), strict on "is this a genuinely liquid market with a daily price."

### Honest-N / methodology corrections recorded here
1. **Continuity correction (registered).** Raw Yahoo data showed liquid names at ~98%
   continuity purely because the feed carries **market-wide holiday rows** with a
   forward-filled close and volume 0. Continuity is measured **excluding market-wide
   non-session dates** (`market_wide_dead_dates`: a date where ≤1 symbol traded *and* the
   date is present in ≥50% of the panel). This is a correct data-quality fix, not a
   threshold relaxation — the 99% bar is unchanged. *Verified:* 2025-12-19 is **not**
   excluded (7 symbols traded → a real day where a few names have a Yahoo gap), so the fix
   does not over-exclude.
2. Two data-quality artifacts caught and fixed during measurement (no result impact, logged
   for honesty): Yahoo `range=max&interval=1d` returns a **sparse** series for pre-2015
   ETFs (corrupted the trailing-252 slice → switched to `range=2y`); and null-volume rows
   must be distinguished from genuine zero-volume.

## Result (trailing 252 sessions, artifact dates excluded)

| Symbol | Exposure | Median ₹cr/day | Continuity | Gate ≥₹5cr |
|---|---|---:|---:|:--:|
| SILVERBEES | Silver | 618.4 | 100.0% | **PASS** |
| GOLDBEES | Gold | 328.0 | 100.0% | **PASS** |
| LIQUIDBEES | Cash | 298.8 | 99.6% | **PASS** |
| NIFTYBEES | India large-cap | 168.8 | 99.6% | **PASS** |
| SETFGOLD | Gold | 68.6 | 100.0% | **PASS** |
| ITBEES | India IT | 38.1 | 100.0% | **PASS** |
| BANKBEES | India banks | 37.8 | 99.6% | **PASS** |
| JUNIORBEES | India Next50 | 24.2 | 99.6% | **PASS** |
| MON100 | US equity (Nasdaq100) | 19.4 | 99.6% | **PASS** |
| SETFNIF50 | India large-cap | 17.5 | 99.6% | **PASS** |
| MID150BEES | India midcap | 16.8 | 100.0% | **PASS** |
| MIDCAPETF | India midcap | 5.3 | 100.0% | **PASS** |

(Measured 2026-06-28; window from ~2025-06-17.)

## Finding: turnover is NOT the binding constraint at ₹1 lakh

**Every candidate clears ₹5 cr/day by 1–120×.** At ₹1 lakh a leg's monthly turnover is a
rounding error against even the thinnest name. So the liquidity gate, on turnover, does
**not** shrink the universe. The constraints that actually shape it are downstream:

1. **Substitutes — don't double-count an exposure.** NIFTYBEES (₹169cr) ≫ SETFNIF50 (₹17cr);
   GOLDBEES (₹328cr) ≫ SETFGOLD (₹69cr); MID150BEES (₹17cr) ≫ MIDCAPETF (₹5cr). Keep the
   more-liquid of each pair.
2. **Thin cross-section / independence — the live risk.** Stripping substitutes, the distinct
   *drivers* are: Indian equity (NIFTYBEES; BANKBEES/ITBEES/JUNIORBEES/MID150 all ~0.8
   correlated to it), US equity (MON100), gold, silver, cash. Genuinely independent blocks
   ≈ **{Indian equity, US equity, precious metals, cash} ≈ 3–4**. This *passes* the spec's
   "<4 risk assets" count kill (§8), but it is exactly the "collapses into a macro tactical
   bet, not a cross-section" warning the spec raised against itself (§2). **Watch this.**
3. **History / DSR.** The youngest members cap the common backtest window — SILVERBEES
   (~2022) and the midcaps are the binding constraints; a precious-metals-inclusive basket
   gives ~4.5y common history, which tightens DSR. (Full per-symbol history depth to be
   pulled before Step 4 sizing.)

## Frozen tradeable universe (client-ratified — locked)

> **NIFTYBEES** (India large-cap), **BANKBEES** (India banks), **MON100** (US equity),
> **GOLDBEES** (gold), **SILVERBEES** (silver) **+ LIQUIDBEES** (cash) — 5 risk assets + cash.

Dropped: SETFNIF50, SETFGOLD, MIDCAPETF (inferior substitutes); ITBEES, JUNIORBEES,
MID150BEES (correlated Indian-equity breadth, not independent drivers).

**This list is frozen.** No alternative basket compositions will be tried (best-of-N trap,
spec rule 4); any later change to the universe counts against the DSR budget.

## Honest-N ledger (running)

| N | Choice | Notes |
|---:|---|---|
| 1 | Step 1 liquidity gate threshold (₹5cr median + 99% continuity, 252-session window) | this doc |

## Status of previously-owed items (resolved 2026-06-28)
- **Gate 2 max-drawdown cap** — **20% hard kill** (client-specified). Recorded in spec §5.
- **STT-on-ETF** — **resolved at the low end** per Zerodha's official charges page: equity
  legs (NIFTYBEES, BANKBEES) 0.001% sell-side only (~0.1 bps); GOLDBEES/SILVERBEES/
  LIQUIDBEES none; MON100 likely exempt. The ~20 bps fear is off. *Residual:* MON100
  confirmation (NSE STT-non-applicability report) + a contract-note final check before a
  trusted net Sharpe. New cost flag for Step 2: Zerodha's flat **DP charge (~₹13.5+GST per
  scrip per sell)** is ~10 bps on a ₹16k leg — likely the dominant per-rebalance cost at
  ₹1 lakh; model as a flat per-leg-sold fee.

## Next
Step 2 — populate the ETF cost model with **measured** spreads + confirmed STT, then Step 3
(build the fixed-weight equal-weight benchmark) **before** any ML. No backtest until costs
hold measured numbers and the benchmark exists.
