"""Combinatorial Purged Cross-Validation (Deep Dive #2 §4b.2).

Walk-forward yields exactly **one** historical path, so its Sharpe reflects one ordering
of luck. CPCV generates **many** out-of-sample paths and judges the whole distribution.

**Mechanics.** Partition the timeline into ``N`` groups; choose ``k`` of them as the test
set each time. That yields ``C(N, k)`` purged train/test splits, which stitch together
into::

    φ = C(N, k)·k / N = C(N-1, k-1)   distinct backtest paths

(e.g. N=6, k=2 → C(6,2)=15 splits → φ=5 paths, each covering the full timeline once).
The performance metric is computed **per path** — *the paths, not the individual splits,
are the correct unit*.

**How to read it.** A *robust* strategy shows a **narrow, positive** path-Sharpe
distribution (kill-gate: median > 1.0, no deeply negative paths); a *fragile* one shows
**wild variance** — a high mean is meaningless if some paths are deeply negative.

Every split is purged + embargoed via the shared primitive
(:func:`~quant.research.validation.splits.purged_train_mask`); because the ``k`` test
groups may be non-adjacent, that primitive purges each contiguous test run independently.
"""

import itertools
import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.validation.errors import SplitError
from quant.research.validation.metrics import sharpe_ratio
from quant.research.validation.splits import (
    _validate_label_times,
    embargo_size,
    purged_train_mask,
)

_logger = get_logger(__name__)

#: A backtest callable: given a split's train and test positions, return the per-test
#: observation OOS returns indexed by the test observations' timestamps.
BacktestFn = Callable[[npt.NDArray[np.intp], npt.NDArray[np.intp]], pd.Series]


@dataclass(frozen=True, slots=True)
class CombinatorialSplit:
    """One CPCV split: purged training positions + a test set spanning ``k`` groups."""

    train: npt.NDArray[np.intp]
    test: npt.NDArray[np.intp]
    test_groups: tuple[int, ...]  # which of the N groups form this split's test set


@dataclass(frozen=True, slots=True)
class PathDistribution:
    """The distribution of per-path Sharpe ratios — the CPCV verdict surface.

    The kill-gate reads ``median`` (criterion 1: > 1.0 after costs) and ``minimum`` /
    ``fraction_negative`` (criterion 4: a narrow, positive distribution with no deeply
    negative paths). ``std`` quantifies fragility.
    """

    path_sharpes: npt.NDArray[np.float64]

    @property
    def num_paths(self) -> int:
        """Number of reconstructed paths φ."""
        return int(self.path_sharpes.shape[0])

    @property
    def median(self) -> float:
        """Median path-Sharpe (the kill-gate's central estimate)."""
        return float(np.median(self.path_sharpes))

    @property
    def mean(self) -> float:
        """Mean path-Sharpe."""
        return float(np.mean(self.path_sharpes))

    @property
    def std(self) -> float:
        """Dispersion of path-Sharpes (wide → fragile)."""
        return float(np.std(self.path_sharpes, ddof=1)) if self.num_paths > 1 else 0.0

    @property
    def minimum(self) -> float:
        """Worst path-Sharpe (a deeply negative value disqualifies regardless of mean)."""
        return float(np.min(self.path_sharpes))

    @property
    def fraction_negative(self) -> float:
        """Fraction of paths with a negative Sharpe."""
        return float(np.mean(self.path_sharpes < 0.0))


class CombinatorialPurgedCV:
    """CPCV splitter + path reconstruction (the primary "is the edge real?" test)."""

    def __init__(self, n_groups: int, n_test_groups: int, *, embargo_pct: float = 0.0) -> None:
        """Build the CPCV scheme.

        Args:
            n_groups: Number of contiguous timeline groups ``N`` (>= 2).
            n_test_groups: Test groups per split ``k`` (``1 <= k < N``; the standard choice
                is 2, which gives multiple paths while keeping the test set small).
            embargo_pct: Forward embargo as a fraction of the sample (``[0, 1)``), applied
                after each contiguous test run.

        Raises:
            SplitError: If ``N < 2``, ``k`` is outside ``[1, N)``, or ``embargo_pct`` is
                outside ``[0, 1)``.
        """
        if n_groups < 2:
            raise SplitError(f"n_groups must be >= 2, got {n_groups}")
        if not 1 <= n_test_groups < n_groups:
            raise SplitError(f"n_test_groups must be in [1, {n_groups}), got {n_test_groups}")
        if not 0.0 <= embargo_pct < 1.0:
            raise SplitError(f"embargo_pct must be in [0, 1), got {embargo_pct}")
        self._n_groups = n_groups
        self._k = n_test_groups
        self._embargo_pct = embargo_pct

    @property
    def num_splits(self) -> int:
        """Number of train/test splits ``C(N, k)``."""
        return math.comb(self._n_groups, self._k)

    @property
    def num_paths(self) -> int:
        """Number of reconstructed backtest paths ``φ = C(N-1, k-1)``."""
        return math.comb(self._n_groups - 1, self._k - 1)

    def split(self, label_times: pd.Series) -> Iterator[CombinatorialSplit]:
        """Yield the ``C(N, k)`` purged, embargoed combinatorial splits for ``label_times``.

        Args:
            label_times: Event-time-indexed Series of label-resolution times (the same
                contract as :class:`~quant.research.validation.splits.PurgedKFold`).

        Raises:
            SplitError: On any ``label_times`` contract violation, or fewer observations
                than groups.
        """
        starts, ends = _validate_label_times(label_times, self._n_groups)
        n = starts.shape[0]
        embargo = embargo_size(n, self._embargo_pct)
        membership = self._group_membership(n)
        positions = np.arange(n)
        for test_groups in self._combinations():
            test_mask = np.isin(membership, np.asarray(test_groups))
            test = positions[test_mask]
            train = positions[purged_train_mask(starts, ends, test_mask, embargo)]
            yield CombinatorialSplit(train=train, test=test, test_groups=test_groups)

    def reconstruct_paths(
        self, label_times: pd.Series, per_split_returns: Sequence[pd.Series]
    ) -> list[pd.Series]:
        """Stitch per-split OOS returns into ``φ`` full-timeline path return series.

        Args:
            label_times: The same Series passed to :meth:`split` (defines the timeline).
            per_split_returns: One OOS return series per split (in :meth:`split` order),
                each indexed by that split's test-observation timestamps. Element ``c`` is
                the backtest's per-observation return on split ``c``'s test set.

        Returns:
            ``φ`` Series, each indexed by the full ``label_times`` index — every group's
            returns drawn from exactly one split, tiling the timeline once.

        Raises:
            SplitError: If ``per_split_returns`` does not have exactly ``num_splits``
                elements.
        """
        if len(per_split_returns) != self.num_splits:
            raise SplitError(
                f"expected {self.num_splits} per-split return series, got {len(per_split_returns)}"
            )
        _validate_label_times(label_times, self._n_groups)  # enforce the timeline contract
        index = label_times.index
        n = len(label_times)
        groups = self._groups(n)
        assignment = self._path_assignment()  # assignment[g][p] = split index for group g, path p
        aligned = [series.reindex(index).to_numpy(dtype="float64") for series in per_split_returns]

        paths: list[pd.Series] = []
        for path in range(self.num_paths):
            values = np.full(n, np.nan, dtype="float64")
            for group, positions in enumerate(groups):
                split_index = assignment[group][path]
                values[positions] = aligned[split_index][positions]
            paths.append(pd.Series(values, index=index, name=f"path_{path}"))
        return paths

    def path_distribution(
        self, paths: Sequence[pd.Series], *, periods_per_year: float | None = None
    ) -> PathDistribution:
        """Return the per-path Sharpe distribution (optionally annualised)."""
        sharpes = np.array(
            [sharpe_ratio(path, periods_per_year) for path in paths], dtype="float64"
        )
        _logger.info(
            "cpcv path distribution",
            extra={"num_paths": len(paths), "median_sharpe": float(np.median(sharpes))},
        )
        return PathDistribution(path_sharpes=sharpes)

    def run(
        self,
        label_times: pd.Series,
        backtest_fn: BacktestFn,
        *,
        periods_per_year: float | None = None,
    ) -> tuple[list[pd.Series], PathDistribution]:
        """End-to-end: run ``backtest_fn`` over every split, reconstruct paths, summarise.

        ``backtest_fn(train_positions, test_positions)`` returns the OOS per-observation
        returns for that split's test set, indexed by the test observations' timestamps.
        """
        splits = list(self.split(label_times))
        per_split_returns = [backtest_fn(s.train, s.test) for s in splits]
        paths = self.reconstruct_paths(label_times, per_split_returns)
        return paths, self.path_distribution(paths, periods_per_year=periods_per_year)

    def _combinations(self) -> list[tuple[int, ...]]:
        """The canonical, ordered list of test-group combinations (``C(N, k)`` of them)."""
        return list(itertools.combinations(range(self._n_groups), self._k))

    def _groups(self, n: int) -> list[npt.NDArray[np.intp]]:
        """Partition ``n`` positions into ``N`` contiguous, roughly-equal groups."""
        return np.array_split(np.arange(n), self._n_groups)

    def _group_membership(self, n: int) -> npt.NDArray[np.intp]:
        """Map each position to its group index."""
        membership = np.empty(n, dtype=np.intp)
        for group, positions in enumerate(self._groups(n)):
            membership[positions] = group
        return membership

    def _path_assignment(self) -> list[list[int]]:
        """For each group, the ordered split indices that test it (length ``φ`` each).

        Path ``p`` takes group ``g``'s returns from split ``assignment[g][p]``; because a
        group is a test group in exactly ``φ`` splits, the columns of this grid are the
        ``φ`` full-timeline paths.
        """
        assignment: list[list[int]] = [[] for _ in range(self._n_groups)]
        for split_index, combo in enumerate(self._combinations()):
            for group in combo:
                assignment[group].append(split_index)
        return assignment
