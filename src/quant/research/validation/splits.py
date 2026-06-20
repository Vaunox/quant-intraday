"""Purged k-fold cross-validation with an embargo (Deep Dive #2 §4b.1).

*"Ordinary k-fold cross-validation leaks in finance because (a) labels span time
windows that overlap across folds, and (b) serial correlation makes adjacent
observations non-independent."* Two corrections, applied to **every** CV in this layer:

* **Purging** — remove from the *training* set any observation whose label window
  overlaps the test set's time span. Kills the most direct leak.
* **Embargoing** — drop a small buffer of observations immediately *after* the test
  set before resuming training, so serial correlation can't leak test information
  forward into training. The embargo length should be ≈ the label horizon.

This is the foundation the rest of the validation engine (CPCV, the cost backtester
walk-forward, hyper-parameter tuning) builds on — without it *"every number below is
optimistic fiction"* (§4b.1). The technique is from López de Prado, *Advances in
Financial ML* (AFML), ch. 7.

**Contract.** Each observation is described by its label window ``[t0, t1]``: ``t0`` is
the event/decision time (when the features are computed), ``t1`` is when the label
resolves (the triple-barrier touch or the vertical/square-off barrier; P2.3). Callers
pass these as a :class:`pandas.Series` named ``label_times`` whose **index** is ``t0``
(sorted, unique, tz-aware) and whose **values** are ``t1``. :meth:`PurgedKFold.split`
yields integer-position :class:`Fold` index arrays — the same shape sklearn produces —
so a model trainer can do ``X.iloc[fold.train]`` / ``X.iloc[fold.test]``.

**Overlap definition (the invariant the tests pin).** Two closed windows ``[a0, a1]``
and ``[b0, b1]`` overlap iff ``a0 <= b1 and b0 <= a1``. After purging+embargo, **no**
training window overlaps the test set's span — the splitter enforces strict
non-overlap, slightly stricter than AFML's ``<=`` boundary, because a label resolving
at the exact instant the test begins (or ends) is a leak we would rather drop than keep.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.validation.errors import SplitError

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Fold:
    """One purged train/test split as integer positions into the observation sequence.

    ``train`` and ``test`` are disjoint, sorted position arrays (``numpy`` intp), used
    directly with ``DataFrame.iloc`` / ``ndarray`` fancy-indexing. ``train`` has already
    had overlapping and embargoed observations removed.
    """

    train: npt.NDArray[np.intp]
    test: npt.NDArray[np.intp]


def embargo_size(n_observations: int, embargo_pct: float) -> int:
    """Return the embargo length in observations: ``floor(n * embargo_pct)``.

    Exposed (and tested) separately because the embargo is a distinct, citable knob:
    the number of post-test observations dropped to stop serial correlation leaking
    forward. ``embargo_pct`` should be set to ≈ the label horizon as a fraction of the
    sample (§4b.1).
    """
    return int(n_observations * embargo_pct)


class PurgedKFold:
    """k-fold splitter that purges overlapping labels and embargoes the post-test buffer.

    Folds are contiguous in time (the timeline is cut into ``n_splits`` equal blocks,
    each used once as the test set), which is what makes a financial CV honest: a
    shuffled k-fold would scatter test points among their own overlapping neighbours.
    """

    def __init__(self, n_splits: int, *, embargo_pct: float = 0.0) -> None:
        """Build the splitter.

        Args:
            n_splits: Number of folds (>= 2). The timeline is cut into this many
                contiguous test blocks.
            embargo_pct: Fraction of the sample to embargo *after* each test block
                (``[0, 1)``). Defaults to 0; set it to ≈ the label horizon / sample
                length. Purging alone handles the pre-test side; the embargo is the
                forward-only buffer.

        Raises:
            SplitError: If ``n_splits < 2`` or ``embargo_pct`` is outside ``[0, 1)``.
        """
        if n_splits < 2:
            raise SplitError(f"n_splits must be >= 2, got {n_splits}")
        if not 0.0 <= embargo_pct < 1.0:
            raise SplitError(f"embargo_pct must be in [0, 1), got {embargo_pct}")
        self._n_splits = n_splits
        self._embargo_pct = embargo_pct

    @property
    def n_splits(self) -> int:
        """The configured number of folds."""
        return self._n_splits

    def split(self, label_times: pd.Series) -> Iterator[Fold]:
        """Yield ``n_splits`` purged, embargoed train/test folds for ``label_times``.

        Args:
            label_times: A Series indexed by event time ``t0`` (sorted, unique, tz-aware)
                whose values are the label-resolution time ``t1`` (>= the index). This is
                the natural output of the triple-barrier labeler (P2.3).

        Yields:
            One :class:`Fold` per split, in time order. ``test`` is the contiguous block;
            ``train`` is every other observation whose label window does not overlap the
            block's span, minus the post-block embargo.

        Raises:
            SplitError: If the index is not a sorted, unique ``DatetimeIndex``, the values
                are not datetimes, any ``t1 < t0``, or there are fewer observations than
                folds.
        """
        starts, ends = _validate_label_times(label_times, self._n_splits)
        n = starts.shape[0]
        embargo = embargo_size(n, self._embargo_pct)
        positions = np.arange(n)

        for block in np.array_split(positions, self._n_splits):
            test_start = int(block[0])
            test_end = int(block[-1])  # inclusive
            test = positions[test_start : test_end + 1]

            t0_test = starts[test_start]  # the test block's first event time
            t1_test_max = ends[test_start : test_end + 1].max()  # last label resolution in block

            # Train-before: the label resolved strictly before the test block begins, so
            # its window cannot reach into the block.
            before = ends < t0_test
            # Train-after: the event begins strictly after the block's last label resolves
            # (no overlap), then skip a further `embargo` observations (forward buffer).
            # searchsorted(side="right") gives the first position whose t0 > t1_test_max.
            resume = int(np.searchsorted(starts, t1_test_max, side="right")) + embargo
            after = positions >= resume

            keep = before | after
            keep[test_start : test_end + 1] = False  # never train on a test observation
            train = positions[keep]

            _logger.debug(
                "purged fold",
                extra={
                    "test_start": test_start,
                    "test_size": int(test.shape[0]),
                    "train_size": int(train.shape[0]),
                    "embargo": embargo,
                },
            )
            yield Fold(train=train, test=test)


def _validate_label_times(
    label_times: pd.Series, n_splits: int
) -> tuple[npt.NDArray[np.datetime64], npt.NDArray[np.datetime64]]:
    """Validate the label-times contract and return ``(t0_array, t1_array)``.

    Returns the event times (index) and label-resolution times (values) as ``datetime64``
    arrays in a single (UTC) basis for fast, order-correct vectorized comparison. Raises
    :class:`SplitError` on any contract violation (Ground Rule 7: fail loudly at boundary).
    """
    index = label_times.index
    if not isinstance(index, pd.DatetimeIndex):
        raise SplitError(f"label_times must have a DatetimeIndex, got {type(index)}")
    if index.tz is None:
        raise SplitError("label_times index must be timezone-aware (the system is IST)")
    if not index.is_monotonic_increasing:
        raise SplitError("label_times index must be sorted ascending by event time")
    if not index.is_unique:
        raise SplitError("label_times index must be unique (one label per event time)")
    n = len(label_times)
    if n < n_splits:
        raise SplitError(f"need at least n_splits={n_splits} observations, got {n}")
    if not isinstance(label_times.dtype, pd.DatetimeTZDtype):
        raise SplitError("label_times values (t1) must be timezone-aware datetimes")

    # Convert both sides to a single UTC datetime64 basis: ordering is preserved and the
    # two arrays are directly comparable (searchsorted/`<`), independent of the input tz.
    starts = index.tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    ends = pd.DatetimeIndex(label_times).tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    if np.any(ends < starts):
        raise SplitError("every label-resolution time t1 must be >= its event time t0")
    return starts, ends
