# Phase 2R · Cycle 5 — Previous project config under honest harness (diagnostic)

**Subtask:** P2R.2 Cycle 5 (budget: 2 cycles remain; this is the operator-requested
empirical test of the previous project's claimed 60% returns).  See the
[cycle-4 finding](cycle-4_finding.md), [budget](budget.md), and the
[phase closeout](closeout.md) for context on why the stop criterion was already met.

**Purpose:** Validate the hypothesis that the previous project
(`quant-ensemble-trader-main`) reported artificially inflated returns due to:
(1) understated costs (0.02% vs 0.14% realistic CNC round-trip),
(2) selection-of-42-bots bias (best-of-42 without DSR correction),
(3) single-path variance (no CPCV),
(4) GAN augmentation leaking into the validation period.

Rather than accepting this on inference, run the same feature / universe configuration
through the current project's honest kill-gate and observe the result.

**Commitment:** this is Cycle 5 of 6; operator authorised it explicitly.  Results do NOT
re-open the P2.9 kill-gate or Phase 3 — they either (A) confirm the artifacts hypothesis
(supporting the closeout verdict), or (B) find real signal, which would warrant a
deliberate operator decision to restart a new research program.

---

## Method

**Universe:** 49 NSE stocks from the previous project's `TICKER_LIST` (Nifty-50 large-caps,
daily OHLCV from yfinance, 2010-2026, split/dividend adjusted).  Stocks with <500 usable
trading days are dropped.

**Frequency:** daily close-to-close (overnight CNC hold; no intraday MIS square-off).

**Features:** 12 technical indicators (TA-Lib equivalents of the previous project's
stockstats indicators) + India VIX.  Exactly:

| indicator | implementation | notes |
|---|---|---|
| `macd` | `talib.MACD(close, 12, 26, 9)[0]` | MACD line |
| `boll_ub` | `talib.BBANDS(close, 20, 2)[0]` | upper band |
| `boll_lb` | `talib.BBANDS(close, 20, 2)[2]` | lower band |
| `rsi_30` | `talib.RSI(close, 30)` | RSI-30 (previous project used 30, not 14) |
| `cci_30` | `talib.CCI(H, L, C, 30)` | |
| `dx_30` | `talib.DX(H, L, C, 30)` | ADX/DMI directional movement |
| `close_30_sma` | `talib.SMA(close, 30)` | |
| `close_60_sma` | `talib.SMA(close, 60)` | |
| `wr_30` | `talib.WILLR(H, L, C, 30)` | Williams %R |
| `atr_30` | `talib.ATR(H, L, C, 30)` | |
| `mfi_30` | `talib.MFI(H, L, C, vol, 30)` | money flow index |
| `vwma_30` | `(C*V).rolling(30).sum() / V.rolling(30).sum()` | manual |
| `vix` | `yfinance.download("^INDIAVIX")` | |

Sentiment = 0 (unchanged from the previous project; excluded from the model features).

**Labels:** daily triple-barrier (inlined in `scripts/run_cycle5_diagnostic.py`, not the
existing session-based `TripleBarrierLabeler` which is intraday MIS).

- Volatility: 20-day rolling std of daily log-returns (point-in-time; no lookahead).
- Upper / lower barriers: ±max(1.5σ, 0.002) around the event bar's close.
- Vertical barrier: 5 trading days.
- Tie resolution (both barriers touched in the same bar): stop wins (conservative).
- Binary target: `label = 1` iff take-profit was reached first.

**Cost model:** Indian CNC (Zerodha), round-trip ~0.14% (conservative).

| component | rate | leg |
|---|---|---|
| Brokerage | 0% | both |
| STT | 0.1% | sell |
| Exchange txn | 0.00345% | both |
| SEBI | 0.0001% | both |
| Stamp duty | 0.015% | buy |
| GST | 18% on (exchange + SEBI) | both |

Round-trip from formula: ~0.123%; operator estimate ~0.14% (incl. depository charges).
Script uses 0.14%.

**Model:** existing cross-family ensemble — LightGBM + XGBoost + logistic + GMM regime
gate (3 regimes) + rank-averaging meta — identical to P2A.6/P2.8 (`cross_family_estimators`,
`evaluate_ensemble_under_cpcv`).  No architectural changes.  Smoke config: `num_boost_round=80`.

**No GAN augmentation.** Trained on real data (yfinance), proper purged splits.

**Validation:** smoke CPCV 6×2 → φ=5 paths, embargo=1%.  DSR (N=5 cumulative trials
across cycles 3–5).  PBO (CSCV, S=16).  Periods/year=252.  MLflow experiment `p2r-cycle5`.

**Script:** `scripts/run_cycle5_diagnostic.py`

**Pooling:** each stock's events are placed on a synthetic timeline with a 10-day gap
between symbols (> 5-day vertical barrier → no label window spans two symbols).

---

## What this cycle does NOT test

- The previous project's 42-bot RL architecture (replaced by the current project's ensemble).
- GAN-augmented training (deliberately excluded to isolate the signal question).
- Short selling (the current project's CPCV allows long/short; a long-only clip would
  be even worse if there's no gross signal).

## Pass / continue / stop routing (pre-committed)

| net annualised CPCV median path-Sharpe | routing |
|---|---|
| > +1.0 | PASS — triggers full P2.8 robustness battery; this becomes the new cycle-5 artifact |
| +0.3 to +1.0 | MARGINAL — operator decision: is this a new research program? |
| < +0.3 | CONFIRMS CLOSEOUT — the previous project's 60% return was a measurement artifact |

The finding document is `cycle-5_finding.md` (populated after the run).
