# Step 2 — ETF cost model (multi-ETF rotation)

**Track:** `etf-rotation`. Spec: `SPEC_MultiETF_Rotation.md` §6.
**Status:** Populated with **provisional** numbers (client opted to use web estimates instead of the live Kite spread job). Code: `src/quant/research/etf/costs.py` (pure, 7 unit tests, mypy-strict clean). `default_cost_model()` carries the frozen-universe profiles.

## Inputs

**Statutory / broker charges** (Zerodha published rates, 2026 — [zerodha.com/charges](https://zerodha.com/charges/)):
- Brokerage: **₹0** (ETF delivery).
- STT: **0.001% sell-side** on equity ETFs (NIFTYBEES, BANKBEES); **0** on GOLDBEES/SILVERBEES/LIQUIDBEES; MON100 **0** (international, likely exempt — *residual confirmation owed*).
- Exchange txn: **0.00325%** of turnover. SEBI: **0.0001%**. Stamp: **0.015% buy-side**. GST: **18%** on (brokerage+txn+SEBI).
- **DP charge: ₹13.50 + 18% GST = ₹15.93 flat per leg sold.** The decisive one at this scale.

**Bid-ask spreads — PROVISIONAL, conservative web/liquidity-tier estimates (NOT live-measured):**

| Leg | spread (bps) | TER (annual) | STT sell (bps) |
|---|---:|---:|---:|
| LIQUIDBEES | 2.0 | 0.27% | 0 |
| NIFTYBEES | 3.0 | 0.04% | 0.1 |
| BANKBEES | 4.0 | 0.19% | 0.1 |
| GOLDBEES | 5.0 | 0.82% | 0 |
| SILVERBEES | 5.0 | 0.50% | 0 |
| MON100 | 20.0 | 0.58% | 0 |

Spreads are rounded **up** on purpose: if the edge survives inflated costs the result is robust; if it dies, it's an honest NO-GO. They are assumptions, not measurements — see residual below.

## Worked round-trip cost at ₹1 lakh / 6 legs (~₹16,667/leg)

| Leg | spread bps | **round-trip bps** |
|---|---:|---:|
| LIQUIDBEES | 2.0 | 13.8 |
| NIFTYBEES | 3.0 | 14.9 |
| BANKBEES | 4.0 | 15.9 |
| GOLDBEES | 5.0 | 16.8 |
| SILVERBEES | 5.0 | 16.8 |
| MON100 | 20.0 | 31.8 |

## Finding: the flat DP charge, not the spread, sets the cost floor

At ₹1 lakh the **DP charge alone is ~9.5 bps** of a ₹16.7k leg; with stamp (1.5 bps buy) the statutory floor is **~11–12 bps round-trip before spread**. So even the tightest ETF costs **~14 bps round-trip**, and MON100 ~32 bps — an order of magnitude above the "ETFs are ~3 bps" prior. Direct implications:
- **Rebalance frequency is the dominant design lever.** A monthly full-basket rebalance that turns over ~6 legs is plausibly ~0.5–1%+ of capital per year in DP+spread alone; weekly/daily would be ruinous at this size.
- This is a per-leg-sold *flat* fee, so it **shrinks in bps as capital grows** — the strategy is structurally cheaper at higher capital, a Gate-2 consideration.
- It sharpens the benchmark test: the fixed-weight benchmark pays the *same* DP/spread on its (rarer) rebalances, so the ML must beat it on **excess** after both pay this regressive cost.

## Residuals before a trusted net Sharpe (flagged, per spec §6)
- **Live spread confirmation** — current spreads are web estimates. The sampler (`scripts/etf_spread_sampler.py`) remains available to confirm in one market session if/when wanted; until then every net Sharpe carries this assumption.
- **MON100 STT** — confirm exempt (NSE STT-non-applicability report / a note).
- **Contract-note final check** on the statutory rates.

## Honest-N note
Cost-model parameter choices (the provisional spreads) are modeling assumptions held fixed, not search trials. The **rebalance frequency** chosen in Step 4 *is* a trial and counts toward N.

## Next
Step 3 — build the fixed-weight equal-weight monthly-rebalance benchmark, net of this cost model. Only then Step 4 (ML rotation). No backtest result is trusted until spreads are live-confirmed.
