"""Sample weighting for non-IID labels (Deep Dive #2 §3.5).

*"ML libraries assume independent samples. Financial labels violate this badly: overlapping
triple-barrier windows share the same underlying returns, so two 'samples' can be largely
the same information."* Three of the four corrections (all from López de Prado, *Advances
in Financial ML*, ch. 4) live here; the fourth — sequential bootstrap — is in
:mod:`~quant.research.labeling.bootstrap`.

The foundation is the **indicator matrix** ``1[t in [t0_i, t1_i]]`` (bars x labels): a label
is "active" over every bar from its event ``t0`` to its resolution ``t1``. From it:

* **Concurrency** ``c_t`` = how many labels are active at bar ``t`` (the row sums).
* **Average uniqueness** of label ``i`` = the mean over its active bars of ``1/c_t`` —
  overlapping (redundant) labels get down-weighted, isolated ones up-weighted. *"This is
  the single most important correction."* These are the primary sample weights.
* **Return-attribution** weight of label ``i`` = ``|Σ_t r_t / c_t|`` over its active bars —
  each bar's return split among the labels co-active there, so large, genuinely-attributable
  moves matter more (§4.4).
* **Time-decay** factors over *cumulative uniqueness* (not raw time): the newest label keeps
  weight 1, older ones decay toward ``last_weight`` (§4.5), reflecting that older
  relationships fade. Multiply these into the uniqueness / return-attribution weights.

``label_times`` is the triple-barrier output (event ``t0`` -> resolution ``t1``); ``bar_times``
is the full bar timeline spanning the labels (concurrency is counted over *bars*, not just
events). This package consumes the labeler output and stays independent of the validation
package (labels are upstream of cross-validation).
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.labeling.errors import LabelingInputError

_logger = get_logger(__name__)

#: Column/series names produced here (stable for downstream consumers).
CONCURRENCY = "concurrency"
UNIQUENESS = "uniqueness"
WEIGHT = "weight"
DECAY = "time_decay"


class SampleWeights:
    """Concurrency-based sample weights for an overlapping label set.

    Builds the (bars x labels) indicator matrix once at construction, then derives
    concurrency, average uniqueness, and return-attribution weights from it. The matrix is
    also the input to the sequential bootstrap.
    """

    def __init__(self, bar_times: pd.DatetimeIndex, label_times: pd.Series) -> None:
        """Build the indicator matrix from the bar timeline and the label spans.

        Args:
            bar_times: The full bar timeline (tz-aware, sorted, unique) spanning the labels.
            label_times: The triple-barrier label spans — index is the event time ``t0``
                (sorted, unique, tz-aware), values are the resolution time ``t1`` (every
                ``t0`` and ``t1`` must be a bar in ``bar_times``).

        Raises:
            LabelingInputError: On any malformed timeline / label-times contract.
        """
        _validate_timeline(bar_times)
        start_pos, end_pos = _label_positions(bar_times, label_times)
        self._bar_times = bar_times
        self._label_index = label_times.index
        # Indicator matrix: int8 to keep a long, wide panel cheap; a label is active over
        # every bar in [t0, t1] inclusive.
        matrix = np.zeros((len(bar_times), len(label_times)), dtype="int8")
        for column, (start, end) in enumerate(zip(start_pos, end_pos, strict=True)):
            matrix[start : end + 1, column] = 1
        self._matrix = matrix

    @property
    def indicator_matrix(self) -> npt.NDArray[np.int8]:
        """The (bars x labels) binary activity matrix (input to the sequential bootstrap)."""
        return self._matrix

    def concurrency(self) -> pd.Series:
        """Number of labels active at each bar, ``c_t`` (indexed by ``bar_times``)."""
        return pd.Series(self._matrix.sum(axis=1), index=self._bar_times, name=CONCURRENCY)

    def average_uniqueness(self) -> pd.Series:
        """Average uniqueness per label (the primary sample weight), indexed by ``t0``.

        For label ``i``: the mean over its active bars of ``1/c_t``. A fully isolated label
        is ``1.0``; two identical-span labels are ``0.5`` each.
        """
        if self._matrix.shape[1] == 0:
            return pd.Series(dtype="float64", index=self._label_index, name=UNIQUENESS)
        inverse = self._inverse_concurrency()
        active_bars = self._matrix.sum(axis=0)  # length of each label window (>= 1)
        uniqueness = (self._matrix.T @ inverse) / active_bars
        return pd.Series(uniqueness, index=self._label_index, name=UNIQUENESS)

    def return_attribution(self, prices: pd.Series, *, normalize: bool = True) -> pd.Series:
        """Return-attribution weight per label: ``|Σ_t r_t / c_t|`` over its active bars.

        Args:
            prices: Close prices indexed by ``bar_times`` (the same timeline). Per-bar log
                returns are taken internally.
            normalize: If ``True`` (default), scale the weights to average 1 (sum to the
                number of labels), the AFML convention; otherwise return the raw magnitudes.

        Raises:
            LabelingInputError: If ``prices`` does not cover the bar timeline.
        """
        if self._matrix.shape[1] == 0:
            return pd.Series(dtype="float64", index=self._label_index, name=WEIGHT)
        returns = self._log_returns(prices)
        attributed = returns * self._inverse_concurrency()  # r_t / c_t per bar
        weights = np.abs(self._matrix.T @ attributed)
        total = weights.sum()
        if normalize and total > 0:
            weights = weights * (len(weights) / total)
        return pd.Series(weights, index=self._label_index, name=WEIGHT)

    def _inverse_concurrency(self) -> npt.NDArray[np.float64]:
        """``1/c_t`` per bar (0 where no label is active — never inside a label's window)."""
        concurrency = self._matrix.sum(axis=1).astype("float64")
        inverse: npt.NDArray[np.float64] = np.divide(
            1.0, concurrency, out=np.zeros_like(concurrency), where=concurrency > 0
        )
        return inverse

    def _log_returns(self, prices: pd.Series) -> npt.NDArray[np.float64]:
        """Per-bar log returns aligned to ``bar_times`` (leading return -> 0)."""
        aligned = prices.reindex(self._bar_times)
        if bool(aligned.isna().any()):
            raise LabelingInputError("prices must cover every bar in the timeline")
        log_prices = np.log(aligned.to_numpy(dtype="float64"))
        return np.diff(log_prices, prepend=log_prices[:1])  # first bar's return is 0


def time_decay_weights(average_uniqueness: pd.Series, last_weight: float = 1.0) -> pd.Series:
    """Piecewise-linear time-decay factors over cumulative uniqueness (AFML §4.5).

    The newest label keeps weight 1; weights decay linearly in *cumulative uniqueness*
    (not raw time, so redundant stretches decay slower) down to ``last_weight`` for the
    oldest. ``last_weight`` in ``[0, 1]`` sets the oldest label's weight (1 = no decay);
    a negative value drives the oldest fraction to exactly 0. Multiply these factors into
    the uniqueness / return-attribution weights to get the final sample weights.

    Args:
        average_uniqueness: Average-uniqueness weights indexed by event time ``t0``.
        last_weight: Weight of the oldest observation (``>= -1``). Defaults to 1 (no decay).

    Raises:
        LabelingInputError: If ``last_weight < -1``.
    """
    if last_weight < -1.0:
        raise LabelingInputError(f"last_weight must be >= -1, got {last_weight}")
    if len(average_uniqueness) == 0:
        return pd.Series(dtype="float64", name=DECAY)
    cumulative = average_uniqueness.sort_index().cumsum()
    total = float(cumulative.iloc[-1])
    if last_weight >= 0.0:
        slope = (1.0 - last_weight) / total
    else:
        # A negative last_weight zeroes out the oldest fraction of (cumulative) uniqueness.
        slope = 1.0 / ((last_weight + 1.0) * total)
    constant = 1.0 - slope * total
    decay = constant + slope * cumulative
    decay[decay < 0.0] = 0.0  # the zeroed-out oldest fraction
    return decay.rename(DECAY)


def _validate_timeline(bar_times: pd.DatetimeIndex) -> None:
    """Validate the bar-timeline contract (Ground Rule 7: fail loud at the boundary)."""
    if not isinstance(bar_times, pd.DatetimeIndex):
        raise LabelingInputError(f"bar_times must be a DatetimeIndex, got {type(bar_times)}")
    if bar_times.tz is None:
        raise LabelingInputError("bar_times must be timezone-aware (the system is IST)")
    if not bar_times.is_monotonic_increasing:
        raise LabelingInputError("bar_times must be sorted ascending")
    if not bar_times.is_unique:
        raise LabelingInputError("bar_times must be unique (one timestamp per bar)")


def _label_positions(
    bar_times: pd.DatetimeIndex, label_times: pd.Series
) -> tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]:
    """Map each label's ``[t0, t1]`` to bar positions, failing loud on contract violations."""
    index = label_times.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise LabelingInputError("label_times must be indexed by tz-aware event times (t0)")
    if not index.is_monotonic_increasing or not index.is_unique:
        raise LabelingInputError("label_times index (t0) must be sorted and unique")
    if not isinstance(label_times.dtype, pd.DatetimeTZDtype):
        raise LabelingInputError("label_times values (t1) must be tz-aware datetimes")
    start_pos = bar_times.get_indexer(index)
    end_pos = bar_times.get_indexer(pd.DatetimeIndex(label_times.to_numpy()))
    if (start_pos < 0).any() or (end_pos < 0).any():
        raise LabelingInputError("every label t0 and t1 must be a bar in bar_times")
    if (end_pos < start_pos).any():
        raise LabelingInputError("every label resolution t1 must be at or after its event t0")
    return start_pos, end_pos
