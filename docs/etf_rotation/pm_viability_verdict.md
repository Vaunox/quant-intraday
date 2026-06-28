# Risk-managed PM viability — verdict: **NO-GO**

**Pre-registration:** `docs/etf_rotation/pm_viability_prereg.md`. **Status:** COMPLETE, **NO-GO.**
**Code:** `src/quant/research/etf/portfolio.py` (4 unit tests, mypy-strict) + `scripts/etf_portfolio.py` (cleans data, runs the committed config). Reproduce: `uv run python scripts/etf_portfolio.py`.

## Result (committed config: vol-target 10% / 63d, 4 risk + cash, 2016–26, CLEAN data)

| Line | CAGR | Sharpe | maxDD |
|---|---:|---:|---:|
| **PM (vol-target risk-parity)** | 13.88% | 1.34 | **−28.75%** |
| Equal-weight benchmark | 15.92% | 1.54 | −22.56% |
| Buy-hold NIFTYBEES | 13.03% | 0.91 | −36.34% |

Gate-2 (pre-committed): **(1) maxDD ≤ 20% → FAIL (−28.75%)**; (2) beat buy-hold NIFTYBEES → PASS; (3) beat cash → PASS. **One fail = NO-GO.**

## Findings
1. **No long-only ETF book here clears the 20% drawdown cap over a full cycle.** The PM draws down −28.75% and even the diversified equal-weight basket −22.56% — both breach 20%. The 2020 COVID crash alone takes a diversified long-only basket past −20%. Without leverage to *de*-risk faster (and the charter forbids leverage here) or a much broader/uncorrelated universe, the 20% cap is structurally unreachable.
2. **The risk-managed PM is dominated by dumb equal-weight on *both* axes** — worse Sharpe (1.34 vs 1.54) *and* worse drawdown (−28.75% vs −22.56%). The vol-targeting/inverse-vol machinery *subtracted* value: it concentrated into low-vol legs and de-risked procyclically. Same lesson as the ML rotation — sophistication lost to the simple basket.

**Answer to "did we ever have a viable portfolio manager?": No.** The simple equal-weight basket is the best PM in this set (Sharpe ~1.5), but it still **breaches the 20% DD cap** over a representative window, and neither the ML overlay nor a standard risk-managed overlay improves on it.

## DATA-QUALITY CORRECTION (important)
While running this test I found **Yahoo adjusted-close bad ticks** — isolated ~90–99% one-day collapses that immediately reverse (NIFTYBEES/BANKBEES/GOLDBEES on 2019-12-19..22; MON100 on 2021-06-17..20). They fake enormous drawdowns and distort returns.

**Impact:** every prior result using a **>2022 window** (the 10y and 2020–26 sensitivity/variant runs) was contaminated on the drawdown/return dimension. The clean fix is a centered-median bad-tick filter (~2 ticks/series dropped), now applied in `scripts/etf_portfolio.py`.

**Corrections to earlier claims:**
- The 10y equal-weight benchmark is **Sharpe 1.54** (clean) — **not** the "0.49–0.57 / −45 to −55% DD" reported earlier; those were the bug. The basket is robustly ~1.5 Sharpe over 10y, not just 2022–26.
- Therefore my earlier statement that "the 2022–26 Sharpe 1.53 was a recent precious-metals artifact" was **wrong** — it was a data artifact in the *10y* series, not a real collapse. The benchmark is genuinely strong over a full decade.
- The contaminated variant runs in `step3_benchmark.md` and `step4_5_verdict.md` are flagged there. **The core ML NO-GO stands and is reinforced** — it was measured on the *clean* 2022–26 window, against a benchmark now confirmed robustly strong over 10y too.

## Outcome
Documented **NO-GO**: no economically viable portfolio manager (ML, risk-managed, or simple) clears the ₹1 lakh / 20%-DD bar over a representative window with this universe. No live trading, $0 risked. A genuine path would need a broader, less-correlated, possibly less-liquid universe (more capital) and/or a revised drawdown mandate — a fresh pre-registered question.
