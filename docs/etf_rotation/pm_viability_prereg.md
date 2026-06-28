# PRE-REGISTRATION — Risk-managed portfolio-manager viability (no ML)

**Track:** `etf-rotation` (new sub-question). **Status:** committed BEFORE any scoring of this rule.
**Why:** the ML-rotation question is settled (NO-GO). This asks the *different* question the client actually cares about — **is there a deployable, economically viable portfolio manager at ₹1 lakh?** — judged purely on Gate-2 economics, with ML set aside.

> Honesty caveat (stated up front): this data has already been explored across many universe/window variants, so a clean pre-registration is impossible — prior knowledge contaminates it. To minimise that, the rule below is a **single, convention-default, parameter-fixed** allocation (NOT tuned/searched), judged on the **longest, hardest window** (10y, deliberately *not* the favourable 2022–26), with one committed universe. Any apparent pass still gets the honest-N skepticism the 3-ETF run taught us.

## Hypothesis
A standard **volatility-targeted risk-parity** allocator (no ML, no return forecasting) is economically viable: it **beats passive net of cost while holding max drawdown ≤ 20%.**

## The rule (COMMITTED — convention-default, not tuned)
- **Weights:** inverse-volatility (risk-parity) across the risk assets, monthly.
- **Risk control:** portfolio **target vol 10% annualised** via gross-exposure scaling — gross `G = min(1, target_vol / trailing_portfolio_vol)`; the `(1−G)` residual sits in cash. **Long/flat only, no leverage (G ≤ 1).** This is the drawdown-control mechanism.
- **Vol lookback:** 63 sessions (≈3 months). **Rebalance:** month-end.
- All parameters are conventional defaults, fixed a priori — no grid, no search.

## Universe (COMMITTED)
`NIFTYBEES, BANKBEES, MON100, GOLDBEES` + `LIQUIDBEES` (cash). 4 risk drivers incl. a gold diversifier (≥4, clears the §8 kill). Silver excluded — its ETF only began in 2022 and would cap the window.

## Window (COMMITTED)
**2016-06-27 → 2026-06-26 (~10y)** — the longest feasible, and deliberately the *hard* window (includes the 2018 mid-cap bear, the 2020 COVID crash), not the flattering recent stretch.

## Costs (COMMITTED)
Step 2 cost model (provisional spreads + flat DP charge); cash yield 6%.

## Gate-2 pass conditions (COMMITTED — ALL required)
1. **Max drawdown ≤ 20%** (the risk-management claim; the whole point of the vol target).
2. **Net Sharpe AND CAGR > buy-and-hold NIFTYBEES** (beat passive, the honest floor).
3. **Net CAGR > 6%** (beat parked cash).
- Reported, NOT pass conditions: comparison vs the equal-weight benchmark; and vs the client's 30–35% target (treated as aspirational — already known unrealistic for an unlevered ETF book).

## Verdict logic
All of 1–3 pass → **viable PM** (proceed to a proper, separately-validated build). Any fail → **NO-GO**, documented. A pass that depends on the favourable window or vanishes under honest scrutiny is a NO-GO.
