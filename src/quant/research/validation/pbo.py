"""Probability of Backtest Overfitting via CSCV (Deep Dive #2 §4b.4).

**Combinatorially Symmetric Cross-Validation** (Bailey, Borwein, López de Prado, Zhu)
estimates the probability that the configuration which looked **best in-sample** actually
**underperforms the median out-of-sample**. It is model-free and non-parametric: a high
PBO means the selection process is just picking lucky overfits. *"Treat anything above
~0.2-0.5 as a serious warning."*

**Algorithm.** Given a performance matrix ``M`` of shape ``(T observations, N candidate
strategies)`` (per-observation returns), split the ``T`` rows into ``S`` disjoint
contiguous partitions (``S`` even). For each of the ``C(S, S/2)`` ways to choose ``S/2``
partitions as the in-sample (IS) set, with the complement as out-of-sample (OOS):

1. Rank the strategies by IS Sharpe; pick the best, ``n*``.
2. Find ``n*``'s **relative rank** ``ω`` among the OOS Sharpes (``ω ∈ (0, 1)``; 0.5 = the
   OOS median), and its logit ``λ = ln(ω / (1-ω))``.

``PBO = mean(λ <= 0)`` — the rate at which the IS-best strategy lands at or below the OOS
median. A genuine edge keeps the IS winner winning OOS (``λ > 0`` → low PBO); pure
selection among noise gives ``λ`` symmetric about 0 → ``PBO ≈ 0.5``.
"""

import itertools
import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.validation.errors import PBOError

_logger = get_logger(__name__)

#: Default number of CSCV partitions (the BBLZ paper's choice; must be even).
DEFAULT_PARTITIONS = 16


@dataclass(frozen=True, slots=True)
class PBOResult:
    """The CSCV verdict: the PBO scalar plus the per-combination logit distribution."""

    pbo: float
    logits: npt.NDArray[np.float64]

    @property
    def n_combinations(self) -> int:
        """Number of CSCV IS/OOS combinations evaluated, ``C(S, S/2)``."""
        return int(self.logits.shape[0])


def probability_of_backtest_overfitting(
    performance: pd.DataFrame | npt.NDArray[np.float64],
    *,
    n_partitions: int = DEFAULT_PARTITIONS,
) -> PBOResult:
    """Return the Probability of Backtest Overfitting of a candidate-strategy set.

    Args:
        performance: A ``(T, N)`` matrix of per-observation returns — one column per
            candidate strategy/configuration (>= 2 columns).
        n_partitions: Number of CSCV partitions ``S`` (even, >= 2). ``T`` must be at least
            ``2·S`` so every IS/OOS block has the >= 2 rows a Sharpe needs.

    Returns:
        A :class:`PBOResult` with the PBO scalar and the ``C(S, S/2)`` logits.

    Raises:
        PBOError: If the matrix is not 2-D with >= 2 strategies, ``n_partitions`` is odd or
            < 2, or there are fewer than ``2·n_partitions`` observations.
    """
    matrix = np.asarray(performance, dtype="float64")
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise PBOError(f"performance must be (T, N>=2), got shape {matrix.shape}")
    if n_partitions < 2 or n_partitions % 2 != 0:
        raise PBOError(f"n_partitions must be even and >= 2, got {n_partitions}")
    n_obs, n_strategies = matrix.shape
    if n_obs < 2 * n_partitions:
        raise PBOError(f"need at least 2*n_partitions={2 * n_partitions} observations, got {n_obs}")

    partitions = np.array_split(np.arange(n_obs), n_partitions)
    half = n_partitions // 2
    logits: list[float] = []
    for is_groups in itertools.combinations(range(n_partitions), half):
        is_set = set(is_groups)
        is_rows = np.concatenate([partitions[g] for g in is_groups])
        oos_rows = np.concatenate([partitions[g] for g in range(n_partitions) if g not in is_set])
        is_sharpes = _strategy_sharpes(matrix[is_rows])
        oos_sharpes = _strategy_sharpes(matrix[oos_rows])
        best = int(np.argmax(is_sharpes))
        logits.append(_relative_logit(oos_sharpes, best, n_strategies))

    logit_array = np.asarray(logits, dtype="float64")
    pbo = float(np.mean(logit_array <= 0.0))
    _logger.info(
        "pbo via cscv",
        extra={"pbo": pbo, "combinations": logit_array.shape[0], "strategies": n_strategies},
    )
    return PBOResult(pbo=pbo, logits=logit_array)


def _strategy_sharpes(block: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Per-strategy Sharpe over a block of rows (zero where a strategy has no dispersion)."""
    mean = block.mean(axis=0)
    std = block.std(axis=0, ddof=1)
    sharpes: npt.NDArray[np.float64] = np.zeros_like(mean)
    nonzero = std > 0.0
    sharpes[nonzero] = mean[nonzero] / std[nonzero]
    return sharpes


def _relative_logit(oos_sharpes: npt.NDArray[np.float64], best: int, n_strategies: int) -> float:
    """Logit of the IS-best strategy's relative OOS rank (ties averaged).

    Rank is 1 (worst) .. ``N`` (best); ``ω = rank / (N+1) ∈ (0, 1)`` so the logit is always
    finite. ``λ <= 0`` means the IS winner is at or below the OOS median.
    """
    target = oos_sharpes[best]
    fewer = int(np.sum(oos_sharpes < target))
    tied = int(np.sum(oos_sharpes == target))
    rank = fewer + (tied + 1) / 2.0  # 1-based average rank
    omega = rank / (n_strategies + 1)
    return math.log(omega / (1.0 - omega))
