# P3T.2 — ETF universe + data

**Arc:** Phase 3T (cross-regime Turtle sweep). **Spec:** `SPEC_Turtle_TrendFollowing_CrossRegime.md`
§P3T.2, §2 Rung 3. **Status: COMPLETE.** Universe + backfill/verify wiring committed; the **Kite
daily backfill was run (2026-07-02)** — all sleeves pulled clean, the bond ticker finalized on the
data (see "Kite verification results"). No live trading, no orders; the pull is read-only historical
bars. The operator did the one-time manual login (TOTP); the agent ran the read-only backfill/DQ.

## What landed (code)

- **`config/etf_universe.yaml`** — both baskets, pinned (Ground Rule 2: config is the single
  source of truth; symbols are never hand-typed on the CLI).
- **`src/quant/research/etf/universe.py`** — the typed, validated loader (`load_etf_universe`,
  `EtfBasket`, `basket_symbols`), 7 unit tests. Mirrors the `load_universe` convention.
- **`scripts/backfill_etf.py`** / **`scripts/check_etf_data.py`** — thin operator shims that
  resolve the symbol list from the config and delegate to the *existing, unit-tested* backfill
  and DQ-check CLIs (`--interval day --tier parquet`). No new backfill engine — the reuse the
  spec promised holds.

## The two baskets (operator decision 2026-07-01: run BOTH, side by side, not a swap)

| Basket | Sleeves (role) |
|---|---|
| **frozen** (ratified — `docs/etf_rotation/step1`) | NIFTYBEES (India eq) · BANKBEES (India eq) · MON100 (US eq) · GOLDBEES (gold) · SILVERBEES (silver) · LIQUIDBEES (cash) |
| **spec_literal** (SPEC §2 literal) | NIFTYBEES (Nifty 50) · JUNIORBEES (Next 50) · GOLDBEES (gold) · **LTGILTBEES (bond/duration)** · MON100 (intl) |

**Bond-sleeve decision (agent's call, operator delegated) — FINALIZED on the data:** a **G-Sec
duration ETF**, not a cash-like or roll-down target-maturity leg (the frozen basket already holds
LIQUIDBEES as cash, so a cash-like bond sleeve would add nothing; the bond sleeve's job, SPEC §2
Rung 3, is genuine cross-asset **rate/duration** diversification). The provisional GSEC10IETF was
**rejected on the Kite backfill** — only 760 daily bars from 2022-12, which would cap the whole
spec_literal basket at ~2022. **LTGILTBEES (Nippon Long Term Gilt) chosen** — 2262 clean daily bars
from 2016-07, the longest + most complete gilt history on Kite; SETF10GILT was gappier with a >25%
tick. A pre-run **data-availability** choice (made before any backtest), not a best-of-N search.

## Honest-N consequence

Two baskets × {3a classic-breakout, 3b relative-momentum} = **4** ETF baseline trials (not 2), so
the §6 baseline ledger grows **6 → 8**. Freeze that in P3T.6 and carry it in both the primary and
the conservative (+prior-23) DSR. Running two baskets is a mild multiple-comparison surface — the
honest-N deflation is exactly what charges for it.

## Operator runbook (Kite pull — needs today's morning session seed)

On the static-IP engine host, after the morning Kite auth (`scripts/kite_morning_auth.py`):

```bash
# 1) backfill both baskets' daily bars into the Parquet archive (union fetched once)
uv run python scripts/backfill_etf.py --start 2016-01-01 --end 2026-06-30 \
    --request-token <today's request_token>

# 2) read them back and run the P1.9 data-quality dashboard (read-only)
uv run python scripts/check_etf_data.py --start 2016-01-01 --end 2026-06-30
```

(The bond comparison above also backfilled the two gilt alternates LTGILTBEES + SETF10GILT via the
generic `run_backfill.py --symbols … --interval day` — the same reused engine.)

## Kite verification results (2026-07-02)

All 10 candidate tickers resolve in the Kite NSE instruments dump and backfilled clean daily bars
through 2026-06-30 (0 non-positive prices, 0 return spikes >25% except one in the rejected
SETF10GILT):

| symbol | role | bars | history start | note |
|---|---|---:|---|---|
| NIFTYBEES | India eq | 2595 | 2016-01 | |
| JUNIORBEES | India eq | 2595 | 2016-01 | |
| BANKBEES | India eq | 2595 | 2016-01 | |
| MON100 | US eq | 2594 | 2016-01 | intl feeder |
| GOLDBEES | gold | 2594 | 2016-01 | |
| SILVERBEES | silver | 1088 | **2022-02** | caps the *frozen* basket window |
| LIQUIDBEES | cash | 2595 | 2016-01 | ~flat ≈ ₹1000 (correct) |
| **LTGILTBEES** | **bond** | **2262** | **2016-07** | **chosen** — longest/cleanest gilt |
| ~~GSEC10IETF~~ | bond | 760 | 2022-12 | rejected — too short |
| ~~SETF10GILT~~ | bond | 2019 | 2016-06 | rejected — gappier, one >25% tick |

**Per-basket common backtest window (bounded by the youngest sleeve):**
- **frozen** → **2022-02** onward (~4.4y), capped by **SILVERBEES**.
- **spec_literal** (with LTGILTBEES) → **2016-07** onward (**~10y**) — materially longer history, so
  the spec-literal basket is the better-powered one for DSR. A genuine, useful asymmetry to carry
  into P3T.9.

**Storage note (flag for P3T.3).** The Parquet archive partitions by **day**, so daily bars land as
~2,500 one-row files per symbol; on Windows both the backfill *and* a naive per-partition
`read_bars` loop are pathologically slow (both timed out at 2 min). Reading via
`pyarrow.dataset(...).to_table()` in one shot is fast. P3T.3's daily backtests must read that way (or
consolidate to one file per symbol) — do **not** loop `read_bars` per partition.

**Residual for P3T.4:** the real per-leg **spread/impact** (esp. LTGILTBEES and MON100) is still an
assumption — it must be an explicit cost charge, not mid. History + cleanliness are now confirmed;
spread is the remaining ETF-cost unknown.

## Rung-2 stock universe — CONFIRMED PRESENT (no pull needed)

- **56 survivorship-aware Nifty names** in the Kite→hygiene→Parquet archive (`data/parquet/symbol=*`,
  minute bars from 2021-06-24), the Cycle-5 set defined in `scripts/run_complete_pipeline.py`.
- Plus the **survivorship-free NSE bhavcopy daily panel** (`data/nifty_panel`, 2016–2024,
  split-adjusted) from Phase 3X.
- *Open (P3T.3/P3T.8):* Rung 2's daily Turtle needs **daily adjusted OHLC**. Either resample the
  minute archive (then corporate-action-adjust) or use the bhavcopy daily panel — a P3T.3 data-
  sourcing decision, not a P3T.2 blocker.

## Done-when (spec P3T.2)

- [x] ETF baskets defined + validated (both), config-pinned.
- [x] Backfill + DQ path wired via the existing Kite→hygiene→Parquet CLIs (daily).
- [x] **ETFs have clean daily history + DQ green** — all 8 union sleeves + gilt alternates pulled
      clean through 2026-06-30 (discharges the "does Kite serve clean ETF bars" open item).
- [x] Rung-2 stock universe confirmed present.

## Residual open items (carried to P3T.4 / go-live)

- **Thin-ETF spread/impact** — the real per-leg spread (esp. LTGILTBEES and MON100) must be an
  explicit charge in P3T.4, not assumed mid. (History + cleanliness are now confirmed; spread isn't.)
- **MON100 STT-exemption** + a live spread confirmation (owed since the etf-rotation arc).
- **Corporate-action adjustment** — the pulled bars are Kite's as-traded daily series; confirm
  split/bonus adjustment for the equity ETFs before Rung-3 breakouts (SPEC §1: adjusted only). ETFs
  rarely split, but verify (a P3T.3 hygiene step).
