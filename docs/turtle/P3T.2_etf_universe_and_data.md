# P3T.2 — ETF universe + data

**Arc:** Phase 3T (cross-regime Turtle sweep). **Spec:** `SPEC_Turtle_TrendFollowing_CrossRegime.md`
§P3T.2, §2 Rung 3. **Status:** universe + backfill/verify wiring **DONE and committed**; the
actual Kite pull + DQ report is **operator-pending** (see runbook). No live trading, no orders.

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
| **spec_literal** (SPEC §2 literal) | NIFTYBEES (Nifty 50) · JUNIORBEES (Next 50) · GOLDBEES (gold) · **GSEC10IETF (bond/duration)** · MON100 (intl) |

**Bond-sleeve decision (agent's call, operator delegated):** a **G-Sec duration ETF**, not a
cash-like or roll-down target-maturity leg. Rationale: the frozen basket already holds LIQUIDBEES
as cash, so a cash-like bond sleeve would add nothing; the bond sleeve's whole job (SPEC §2 Rung 3)
is to supply genuine cross-asset **rate/duration** diversification — the mechanism behind trend-
following's convex payoff. **GSEC10IETF is PROVISIONAL** pending the Kite verification run (Indian
G-Sec ETFs are thin, so this is the ticker most likely to sink Rung 3 on spread/impact — a P3T.4
concern). If Kite lacks clean history/liquidity for it, fall back to **SETFGILT** or **LTGILTBEES**
(a data-availability swap, documented, not a search trial).

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

Record, per ETF, from step 2's output: first/last session, observed vs expected sessions,
intraday-gap / missing-day / bad-tick counts. Flag any thin/young sleeve (expected: SILVERBEES
~2022 start; **GSEC10IETF** the liquidity unknown) — that flag feeds the P3T.4 spread/impact charge.

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
- [ ] **~5 ETFs have clean adjusted daily history + DQ green** — *operator run pending* (discharges
      the flagged "does Kite serve clean ETF bars" open item).
- [x] Rung-2 stock universe confirmed present.

## Residual open items (carried to P3T.4 / go-live)

- **GSEC10IETF ticker + liquidity** — confirm Kite serves it with adequate clean history and a
  tradeable spread; else fall back (SETFGILT / LTGILTBEES).
- **Thin-ETF spread/impact** — the real per-leg spread (esp. the bond ETF and MON100) must be an
  explicit charge in P3T.4, not assumed mid.
- **MON100 STT-exemption** + a live spread confirmation (owed since the etf-rotation arc).
