"""Performance statistics for the "is the edge real?" toolkit (Deep Dive #2 §4b.3).

The Sharpe ratio and its multiple-testing-aware corrections — the **Probabilistic** and
**Deflated** Sharpe Ratios (Bailey & López de Prado, 2014). A high Sharpe is trivially
manufacturable by trying enough configurations; these statistics ask whether an observed
Sharpe is significant *given* how non-normal the returns are and *how many trials* were
run.

* **PSR** — the probability the true Sharpe exceeds a benchmark, correcting for sample
  length ``T`` and the returns' skewness ``g3`` and kurtosis ``g4``::

      PSR(SR*) = Φ[ (SR_hat - SR*)·√(T-1) / √(1 - g3·SR_hat + (g4-1)/4·SR_hat²) ]

* **DSR** — PSR evaluated at the **expected maximum** Sharpe under ``N`` independent
  trials, the deflation benchmark::

      SR0 = √V · [ (1-gamma)·Φ⁻¹(1 - 1/N) + gamma·Φ⁻¹(1 - 1/(N·e)) ]

  where ``V`` is the variance of the trials' Sharpes, ``gamma`` is the Euler-Mascheroni
  constant, and ``Φ`` the standard-normal CDF. DSR = ``PSR(SR0)``.

All Sharpes fed to PSR/DSR are **non-annualised** (per-observation): the ``√(T-1)`` term
already scales for sample length. The standard-normal CDF/quantile come from the stdlib
:class:`statistics.NormalDist` (no SciPy dependency). NaNs (e.g. a backtest's first,
undefined return) are dropped before any moment is computed.
"""

import math
from collections.abc import Sequence
from statistics import NormalDist

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.validation.errors import MetricError

#: Euler-Mascheroni constant gamma, used in the expected-maximum-Sharpe deflation benchmark.
_EULER_MASCHERONI = 0.5772156649015329
_NORMAL = NormalDist()
ReturnsLike = Sequence[float] | npt.NDArray[np.float64] | pd.Series


def _clean(returns: ReturnsLike) -> npt.NDArray[np.float64]:
    """Return ``returns`` as a 1-D float array with NaNs dropped."""
    array = np.asarray(returns, dtype="float64").ravel()
    clean: npt.NDArray[np.float64] = array[~np.isnan(array)]
    return clean


def sharpe_ratio(returns: ReturnsLike, periods_per_year: float | None = None) -> float:
    """Return the Sharpe ratio of ``returns`` (excess assumed already applied).

    Args:
        returns: A return series (NaNs are dropped).
        periods_per_year: If given, annualise by ``√(periods_per_year)``; otherwise the
            ratio is per-observation (what PSR/DSR require). For the CPCV path-Sharpe
            distribution and the kill-gate's "median path-Sharpe > 1.0", pass the
            annualisation factor.

    Returns:
        ``mean / std`` (sample std, ``ddof=1``), optionally annualised. A flat
        zero-return stream has Sharpe 0.

    Raises:
        MetricError: If fewer than two finite returns, or a riskless non-zero stream
            (zero dispersion with non-zero mean — an undefined Sharpe).
    """
    clean = _clean(returns)
    if clean.size < 2:
        raise MetricError(f"need at least 2 finite returns for a Sharpe ratio, got {clean.size}")
    std = float(clean.std(ddof=1))
    mean = float(clean.mean())
    if std == 0.0:
        if mean == 0.0:
            return 0.0  # a flat stream: zero risk-adjusted excess
        raise MetricError("Sharpe ratio undefined: zero dispersion with non-zero mean")
    ratio = mean / std
    if periods_per_year is not None:
        ratio *= math.sqrt(periods_per_year)
    return ratio


def return_moments(returns: ReturnsLike) -> tuple[float, float, float, int]:
    """Return ``(sharpe, skewness, kurtosis, n)`` for PSR/DSR (non-annualised, biased).

    ``sharpe`` uses the sample std (``ddof=1``); ``skewness``/``kurtosis`` are the biased
    (population) moments — ``g3 = m3/m2^1.5``, ``g4 = m4/m2²`` (non-excess; normal → 3) —
    matching the convention the PSR/DSR formulas were calibrated against.

    Raises:
        MetricError: If fewer than two finite returns or zero dispersion.
    """
    clean = _clean(returns)
    n = clean.size
    if n < 2:
        raise MetricError(f"need at least 2 finite returns for moments, got {n}")
    mean = float(clean.mean())
    m2 = float(((clean - mean) ** 2).mean())
    if m2 == 0.0:
        raise MetricError("return moments undefined: zero dispersion")
    m3 = float(((clean - mean) ** 3).mean())
    m4 = float(((clean - mean) ** 4).mean())
    sharpe = mean / float(clean.std(ddof=1))
    skewness = m3 / m2**1.5
    kurtosis = m4 / m2**2
    return sharpe, skewness, kurtosis, n


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    n_obs: int,
    skewness: float,
    kurtosis: float,
    benchmark_sharpe: float = 0.0,
) -> float:
    """Return the Probabilistic Sharpe Ratio: ``P(true SR > benchmark)`` in ``[0, 1]``.

    Args:
        observed_sharpe: The non-annualised observed Sharpe ``SR_hat``.
        n_obs: Number of return observations ``T`` (>= 2).
        skewness: Returns skewness ``g3``.
        kurtosis: Returns kurtosis ``g4`` (non-excess; normal → 3).
        benchmark_sharpe: The benchmark ``SR*`` to beat (0 = "better than nothing"; the
            DSR passes the expected-maximum Sharpe here).

    Raises:
        MetricError: If ``n_obs < 2`` or the variance term is non-positive (an
            ill-defined estimator for these moments).
    """
    if n_obs < 2:
        raise MetricError(f"PSR needs at least 2 observations, got {n_obs}")
    variance_term = 1.0 - skewness * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe**2
    if variance_term <= 0.0:
        raise MetricError(f"PSR variance term must be positive, got {variance_term:.4g}")
    test_statistic = (observed_sharpe - benchmark_sharpe) * math.sqrt(n_obs - 1)
    test_statistic /= math.sqrt(variance_term)
    return _NORMAL.cdf(test_statistic)


def expected_maximum_sharpe_ratio(sharpe_variance: float, n_trials: int) -> float:
    """Return the expected maximum of ``n_trials`` i.i.d. Sharpes — the DSR benchmark.

    ``SR0 = √V·[(1-gamma)·Φ⁻¹(1 - 1/N) + gamma·Φ⁻¹(1 - 1/(N·e))]``. With a single trial there is
    no multiple-testing inflation, so the benchmark is 0.

    Args:
        sharpe_variance: Variance ``V`` of the trials' Sharpe ratios (>= 0).
        n_trials: Number of trials ``N`` (>= 1).

    Raises:
        MetricError: If ``sharpe_variance < 0`` or ``n_trials < 1``.
    """
    if sharpe_variance < 0.0:
        raise MetricError(f"sharpe_variance must be non-negative, got {sharpe_variance}")
    if n_trials < 1:
        raise MetricError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_obs: int,
    skewness: float,
    kurtosis: float,
    sharpe_variance: float,
    n_trials: int,
) -> float:
    """Return the Deflated Sharpe Ratio = ``PSR`` at the expected-maximum-Sharpe benchmark.

    Corrects the observed Sharpe's significance for the number of trials, the returns'
    skew/kurtosis, and the sample length. A value near 1 means the edge survives the
    multiple-testing deflation; near 0 means it does not.
    """
    benchmark = expected_maximum_sharpe_ratio(sharpe_variance, n_trials)
    return probabilistic_sharpe_ratio(observed_sharpe, n_obs, skewness, kurtosis, benchmark)


def deflated_sharpe_ratio_from_returns(
    returns: ReturnsLike, sharpe_variance: float, n_trials: int
) -> float:
    """Convenience: compute the DSR directly from a return series and the trial stats.

    Derives the non-annualised Sharpe, skewness, kurtosis, and sample length from
    ``returns`` (via :func:`return_moments`), then applies :func:`deflated_sharpe_ratio`.
    ``sharpe_variance`` and ``n_trials`` come from the honest trial log
    (:class:`~quant.research.validation.trials.TrialTracker`).
    """
    observed_sharpe, skewness, kurtosis, n_obs = return_moments(returns)
    return deflated_sharpe_ratio(
        observed_sharpe, n_obs, skewness, kurtosis, sharpe_variance, n_trials
    )
