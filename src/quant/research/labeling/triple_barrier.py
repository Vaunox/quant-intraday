"""The triple-barrier labeling method (Deep Dive #2 §3.2 — the correct intraday label).

For each candidate event, set **three barriers** and label by whichever is touched *first*
— this path-dependence is the whole point: it directly solves the stop-loss problem (a
trade that would have been stopped out before recovering is labeled a loss, not a fantasy
win). For our intraday MIS context (§3.2):

* **Upper / profit-take** at ``+k_up·sigma`` → label **+1**.
* **Lower / stop-loss** at ``-k_dn·sigma`` → label **-1** (asymmetric: typically a tighter
  stop than target).
* **Vertical / time barrier** = end of session (MIS auto-square-off; no overnight), or a
  shorter ``max_hold`` cap → label the **sign of the return** at expiry.

**Volatility-scaled, cost-floored.** Barriers are multiples of a point-in-time trailing
volatility ``sigma_t`` (e.g. :func:`~quant.data.features.volatility.realized_volatility`, in
return units), so labels are comparable across calm and volatile periods. Each barrier is
floored at ``barrier_min_return`` so a labeled ``+1`` is a move large enough to clear the
~0.12-0.20% round-trip cost — *"size barriers so a +1 is actually a tradeable win."*

**Path & point-in-time correctness.** The reference price is the event bar's close (the
decision price); the barrier *widths* use only ``sigma`` at the event (no future data). The
outcome is then read from the **future** path (bars strictly after the event), checking
each bar's high against the upper barrier and low against the lower — an honest intrabar
touch. When a single bar breaches *both* (gaps through the channel) the order is unknown,
so the **stop wins** (the conservative, non-fantasy choice). Labels legitimately use the
future path; the leakage rule constrains *features*, not the label's own resolution.

**Output.** A :class:`LabelSet` whose ``frame`` is indexed by event time ``t0`` with the
exit time ``t1`` (``label_times`` for purged CV / CPCV), the ``label`` (the primary side),
the touched ``barrier``, the realized ``ret``, and the profit-take ``target``.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.core.calendar import IST
from quant.core.config import LabelingConfig
from quant.core.logging import get_logger
from quant.data.store import serde
from quant.research.labeling.errors import LabelingInputError

_logger = get_logger(__name__)

#: Index name and column names of the label frame (kept stable for downstream consumers).
EVENT_TIME = "event_time"
EXIT_TIME = "exit_time"
LABEL = "label"
BARRIER = "barrier"
RETURN = "ret"
TARGET = "target"
_COLUMNS = (EXIT_TIME, LABEL, BARRIER, RETURN, TARGET)

#: Barrier-touch reasons recorded per label.
UPPER = "upper"
LOWER = "lower"
VERTICAL = "vertical"


@dataclass(frozen=True, slots=True)
class LabelSet:
    """Triple-barrier labels as a frame indexed by event time, with typed accessors."""

    frame: pd.DataFrame

    @property
    def label_times(self) -> pd.Series:
        """The ``t0 -> t1`` Series (event time -> resolution time) for purged CV / CPCV."""
        return self.frame[EXIT_TIME].rename("t1")

    @property
    def sides(self) -> pd.Series:
        """The primary-side label per event (``+1`` long / ``-1`` short / ``0`` flat)."""
        return self.frame[LABEL]

    def __len__(self) -> int:
        """Number of labeled events."""
        return len(self.frame)


class TripleBarrierLabeler:
    """Labels candidate events by the first of three volatility-scaled barriers touched."""

    def __init__(self, config: LabelingConfig) -> None:
        """Build the labeler from the configured barrier multiples / floor / vertical cap."""
        self._k_up = config.barrier_upper_multiple
        self._k_dn = config.barrier_lower_multiple
        self._min_return = config.barrier_min_return
        self._max_hold = config.vertical_max_hold_bars

    def label(
        self, bars: pd.DataFrame, events: pd.DatetimeIndex, volatility: pd.Series
    ) -> LabelSet:
        """Label each event by the first barrier its forward price path touches.

        Args:
            bars: A single symbol's canonical-schema, hygiene-clean, adjusted bars.
            events: Candidate event timestamps (a subset of ``bars``' timestamps), e.g.
                from :func:`~quant.research.labeling.cusum.cusum_events`.
            volatility: Point-in-time trailing volatility in **return units** (e.g.
                ``realized_volatility``), indexed by the bar timestamps. ``sigma`` at the event
                bar scales that event's barriers; an event with no ``sigma`` (warm-up NaN) is
                skipped.

        Returns:
            A :class:`LabelSet`. Events with no holding room before the vertical barrier
            (the event is the session's last bar) or no volatility are dropped.

        Raises:
            LabelingInputError: If ``events`` are not all bar timestamps, or ``volatility``
                does not align to the bars.
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        if frame.empty or len(events) == 0:
            return LabelSet(_empty_frame())

        times = pd.DatetimeIndex(frame[serde.TIME_COLUMN])
        if not times.is_unique:
            raise LabelingInputError("bars must have unique timestamps")
        event_positions = _event_positions(events, times)
        sigma = _aligned_volatility(volatility, times)

        close = frame["close"].to_numpy(dtype="float64")
        high = frame["high"].to_numpy(dtype="float64")
        low = frame["low"].to_numpy(dtype="float64")
        session_last = _session_last_position(times)

        rows: list[dict[str, object]] = []
        index: list[pd.Timestamp] = []
        skipped = 0
        for position in event_positions:
            row = self._label_one(position, close, high, low, sigma, session_last, times)
            if row is None:
                skipped += 1
                continue
            index.append(times[position])
            rows.append(row)

        _logger.info(
            "triple-barrier labels",
            extra={"events": len(events), "labeled": len(rows), "skipped": skipped},
        )
        return LabelSet(_build_frame(rows, index))

    def _label_one(
        self,
        position: int,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        sigma: np.ndarray,
        session_last: np.ndarray,
        times: pd.DatetimeIndex,
    ) -> dict[str, object] | None:
        """Resolve one event's label, or ``None`` if it cannot be labeled (no sigma / no room)."""
        vol = sigma[position]
        if np.isnan(vol):
            return None  # no trailing volatility yet to scale the barriers
        upper_ret = max(self._k_up * float(vol), self._min_return)
        lower_ret = max(self._k_dn * float(vol), self._min_return)
        reference = float(close[position])
        upper_price = reference * (1.0 + upper_ret)
        lower_price = reference * (1.0 - lower_ret)

        vertical = int(session_last[position])
        if self._max_hold > 0:
            vertical = min(vertical, position + self._max_hold)
        if vertical <= position:
            return None  # the event is the session's last bar — no bar left to hold

        for pos in range(position + 1, vertical + 1):
            hit_up = high[pos] >= upper_price
            hit_dn = low[pos] <= lower_price
            if hit_dn:  # stop wins a same-bar tie (intrabar order unknown -> conservative)
                return _row(times[pos], -1, LOWER, -lower_ret, upper_ret)
            if hit_up:
                return _row(times[pos], 1, UPPER, upper_ret, upper_ret)

        # No barrier touched: the vertical (session-end) barrier resolves it by sign.
        exit_return = float(close[vertical]) / reference - 1.0
        label = int(np.sign(exit_return))
        return _row(times[vertical], label, VERTICAL, exit_return, upper_ret)


def _row(
    exit_time: pd.Timestamp, label: int, barrier: str, ret: float, target: float
) -> dict[str, object]:
    """Assemble one label row."""
    return {EXIT_TIME: exit_time, LABEL: label, BARRIER: barrier, RETURN: ret, TARGET: target}


def _event_positions(events: pd.DatetimeIndex, times: pd.DatetimeIndex) -> list[int]:
    """Map event timestamps to bar positions (sorted), failing loud on an unknown event."""
    if not isinstance(events, pd.DatetimeIndex):
        raise LabelingInputError(f"events must be a DatetimeIndex, got {type(events)}")
    locations = times.get_indexer(events)
    if (locations < 0).any():
        raise LabelingInputError("every event must correspond to a bar timestamp")
    # De-dup and order by time: a candidate bar yields one label regardless of input order.
    return sorted({int(loc) for loc in locations})


def _aligned_volatility(volatility: pd.Series, times: pd.DatetimeIndex) -> np.ndarray:
    """Reindex the volatility Series onto the bar timeline (NaN where absent)."""
    if not isinstance(volatility.index, pd.DatetimeIndex):
        raise LabelingInputError("volatility must be indexed by bar timestamp (DatetimeIndex)")
    return volatility.reindex(times).to_numpy(dtype="float64")


def _session_last_position(times: pd.DatetimeIndex) -> np.ndarray:
    """For each bar, the position of the last bar in its IST session (the vertical barrier)."""
    session = np.asarray(times.tz_convert(IST).date, dtype="object")
    n = session.shape[0]
    last = np.empty(n, dtype=np.intp)
    boundary = n - 1
    for i in range(n - 1, -1, -1):
        if i == n - 1 or session[i] != session[i + 1]:
            boundary = i
        last[i] = boundary
    return last


def _empty_frame() -> pd.DataFrame:
    """The well-typed empty label frame (a tz-aware event index, the standard columns)."""
    index = pd.DatetimeIndex([], name=EVENT_TIME)
    return pd.DataFrame(
        {
            EXIT_TIME: pd.Series(dtype="datetime64[ns, Asia/Kolkata]"),
            LABEL: pd.Series(dtype="int64"),
            BARRIER: pd.Series(dtype="object"),
            RETURN: pd.Series(dtype="float64"),
            TARGET: pd.Series(dtype="float64"),
        },
        index=index,
    )


def _build_frame(rows: list[dict[str, object]], index: list[pd.Timestamp]) -> pd.DataFrame:
    """Assemble the label frame from accumulated rows (empty-safe)."""
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name=EVENT_TIME))
    return frame.loc[:, list(_COLUMNS)]
