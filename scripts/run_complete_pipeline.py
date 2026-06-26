#!/usr/bin/env python
"""Complete gated pipeline (Step 1: 8-name validated + yfinance comparison).

Brings the Cycle-5 strategy onto this project's own gated path and wires the four
previously-dormant components, then runs a smoke CPCV on BOTH data sources for the same
8 names so the data-source effect is isolated with zero universe confound.

Gates closed vs Cycle 5:
  * **Data** — validated arm reads the Kite->P1.5-hygiene->Parquet archive (bad-tick filter)
    and resamples to daily; yfinance arm is the un-validated control. Same 8 names, same code.
  * **Features** — computed through the P1.7 harness functions (returns/vol/atr/parkinson +
    technical.py indicators), all registered in the P1.8 adversarial leakage suite.
  * **Leakage** — every feature column is a leakage-suite-covered function.

Components wired:
  1. **MetaLabeler** (P2.5) — momentum primary side -> bet/no-bet meta-label; the meta-model
     sizes the bet (position = P(bet) on the side-aware return), replacing position = 2p-1.
  2. **Cross-sectional** (P1.7) — cross_sectional_rank + sector_neutral_zscore across the 8 names.
  3. **Frac-diff** (P2.5 min_ffd) — the non-stationary price-level columns (SMAs, VWMA, raw
     Bollinger bands) are fractionally differenced to their minimum stationary order.
  4. **Honest DSR N** — cumulative distinct trials counted from the MLflow p2r* experiments
     (not the hardcoded 5).

Two strategies are evaluated per arm under a smoke CPCV:
  * **DIRECT** — the Cycle-5-comparable 2p-1 ensemble on direction labels (isolates the
    data-source effect against the +0.662 baseline).
  * **META** — the complete wired pipeline (meta-labeled, cross-sectional, frac-diff).

Usage::

    python scripts/run_complete_pipeline.py            # both arms, MLflow
    python scripts/run_complete_pipeline.py --no-mlflow
    python scripts/run_complete_pipeline.py --arm validated   # single arm

Hold commits; hold for review before the full battery (operator instruction).
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# The quant.* imports below intentionally follow the sys.path bootstrap above (this is a
# research-script entry point, not an installed module), so E402 does not apply here.
# ruff: noqa: E402
from quant.core.calendar import IST
from quant.core.config import Config, load_config
from quant.data.features import (
    atr,
    bollinger_bands,
    bollinger_percent_b,
    cci,
    cross_sectional_rank,
    directional_index,
    log_return,
    macd_histogram,
    macd_line,
    money_flow_index,
    parkinson_volatility,
    realized_volatility,
    rsi,
    sector_neutral_zscore,
    sma,
    trend_strength,
    volatility_regime,
    volume_weighted_ma,
)
from quant.data.hygiene.bad_ticks import BadTickFilter
from quant.data.store import serde
from quant.data.store.parquet import create_parquet_archive
from quant.research.features_research.frac_diff import FracDiffError, frac_diff, min_ffd
from quant.research.labeling.cusum import cusum_events
from quant.research.labeling.meta import META_LABEL, MetaLabeler, momentum_side
from quant.research.labeling.meta import RETURN as META_RETURN
from quant.research.labeling.triple_barrier import LABEL, RETURN, TripleBarrierLabeler
from quant.research.models.ensemble import build_ensemble
from quant.research.models.estimators import cross_family_estimators
from quant.research.models.evaluation import CPCVEvaluation, evaluate_ensemble_under_cpcv
from quant.research.pipeline.dataset import resample_bars
from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution
from quant.research.validation.metrics import deflated_sharpe_ratio_from_returns

# ---------------------------------------------------------------------------
# Universe (the 8 validated names) + sectors (from config/universe.yaml)
# ---------------------------------------------------------------------------
# Survivorship-aware Nifty-50 union over 2021-06→2026-06 (58 names): today's 50 + the
# members removed during the window (SHREECEM, LTIM, DIVISLAB, UPL, BPCL, BRITANNIA,
# HEROMOTOCO, INDUSINDBK). HDFC Ltd (delisted Jul-2023 merger) excluded — Kite cannot serve it
# (empirically confirmed); the one residual gap, and the harmless merger case.
SECTORS: dict[str, str] = {
    # Financials (12)
    "HDFCBANK": "Financials",
    "ICICIBANK": "Financials",
    "AXISBANK": "Financials",
    "KOTAKBANK": "Financials",
    "SBIN": "Financials",
    "BAJFINANCE": "Financials",
    "BAJAJFINSV": "Financials",
    "SBILIFE": "Financials",
    "HDFCLIFE": "Financials",
    "JIOFIN": "Financials",
    "SHRIRAMFIN": "Financials",
    "INDUSINDBK": "Financials",
    # IT (6)
    "TCS": "IT",
    "INFY": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    "WIPRO": "IT",
    "LTIM": "IT",
    # Energy (4)
    "RELIANCE": "Energy",
    "ONGC": "Energy",
    "BPCL": "Energy",
    "COALINDIA": "Energy",
    # Auto (6)
    "MARUTI": "Auto",
    "M&M": "Auto",
    "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto",
    "TATAMOTORS": "Auto",
    # Healthcare (6)
    "SUNPHARMA": "Healthcare",
    "CIPLA": "Healthcare",
    "DRREDDY": "Healthcare",
    "DIVISLAB": "Healthcare",
    "APOLLOHOSP": "Healthcare",
    "MAXHEALTH": "Healthcare",
    # Consumer (8)
    "ITC": "Consumer",
    "HINDUNILVR": "Consumer",
    "NESTLEIND": "Consumer",
    "BRITANNIA": "Consumer",
    "TATACONSUM": "Consumer",
    "TITAN": "Consumer",
    "TRENT": "Consumer",
    "ETERNAL": "Consumer",
    # Materials (8)
    "TATASTEEL": "Materials",
    "JSWSTEEL": "Materials",
    "HINDALCO": "Materials",
    "ULTRACEMCO": "Materials",
    "GRASIM": "Materials",
    "SHREECEM": "Materials",
    "ASIANPAINT": "Materials",
    "UPL": "Materials",
    # Industrials (5)
    "LT": "Industrials",
    "BEL": "Industrials",
    "ADANIENT": "Industrials",
    "ADANIPORTS": "Industrials",
    "INDIGO": "Industrials",
    # Infra/Utilities (3)
    "NTPC": "Infra",
    "POWERGRID": "Infra",
    "BHARTIARTL": "Infra",
}
SYMBOLS: list[str] = sorted(SECTORS)
YF_TICKER: dict[str, str] = {s: f"{s}.NS" for s in SYMBOLS}

DATA_START = datetime(2021, 6, 24, tzinfo=IST)
DATA_END = datetime(2026, 6, 24, tzinfo=IST)
DAILY_MINUTES = 1440

# Labeling (daily): 5-day vertical, vol-scaled barriers, CUSUM events
VERTICAL_DAYS = 5
CUSUM_THRESHOLD = 0.01
VOL_WINDOW = 20

# Costs / CPCV smoke knobs.
# Honest CNC (delivery) round-trip transaction cost — NOT Cycle-5's understated 0.14%:
#   STT          0.10% x 2 legs            = 0.200%   (delivery STT is both buy & sell)
#   Stamp duty   0.015% buy leg            = 0.015%
#   Exchange txn ~0.00297% x 2 legs        ~ 0.006%
#   SEBI + GST   (on a zero-brokerage DP)  ~ 0.001%
#   ----------------------------------------------
#   honest CNC round trip                  ~ 0.222%  -> 0.0022  (vs Cycle-5's 0.0014)
CNC_ROUND_TRIP = 0.0022
PERIODS_PER_YEAR = 252
ANNUALISER = float(np.sqrt(PERIODS_PER_YEAR))
CPCV_GROUPS = 6
CPCV_TEST_GROUPS = 2
CPCV_EMBARGO = 0.01
BOOST_ROUNDS = 120
POOL_GAP_DAYS = 10

# Price-level feature columns that get fractionally differenced (non-stationary)
PRICE_LEVEL_COLUMNS = ["sma_30", "sma_60", "vwma_30", "boll_ub", "boll_lb"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _canonical_daily_from_yf(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Build a canonical-schema daily bars frame from a yfinance OHLCV download."""
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    raw = raw.rename(columns={c: c.lower() for c in raw.columns})
    idx = pd.to_datetime(raw.index)
    # Label at 00:00 IST to match the validated daily resample convention.
    ts = (
        pd.DatetimeIndex(idx).tz_localize(IST)
        if idx.tz is None
        else pd.DatetimeIndex(idx).tz_convert(IST)
    )
    ts = ts.normalize()
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": symbol,
            "open": raw["open"].to_numpy(dtype="float64"),
            "high": raw["high"].to_numpy(dtype="float64"),
            "low": raw["low"].to_numpy(dtype="float64"),
            "close": raw["close"].to_numpy(dtype="float64"),
            "volume": raw["volume"].fillna(0).to_numpy().round().astype("int64"),
        }
    )
    frame = frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return serde.ensure_bars_schema(frame)


def load_validated_daily(symbol: str, config: Config) -> pd.DataFrame:
    """Validated arm: Parquet archive -> bad-tick hygiene -> daily resample."""
    archive = create_parquet_archive(config.storage)
    bars = archive.read_bars(symbol, DATA_START, DATA_END)
    if bars.empty:
        return bars
    clean = BadTickFilter.from_config(config.hygiene).filter(symbol, bars).clean
    return resample_bars(clean, DAILY_MINUTES)


def load_yfinance_daily(symbol: str) -> pd.DataFrame:
    """Yfinance control arm: daily OHLCV download -> canonical schema."""
    raw = yf.download(
        YF_TICKER[symbol], start="2021-06-24", end="2026-06-24", progress=False, auto_adjust=True
    )
    if raw.empty:
        return serde.empty_bars_frame()
    return _canonical_daily_from_yf(symbol, raw)


# ---------------------------------------------------------------------------
# Feature engineering (through P1.7 harness functions + frac-diff)
# ---------------------------------------------------------------------------


def compute_feature_matrix(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute the gated feature matrix for one symbol's daily bars.

    All columns come from leakage-suite-covered P1.7 harness functions. Price-level columns
    are fractionally differenced (min_ffd) to their minimum stationary order.
    """
    b = serde.sort_bars(serde.ensure_bars_schema(bars))
    idx = pd.DatetimeIndex(b[serde.TIME_COLUMN], name=serde.TIME_COLUMN)

    cols: dict[str, pd.Series] = {}
    # Core (P1.6) — daily-appropriate
    for h in (1, 3, 5, 10):
        cols[f"ret_{h}"] = pd.Series(log_return(b, h).to_numpy(), index=idx)
    cols["rvol_20"] = pd.Series(realized_volatility(b, 20).to_numpy(), index=idx)
    cols["atr_14"] = pd.Series(atr(b, 14).to_numpy(), index=idx)
    cols["parkinson_20"] = pd.Series(parkinson_volatility(b, 20).to_numpy(), index=idx)
    # Technical oscillators (bounded / ~stationary)
    cols["rsi_30"] = pd.Series(rsi(b, 30).to_numpy(), index=idx)
    cols["macd_hist"] = pd.Series(
        macd_histogram(b, fast=12, slow=26, signal=9).to_numpy(), index=idx
    )
    cols["macd_line"] = pd.Series(macd_line(b, fast=12, slow=26, signal=9).to_numpy(), index=idx)
    cols["bbands_pb"] = pd.Series(
        bollinger_percent_b(b, period=20, num_std=2.0).to_numpy(), index=idx
    )
    cols["cci_30"] = pd.Series(cci(b, 30).to_numpy(), index=idx)
    cols["dx_30"] = pd.Series(directional_index(b, 30).to_numpy(), index=idx)
    cols["mfi_30"] = pd.Series(money_flow_index(b, 30).to_numpy(), index=idx)
    # Price-level columns (to be frac-diffed)
    cols["sma_30"] = pd.Series(sma(b, 30).to_numpy(), index=idx)
    cols["sma_60"] = pd.Series(sma(b, 60).to_numpy(), index=idx)
    cols["vwma_30"] = pd.Series(volume_weighted_ma(b, 30).to_numpy(), index=idx)
    bb = bollinger_bands(b, period=20, num_std=2.0)
    cols["boll_ub"] = pd.Series(bb["boll_ub"].to_numpy(), index=idx)
    cols["boll_lb"] = pd.Series(bb["boll_lb"].to_numpy(), index=idx)

    feat = pd.DataFrame(cols, index=idx)
    # Frac-diff the price-level columns to their min stationary order (per symbol).
    for col in PRICE_LEVEL_COLUMNS:
        feat[col] = _fracdiff_column(feat[col])
    return feat


# Frac-diff search grid + truncation threshold. The grid starts at 0.2 (a tiny ``d`` has a
# very wide weight window that NaN-warms-up most of the series) and the wider 1e-3 threshold
# keeps windows to tens of bars, so a single column can't collapse the usable matrix.
_FFD_D_GRID = [round(0.1 * i, 1) for i in range(2, 11)]  # 0.2, 0.3, ..., 1.0
_FFD_THRESHOLD = 1e-3
_FFD_MIN_RETENTION = 0.5  # require the chosen d to retain >= half the (non-warmup) rows


def _fracdiff_column(col: pd.Series) -> pd.Series:
    """Replace a price-level column with its minimum-stationary fractional difference.

    Uses :func:`min_ffd` (the smallest stationary ``d``) over a bounded ``d`` grid + wide
    truncation threshold, with a retention guard: a degenerate wide-window solution that keeps
    less than half the data falls back to a fixed ``d=0.5`` (the canonical memory-preserving
    half-difference), and a total failure to ``d=1`` (first difference).
    """
    clean = col.dropna()
    if len(clean) < 128:
        return col  # too short to stationarize; leave as-is (will warm-up-drop)
    try:
        result = min_ffd(clean, d_candidates=_FFD_D_GRID, threshold=_FFD_THRESHOLD)
        differenced = result.series
    except FracDiffError:
        differenced = frac_diff(clean, 0.5, threshold=_FFD_THRESHOLD)
    if int(differenced.notna().sum()) < _FFD_MIN_RETENTION * len(clean):
        differenced = frac_diff(clean, 0.5, threshold=_FFD_THRESHOLD)
    return differenced.reindex(col.index)


def regime_frame(bars: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Regime-gate features (vol regime + trend strength), indexed by bar time."""
    b = serde.sort_bars(serde.ensure_bars_schema(bars))
    idx = pd.DatetimeIndex(b[serde.TIME_COLUMN], name=serde.TIME_COLUMN)
    f = config.features
    return pd.DataFrame(
        {
            "vol_regime": volatility_regime(
                b, vol_window=f.regime_vol_window, lookback=f.regime_vol_lookback
            ).to_numpy(),
            "trend_strength": trend_strength(b, window=f.trend_window).to_numpy(),
        },
        index=idx,
    )


def add_cross_sectional(
    feats_by_symbol: dict[str, pd.DataFrame], bars_by_symbol: dict[str, pd.DataFrame]
) -> None:
    """Attach cross-sectional rank + sector-neutral z-score (computed on real dates) in place.

    Built from the 1-day return panel across the universe at each real timestamp — contemporaneous
    (point-in-time), then merged back onto each symbol's feature rows by real date.
    """
    ret_panel = pd.DataFrame(
        {
            sym: pd.Series(
                log_return(serde.sort_bars(serde.ensure_bars_schema(bars)), 1).to_numpy(),
                index=pd.DatetimeIndex(
                    serde.sort_bars(serde.ensure_bars_schema(bars))[serde.TIME_COLUMN]
                ),
            )
            for sym, bars in bars_by_symbol.items()
        }
    )
    rank = cross_sectional_rank(ret_panel)
    zscore = sector_neutral_zscore(ret_panel, SECTORS)
    for sym, feat in feats_by_symbol.items():
        feat["xs_rank"] = rank[sym].reindex(feat.index)
        feat["xs_sector_z"] = zscore[sym].reindex(feat.index)


# ---------------------------------------------------------------------------
# Per-symbol dataset (direct + meta labels) and pooling
# ---------------------------------------------------------------------------


class SymbolRows:
    """One symbol's aligned feature/label rows for both the direct and meta strategies."""

    def __init__(
        self,
        symbol: str,
        features: pd.DataFrame,
        regime: pd.DataFrame,
        direction_label: pd.Series,
        forward_return: pd.Series,
        direct_t1: pd.Series,
        meta_label: pd.Series,
        side_return: pd.Series,
        meta_t1: pd.Series,
    ) -> None:
        """Store the per-symbol arrays for the direct and meta strategies (all event-aligned)."""
        self.symbol = symbol
        self.features = features
        self.regime = regime
        self.direction_label = direction_label
        self.forward_return = forward_return
        self.direct_t1 = direct_t1
        self.meta_label = meta_label
        self.side_return = side_return
        self.meta_t1 = meta_t1


def build_symbol_rows(symbol: str, bars: pd.DataFrame, config: Config) -> SymbolRows | None:
    """Resample-clean daily bars -> features, regime, CUSUM events, direct + meta labels."""
    b = serde.sort_bars(serde.ensure_bars_schema(bars))
    if len(b) < 200:
        return None
    idx = pd.DatetimeIndex(b[serde.TIME_COLUMN], name=serde.TIME_COLUMN)
    close = pd.Series(b["close"].to_numpy(dtype="float64"), index=idx)
    sigma = pd.Series(realized_volatility(b, VOL_WINDOW).to_numpy(dtype="float64"), index=idx)

    features = compute_feature_matrix(b)
    regime = regime_frame(b, config)

    events = cusum_events(close, CUSUM_THRESHOLD)
    if len(events) < 80:
        return None

    # CNC holding mode: the gated labeler now expresses multi-day (overnight) holds instead of
    # clamping to the intraday session end, so the daily/CNC strategy is labeled on the gated path.
    labeling = config.labeling.model_copy(
        update={"vertical_max_hold_bars": VERTICAL_DAYS, "holding_mode": "cnc"}
    )

    # Direct triple-barrier labels (direction + realized return)
    direct = TripleBarrierLabeler(labeling).label(b, events, sigma)
    if len(direct) == 0:
        return None
    d_idx = direct.frame.index
    direction = (direct.frame[LABEL] > 0).astype("int64")
    fwd = direct.frame[RETURN].astype("float64")
    direct_t1 = direct.label_times

    # Meta labels: momentum primary side -> bet/no-bet + side-aware return
    sides = momentum_side(b, lookback=VERTICAL_DAYS)
    meta = MetaLabeler(labeling).label(b, events, sides, sigma)
    if len(meta) == 0:
        return None
    meta_label = meta.frame[META_LABEL].astype("int64")
    side_return = meta.frame[META_RETURN].astype("float64")
    meta_t1 = meta.label_times

    return SymbolRows(
        symbol=symbol,
        features=features,
        regime=regime,
        direction_label=direction.reindex(d_idx),
        forward_return=fwd,
        direct_t1=direct_t1,
        meta_label=meta_label,
        side_return=side_return,
        meta_t1=meta_t1,
    )


def _pool(
    rows: list[SymbolRows],
    *,
    which: str,
) -> dict[str, object]:
    """Pool per-symbol rows for one strategy ('direct' or 'meta') onto a compressed synthetic clock.

    Each event is placed one synthetic SECOND after the previous (within a symbol); the label
    horizon t1 = t0 + ``hold_days`` synthetic seconds (``hold_days`` = the label's real calendar
    span, >= 1). Symbols are separated by a gap (synthetic seconds) strictly larger than the max
    label horizon, so no label window crosses a symbol boundary.

    The 1-second clock keeps the whole 56-symbol panel inside pandas' Timestamp range — real-date
    offsets place 56 x ~5-year spans end-to-end (~year 2300) and overflow int64 ns (~year 2262).
    It preserves event order and the cross-symbol non-overlap the purge needs; the purge becomes
    (conservatively) stricter, never leakier. This matches the Cycle-5 diagnostic's pooling, so the
    49-name number is comparable to the +0.662 baseline.
    """
    feat_parts: list[pd.DataFrame] = []
    regime_parts: list[pd.DataFrame] = []
    label_parts: list[pd.Series] = []
    ret_parts: list[pd.Series] = []
    t1_parts: list[pd.Series] = []
    epoch_ns = pd.Timestamp("2020-01-01", tz="UTC").value
    # Gap (in synthetic seconds) must exceed the max calendar hold (a 5-trading-bar CNC vertical
    # can span weekends/holidays — up to ~11 calendar days), so no cross-symbol window overlap.
    gap_seconds = max(POOL_GAP_DAYS, 4 * VERTICAL_DAYS)

    for sr in sorted(rows, key=lambda r: r.symbol):
        if which == "direct":
            ev_idx = sr.direction_label.index
            label = sr.direction_label
            ret = sr.forward_return
            t1 = sr.direct_t1
        else:
            ev_idx = sr.meta_label.index
            label = sr.meta_label
            ret = sr.side_return
            t1 = sr.meta_t1

        feat = sr.features.reindex(ev_idx)
        regime = sr.regime.reindex(ev_idx)
        valid = feat.notna().all(axis=1) & regime.notna().all(axis=1) & ret.notna() & t1.notna()
        ev_idx = ev_idx[valid.to_numpy()]
        if len(ev_idx) == 0:
            continue
        feat = feat.loc[ev_idx]
        regime = regime.loc[ev_idx]
        label = label.loc[ev_idx]
        ret = ret.loc[ev_idx]
        t1 = t1.loc[ev_idx]

        n = len(ev_idx)
        hold_days = np.maximum(
            (pd.DatetimeIndex(t1.to_numpy()) - pd.DatetimeIndex(ev_idx)).days.to_numpy(), 1
        ).astype("int64")
        t0_ns = epoch_ns + np.arange(n, dtype="int64") * 1_000_000_000
        t1_ns = t0_ns + hold_days * 1_000_000_000
        syn_t0 = pd.DatetimeIndex(t0_ns, dtype="datetime64[ns, UTC]", name="event_time")
        # Pass the tz-aware DatetimeIndex directly (NOT .values, which strips the tz to numpy
        # datetime64 and trips the CPCV "t1 must be tz-aware" contract).
        syn_t1 = pd.Series(
            pd.DatetimeIndex(t1_ns, dtype="datetime64[ns, UTC]"), index=syn_t0, name="t1"
        )

        feat_parts.append(feat.set_axis(syn_t0))
        regime_parts.append(regime.set_axis(syn_t0))
        label_parts.append(label.set_axis(syn_t0).rename("label"))
        ret_parts.append(ret.set_axis(syn_t0).rename("ret"))
        t1_parts.append(syn_t1)
        epoch_ns = int(t1_ns.max()) + gap_seconds * 1_000_000_000

    if not feat_parts:
        raise RuntimeError(f"no poolable rows for strategy {which!r}")

    return {
        "features": pd.concat(feat_parts),
        "regime_features": pd.concat(regime_parts),
        "labels": pd.concat(label_parts),
        "returns": pd.concat(ret_parts),
        "label_times": pd.concat(t1_parts),
    }


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------


def evaluate_direct(pooled: dict[str, object], config: Config) -> CPCVEvaluation:
    """Direct 2p-1 ensemble (regime-gated) under CPCV — the Cycle-5-comparable strategy."""
    cpcv = CombinatorialPurgedCV(CPCV_GROUPS, CPCV_TEST_GROUPS, embargo_pct=CPCV_EMBARGO)
    model_cfg = config.model.model_copy(update={"num_boost_round": BOOST_ROUNDS})
    estimators = cross_family_estimators(model_cfg)
    return evaluate_ensemble_under_cpcv(
        estimators,
        pooled["features"],  # type: ignore[arg-type]
        pooled["labels"],  # type: ignore[arg-type]
        pooled["label_times"],  # type: ignore[arg-type]
        pooled["returns"],  # type: ignore[arg-type]
        cpcv,
        regime_features=pooled["regime_features"],  # type: ignore[arg-type]
        n_regimes=config.pipeline.n_regimes,
        method="rank_average",
        round_trip_cost=CNC_ROUND_TRIP,
        periods_per_year=None,
        random_seed=7,
    )


def evaluate_meta(pooled: dict[str, object], config: Config) -> PathDistribution:
    """Meta-labeled strategy: meta-model sizes the bet (position = P(bet)) on the side return.

    Two-stage: the primary side is baked into the side-aware return (``returns``); the meta-model
    predicts P(bet) and sizes a one-sided position in [0, 1]. Strategy return = P(bet) * side_return
    - P(bet) * cost. Trained per CPCV fold on train only (no lookahead).
    """
    features: pd.DataFrame = pooled["features"]  # type: ignore[assignment]
    labels: pd.Series = pooled["labels"]  # type: ignore[assignment]
    label_times: pd.Series = pooled["label_times"]  # type: ignore[assignment]
    returns: pd.Series = pooled["returns"]  # type: ignore[assignment]
    returns_arr = returns.to_numpy(dtype="float64")

    model_cfg = config.model.model_copy(update={"num_boost_round": BOOST_ROUNDS})
    cpcv = CombinatorialPurgedCV(CPCV_GROUPS, CPCV_TEST_GROUPS, embargo_pct=CPCV_EMBARGO)

    def backtest_fn(train: np.ndarray, test: np.ndarray) -> pd.Series:
        estimators = cross_family_estimators(model_cfg)
        model = build_ensemble(
            estimators,
            features.iloc[train],
            labels.iloc[train],
            method="rank_average",
        )
        p_bet = model.predict_proba(features.iloc[test])
        # One-sided conviction size in [0, 1]: 2*max(p-0.5, 0) -> bet only when meta is confident.
        size = np.clip(2.0 * (np.asarray(p_bet, dtype="float64") - 0.5), 0.0, 1.0)
        strat = size * returns_arr[test] - size * CNC_ROUND_TRIP
        return pd.Series(strat, index=features.index[test])

    _paths, distribution = cpcv.run(label_times, backtest_fn, periods_per_year=None)
    return distribution


# ---------------------------------------------------------------------------
# Honest DSR trial count (cumulative across the P2R MLflow experiments)
# ---------------------------------------------------------------------------


def honest_trial_count(tracking_uri: str) -> tuple[int, list[str]]:
    """Count distinct cumulative trials across the p2r* MLflow experiments (honest DSR N)."""
    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient()
        names: list[str] = []
        total = 0
        for exp in client.search_experiments():
            if not exp.name.lower().startswith(("p2r", "p2.9", "p2r-cycle")):
                continue
            runs = client.search_runs([exp.experiment_id], max_results=1000)
            n = len(runs)
            if n:
                names.append(f"{exp.name}:{n}")
                total += n
        return total, names
    except Exception as exc:  # pragma: no cover - telemetry only
        print(f"  [WARN] honest N count failed: {exc}; falling back to documented N=5")
        return 5, ["fallback:5"]


# ---------------------------------------------------------------------------
# Arm runner
# ---------------------------------------------------------------------------


def run_arm(arm: str, config: Config) -> dict[str, object]:
    """Build datasets + evaluate both strategies for one data arm ('validated' | 'yfinance')."""
    print(f"\n=== ARM: {arm} ===")

    def _load_validated(symbol: str) -> pd.DataFrame:
        return load_validated_daily(symbol, config)

    loader: Callable[[str], pd.DataFrame] = (
        _load_validated if arm == "validated" else load_yfinance_daily
    )

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        bars = loader(sym)
        if not bars.empty:
            bars_by_symbol[sym] = bars
            print(f"  {sym}: {len(bars)} daily bars")
    if len(bars_by_symbol) < 5:
        raise RuntimeError(f"{arm}: too few symbols with data ({len(bars_by_symbol)})")

    # Build per-symbol rows + attach cross-sectional features (panel on real dates)
    rows: list[SymbolRows] = []
    feats_by_symbol: dict[str, pd.DataFrame] = {}
    for sym, bars in bars_by_symbol.items():
        sr = build_symbol_rows(sym, bars, config)
        if sr is None:
            print(f"  {sym}: insufficient labeled events — skipped")
            continue
        rows.append(sr)
        feats_by_symbol[sym] = sr.features
    add_cross_sectional(feats_by_symbol, bars_by_symbol)  # mutates sr.features in place
    print(f"  usable symbols: {len(rows)}")

    direct_pool = _pool(rows, which="direct")
    meta_pool = _pool(rows, which="meta")
    print(
        f"  direct events: {len(direct_pool['features']):,}  | "  # type: ignore[arg-type]
        f"meta events: {len(meta_pool['features']):,}"
    )  # type: ignore[arg-type]

    t0 = time.time()
    direct_eval = evaluate_direct(direct_pool, config)
    meta_dist = evaluate_meta(meta_pool, config)
    elapsed = time.time() - t0

    direct_dist = direct_eval.distribution
    direct_obs = float(direct_dist.median)
    meta_obs = float(meta_dist.median)
    print(
        f"  [DIRECT] net/obs {direct_obs:+.4f}  ann {direct_obs * ANNUALISER:+.3f}  "
        f"frac_neg {direct_dist.fraction_negative:.3f}"
    )
    print(
        f"  [META]   net/obs {meta_obs:+.4f}  ann {meta_obs * ANNUALISER:+.3f}  "
        f"frac_neg {meta_dist.fraction_negative:.3f}"
    )
    print(f"  elapsed {elapsed:.1f}s")

    # Combined per-obs returns + path-sharpe variance for the DSR (direct arm).
    combined = pd.concat(list(direct_eval.paths)).dropna()
    sharpe_var = (
        float(np.var(direct_dist.path_sharpes, ddof=1)) if direct_dist.num_paths > 1 else 0.0
    )

    return {
        "arm": arm,
        "n_symbols": len(rows),
        "direct_obs": direct_obs,
        "direct_ann": direct_obs * ANNUALISER,
        "direct_frac_neg": float(direct_dist.fraction_negative),
        "direct_combined": combined,
        "direct_sharpe_var": sharpe_var,
        "meta_obs": meta_obs,
        "meta_ann": meta_obs * ANNUALISER,
        "meta_frac_neg": float(meta_dist.fraction_negative),
        "feature_columns": list(direct_pool["features"].columns),  # type: ignore[union-attr]
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the complete gated pipeline for the requested arm(s) and print the summary."""
    parser = argparse.ArgumentParser(description="Complete gated pipeline (Step 1).")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--arm", choices=["validated", "yfinance", "both"], default="both")
    args = parser.parse_args()

    config = load_config(environ={})
    arms = ["validated", "yfinance"] if args.arm == "both" else [args.arm]
    results = {arm: run_arm(arm, config) for arm in arms}

    tracking_uri = "sqlite:///C:/Users/vinay/Documents/quant-intraday/mlruns/mlflow.db"
    n_trials, n_breakdown = honest_trial_count(tracking_uri)

    # Honest-N DSR for each arm's DIRECT strategy (per-obs returns + path-sharpe variance).
    dsr_by_arm: dict[str, float] = {}
    for arm in arms:
        r = results[arm]
        try:
            dsr_by_arm[arm] = float(
                deflated_sharpe_ratio_from_returns(
                    r["direct_combined"],
                    float(r["direct_sharpe_var"]),
                    n_trials=max(n_trials, 1),
                )
            )
        except Exception as exc:
            print(f"  [WARN] DSR failed for {arm}: {exc}")
            dsr_by_arm[arm] = float("nan")

    print("\n" + "=" * 70)
    print("COMPLETE GATED PIPELINE — STEP 1 SUMMARY")
    print("=" * 70)
    print(f"Universe: {len(SYMBOLS)} validated names | daily | CNC {CNC_ROUND_TRIP*100:.2f}% RT")
    print(f"Honest cumulative DSR N: {n_trials}  ({', '.join(n_breakdown)})")
    print(
        f"Feature columns ({len(results[arms[0]]['feature_columns'])}): "
        f"{', '.join(results[arms[0]]['feature_columns'])}"
    )
    print()
    for arm in arms:
        r = results[arm]
        print(
            f"[{arm:9s}] DIRECT ann {r['direct_ann']:+.3f} (obs {r['direct_obs']:+.4f}, "
            f"neg {r['direct_frac_neg']:.2f}, DSR {dsr_by_arm[arm]:.3f}) | "
            f"META ann {r['meta_ann']:+.3f} "
            f"(obs {r['meta_obs']:+.4f}, neg {r['meta_frac_neg']:.2f})"
        )
    if "validated" in results and "yfinance" in results:
        d_delta = results["validated"]["direct_ann"] - results["yfinance"]["direct_ann"]
        print()
        print(f"DATA-SOURCE EFFECT (validated - yfinance, DIRECT ann): {d_delta:+.3f}")
        print(f"  yfinance DIRECT ann : {results['yfinance']['direct_ann']:+.3f}")
        print(f"  validated DIRECT ann: {results['validated']['direct_ann']:+.3f}")
        print("  (Cycle-5 49-name yfinance baseline was +0.662 ann)")

    if not args.no_mlflow:
        _log_mlflow(results, arms, n_trials, dsr_by_arm, tracking_uri)
    print("=" * 70)
    return 0


def _log_mlflow(
    results: dict[str, dict[str, object]],
    arms: list[str],
    n_trials: int,
    dsr_by_arm: dict[str, float],
    tracking_uri: str,
) -> None:
    try:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("p2r-cycle5-complete-pipeline")
        with mlflow.start_run(run_name="step1-8name-validated-vs-yfinance") as run:
            mlflow.log_params(
                {
                    "universe_size": len(SYMBOLS),
                    "frequency": "daily",
                    "cpcv": f"{CPCV_GROUPS}x{CPCV_TEST_GROUPS}",
                    "boost_rounds": BOOST_ROUNDS,
                    "round_trip_cost": CNC_ROUND_TRIP,
                    "honest_dsr_n": n_trials,
                    "components": "metalabeler+crosssectional+fracdiff+honestN",
                }
            )
            for arm in arms:
                r = results[arm]
                mlflow.log_metrics(
                    {
                        f"{arm}_direct_obs": float(r["direct_obs"]),
                        f"{arm}_direct_ann": float(r["direct_ann"]),
                        f"{arm}_direct_frac_neg": float(r["direct_frac_neg"]),
                        f"{arm}_direct_dsr": float(dsr_by_arm.get(arm, float("nan"))),
                        f"{arm}_meta_obs": float(r["meta_obs"]),
                        f"{arm}_meta_ann": float(r["meta_ann"]),
                        f"{arm}_meta_frac_neg": float(r["meta_frac_neg"]),
                    }
                )
            if "validated" in results and "yfinance" in results:
                mlflow.log_metric(
                    "data_source_effect_direct_ann",
                    float(results["validated"]["direct_ann"] - results["yfinance"]["direct_ann"]),
                )
            run_id = run.info.run_id
        print(f"\nLogged to MLflow 'p2r-cycle5-complete-pipeline' run_id={run_id}")
    except Exception as exc:
        print(f"  [WARN] MLflow logging failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
