"""Step 4 ML cross-sectional rotation for the multi-ETF track (SPEC §7 Step 4).

Reuses the framework: the cross-family ensemble (:func:`build_ensemble` — LightGBM + XGBoost
+ logistic, calibrated), purged time-series CV (:class:`PurgedKFold`), the cost model, and
the DSR metric. The cross-sectional orchestration (per-asset features, cross-sectional
outperformance labels, rank-to-weights, the cost-aware weighted backtest) is implemented here
— it is the equity-research layer the base commit deliberately excluded, re-pointed at ETFs.

The test (SPEC §4): does the rotation beat the equal-weight benchmark on **excess** return,
DSR-corrected on the honest trial count? Pure over an aligned price panel; Yahoo I/O and the
trial grid live in ``scripts/etf_rotation.py``.

Note on the regime gate: this first full pass uses a **causal trailing-volatility regime
proxy** (risk-off when market vol is in its trailing top tercile) as the gross-exposure gate,
rather than wiring the framework GMM with per-fold OOS fitting. The GMM is the production
choice; substituting it is only justified if this pass shows excess (it does not). Flagged in
the Step 4 doc and counted as a design choice.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from quant.core.config import ModelConfig
from quant.research.etf.benchmark import EquityCurve, month_end_indices
from quant.research.etf.costs import ETFCostModel, Side
from quant.research.models.ensemble import build_ensemble
from quant.research.models.estimators import (
    Estimator,
    LightGBMEstimator,
    LogisticEstimator,
    XGBoostEstimator,
)
from quant.research.validation.metrics import deflated_sharpe_ratio_from_returns, sharpe_ratio
from quant.research.validation.splits import PurgedKFold

#: Low-capacity learner config (shallow trees, strong L2, few rounds): the cross-section is
#: only ~6 wide over a short window, so capacity is deliberately small to limit overfitting.
#: Capacity is a registered modelling choice (counts toward honest N if changed).
_MODEL_CONFIG = ModelConfig(
    objective="binary",
    learning_rate=0.05,
    num_leaves=7,
    max_depth=3,
    min_child_samples=20,
    num_boost_round=100,
    feature_fraction=0.8,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l1=0.0,
    lambda_l2=1.0,
    min_gain_to_split=0.0,
    max_bin=63,
    cv_folds=5,
    cv_embargo_pct=0.02,
    permutation_repeats=5,
    random_seed=7,
    model_version="etf-rotation-step4",
)


@dataclass(frozen=True, slots=True)
class RotationConfig:
    """One pre-registered rotation configuration (each distinct config is a trial vs DSR).

    Attributes:
        lookbacks: Momentum lookback windows (sessions).
        horizon: Forward-return horizon for the label and rebalance cadence (sessions).
        vol_window: Realized-volatility window (sessions) for features and inverse-vol sizing.
        top_k: Number of top-ranked risk assets to hold each rebalance.
        n_splits: Purged-CV folds.
        use_regime_gate: Whether to apply the causal volatility regime gate.
        risk_off_cash_weight: Fraction shifted to cash when the gate reads risk-off.
    """

    lookbacks: tuple[int, ...] = (21, 63, 126)
    horizon: int = 21
    vol_window: int = 21
    top_k: int = 3
    n_splits: int = 5
    use_regime_gate: bool = False
    risk_off_cash_weight: float = 0.5

    @property
    def max_lookback(self) -> int:
        """Longest history a feature row needs before it can be formed."""
        return max(max(self.lookbacks), self.vol_window)


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One (date, asset) training observation."""

    date: date
    asset: str
    features: dict[str, float]
    fwd_return: float


def _realized_vol(prices: Sequence[float], end: int, window: int) -> float:
    """Annualised realized volatility over the ``window`` sessions ending at ``end``."""
    rets = [prices[i] / prices[i - 1] - 1.0 for i in range(end - window + 1, end + 1)]
    return float(np.std(rets, ddof=1) * np.sqrt(252.0)) if len(rets) > 1 else 0.0


def build_feature_rows(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    cfg: RotationConfig,
) -> list[FeatureRow]:
    """Build per-asset momentum/vol feature rows with a forward-return label target.

    A row at ``t`` exists only when ``t`` has full lookback history and a full forward
    horizon (so labels never reference unseen-at-train data beyond the purged window).

    Args:
        dates: Aligned session dates.
        prices: Risk-asset symbol -> aligned total-return prices.
        cfg: The rotation configuration.

    Returns:
        Feature rows in (date, asset) order.
    """
    rows: list[FeatureRow] = []
    n = len(dates)
    for asset, series in prices.items():
        for t in range(cfg.max_lookback, n - cfg.horizon):
            feats: dict[str, float] = {}
            for lb in cfg.lookbacks:
                feats[f"mom_{lb}"] = series[t] / series[t - lb] - 1.0
            feats[f"vol_{cfg.vol_window}"] = _realized_vol(series, t, cfg.vol_window)
            sma = sum(series[t - cfg.vol_window + 1 : t + 1]) / cfg.vol_window
            feats["ma_ratio"] = series[t] / sma - 1.0
            fwd = series[t + cfg.horizon] / series[t] - 1.0
            rows.append(FeatureRow(date=dates[t], asset=asset, features=feats, fwd_return=fwd))
    return rows


def cross_sectional_labels(rows: Sequence[FeatureRow]) -> dict[tuple[date, str], int]:
    """Label 1 if an asset's forward return is >= the cross-sectional median that date."""
    by_date: dict[date, list[FeatureRow]] = {}
    for row in rows:
        by_date.setdefault(row.date, []).append(row)
    labels: dict[tuple[date, str], int] = {}
    for day, day_rows in by_date.items():
        median = statistics.median(r.fwd_return for r in day_rows)
        for r in day_rows:
            labels[(day, r.asset)] = int(r.fwd_return >= median)
    return labels


def _estimators() -> list[Estimator]:
    """The framework's cross-family base learners (LightGBM + XGBoost + logistic)."""
    return [
        LightGBMEstimator.from_config(_MODEL_CONFIG),
        XGBoostEstimator.from_config(_MODEL_CONFIG),
        LogisticEstimator(),
    ]


def oos_probabilities(
    rows: Sequence[FeatureRow],
    labels: Mapping[tuple[date, str], int],
    cfg: RotationConfig,
) -> dict[tuple[date, str], float]:
    """Leakage-free out-of-sample P(outperform) per (date, asset) via purged CV.

    Purging is applied on the *time* axis (unique dates), so an asset-date in a test block is
    never trained on its own overlapping-label neighbours. Folds whose train side is single-
    class fall back to 0.5.

    Args:
        rows: Feature rows.
        labels: Cross-sectional outperformance labels.
        cfg: The rotation configuration.

    Returns:
        OOS calibrated probabilities keyed by (date, asset).
    """
    obs_dates = sorted({r.date for r in rows})
    pos_of = {d: i for i, d in enumerate(obs_dates)}
    feat_names = sorted(rows[0].features)
    features = pd.DataFrame([[r.features[f] for f in feat_names] for r in rows], columns=feat_names)
    targets = pd.Series([labels[(r.date, r.asset)] for r in rows], dtype="float64")
    row_date_pos = np.array([pos_of[r.date] for r in rows])

    index = pd.DatetimeIndex([pd.Timestamp(d, tz="UTC") for d in obs_dates])
    label_times = pd.Series(index + pd.Timedelta(days=2 * cfg.horizon), index=index)
    embargo = min(0.2, (cfg.horizon + 1) / len(obs_dates))
    splitter = PurgedKFold(cfg.n_splits, embargo_pct=embargo)

    probs = np.full(len(rows), np.nan)
    for fold in splitter.split(label_times):
        train_dpos = set(fold.train.tolist())
        test_dpos = set(fold.test.tolist())
        train_idx = np.array([i for i, p in enumerate(row_date_pos) if p in train_dpos], dtype=int)
        test_idx = np.array([i for i, p in enumerate(row_date_pos) if p in test_dpos], dtype=int)
        if test_idx.size == 0:
            continue
        y_train = targets.iloc[train_idx]
        if train_idx.size == 0 or y_train.nunique() < 2:
            probs[test_idx] = 0.5
            continue
        model = build_ensemble(
            _estimators(),
            features.iloc[train_idx].reset_index(drop=True),
            y_train.reset_index(drop=True),
        )
        probs[test_idx] = model.predict_proba(features.iloc[test_idx].reset_index(drop=True))
    return {
        (rows[i].date, rows[i].asset): float(probs[i])
        for i in range(len(rows))
        if not np.isnan(probs[i])
    }


def _risk_off_dates(
    dates: Sequence[date], market: Sequence[float], cfg: RotationConfig
) -> set[int]:
    """Indices flagged risk-off: market 21d realized vol in its trailing-252 top tercile."""
    flagged: set[int] = set()
    for t in range(252, len(dates)):
        recent = [_realized_vol(market, s, cfg.vol_window) for s in range(t - 60, t + 1)]
        if _realized_vol(market, t, cfg.vol_window) >= float(np.quantile(recent, 2 / 3)):
            flagged.add(t)
    return flagged


def rotation_weights(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    probs: Mapping[tuple[date, str], float],
    cfg: RotationConfig,
    *,
    cash_symbol: str,
    market_symbol: str,
) -> dict[int, dict[str, float]]:
    """Build target weights at each month-end from OOS ranks, inverse-vol within top-k.

    Args:
        dates: Aligned session dates.
        prices: All-leg prices (risk legs + cash), aligned.
        probs: OOS P(outperform) per (date, asset).
        cfg: The rotation configuration.
        cash_symbol: The cash leg (receives unallocated/risk-off weight).
        market_symbol: The leg whose vol drives the regime gate.

    Returns:
        Mapping of rebalance date-index -> target weights (sum to 1, incl. cash).
    """
    risk_assets = [s for s in prices if s != cash_symbol]
    risk_off = _risk_off_dates(dates, prices[market_symbol], cfg) if cfg.use_regime_gate else set()
    schedule: dict[int, dict[str, float]] = {}
    for t in month_end_indices(dates):
        ranked = sorted(
            (a for a in risk_assets if (dates[t], a) in probs),
            key=lambda a: probs[(dates[t], a)],
            reverse=True,
        )
        weights = dict.fromkeys(prices, 0.0)
        if not ranked:
            weights[cash_symbol] = 1.0
            schedule[t] = weights
            continue
        chosen = ranked[: cfg.top_k]
        risk_budget = 1.0 - (cfg.risk_off_cash_weight if t in risk_off else 0.0)
        inv_vol = {a: 1.0 / max(_realized_vol(prices[a], t, cfg.vol_window), 1e-6) for a in chosen}
        denom = sum(inv_vol.values())
        for a in chosen:
            weights[a] = risk_budget * inv_vol[a] / denom
        weights[cash_symbol] = 1.0 - sum(weights[a] for a in chosen)
        schedule[t] = weights
    return schedule


def backtest_weights(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    schedule: Mapping[int, dict[str, float]],
    cost_model: ETFCostModel,
    *,
    capital: float = 100_000.0,
) -> EquityCurve:
    """Backtest a target-weight schedule net of costs (drift between rebalances).

    Args:
        dates: Aligned session dates.
        prices: All-leg prices, aligned.
        schedule: Rebalance date-index -> target weights.
        cost_model: The Step 2 cost model.
        capital: Starting capital (Rs).

    Returns:
        Net-of-cost :class:`EquityCurve`.
    """
    symbols = list(prices)
    legs = dict.fromkeys(symbols, 0.0)
    portfolio = capital
    first = min(schedule) if schedule else 0
    equity: list[float] = []
    for t in range(len(dates)):
        if t > 0:
            for s in symbols:
                if legs[s]:
                    legs[s] *= prices[s][t] / prices[s][t - 1]
            portfolio = sum(legs.values()) or portfolio
        if t in schedule and t >= first:
            target = {s: schedule[t][s] * portfolio for s in symbols}
            cost = 0.0
            for s in symbols:
                delta = target[s] - legs[s]
                if abs(delta) < 1e-9:
                    continue
                side: Side = "buy" if delta > 0 else "sell"
                cost += cost_model.trade_cost(s, abs(delta), side=side).total
            portfolio -= cost
            scale = portfolio / sum(target.values()) if sum(target.values()) else 1.0
            legs = {s: target[s] * scale for s in symbols}
        equity.append(portfolio if t >= first else capital)
    return EquityCurve(list(dates), equity)


def excess_returns(strategy: EquityCurve, benchmark: EquityCurve) -> list[float]:
    """Daily strategy-minus-benchmark return series over the shared length."""
    s_ret = strategy.daily_returns()
    b_ret = benchmark.daily_returns()
    n = min(len(s_ret), len(b_ret))
    return [s_ret[i] - b_ret[i] for i in range(n)]


@dataclass(frozen=True, slots=True)
class RotationResult:
    """Outcome of one configuration's OOS run."""

    config: RotationConfig
    strategy: EquityCurve
    excess_ann_sharpe: float


@dataclass(frozen=True, slots=True)
class GridVerdict:
    """The DSR-corrected verdict over a pre-registered configuration grid.

    Attributes:
        results: Per-config results.
        best_excess_ann_sharpe: Best annualised excess Sharpe across the grid (the Gate-1
            ``> +0.3`` Sharpe bar is on this).
        dsr_probability: Deflated-Sharpe probability that the best config's excess Sharpe
            exceeds the trial-deflated benchmark (PSR-style, in [0, 1]); significance
            conventionally needs ~0.95.
        n_trials: Honest trial count (grid size).
    """

    results: list[RotationResult] = field(default_factory=list)
    best_excess_ann_sharpe: float = 0.0
    dsr_probability: float = 0.0
    n_trials: int = 0


def run_grid(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    benchmark: EquityCurve,
    cost_model: ETFCostModel,
    configs: Sequence[RotationConfig],
    *,
    cash_symbol: str,
    market_symbol: str,
) -> GridVerdict:
    """Run every configuration, then DSR-correct the best excess Sharpe on the trial count.

    The DSR's ``sharpe_variance`` is the variance of the grid's (per-observation) excess
    Sharpes — the honest dispersion of the search that the best result is deflated against.

    Args:
        dates: Aligned session dates.
        prices: All-leg prices (risk + cash), aligned.
        benchmark: The Step 3 equal-weight benchmark curve.
        cost_model: The Step 2 cost model.
        configs: The pre-registered grid (each a trial).
        cash_symbol: The cash leg.
        market_symbol: The regime-gate market leg.

    Returns:
        The :class:`GridVerdict`.
    """
    risk_prices = {s: prices[s] for s in prices if s != cash_symbol}
    results: list[RotationResult] = []
    per_obs_excess_sharpes: list[float] = []
    for cfg in configs:
        rows = build_feature_rows(dates, risk_prices, cfg)
        labels = cross_sectional_labels(rows)
        probs = oos_probabilities(rows, labels, cfg)
        schedule = rotation_weights(
            dates, prices, probs, cfg, cash_symbol=cash_symbol, market_symbol=market_symbol
        )
        strat = backtest_weights(dates, prices, schedule, cost_model)
        excess = excess_returns(strat, benchmark)
        ann = sharpe_ratio(excess, periods_per_year=252.0)
        per_obs_excess_sharpes.append(sharpe_ratio(excess))
        results.append(RotationResult(config=cfg, strategy=strat, excess_ann_sharpe=ann))

    best_i = max(range(len(results)), key=lambda i: results[i].excess_ann_sharpe)
    best = results[best_i]
    sharpe_var = float(np.var(per_obs_excess_sharpes, ddof=1)) if len(configs) > 1 else 0.0
    best_excess = excess_returns(best.strategy, benchmark)
    dsr = deflated_sharpe_ratio_from_returns(best_excess, sharpe_var, len(configs))
    return GridVerdict(
        results=results,
        best_excess_ann_sharpe=best.excess_ann_sharpe,
        dsr_probability=dsr,
        n_trials=len(configs),
    )
