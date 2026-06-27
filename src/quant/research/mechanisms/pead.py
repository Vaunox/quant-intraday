"""Post-earnings-announcement-drift mechanism (Part VI / P7.3).

The third and last mechanism in the pre-committed slate (pursued because P7.1 and P7.2 did not
clear). PEAD is one of the most-documented anomalies: prices **underreact** to an earnings surprise
and drift in the surprise direction for weeks. A book that goes **long** large positive surprises
and **short** large negative ones, held over the drift window, harvests that slow diffusion
(pre-registration: ``docs/mechanisms/pead_prereg.md``).

It plugs into the **existing** seven-point kill-gate via the Part-VI harness (P6.1):
:class:`PeadSpec` is a :class:`~quant.research.mechanisms.spec.StrategySpec` over the P9.2
:class:`~quant.data.recorders.events.EventReactionRecord` dataset — per event the net return is
``sign(surprise) * drift_return`` minus the CNC round-trip cost.

**The binding dependency is the event data** (the same shape of constraint as P7.1): the
:class:`~quant.data.recorders.events.EventReactionRecorder` (P9.2) is built and tested, but its
store is empty without an **external earnings-surprise feed**, which is not in the repo. The
machinery here is complete and tested; it judges PEAD the moment the feed populates the store.
"""

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.data.recorders.events import EventReactionRecord
from quant.research.mechanisms.errors import MechanismDataError, SpecError

_logger = get_logger(__name__)

#: A rough trading-days-per-year for annualising a per-event drift book (events are sparse).
DEFAULT_PERIODS_PER_YEAR = 12.0


class PeadSpec:
    """A surprise-sorted PEAD :class:`~quant.research.mechanisms.spec.StrategySpec`.

    Per event: take ``sign(surprise)`` (long positive, short negative), keep only events with
    ``|surprise| >= min_abs_surprise``, and realise ``sign(surprise) * drift_return`` over the PEAD
    window, **net** of the CNC round-trip cost. Rule-based — ``fit`` is a no-op. Events are ordered
    by announcement time so the label timeline is monotonic for the CPCV purge.
    """

    def __init__(
        self,
        records: Sequence[EventReactionRecord],
        *,
        round_trip_cost: float,
        min_abs_surprise: float = 0.0,
        drift_window_days: int = 20,
        name: str = "pead",
    ) -> None:
        """Bind the spec to the recorded earnings events and the (searched) configuration.

        Args:
            records: the P9.2 ``EventReactionRecord`` dataset.
            round_trip_cost: CNC round-trip cost fraction charged per event (Rule 4).
            min_abs_surprise: trade only events whose absolute surprise clears this.
            drift_window_days: holding horizon in calendar days (the ``t0 -> t1`` span).
            name: mechanism name (logged + used in the trial count).

        Raises:
            SpecError: On a non-positive cost or window.
            MechanismDataError: If no recorded event clears the surprise filter (data gate).
        """
        if round_trip_cost < 0.0:
            raise SpecError(f"round_trip_cost must be non-negative, got {round_trip_cost}")
        if drift_window_days <= 0:
            raise SpecError(f"drift_window_days must be positive, got {drift_window_days}")
        self._name = name
        kept = sorted(
            (r for r in records if abs(r.surprise) >= min_abs_surprise),
            key=lambda r: r.event_time,
        )
        if not kept:
            raise MechanismDataError(
                f"{name}: no recorded earnings event clears the surprise filter "
                f"(|surprise| >= {min_abs_surprise}) — the study cannot be judged on these inputs"
            )
        starts = pd.DatetimeIndex([pd.Timestamp(r.event_time) for r in kept], name="event")
        window = pd.Timedelta(days=drift_window_days)
        self._label_times = pd.Series(
            [ts + window for ts in starts], index=starts, name="drift_end"
        )
        self._net_returns = pd.Series(
            [float(np.sign(r.surprise)) * r.drift_return - round_trip_cost for r in kept],
            index=starts,
            name="net",
        )

    @property
    def name(self) -> str:
        """The mechanism name."""
        return self._name

    @property
    def label_times(self) -> pd.Series:
        """Announcement -> drift-end spans (the CPCV purge/embargo timeline)."""
        return self._label_times

    @property
    def n_events(self) -> int:
        """Number of traded earnings events."""
        return int(self._net_returns.shape[0])

    def fit(self, train_positions: npt.NDArray[np.intp]) -> None:
        """No-op: the surprise-sorted rule is fixed; nothing is calibrated in-sample."""
        return None

    def event_returns(self, positions: npt.NDArray[np.intp]) -> pd.Series:
        """Net per-event drift returns at ``positions``."""
        return self._net_returns.iloc[positions]


__all__ = ["DEFAULT_PERIODS_PER_YEAR", "PeadSpec"]
