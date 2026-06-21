"""Fractional differentiation — the stationarity/memory dilemma (Deep Dive #2 §3.6).

*"ML wants stationary inputs; raw prices are non-stationary. The usual fix — take returns
(full differencing, d=1) — makes the series stationary but erases its memory. That memory
is often where the signal is."* Fractional differentiation is the dimmer switch between
the two: differentiate to a fractional order ``d in [0, 1]`` —

* ``d = 0``: the raw series (full memory, non-stationary),
* ``d = 1``: returns (stationary, memoryless),
* the **goal**: the *minimum* ``d`` that just passes a stationarity test (ADF), preserving
  the maximum possible memory while satisfying the model's statistical needs.

The differencing weights are the binomial series ``w_0 = 1``, ``w_k = -w_{k-1}(d-k+1)/k``;
they decay, so the **fixed-width-window** form (López de Prado, *Advances in Financial ML*
§5.5) truncates them once ``|w_k|`` falls below a threshold and convolves that fixed window
with the series. This makes the transform **causal** (the value at *t* uses only ``y_{t-k}``
for ``k >= 0``) — point-in-time correct, the same property the Layer-1 features guarantee.

Stationarity is judged with the **Augmented Dickey-Fuller** test from ``statsmodels`` (the
trusted implementation; §4b.8) — confined to this module. :func:`min_ffd` searches the ``d``
grid for the smallest order whose differenced series is stationary.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from quant.core.logging import get_logger
from quant.research.features_research.errors import FracDiffError

_logger = get_logger(__name__)

#: Default threshold below which trailing fractional-difference weights are dropped (§5.5).
DEFAULT_WEIGHT_THRESHOLD = 1e-5
#: Default ADF significance level for calling a series stationary.
DEFAULT_SIGNIFICANCE = 0.05
#: Minimum finite observations the ADF test needs (a small d's window can exceed a short
#: series, leaving too few points to test — such a candidate is skipped, not an error).
_MIN_OBSERVATIONS = 8


def frac_diff_weights(
    d: float, threshold: float = DEFAULT_WEIGHT_THRESHOLD
) -> npt.NDArray[np.float64]:
    """Return the fixed-width fractional-difference weights ``[w_0, w_1, ..., w_W]``.

    ``w_0 = 1`` (applied to the current value) and ``w_k = -w_{k-1}(d-k+1)/k``; the series is
    truncated at the first ``|w_k| < threshold``. ``d = 0`` yields ``[1]`` (identity);
    ``d = 1`` yields ``[1, -1]`` (the first difference).

    Raises:
        FracDiffError: If ``d < 0`` or ``threshold <= 0``.
    """
    if d < 0:
        raise FracDiffError(f"d must be non-negative, got {d}")
    if threshold <= 0:
        raise FracDiffError(f"threshold must be positive, got {threshold}")
    weights = [1.0]
    k = 1
    while True:
        nxt = -weights[-1] * (d - k + 1) / k
        if abs(nxt) < threshold:
            break
        weights.append(nxt)
        k += 1
    return np.asarray(weights, dtype="float64")


def frac_diff(
    series: pd.Series, d: float, threshold: float = DEFAULT_WEIGHT_THRESHOLD
) -> pd.Series:
    """Return the fixed-width-window fractional difference of ``series`` at order ``d``.

    The value at bar *t* is ``Σ_k w_k · y_{t-k}`` over the trailing weight window — causal,
    so it never uses a future value. The first ``W`` bars (the window warm-up) are ``NaN``.

    Args:
        series: A numeric series (e.g. log prices) indexed in time order. Must be free of
            NaNs over its span (frac-diff convolves a contiguous window).
        d: The fractional differencing order (``>= 0``; typically in ``[0, 1]``).
        threshold: Weight-truncation threshold (sets the window width).

    Raises:
        FracDiffError: If ``d`` / ``threshold`` are invalid or ``series`` contains NaNs.
    """
    weights = frac_diff_weights(d, threshold)
    width = len(weights) - 1
    values = series.to_numpy(dtype="float64")
    if np.isnan(values).any():
        raise FracDiffError("series must not contain NaNs over its span")
    output = np.full(values.shape[0], np.nan, dtype="float64")
    if values.shape[0] > width:
        # convolve(y, w)[t] = Σ_k y[t-k]·w[k]; valid (full-window) region is t >= width.
        convolved = np.convolve(values, weights)[width : values.shape[0]]
        output[width:] = convolved
    return pd.Series(output, index=series.index, name=f"fracdiff_{d:g}")


@dataclass(frozen=True, slots=True)
class ADFResult:
    """The Augmented Dickey-Fuller test outcome for a series."""

    statistic: float
    pvalue: float
    used_lag: int
    n_obs: int
    critical_values: dict[str, float]

    def is_stationary(self, significance: float = DEFAULT_SIGNIFICANCE) -> bool:
        """Whether the unit-root null is rejected at ``significance`` (i.e. stationary)."""
        return self.pvalue < significance


def adf_test(series: pd.Series, *, regression: str = "c", autolag: str | None = "AIC") -> ADFResult:
    """Run the Augmented Dickey-Fuller stationarity test on ``series`` (NaNs dropped).

    Args:
        series: The series to test.
        regression: ADF deterministic term (``"c"`` constant, default; ``"ct"`` etc.).
        autolag: Lag-selection criterion passed to statsmodels (``"AIC"`` by default).

    Raises:
        FracDiffError: If fewer than a handful of finite observations remain (ADF needs a
            minimal sample).
    """
    clean = series.dropna().to_numpy(dtype="float64")
    if clean.shape[0] < _MIN_OBSERVATIONS:
        raise FracDiffError(
            f"ADF needs at least {_MIN_OBSERVATIONS} observations, got {clean.shape[0]}"
        )
    statistic, pvalue, used_lag, n_obs, critical_values, _ = adfuller(
        clean, regression=regression, autolag=autolag
    )
    return ADFResult(
        statistic=float(statistic),
        pvalue=float(pvalue),
        used_lag=int(used_lag),
        n_obs=int(n_obs),
        critical_values={key: float(value) for key, value in critical_values.items()},
    )


@dataclass(frozen=True, slots=True)
class FracDiffResult:
    """The minimum-``d`` fractional-differentiation outcome."""

    d: float
    series: pd.Series
    adf: ADFResult


def min_ffd(
    series: pd.Series,
    *,
    d_candidates: Sequence[float] | None = None,
    threshold: float = DEFAULT_WEIGHT_THRESHOLD,
    significance: float = DEFAULT_SIGNIFICANCE,
) -> FracDiffResult:
    """Find the smallest ``d`` whose fractional difference of ``series`` is stationary.

    Searches ``d_candidates`` in ascending order, returning the first order whose
    fixed-width fractional difference passes the ADF test at ``significance`` — the maximum
    memory retained subject to stationarity (§3.6).

    Args:
        series: The series to difference (e.g. log prices).
        d_candidates: Ascending grid of ``d`` to try (default ``0, 0.05, ..., 1.0``).
        threshold: Weight-truncation threshold for the fractional differences.
        significance: ADF significance level for stationarity.

    Returns:
        The :class:`FracDiffResult` for the smallest stationary ``d``.

    Raises:
        FracDiffError: If no candidate ``d`` achieves stationarity.
    """
    grid = (
        list(d_candidates) if d_candidates is not None else [round(0.05 * i, 4) for i in range(21)]
    )
    for d in grid:
        differenced = frac_diff(series, d, threshold)
        # A small d's weight window can be wider than the series, leaving too few finite
        # points to test — skip such a candidate rather than failing the whole search.
        if int(differenced.notna().sum()) < _MIN_OBSERVATIONS:
            continue
        result = adf_test(differenced)
        if result.is_stationary(significance):
            _logger.info("min_ffd selected", extra={"d": d, "adf_pvalue": result.pvalue})
            return FracDiffResult(d=float(d), series=differenced, adf=result)
    raise FracDiffError(
        f"no d in [{grid[0]}, {grid[-1]}] achieved stationarity at significance {significance}"
    )
