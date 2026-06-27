"""Tests for the index-rebalance flow mechanism (Part VI / P7.1) on synthetic events + panel.

Proves the machinery end-to-end (a planted addition-flow edge is recovered through the existing
CPCV harness) and that the data gates fire (missing change-log, untradeable events).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.mechanisms.errors import MechanismDataError, SpecError
from quant.research.mechanisms.index_rebalance import (
    IndexRebalanceSpec,
    ReconstitutionEvent,
    evaluate_index_rebalance,
    load_reconstitution_events,
)
from quant.research.validation.cpcv import CombinatorialPurgedCV

_DATES = pd.date_range("2016-01-01", periods=900, freq="D", tz=IST)


def _panel_with_addition_drift(n_events: int) -> tuple[pd.DataFrame, list[ReconstitutionEvent]]:
    """A panel where each addition drifts up over its window — a recoverable positive flow edge."""
    rng = np.random.default_rng(11)
    symbols = [f"ADD{i}" for i in range(n_events)] + [f"DEL{i}" for i in range(n_events)]
    # Base random-walk closes for every name.
    closes = pd.DataFrame(
        100.0 * np.exp(np.cumsum(0.001 * rng.standard_normal((len(_DATES), len(symbols))), axis=0)),
        index=_DATES,
        columns=symbols,
    )
    events: list[ReconstitutionEvent] = []
    for i in range(n_events):
        ann = 30 + i * 25  # spaced announcements
        eff = ann + 10  # 10-day effective window
        # Plant the flow: addition rises, deletion falls, across the window.
        add_col = symbols.index(f"ADD{i}")
        del_col = symbols.index(f"DEL{i}")
        closes.iloc[eff:, add_col] = closes.iloc[eff:, add_col] * 1.04
        closes.iloc[eff:, del_col] = closes.iloc[eff:, del_col] * 0.97
        events.append(
            ReconstitutionEvent(
                review_id=f"R{i}",
                announcement_date=_DATES[ann],
                effective_date=_DATES[eff],
                additions=(f"ADD{i}",),
                deletions=(f"DEL{i}",),
            )
        )
    return closes, events


def test_reconstitution_event_validates_dates() -> None:
    with pytest.raises(SpecError, match="precedes announcement"):
        ReconstitutionEvent(
            review_id="bad",
            announcement_date=_DATES[50],
            effective_date=_DATES[40],
            additions=("X",),
            deletions=(),
        )


def test_reconstitution_event_requires_a_name() -> None:
    with pytest.raises(SpecError, match="add or delete at least one name"):
        ReconstitutionEvent(
            review_id="empty",
            announcement_date=_DATES[10],
            effective_date=_DATES[20],
            additions=(),
            deletions=(),
        )


def test_spec_builds_net_event_returns_and_label_times() -> None:
    panel, events = _panel_with_addition_drift(6)
    spec = IndexRebalanceSpec(events, panel, round_trip_cost=0.0022)
    assert spec.label_times.shape[0] == 6
    # Announcement < effective for every event (the purge timeline).
    assert (spec.label_times.to_numpy() > spec.label_times.index.to_numpy()).all()
    # The planted long-addition / short-deletion flow is net positive after the 0.22% cost.
    assert spec.event_returns(np.arange(6, dtype=np.intp)).mean() > 0.0


def test_evaluate_index_rebalance_recovers_positive_edge() -> None:
    panel, events = _panel_with_addition_drift(8)
    spec = IndexRebalanceSpec(events, panel, round_trip_cost=0.0022)
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_index_rebalance(spec, cpcv)
    assert ev.distribution.num_paths == 3
    assert ev.annualised_median_sharpe > 0.0  # the planted flow edge is recovered
    assert ev.periods_per_year > 0.0


def test_missing_change_log_raises_data_gate(tmp_path: Path) -> None:
    with pytest.raises(MechanismDataError, match="reconstitution change-log not found"):
        load_reconstitution_events(str(tmp_path / "nope.csv"))


def test_change_log_round_trip(tmp_path: Path) -> None:
    csv = tmp_path / "changes.csv"
    csv.write_text(
        "review_id,announcement_date,effective_date,symbol,action\n"
        "2020H1,2020-02-28,2020-03-31,AAA,add\n"
        "2020H1,2020-02-28,2020-03-31,BBB,delete\n"
        "2020H2,2020-08-31,2020-09-30,CCC,add\n",
        encoding="utf-8",
    )
    events = load_reconstitution_events(str(csv))
    assert [e.review_id for e in events] == ["2020H1", "2020H2"]
    assert events[0].additions == ("AAA",) and events[0].deletions == ("BBB",)
    assert events[1].additions == ("CCC",)


def test_untradeable_events_raise_data_gate() -> None:
    # Events whose symbols are absent from the panel -> no tradeable basket -> data gate.
    panel = pd.DataFrame(100.0, index=_DATES, columns=["OTHER"])
    events = [
        ReconstitutionEvent(
            review_id="R0",
            announcement_date=_DATES[100],
            effective_date=_DATES[110],
            additions=("MISSING",),
            deletions=(),
        )
    ]
    with pytest.raises(MechanismDataError, match="no reconstitution event resolved"):
        IndexRebalanceSpec(events, panel, round_trip_cost=0.0022)
