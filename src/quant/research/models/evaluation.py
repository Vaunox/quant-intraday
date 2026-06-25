"""Evaluating the ensemble + regime gate under CPCV (P2.7 acceptance criterion).

The deliverable is *"ensemble + regime gate evaluated under CPCV"*. This module is that
evaluation: it drives a :class:`~quant.research.validation.cpcv.CombinatorialPurgedCV` over
the model stack, producing the **path-Sharpe distribution** the kill-gate reads (Deep Dive #2
§4b.2; criteria 1 and 4). It is the bridge between the model stack (P2.6/P2.7) and the
validation engine (P2.1/P2.2) — the "judge" meeting the "contestant".

Per CPCV split it:

1. fits the cross-family ensemble on the split's **purged train** rows
   (:func:`~quant.research.models.ensemble.build_ensemble`);
2. fits a :class:`~quant.research.models.regime.RegimeGate` on the train regime features —
   data-driven from the train returns, so unprofitable regimes are switched off *without*
   looking at the test set;
3. predicts on the held-out **test** rows, turns the calibrated probability into a position
   (``2·p - 1`` ∈ ``[-1, 1]``: long when bullish, short when bearish), gates it by the test
   regime, and multiplies by the realized forward return — the per-observation OOS strategy
   return.

The CPCV machinery then stitches these per-split test returns into ``φ`` full-timeline paths
and summarizes the path-Sharpe distribution. Everything is strictly out-of-sample: the test
block is purged and embargoed from the train block by the splitter, and the gate's regime
selection uses train returns only — no lookahead (Inviolable Rule 2).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.models.ensemble import CombinationMethod, build_ensemble
from quant.research.models.errors import ModelTrainingError
from quant.research.models.estimators import Estimator
from quant.research.models.regime import fit_regime_gate
from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CPCVEvaluation:
    """The CPCV outcome for the model stack: the reconstructed paths + their Sharpe distribution."""

    paths: tuple[pd.Series, ...]
    distribution: PathDistribution

    @property
    def num_paths(self) -> int:
        """Number of reconstructed backtest paths φ."""
        return self.distribution.num_paths


def probability_to_position(probabilities: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Map a calibrated ``P(y=1)`` to a directional position in ``[-1, 1]`` (``2·p - 1``).

    ``p = 1`` → fully long, ``p = 0`` → fully short, ``p = 0.5`` → flat. A monotone, symmetric
    map; conviction sizing proper (fractional Kelly off this probability) is the Capital
    Layer's job (Deep Dive #3), not the research evaluator's.
    """
    return 2.0 * np.asarray(probabilities, dtype="float64").ravel() - 1.0


def evaluate_ensemble_under_cpcv(
    estimators: Sequence[Estimator],
    features: pd.DataFrame,
    labels: pd.Series,
    label_times: pd.Series,
    forward_returns: pd.Series,
    cpcv: CombinatorialPurgedCV,
    *,
    regime_features: pd.DataFrame | None = None,
    n_regimes: int = 3,
    method: CombinationMethod = "rank_average",
    meta_l2: float = 1.0,
    sample_weight: pd.Series | None = None,
    periods_per_year: float | None = None,
    round_trip_cost: float = 0.0,
    random_seed: int = 7,
) -> CPCVEvaluation:
    """Evaluate the ensemble (optionally regime-gated) under CPCV; return the path distribution.

    Args:
        estimators: The base learners to blend (LightGBM + XGBoost + logistic, per §4.1).
        features: Point-in-time feature matrix indexed by event time ``t0``.
        labels: Binary outcomes ``{0, 1}`` aligned to ``features`` (the model's target).
        label_times: The ``t0 -> t1`` Series (P2.3) driving the purge/embargo.
        forward_returns: Realized per-observation return earned by a unit long position taken
            on that event (e.g. the triple-barrier outcome return), aligned to ``features``.
        cpcv: The configured combinatorial purged CV scheme.
        regime_features: Optional volatility/trend features for the regime gate. If omitted,
            the ensemble runs ungated.
        n_regimes: Number of GMM regimes when ``regime_features`` is given.
        method: Ensemble blend mode (``"rank_average"`` or ``"stack"``).
        meta_l2: L2 penalty for the stacking meta-learner (ignored for rank averaging).
        sample_weight: Optional per-event training weights (P2.4).
        periods_per_year: If given, the path Sharpes are annualized by ``√periods_per_year``.
        round_trip_cost: A round-trip transaction cost, as a fraction of notional, charged once
            per event (enter at ``t0``, exit at the barrier) scaled by the position size taken.
            ``0.0`` (default) leaves the returns **gross** — the P2.7/P2.8 behaviour; the P2.9
            kill-gate passes the representative Indian round-trip cost so criterion 1 is *"after
            costs"*. The gate's per-regime train selection is netted on the same basis (no
            lookahead).
        random_seed: Seed for the regime GMM (the ensemble members carry their own seeds).

    Returns:
        A :class:`CPCVEvaluation` with the ``φ`` paths and their Sharpe distribution.

    Raises:
        ModelTrainingError: On misaligned inputs.
    """
    _validate_alignment(features, labels, label_times, forward_returns, regime_features)
    returns_array = forward_returns.to_numpy(dtype="float64")
    weight_array = None if sample_weight is None else sample_weight.to_numpy(dtype="float64")

    def backtest_fn(train: npt.NDArray[np.intp], test: npt.NDArray[np.intp]) -> pd.Series:
        """Fit on the purged train rows; return the per-observation OOS strategy return on test."""
        weight_train = None if weight_array is None else weight_array[train]
        model = build_ensemble(
            estimators,
            features.iloc[train],
            labels.iloc[train],
            method=method,
            meta_l2=meta_l2,
            sample_weight=weight_train,
        )
        position = probability_to_position(model.predict_proba(features.iloc[test]))
        if regime_features is not None:
            # Gate on the *strategy's* per-regime **net** edge measured on the train slice (does
            # the signal make money after costs in this regime?) — not the market's raw drift.
            # Train-only, so no lookahead: build the train positions from the same fitted model.
            train_position = probability_to_position(model.predict_proba(features.iloc[train]))
            train_strategy_return = (
                train_position * returns_array[train] - np.abs(train_position) * round_trip_cost
            )
            position = _apply_regime_gate(
                position,
                regime_features,
                train,
                test,
                train_strategy_return,
                n_regimes,
                random_seed,
            )
        test_returns = position * returns_array[test] - np.abs(position) * round_trip_cost
        return pd.Series(test_returns, index=features.index[test])

    paths, distribution = cpcv.run(label_times, backtest_fn, periods_per_year=periods_per_year)
    _logger.info(
        "ensemble evaluated under cpcv",
        extra={
            "num_paths": distribution.num_paths,
            "median_path_sharpe": distribution.median,
            "method": method,
            "gated": regime_features is not None,
        },
    )
    return CPCVEvaluation(paths=tuple(paths), distribution=distribution)


def _apply_regime_gate(
    position: npt.NDArray[np.float64],
    regime_features: pd.DataFrame,
    train: npt.NDArray[np.intp],
    test: npt.NDArray[np.intp],
    train_strategy_return: npt.NDArray[np.float64],
    n_regimes: int,
    random_seed: int,
) -> npt.NDArray[np.float64]:
    """Gate the test ``position`` by a regime model fit on the train slice.

    The gate switches off regimes whose train-set *strategy* return is non-positive
    (:func:`~quant.research.models.regime.select_regime_multipliers`), then scales the
    out-of-sample test positions by the surviving regimes' multipliers.
    """
    gate = fit_regime_gate(
        regime_features.iloc[train],
        n_regimes,
        returns=train_strategy_return,
        random_seed=random_seed,
    )
    return gate.gate(position, regime_features.iloc[test])


def _validate_alignment(
    features: pd.DataFrame,
    labels: pd.Series,
    label_times: pd.Series,
    forward_returns: pd.Series,
    regime_features: pd.DataFrame | None,
) -> None:
    """Fail loud if any input is not aligned to the features index (Ground Rule 7)."""
    index = features.index
    if not (index.equals(labels.index) and index.equals(label_times.index)):
        raise ModelTrainingError("features, labels, and label_times must share one index")
    if not index.equals(forward_returns.index):
        raise ModelTrainingError("forward_returns must share the features index")
    if regime_features is not None and not index.equals(regime_features.index):
        raise ModelTrainingError("regime_features must share the features index")
