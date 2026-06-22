"""Cross-family base estimators for the model stack (Deep Dive #2 §4.1, Steps 2-3).

The ensemble's strength is *family diversity*: *"Combine boosting + a linear/logistic model
… diversity across model families is more robust than one big tuned model. Diversity is a
free lunch; tuning a single model harder is not."* (§4.1 Step 3). This module supplies the
three families the ensemble (:mod:`~quant.research.models.ensemble`) blends:

* :class:`LightGBMEstimator` — the §4.1-Step-1 baseline's booster, reused here as one member.
* :class:`XGBoostEstimator` — a *second* gradient-boosting implementation (§4.1 Step 2). A
  different GBM is genuine family diversity, not a re-tune; that is why a real XGBoost
  dependency (not a hand-roll) earns its place, confined here like LightGBM.
* :class:`LogisticEstimator` — a linear/logistic learner. Hand-rolled (L2-regularized,
  standardized, full-batch gradient descent) in the same lean spirit as the isotonic
  calibrator and the scoring metrics: a small, well-understood algorithm is kept dependency
  free rather than dragging in scikit-learn.

Every estimator is reduced to one tiny contract — :class:`Estimator` (``fit -> FittedEstimator``)
and :class:`FittedEstimator` (``predict_proba``) — so the ensemble combines *prediction
vectors*, never library internals. That confinement is what lets the ensemble logic be unit
tested against trivial fakes with no GBM installed (Ground Rule 1). All three are
**deterministic** for a fixed seed (Ground Rule 7): single-threaded boosters with seeds set,
and a zero-initialized convex logistic fit.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd
import xgboost as xgb

from quant.core.config import ModelConfig
from quant.research.models.baseline import booster_proba, fit_booster, params_from_config
from quant.research.models.errors import ModelTrainingError


@runtime_checkable
class FittedEstimator(Protocol):
    """A fitted base learner's batch inference path: ``X -> P(y=1)`` per row.

    ``feature_names`` records the trained column order so the ensemble (and live inference)
    can re-select/re-order columns rather than relying on positional alignment. It is a
    read-only property so the frozen-dataclass fitted models satisfy the Protocol.
    """

    @property
    def feature_names(self) -> tuple[str, ...]:
        """The trained feature column names, in order."""
        ...

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return ``P(y=1)`` per row of ``features`` as a 1-D float array."""
        ...


@runtime_checkable
class Estimator(Protocol):
    """A fittable base learner: ``fit(X, y) -> FittedEstimator``.

    ``name`` is the stable identifier the ensemble keys per-model predictions and importances
    by (and records in the run/registry), so a blend's members stay attributable. It is a
    read-only property so the (frozen-dataclass) estimators satisfy the Protocol.
    """

    @property
    def name(self) -> str:
        """The estimator's stable family identifier (e.g. ``"lightgbm"``)."""
        ...

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        *,
        sample_weight: npt.NDArray[np.float64] | None = None,
    ) -> FittedEstimator:
        """Fit on ``(features, labels)`` with optional per-row ``sample_weight`` (P2.4)."""
        ...


def _sigmoid(z: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Numerically-stable logistic sigmoid, evaluated branch-wise to avoid ``exp`` overflow."""
    out = np.empty_like(z, dtype="float64")
    positive = z >= 0.0
    out[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    out[~positive] = exp_z / (1.0 + exp_z)
    return out


@dataclass(frozen=True, slots=True)
class FittedLightGBM:
    """A fitted LightGBM booster behind the :class:`FittedEstimator` contract."""

    booster: Any  # lgb.Booster (kept Any so this module needs no LightGBM symbol)
    feature_names: tuple[str, ...]

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the booster's ``P(y=1)`` per row, columns re-selected in trained order."""
        return booster_proba(self.booster, features[list(self.feature_names)])


@dataclass(frozen=True, slots=True)
class LightGBMEstimator:
    """The §4.1 baseline booster as an ensemble member (reuses the P2.6 native-API helpers)."""

    params: Mapping[str, Any]
    num_boost_round: int
    name: str = "lightgbm"

    @classmethod
    def from_config(cls, config: ModelConfig) -> "LightGBMEstimator":
        """Build from the shared :class:`ModelConfig` (capacity, regularization, seed)."""
        return cls(params=params_from_config(config), num_boost_round=config.num_boost_round)

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        *,
        sample_weight: npt.NDArray[np.float64] | None = None,
    ) -> FittedLightGBM:
        """Train a LightGBM booster (delegates to the confined P2.6 ``fit_booster``)."""
        booster = fit_booster(
            features, labels, self.params, self.num_boost_round, sample_weight=sample_weight
        )
        return FittedLightGBM(booster, tuple(str(c) for c in features.columns))


def xgb_params_from_config(config: ModelConfig) -> dict[str, Any]:
    """Translate the shared :class:`ModelConfig` into XGBoost native-API parameters.

    Maps the *family-neutral* capacity/regularization knobs onto XGBoost's names so one
    config drives both boosters (Ground Rule 2): XGBoost is depth-wise, so ``max_depth`` is
    the primary capacity knob (vs LightGBM's leaf-wise ``num_leaves``); ``min_child_samples``
    maps to ``min_child_weight``, row/column subsampling to ``subsample``/``colsample_bytree``,
    and the L1/L2/split-gain penalties to ``reg_alpha``/``reg_lambda``/``gamma``. ``seed`` +
    ``nthread=1`` + the deterministic ``hist`` tree method make a fit reproducible (Ground
    Rule 7); ``verbosity=0`` keeps the library quiet (our logging is the audit trail).
    """
    return {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "eta": config.learning_rate,
        "max_depth": config.max_depth,
        "min_child_weight": float(config.min_child_samples),
        "subsample": config.bagging_fraction,
        "colsample_bytree": config.feature_fraction,
        "reg_alpha": config.lambda_l1,
        "reg_lambda": config.lambda_l2,
        "gamma": config.min_gain_to_split,
        "max_bin": config.max_bin,
        "tree_method": "hist",
        "seed": config.random_seed,
        "nthread": 1,
        "verbosity": 0,
    }


@dataclass(frozen=True, slots=True)
class FittedXGBoost:
    """A fitted XGBoost booster behind the :class:`FittedEstimator` contract.

    Predicts on a ``DMatrix`` built from the trained columns (re-selected in order); feature
    names are tracked here rather than handed to the ``DMatrix`` to side-step XGBoost's
    rejection of names containing ``[``, ``]`` or ``<``.
    """

    booster: Any  # xgb.Booster
    feature_names: tuple[str, ...]

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the booster's ``P(y=1)`` per row, columns re-selected in trained order."""
        matrix = xgb.DMatrix(features[list(self.feature_names)].to_numpy(dtype="float64"))
        return np.asarray(self.booster.predict(matrix), dtype="float64").ravel()


@dataclass(frozen=True, slots=True)
class XGBoostEstimator:
    """A second-family gradient booster (§4.1 Step 2), confined like LightGBM."""

    params: Mapping[str, Any]
    num_boost_round: int
    name: str = "xgboost"

    @classmethod
    def from_config(cls, config: ModelConfig) -> "XGBoostEstimator":
        """Build from the shared :class:`ModelConfig` via :func:`xgb_params_from_config`."""
        return cls(params=xgb_params_from_config(config), num_boost_round=config.num_boost_round)

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        *,
        sample_weight: npt.NDArray[np.float64] | None = None,
    ) -> FittedXGBoost:
        """Train an XGBoost booster via the native API (single, confined import site)."""
        matrix = xgb.DMatrix(
            features.to_numpy(dtype="float64"),
            label=labels.to_numpy(dtype="float64"),
            weight=sample_weight,
        )
        booster = xgb.train(dict(self.params), matrix, num_boost_round=self.num_boost_round)
        return FittedXGBoost(booster, tuple(str(c) for c in features.columns))


@dataclass(frozen=True, slots=True)
class FittedLogistic:
    """A fitted standardized L2 logistic model behind the :class:`FittedEstimator` contract.

    Standardization stats (``mean``/``scale``) are the *training* set's, stored and reapplied
    at inference — a trailing-only transform, so the linear member is point-in-time correct
    just like the tree members (Inviolable Rule 2).
    """

    weights: npt.NDArray[np.float64]
    bias: float
    mean: npt.NDArray[np.float64]
    scale: npt.NDArray[np.float64]
    feature_names: tuple[str, ...]

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return ``sigmoid(standardized(X) · w + b)`` per row, columns in trained order."""
        matrix = features[list(self.feature_names)].to_numpy(dtype="float64")
        standardized = (matrix - self.mean) / self.scale
        return _sigmoid(standardized @ self.weights + self.bias)


@dataclass(frozen=True, slots=True)
class LogisticEstimator:
    """Hand-rolled L2-regularized logistic regression (the linear ensemble member).

    Full-batch gradient descent on standardized features. The objective is convex and the
    weights start at zero, so the fit is fully deterministic without an RNG (Ground Rule 7) —
    no seed needed. Defaults are research knobs (overridable per the §4.2 / tuning precedent
    that search settings are explicit arguments, not buried production constants).
    """

    l2: float = 1.0
    learning_rate: float = 0.5
    max_iter: int = 500
    name: str = "logistic"

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        *,
        sample_weight: npt.NDArray[np.float64] | None = None,
    ) -> FittedLogistic:
        """Fit weights by weighted, L2-penalized gradient descent on standardized features.

        Raises:
            ModelTrainingError: If ``max_iter < 1``, ``learning_rate <= 0``, or ``l2 < 0``.
        """
        if self.max_iter < 1 or self.learning_rate <= 0.0 or self.l2 < 0.0:
            raise ModelTrainingError(
                "LogisticEstimator needs max_iter>=1, learning_rate>0, l2>=0; "
                f"got {self.max_iter}/{self.learning_rate}/{self.l2}"
            )
        names = tuple(str(c) for c in features.columns)
        matrix = features.to_numpy(dtype="float64")
        truth = labels.to_numpy(dtype="float64")
        weight = (
            np.ones(truth.shape[0], dtype="float64")
            if sample_weight is None
            else np.asarray(sample_weight, dtype="float64")
        )
        mean = matrix.mean(axis=0)
        scale = matrix.std(axis=0)
        scale = np.where(scale > 0.0, scale, 1.0)  # a constant column contributes nothing
        standardized = (matrix - mean) / scale

        weights = np.zeros(standardized.shape[1], dtype="float64")
        bias = 0.0
        weight_total = float(weight.sum()) or 1.0
        for _ in range(self.max_iter):
            residual = (_sigmoid(standardized @ weights + bias) - truth) * weight
            # L2 penalizes the slopes, never the intercept (the conventional choice).
            weights -= self.learning_rate * (
                standardized.T @ residual / weight_total + self.l2 * weights
            )
            bias -= self.learning_rate * (float(residual.sum()) / weight_total)
        return FittedLogistic(weights, bias, mean, scale, names)
