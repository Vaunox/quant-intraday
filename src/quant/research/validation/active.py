"""Benchmark-relative (active) validation for the monthly factor strategy (Phase 3X.5).

A long-only book's *absolute* Sharpe is mostly market beta; the skill lives in the **active**
return (book minus benchmark TRI). So the kill-gate (config/factor_default.yaml) judges the
**active information ratio**, and this module computes it under the same CombinatorialPurgedCV /
Deflated-Sharpe machinery as the rest of the project — just on the active-return series.

Reuse, not rewrite: :func:`evaluate_active_under_cpcv` drives the existing
:class:`~quant.research.validation.cpcv.CombinatorialPurgedCV` over the monthly rebalance blocks
(the supplied ``backtest_fn`` returns the per-rebalance active return of a test fold), and the
path-Sharpe distribution it reconstructs — annualised by ``√periods_per_year`` (12 for monthly) —
**is** the active-IR distribution. The DSR is computed on the concatenated active returns against
the honest cumulative trial count; the honest **de-duplicated t-stat** (FINDINGS §3) is reported
alongside it, since the φ CPCV paths overlap and the path-concatenated basis flatters significance.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution
from quant.research.validation.metrics import deflated_sharpe_ratio_from_returns, sharpe_ratio

#: Rebalance frequency → periods/year for annualising a monthly active series.
MONTHLY_PERIODS_PER_YEAR = 12.0

#: backtest_fn(train_positions, test_positions) -> per-rebalance active returns of the test fold.
ActiveBacktestFn = Callable[[npt.NDArray[np.intp], npt.NDArray[np.intp]], pd.Series]


def active_returns(book: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Return the active return ``book - benchmark`` on their shared (inner-joined) index."""
    joined = pd.concat([book.rename("book"), benchmark.rename("benchmark")], axis=1).dropna()
    return (joined["book"] - joined["benchmark"]).rename("active")


def active_information_ratio(
    active: pd.Series, *, periods_per_year: float = MONTHLY_PERIODS_PER_YEAR
) -> float:
    """Return the annualised information ratio of an active-return series.

    The IR is the annualised Sharpe of the active (vs-benchmark) returns — mean over standard
    deviation, scaled by ``√periods_per_year`` (12 for a monthly book).
    """
    return sharpe_ratio(active, periods_per_year)


@dataclass(frozen=True, slots=True)
class ActiveEvaluation:
    """The CPCV outcome on active returns: the per-observation path-Sharpe distribution + paths.

    ``distribution`` holds **per-observation** active path-Sharpes (not annualised), so the DSR is
    computed in matching units; :attr:`annualised_ir` annualises the median for the kill-gate.
    """

    distribution: PathDistribution
    paths: tuple[pd.Series, ...]
    combined: pd.Series  # the concatenated active returns across all CPCV paths
    periods_per_year: float

    @property
    def annualised_ir(self) -> float:
        """The median active IR, annualised (kill-gate criterion 1)."""
        return float(self.distribution.median) * math.sqrt(self.periods_per_year)

    @property
    def fraction_negative(self) -> float:
        """Fraction of CPCV paths with a negative active Sharpe (criterion 4)."""
        return float(self.distribution.fraction_negative)

    @property
    def worst_path_ir(self) -> float:
        """Worst (most negative) path's annualised active IR (criterion 4)."""
        return float(self.distribution.minimum) * math.sqrt(self.periods_per_year)

    def deflated_sharpe(self, *, n_trials: int) -> float:
        """The Deflated Sharpe Ratio on the concatenated active returns at the honest ``n_trials``.

        Path-concatenated basis (the FINDINGS §3 convention) — read with :attr:`dedup_tstat`.
        """
        variance = (
            float(np.var(self.distribution.path_sharpes, ddof=1))
            if self.distribution.num_paths > 1
            else 0.0
        )
        return float(deflated_sharpe_ratio_from_returns(self.combined, variance, n_trials=n_trials))

    @property
    def dedup_tstat(self) -> float:
        """The honest de-duplicated t-stat of the active edge (FINDINGS §3).

        The φ CPCV paths are overlapping reconstructions of the same observations, so the
        path-concatenated t-stat over-counts by ≈ ``√φ``; dividing it out gives the de-duplicated,
        independent-sample t-stat that should be read against the multiple-testing hurdle.
        """
        values = self.combined.to_numpy(dtype="float64")
        values = values[~np.isnan(values)]
        std = float(values.std(ddof=1)) if values.size > 1 else 0.0
        if std == 0.0 or values.size < 2:
            return 0.0
        t_concatenated = float(values.mean()) / std * math.sqrt(values.size)
        phi = max(self.distribution.num_paths, 1)
        return t_concatenated / math.sqrt(phi)


def evaluate_active_under_cpcv(
    label_times: pd.Series,
    backtest_fn: ActiveBacktestFn,
    cpcv: CombinatorialPurgedCV,
    *,
    periods_per_year: float = MONTHLY_PERIODS_PER_YEAR,
) -> ActiveEvaluation:
    """Run CPCV over the rebalance blocks; reconstruct the active-IR path distribution.

    Args:
        label_times: monthly ``t0 -> t1`` spans (P3X.3) driving the purge/embargo on the time axis.
        backtest_fn: given purged train / test position arrays, returns that test fold's
            per-rebalance **active** return series (book minus benchmark).
        cpcv: the configured combinatorial purged CV (its embargo must cover ≥ one label horizon).
        periods_per_year: annualisation factor for the IR (12 for monthly).

    Returns:
        An :class:`ActiveEvaluation` (per-observation distribution + paths + concatenated actives).
    """
    paths, distribution = cpcv.run(label_times, backtest_fn, periods_per_year=None)
    combined = pd.concat(list(paths)).dropna() if paths else pd.Series(dtype="float64")
    return ActiveEvaluation(
        distribution=distribution,
        paths=tuple(paths),
        combined=combined,
        periods_per_year=periods_per_year,
    )
