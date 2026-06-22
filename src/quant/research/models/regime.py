"""The regime gate (Deep Dive #2 §4.1, Step 4 — "HMM or Gaussian Mixture Model").

*"An HMM or Gaussian Mixture Model on volatility/trend features classifies the current regime
(trending / ranging / high-vol / low-vol). Strategies/models are switched on or off — or sized
down — by regime. This directly addresses non-stationarity."* The deep dive offers either; we
implement the **GMM**, the simpler and (for an unordered point-in-time regime label) sufficient
choice, and keep it dependency-free — a diagonal-covariance mixture fit by Expectation-
Maximization, in the same lean spirit as the isotonic calibrator and the logistic member.

Two pieces:

* :class:`GaussianMixtureModel` / :class:`FittedGaussianMixture` — the unsupervised density
  model. The fit is **deterministic** for a fixed seed (Ground Rule 7: the only randomness is
  the seeded initialization of the component means) and **point-in-time**: it is fit on
  training-fold regime features and *applied* to later observations, never peeking ahead.
  Components are sorted ascending by their mean on the first feature, so the regime labels are
  stable across fits (no label-switching) and interpretable — e.g. put a volatility feature
  first and regime 0 is the calmest.
* :class:`RegimeGate` — wraps a fitted mixture with a per-regime position **multiplier**
  (0 = switched off, a fraction = sized down, 1 = full), and applies it to a signal. The
  data-driven :func:`select_regime_multipliers` estimates per-regime edge from training
  returns and switches off the unprofitable regimes — the operational form of kill-gate
  criterion 7, "edge stable across regimes, not confined to one bull run".
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.models.errors import ModelTrainingError

_logger = get_logger(__name__)

#: Variance floor added to every component (numerical stability; avoids singular collapse).
_DEFAULT_REG_COVAR = 1e-6
_LOG_2PI = float(np.log(2.0 * np.pi))


@dataclass(frozen=True, slots=True)
class FittedGaussianMixture:
    """A fitted diagonal-covariance Gaussian mixture: weights, means, variances per component.

    ``means``/``variances`` are ``(k, d)`` (one diagonal row per component); ``weights`` is the
    ``(k,)`` mixing proportions. :meth:`predict` returns the most-likely component (the regime
    label) and :meth:`predict_proba` the soft responsibilities.
    """

    weights: npt.NDArray[np.float64]
    means: npt.NDArray[np.float64]
    variances: npt.NDArray[np.float64]
    feature_names: tuple[str, ...]
    log_likelihood: float

    @property
    def n_components(self) -> int:
        """Number of mixture components (regimes)."""
        return int(self.weights.shape[0])

    def _log_responsibilities(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return the ``(n, k)`` log-posterior of each component given each row (log-sum-exp)."""
        log_joint = _log_component_densities(matrix, self.means, self.variances)
        log_joint += np.log(self.weights)[np.newaxis, :]
        log_norm = _logsumexp_rows(log_joint)
        return log_joint - log_norm[:, np.newaxis]

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the ``(n, k)`` soft responsibilities (each row sums to 1)."""
        matrix = features[list(self.feature_names)].to_numpy(dtype="float64")
        return np.exp(self._log_responsibilities(matrix))

    def predict(self, features: pd.DataFrame) -> npt.NDArray[np.intp]:
        """Return the hard regime label (argmax responsibility) per row."""
        matrix = features[list(self.feature_names)].to_numpy(dtype="float64")
        return np.asarray(np.argmax(self._log_responsibilities(matrix), axis=1), dtype=np.intp)


class GaussianMixtureModel:
    """Diagonal-covariance Gaussian mixture fit by Expectation-Maximization (the regime model)."""

    def __init__(
        self,
        n_components: int,
        *,
        max_iter: int = 200,
        tol: float = 1e-5,
        reg_covar: float = _DEFAULT_REG_COVAR,
        random_seed: int = 7,
    ) -> None:
        """Build the GMM fitter.

        Args:
            n_components: Number of regimes ``k`` (>= 1). A small ``k`` (2-4) is the §4.1 use
                (trending / ranging / high-vol / low-vol) — keep it modest to avoid overfitting.
            max_iter: Maximum EM iterations.
            tol: Convergence tolerance on the mean per-sample log-likelihood gain.
            reg_covar: Variance floor added to every component (numerical stability).
            random_seed: Seeds the initial mean selection (the only randomness — Ground Rule 7).

        Raises:
            ModelTrainingError: If ``n_components < 1``, ``max_iter < 1``, or ``reg_covar < 0``.
        """
        if n_components < 1:
            raise ModelTrainingError(f"n_components must be >= 1, got {n_components}")
        if max_iter < 1:
            raise ModelTrainingError(f"max_iter must be >= 1, got {max_iter}")
        if reg_covar < 0.0:
            raise ModelTrainingError(f"reg_covar must be >= 0, got {reg_covar}")
        self._k = n_components
        self._max_iter = max_iter
        self._tol = tol
        self._reg_covar = reg_covar
        self._seed = random_seed

    def fit(self, features: pd.DataFrame) -> FittedGaussianMixture:
        """Fit the mixture on ``features`` and return the component parameters.

        Raises:
            ModelTrainingError: If ``features`` is empty or has fewer rows than components.
        """
        names = tuple(str(c) for c in features.columns)
        matrix = features.to_numpy(dtype="float64")
        n, d = matrix.shape
        if n == 0 or d == 0:
            raise ModelTrainingError("cannot fit a mixture on an empty feature matrix")
        if n < self._k:
            raise ModelTrainingError(f"need at least n_components={self._k} rows, got {n}")

        weights, means, variances = self._initialize(matrix)
        previous = -np.inf
        log_likelihood = previous
        for _ in range(self._max_iter):
            log_resp, log_likelihood = self._e_step(matrix, weights, means, variances)
            weights, means, variances = self._m_step(matrix, log_resp)
            if log_likelihood - previous <= self._tol:
                break
            previous = log_likelihood

        weights, means, variances = _sort_components(weights, means, variances)
        _logger.info(
            "gmm fit", extra={"n_components": self._k, "log_likelihood": float(log_likelihood)}
        )
        return FittedGaussianMixture(weights, means, variances, names, float(log_likelihood))

    def _initialize(
        self, matrix: npt.NDArray[np.float64]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Seed means from ``k`` distinct random rows; variances from the global variance."""
        rng = np.random.default_rng(self._seed)
        chosen = rng.choice(matrix.shape[0], size=self._k, replace=False)
        means = matrix[chosen].copy()
        global_var = matrix.var(axis=0) + self._reg_covar
        variances = np.tile(global_var, (self._k, 1))
        weights = np.full(self._k, 1.0 / self._k, dtype="float64")
        return weights, means, variances

    def _e_step(
        self,
        matrix: npt.NDArray[np.float64],
        weights: npt.NDArray[np.float64],
        means: npt.NDArray[np.float64],
        variances: npt.NDArray[np.float64],
    ) -> tuple[npt.NDArray[np.float64], float]:
        """Return the ``(n, k)`` log-responsibilities and the mean per-sample log-likelihood."""
        log_joint = _log_component_densities(matrix, means, variances) + np.log(weights)
        log_norm = _logsumexp_rows(log_joint)
        return log_joint - log_norm[:, np.newaxis], float(log_norm.mean())

    def _m_step(
        self, matrix: npt.NDArray[np.float64], log_resp: npt.NDArray[np.float64]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Update weights, means, and diagonal variances from the responsibilities."""
        resp = np.exp(log_resp)
        counts = resp.sum(axis=0) + 1e-12  # guard an emptied component
        weights = counts / matrix.shape[0]
        means = (resp.T @ matrix) / counts[:, np.newaxis]
        # E[x^2] - mean^2 per component, then floor for stability.
        mean_sq = (resp.T @ (matrix**2)) / counts[:, np.newaxis]
        variances = mean_sq - means**2 + self._reg_covar
        return weights, means, np.maximum(variances, self._reg_covar)


def _log_component_densities(
    matrix: npt.NDArray[np.float64],
    means: npt.NDArray[np.float64],
    variances: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Return ``(n, k)`` log N(x | mean_k, diag(var_k)) for a diagonal-covariance mixture."""
    # log p = -0.5 * sum_d [ log(2π var) + (x-μ)^2 / var ].
    log_det = np.sum(np.log(variances), axis=1)  # (k,)
    diff = matrix[:, np.newaxis, :] - means[np.newaxis, :, :]  # (n, k, d)
    mahalanobis = np.sum(diff**2 / variances[np.newaxis, :, :], axis=2)  # (n, k)
    d = matrix.shape[1]
    densities = -0.5 * (d * _LOG_2PI + log_det[np.newaxis, :] + mahalanobis)
    return np.asarray(densities, dtype="float64")


def _logsumexp_rows(log_values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Row-wise log-sum-exp (stable): ``max + log(sum(exp(x - max)))`` per row."""
    row_max = np.max(log_values, axis=1, keepdims=True)
    stable = np.exp(log_values - row_max)
    return np.asarray(row_max[:, 0] + np.log(np.sum(stable, axis=1)), dtype="float64")


def _sort_components(
    weights: npt.NDArray[np.float64],
    means: npt.NDArray[np.float64],
    variances: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Order components ascending by their first-feature mean (stable, interpretable labels)."""
    order = np.argsort(means[:, 0], kind="mergesort")
    return weights[order], means[order], variances[order]


@dataclass(frozen=True, slots=True)
class RegimeGate:
    """A fitted regime model + per-regime position multipliers, applied to a signal.

    ``multipliers[r]`` scales any position taken while regime ``r`` is active: ``0`` switches
    the strategy off in that regime, a fraction sizes it down, ``1`` leaves it untouched. This
    is the §4.1 "switched on or off — or sized down — by regime" behaviour.
    """

    mixture: FittedGaussianMixture
    multipliers: tuple[float, ...]

    def __post_init__(self) -> None:
        """Validate the multiplier vector against the mixture's component count."""
        if len(self.multipliers) != self.mixture.n_components:
            raise ModelTrainingError(
                f"expected {self.mixture.n_components} multipliers, got {len(self.multipliers)}"
            )
        if any(m < 0.0 for m in self.multipliers):
            raise ModelTrainingError("regime multipliers must be non-negative")

    def regimes(self, regime_features: pd.DataFrame) -> npt.NDArray[np.intp]:
        """Return the active regime label per row."""
        return self.mixture.predict(regime_features)

    def regime_multiplier(self, regime_features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the position multiplier per row (the row's regime's multiplier)."""
        multipliers = np.asarray(self.multipliers, dtype="float64")
        return multipliers[self.regimes(regime_features)]

    def gate(
        self, signal: npt.NDArray[np.float64], regime_features: pd.DataFrame
    ) -> npt.NDArray[np.float64]:
        """Scale ``signal`` row-wise by the active regime's multiplier.

        Raises:
            ModelTrainingError: If ``signal`` and ``regime_features`` lengths disagree.
        """
        values = np.asarray(signal, dtype="float64").ravel()
        if values.shape[0] != regime_features.shape[0]:
            raise ModelTrainingError(
                f"signal ({values.shape[0]}) and regime_features ({regime_features.shape[0]}) "
                "must align"
            )
        return values * self.regime_multiplier(regime_features)


def select_regime_multipliers(
    regimes: npt.NDArray[np.intp],
    returns: npt.NDArray[np.float64] | pd.Series,
    n_components: int,
    *,
    min_observations: int = 1,
) -> tuple[float, ...]:
    """Switch each regime on (1.0) or off (0.0) by the sign of its mean training return.

    The data-driven half of kill-gate criterion 7: a regime whose in-sample mean strategy
    return is positive (with enough observations to be meaningful) stays on; an unprofitable
    or too-thin regime is switched off. Estimated on **training** data only and then applied
    out-of-sample, so it introduces no lookahead.

    Args:
        regimes: Hard regime label per observation (from :meth:`FittedGaussianMixture.predict`).
        returns: Per-observation strategy return aligned to ``regimes``.
        n_components: Number of regimes ``k`` (so empty regimes still get an explicit 0.0).
        min_observations: Minimum observations a regime needs to be eligible to stay on.

    Returns:
        A length-``k`` multiplier tuple in ``{0.0, 1.0}``.

    Raises:
        ModelTrainingError: If ``regimes`` and ``returns`` lengths disagree.
    """
    values = np.asarray(returns, dtype="float64").ravel()
    labels = np.asarray(regimes, dtype=np.intp).ravel()
    if values.shape[0] != labels.shape[0]:
        raise ModelTrainingError(
            f"regimes ({labels.shape[0]}) and returns ({values.shape[0]}) must align"
        )
    multipliers: list[float] = []
    for regime in range(n_components):
        mask = labels == regime
        count = int(mask.sum())
        keep = count >= min_observations and float(values[mask].mean()) > 0.0 if count else False
        multipliers.append(1.0 if keep else 0.0)
    return tuple(multipliers)


def regime_returns(
    regimes: npt.NDArray[np.intp],
    returns: npt.NDArray[np.float64] | pd.Series,
    n_components: int,
) -> Mapping[int, float]:
    """Return each regime's mean return (a diagnostic for "edge stable across regimes")."""
    values = np.asarray(returns, dtype="float64").ravel()
    labels = np.asarray(regimes, dtype=np.intp).ravel()
    summary: dict[int, float] = {}
    for regime in range(n_components):
        mask = labels == regime
        summary[regime] = float(values[mask].mean()) if mask.any() else float("nan")
    return summary


def fit_regime_gate(
    regime_features: pd.DataFrame,
    n_components: int,
    *,
    returns: npt.NDArray[np.float64] | pd.Series | None = None,
    multipliers: Sequence[float] | None = None,
    random_seed: int = 7,
) -> RegimeGate:
    """Fit a GMM on ``regime_features`` and build a :class:`RegimeGate`.

    If ``multipliers`` is given it is used directly; else if ``returns`` is given the gate is
    made data-driven via :func:`select_regime_multipliers`; else every regime is left on (1.0).

    Raises:
        ModelTrainingError: If both ``multipliers`` and ``returns`` are given (ambiguous).
    """
    if multipliers is not None and returns is not None:
        raise ModelTrainingError("pass either multipliers or returns to fit_regime_gate, not both")
    mixture = GaussianMixtureModel(n_components, random_seed=random_seed).fit(regime_features)
    if multipliers is not None:
        chosen = tuple(float(m) for m in multipliers)
    elif returns is not None:
        chosen = select_regime_multipliers(mixture.predict(regime_features), returns, n_components)
    else:
        chosen = tuple(1.0 for _ in range(n_components))
    return RegimeGate(mixture=mixture, multipliers=chosen)
