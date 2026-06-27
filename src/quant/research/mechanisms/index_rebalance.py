"""Index-rebalance flow mechanism (Part VI / P7.1).

The first mechanism study: capture the mechanical, pre-announced passive-fund flow around NSE
index semi-annual reviews. Names **added** to a tracked index are bid up, and names **deleted**
are sold off, by index-tracking funds that must trade the reconstitution price-insensitively on a
known **effective date**. A market-neutral long-additions / short-deletions basket, entered on the
**announcement** and exited around the **effective date**, expresses that flow (pre-registration:
``docs/mechanisms/index_rebalance_prereg.md``).

This is a flow mechanic, not a directional bar-data prediction — so it plugs into the **existing**
seven-point kill-gate via the Part-VI harness (P6.1): :class:`IndexRebalanceSpec` is a
:class:`~quant.research.mechanisms.spec.StrategySpec` whose per-event return is the net basket
return over the announcement→effective window, and :func:`evaluate_index_rebalance` runs it through
the unchanged CPCV engine.

**The binding dependency is the event data.** The study needs a dated *reconstitution change-log*:
per review, the added / deleted symbols with the **announcement** and **effective** dates (the
:class:`ReconstitutionEvent` schema; :func:`load_reconstitution_events` reads it from CSV). The
survivorship-free **price** panel (``data/nifty_panel/``) is present, but the change-log is **not**
in the repo — a real data-access constraint (analogous to Cycle 3b's historical-depth gate,
``FINDINGS.md`` §6), surfaced in ``docs/mechanisms/budget.md`` and the verdict. The machinery here
is complete and tested; it judges the mechanism the moment the change-log is supplied.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.mechanisms.errors import MechanismDataError, SpecError
from quant.research.mechanisms.spec import MechanismEvaluation, evaluate_spec_under_cpcv
from quant.research.validation.cpcv import CombinatorialPurgedCV

_logger = get_logger(__name__)

#: Days per calendar year, for the events-per-year annualisation factor.
_DAYS_PER_YEAR = 365.25
#: CSV columns the reconstitution change-log must provide.
_CHANGE_LOG_COLUMNS = ("review_id", "announcement_date", "effective_date", "symbol", "action")


@dataclass(frozen=True, slots=True)
class ReconstitutionEvent:
    """One index review's membership change: additions + deletions, with the two key dates.

    ``announcement_date`` is when the review is published (the entry signal); ``effective_date`` is
    when index funds must hold the new membership (the forced-flow exit). ``additions`` are bought
    (long), ``deletions`` are sold (short) — the market-neutral basket.
    """

    review_id: str
    announcement_date: pd.Timestamp
    effective_date: pd.Timestamp
    additions: tuple[str, ...]
    deletions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the dates and that the review touches at least one name."""
        if self.effective_date < self.announcement_date:
            raise SpecError(
                f"{self.review_id}: effective_date {self.effective_date.date()} precedes "
                f"announcement_date {self.announcement_date.date()}"
            )
        if not self.additions and not self.deletions:
            raise SpecError(f"{self.review_id}: a review must add or delete at least one name")


def load_reconstitution_events(path: str) -> list[ReconstitutionEvent]:
    """Load a reconstitution change-log CSV into sorted :class:`ReconstitutionEvent` records.

    The CSV has one row per (review, symbol): columns ``review_id``, ``announcement_date``,
    ``effective_date``, ``symbol``, ``action`` (``add`` | ``delete``). Rows are grouped by
    ``review_id`` into events, sorted by announcement date.

    Raises:
        MechanismDataError: If the file is missing, empty, or malformed (the data gate).
    """
    try:
        frame = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise MechanismDataError(
            f"reconstitution change-log not found: {path} — supply a dated NSE reconstitution "
            "change-log (review_id, announcement_date, effective_date, symbol, action) to run "
            "P7.1 on real events (Part VI; see docs/mechanisms/budget.md)"
        ) from exc
    missing = [c for c in _CHANGE_LOG_COLUMNS if c not in frame.columns]
    if missing:
        raise MechanismDataError(f"change-log {path} missing column(s): {', '.join(missing)}")
    if frame.empty:
        raise MechanismDataError(f"change-log {path} is empty")
    return _events_from_frame(frame)


class IndexRebalanceSpec:
    """A :class:`~quant.research.mechanisms.spec.StrategySpec` for the index-rebalance flow.

    Per event: equal-weight **long** every addition and **short** every deletion, enter at the
    first panel close at/after the announcement and exit at the first close at/after the effective
    date; the per-event return is the basket return over that window, **net** of the CNC round-trip
    cost. Market-neutral by construction. Rule-based — ``fit`` is a no-op.
    """

    def __init__(
        self,
        events: Sequence[ReconstitutionEvent],
        close_panel: pd.DataFrame,
        *,
        round_trip_cost: float,
        name: str = "index_rebalance",
    ) -> None:
        """Bind the events to the survivorship-free close panel and the CNC round-trip cost.

        Args:
            events: the reconstitution events (need ≥ the CPCV group count to be judged).
            close_panel: wide daily close matrix (``DatetimeIndex`` rows, symbol columns).
            round_trip_cost: the CNC round-trip cost fraction charged once per event (Rule 4).
            name: the mechanism name (logged + used in the trial count).

        Raises:
            MechanismDataError: If no event resolves to a tradeable basket on the panel (data gate).
        """
        if round_trip_cost < 0.0:
            raise SpecError(f"round_trip_cost must be non-negative, got {round_trip_cost}")
        self._name = name
        self._round_trip = round_trip_cost
        self._panel = close_panel.sort_index()
        self._dates = self._panel.index
        # Column -> integer position, so cell access is fully-typed numpy indexing.
        self._col_pos = {str(col): i for i, col in enumerate(self._panel.columns)}
        self._values = self._panel.to_numpy(dtype="float64")
        ordered = sorted(events, key=lambda e: (e.announcement_date, e.review_id))
        returns: dict[pd.Timestamp, float] = {}
        exits: dict[pd.Timestamp, pd.Timestamp] = {}
        for event in ordered:
            resolved = self._event_net_return(event)
            if resolved is None:
                continue
            net, exit_ts = resolved
            returns[event.announcement_date] = net
            exits[event.announcement_date] = exit_ts
        if not returns:
            raise MechanismDataError(
                f"{name}: no reconstitution event resolved to a tradeable basket on the panel "
                "(no overlapping price history) — the study cannot be judged on these inputs"
            )
        index = pd.DatetimeIndex(list(returns.keys()), name="announcement")
        self._net_returns = pd.Series(list(returns.values()), index=index, name="net")
        self._label_times = pd.Series([exits[ts] for ts in index], index=index, name="effective")

    @property
    def name(self) -> str:
        """The mechanism name."""
        return self._name

    @property
    def label_times(self) -> pd.Series:
        """Announcement → effective spans (the CPCV purge/embargo timeline)."""
        return self._label_times

    def fit(self, train_positions: npt.NDArray[np.intp]) -> None:
        """No-op: the rule is fixed; nothing is calibrated in-sample."""
        return None

    def event_returns(self, positions: npt.NDArray[np.intp]) -> pd.Series:
        """Net per-event basket returns at ``positions``."""
        return self._net_returns.iloc[positions]

    def _event_net_return(self, event: ReconstitutionEvent) -> tuple[float, pd.Timestamp] | None:
        """Return ``(net basket return, exit ts)`` for an event, or ``None`` if untradeable."""
        entry_pos = self._row_on_or_after(event.announcement_date)
        exit_pos = self._row_on_or_after(event.effective_date)
        if entry_pos is None or exit_pos is None or exit_pos <= entry_pos:
            return None
        legs: list[float] = []
        legs += self._leg_returns(event.additions, entry_pos, exit_pos, sign=1.0)
        legs += self._leg_returns(event.deletions, entry_pos, exit_pos, sign=-1.0)
        if not legs:
            return None
        gross = float(np.mean(legs))
        return gross - self._round_trip, pd.Timestamp(self._dates[exit_pos])

    def _leg_returns(
        self, symbols: Iterable[str], entry_pos: int, exit_pos: int, *, sign: float
    ) -> list[float]:
        """Signed entry→exit returns for symbols present in the panel (missing names skipped)."""
        out: list[float] = []
        for symbol in symbols:
            col = self._col_pos.get(symbol)
            if col is None:
                continue
            entry = self._values[entry_pos, col]
            exit_ = self._values[exit_pos, col]
            if np.isnan(entry) or np.isnan(exit_) or entry <= 0.0:
                continue
            out.append(float(sign * (exit_ / entry - 1.0)))
        return out

    def _row_on_or_after(self, day: pd.Timestamp) -> int | None:
        """The integer row position of the first panel date at/after ``day``, or ``None``."""
        pos = int(self._dates.searchsorted(day, side="left"))
        return pos if pos < len(self._dates) else None


def evaluate_index_rebalance(
    spec: IndexRebalanceSpec,
    cpcv: CombinatorialPurgedCV,
    *,
    periods_per_year: float | None = None,
) -> MechanismEvaluation:
    """Run the index-rebalance spec through the **existing** CPCV engine (P6.1 harness).

    Args:
        spec: the bound :class:`IndexRebalanceSpec`.
        cpcv: the configured combinatorial purged CV.
        periods_per_year: annualisation factor; defaults to the events-per-year implied by the
            event span (semi-annual reviews → ≈ 2).
    """
    ppy = periods_per_year if periods_per_year is not None else _events_per_year(spec.label_times)
    evaluation = evaluate_spec_under_cpcv(spec, cpcv, periods_per_year=ppy)
    _logger.info(
        "index-rebalance evaluated",
        extra={
            "n_events": int(spec.label_times.shape[0]),
            "periods_per_year": ppy,
            "annualised_median_sharpe": evaluation.annualised_median_sharpe,
        },
    )
    return evaluation


def _events_per_year(label_times: pd.Series) -> float:
    """Events per calendar year over the event span (the path-Sharpe annualisation factor)."""
    if label_times.shape[0] < 2:
        return 2.0  # semi-annual prior when the span is undefined
    span_days = float((label_times.index.max() - label_times.index.min()).days)
    years = max(span_days / _DAYS_PER_YEAR, 1e-9)
    return float(label_times.shape[0]) / years


def _events_from_frame(frame: pd.DataFrame) -> list[ReconstitutionEvent]:
    """Group change-log rows by review into sorted :class:`ReconstitutionEvent` records."""
    events: list[ReconstitutionEvent] = []
    for review_id, rows in frame.groupby("review_id", sort=False):
        announcement = pd.Timestamp(rows["announcement_date"].iloc[0])
        effective = pd.Timestamp(rows["effective_date"].iloc[0])
        actions: Mapping[str, list[str]] = {"add": [], "delete": []}
        for _, row in rows.iterrows():
            action = str(row["action"]).strip().lower()
            if action not in actions:
                raise MechanismDataError(
                    f"review {review_id}: action must be 'add' or 'delete', got {row['action']!r}"
                )
            actions[action].append(str(row["symbol"]).strip())
        events.append(
            ReconstitutionEvent(
                review_id=str(review_id),
                announcement_date=announcement,
                effective_date=effective,
                additions=tuple(actions["add"]),
                deletions=tuple(actions["delete"]),
            )
        )
    events.sort(key=lambda e: (e.announcement_date, e.review_id))
    return events


__all__ = [
    "IndexRebalanceSpec",
    "ReconstitutionEvent",
    "evaluate_index_rebalance",
    "load_reconstitution_events",
]
