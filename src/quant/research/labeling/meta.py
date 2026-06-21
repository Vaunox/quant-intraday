"""Meta-labeling: the side/size split (Deep Dive #2 §3.4).

*"This is López de Prado's key contribution and it maps perfectly onto the cost-hurdle
problem."* Split the decision into two models:

* **Primary → SIDE.** Decides long / short / flat; tuned for high recall (catch the
  opportunities, tolerate false positives). It can be a *simple rule* — here, a momentum or
  mean-reversion sign over a trailing window.
* **Secondary (meta) → BET or NO-BET.** A binary classifier that takes the primary's signal
  *plus* features and decides whether to actually take the trade, correcting the primary's
  low precision. It is the natural home for the cost hurdle.

This module generates the **meta label** the secondary model trains on: given the primary's
side at an event, run a **side-aware** triple barrier (the profit-take in the side's
direction, the stop against it) and label **1 = the bet won** (hit the profit-take, or ended
profitable at the vertical barrier) or **0 = no-bet** (hit the stop, or ended unprofitable).
A short profits when price falls, so its barriers mirror a long's. The realized ``ret`` is
the **side-adjusted** return, so a profitable short is positive.

The barrier scan, the conservative same-bar tie, and the session-end vertical barrier are
the shared primitives from :mod:`~quant.research.labeling.barriers` (one implementation for
the primary and meta labelers). A flat (``0``) primary side has no bet to evaluate and is
skipped.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.core.config import LabelingConfig
from quant.core.logging import get_logger
from quant.data.store import serde
from quant.research.labeling import barriers
from quant.research.labeling.errors import LabelingInputError

_logger = get_logger(__name__)

#: Index name and columns of the meta-label frame.
EVENT_TIME = "event_time"
SIDE = "side"
META_LABEL = "meta_label"
BARRIER = "barrier"
RETURN = "ret"
EXIT_TIME = "exit_time"
_COLUMNS = (SIDE, META_LABEL, BARRIER, RETURN, EXIT_TIME)

#: Meta barrier-touch reasons.
PROFIT = "profit"
STOP = "stop"
VERTICAL = "vertical"


def momentum_side(bars: pd.DataFrame, lookback: int) -> pd.Series:
    """A simple momentum primary: ``side = sign(close_t - close_{t-lookback})``.

    Causal (uses only the current and a past close), indexed by bar timestamp, valued in
    ``{-1, 0, +1}`` (0 during the warm-up and on no move). The natural "simple primary
    rule" of §3.4 — the ML then lives in the meta-model deciding when to trust it.

    Raises:
        LabelingInputError: If ``lookback`` is not positive.
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    if lookback <= 0:
        raise LabelingInputError(f"lookback must be positive, got {lookback}")
    frame = serde.sort_bars(serde.ensure_bars_schema(bars))
    times = pd.DatetimeIndex(frame[serde.TIME_COLUMN])
    close = frame["close"].to_numpy(dtype="float64")
    side = np.zeros(close.shape[0], dtype="int64")
    if close.shape[0] > lookback:
        side[lookback:] = np.sign(close[lookback:] - close[:-lookback]).astype("int64")
    return pd.Series(side, index=times, name=SIDE)


def mean_reversion_side(bars: pd.DataFrame, lookback: int) -> pd.Series:
    """A simple mean-reversion primary: the negation of :func:`momentum_side` (bet on reversal)."""
    momentum = momentum_side(bars, lookback)
    return (-momentum).rename(SIDE)


@dataclass(frozen=True, slots=True)
class MetaLabelSet:
    """Meta bet/no-bet labels as a frame indexed by event time, with typed accessors."""

    frame: pd.DataFrame

    @property
    def label_times(self) -> pd.Series:
        """The ``t0 -> t1`` Series (event time -> resolution) for purged CV / CPCV."""
        return self.frame[EXIT_TIME].rename("t1")

    @property
    def meta_labels(self) -> pd.Series:
        """The binary bet (``1``) / no-bet (``0``) label per event."""
        return self.frame[META_LABEL]

    @property
    def sides(self) -> pd.Series:
        """The primary side per event (``+1`` long / ``-1`` short)."""
        return self.frame[SIDE]

    def __len__(self) -> int:
        """Number of meta-labeled events."""
        return len(self.frame)


class MetaLabeler:
    """Generates side-aware bet/no-bet labels from a primary side and the forward path."""

    def __init__(self, config: LabelingConfig) -> None:
        """Build the labeler from the configured barrier multiples / floor / vertical cap."""
        self._k_up = config.barrier_upper_multiple
        self._k_dn = config.barrier_lower_multiple
        self._min_return = config.barrier_min_return
        self._max_hold = config.vertical_max_hold_bars

    def label(
        self,
        bars: pd.DataFrame,
        events: pd.DatetimeIndex,
        sides: pd.Series,
        volatility: pd.Series,
    ) -> MetaLabelSet:
        """Generate meta bet/no-bet labels for ``events`` given the primary ``sides``.

        Args:
            bars: A single symbol's canonical-schema, hygiene-clean, adjusted bars.
            events: Candidate event timestamps (a subset of ``bars``' timestamps).
            sides: Primary side per bar (``+1``/``-1``/``0``), indexed by bar timestamp
                (e.g. :func:`momentum_side`). A flat (``0``) side at an event is skipped.
            volatility: Point-in-time trailing volatility in return units, indexed by bar
                timestamp (scales the barriers).

        Returns:
            A :class:`MetaLabelSet`. Events with a flat side, no volatility, or no holding
            room before the vertical barrier are dropped.

        Raises:
            LabelingInputError: If ``events`` are not all bar timestamps, or ``sides`` /
                ``volatility`` do not align to the bars.
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        if frame.empty or len(events) == 0:
            return MetaLabelSet(_empty_frame())

        times = pd.DatetimeIndex(frame[serde.TIME_COLUMN])
        if not times.is_unique:
            raise LabelingInputError("bars must have unique timestamps")
        positions = barriers.event_positions(events, times)
        sigma = barriers.aligned_volatility(volatility, times)
        side_at = _aligned_sides(sides, times)

        close = frame["close"].to_numpy(dtype="float64")
        high = frame["high"].to_numpy(dtype="float64")
        low = frame["low"].to_numpy(dtype="float64")
        session_last = barriers.session_last_position(times)

        rows: list[dict[str, object]] = []
        index: list[pd.Timestamp] = []
        skipped = 0
        for position in positions:
            row = self._label_one(
                position, int(side_at[position]), close, high, low, sigma, session_last, times
            )
            if row is None:
                skipped += 1
                continue
            index.append(times[position])
            rows.append(row)

        _logger.info(
            "meta labels",
            extra={"events": len(events), "labeled": len(rows), "skipped": skipped},
        )
        return MetaLabelSet(_build_frame(rows, index))

    def _label_one(
        self,
        position: int,
        side: int,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        sigma: np.ndarray,
        session_last: np.ndarray,
        times: pd.DatetimeIndex,
    ) -> dict[str, object] | None:
        """Resolve one event's meta label, or ``None`` if it cannot be evaluated."""
        if side == 0:
            return None  # the primary is flat here — there is no bet to evaluate
        vol = sigma[position]
        if np.isnan(vol):
            return None
        profit_ret = max(self._k_up * float(vol), self._min_return)  # profit-take width
        stop_ret = max(self._k_dn * float(vol), self._min_return)  # stop width
        reference = float(close[position])
        vertical = barriers.vertical_position(position, int(session_last[position]), self._max_hold)
        if vertical <= position:
            return None

        # Side-aware barriers: a long takes profit above / stops below; a short mirrors it.
        # The stop is always the side's adverse barrier and wins a same-bar tie.
        if side > 0:
            high_barrier = reference * (1.0 + profit_ret)
            low_barrier = reference * (1.0 - stop_ret)
            tie_to_low = True  # the stop is the lower barrier
        else:
            high_barrier = reference * (1.0 + stop_ret)
            low_barrier = reference * (1.0 - profit_ret)
            tie_to_low = False  # the stop is the upper barrier

        touched, exit_pos = barriers.first_touch(
            high,
            low,
            position,
            vertical,
            high_barrier=high_barrier,
            low_barrier=low_barrier,
            tie_to_low=tie_to_low,
        )
        if touched == barriers.TOUCH_VERTICAL:
            side_return = side * (float(close[vertical]) / reference - 1.0)
            return _row(times[vertical], side, int(side_return > 0), VERTICAL, side_return)
        # The profit barrier is the side's favourable one (high for a long, low for a short).
        is_profit = (touched == barriers.TOUCH_HIGH) == (side > 0)
        if is_profit:
            return _row(times[exit_pos], side, 1, PROFIT, profit_ret)
        return _row(times[exit_pos], side, 0, STOP, -stop_ret)


def _row(
    exit_time: pd.Timestamp, side: int, meta_label: int, barrier: str, ret: float
) -> dict[str, object]:
    """Assemble one meta-label row."""
    return {SIDE: side, META_LABEL: meta_label, BARRIER: barrier, RETURN: ret, EXIT_TIME: exit_time}


def _aligned_sides(sides: pd.Series, times: pd.DatetimeIndex) -> np.ndarray:
    """Reindex the primary-side Series onto the bar timeline (0 where absent)."""
    if not isinstance(sides.index, pd.DatetimeIndex):
        raise LabelingInputError("sides must be indexed by bar timestamp (DatetimeIndex)")
    return sides.reindex(times).fillna(0).to_numpy(dtype="int64")


def _empty_frame() -> pd.DataFrame:
    """The well-typed empty meta-label frame."""
    index = pd.DatetimeIndex([], name=EVENT_TIME)
    return pd.DataFrame(
        {
            SIDE: pd.Series(dtype="int64"),
            META_LABEL: pd.Series(dtype="int64"),
            BARRIER: pd.Series(dtype="object"),
            RETURN: pd.Series(dtype="float64"),
            EXIT_TIME: pd.Series(dtype="datetime64[ns, Asia/Kolkata]"),
        },
        index=index,
    )


def _build_frame(rows: list[dict[str, object]], index: list[pd.Timestamp]) -> pd.DataFrame:
    """Assemble the meta-label frame from accumulated rows (empty-safe)."""
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name=EVENT_TIME))
    return frame.loc[:, list(_COLUMNS)]
