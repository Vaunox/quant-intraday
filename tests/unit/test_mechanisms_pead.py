"""Tests for the PEAD mechanism (Part VI / P7.3) on synthetic event-reaction records."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from quant.core.calendar import IST
from quant.data.recorders.events import EventReactionRecord
from quant.research.mechanisms.errors import MechanismDataError, SpecError
from quant.research.mechanisms.pead import DEFAULT_PERIODS_PER_YEAR, PeadSpec
from quant.research.mechanisms.spec import evaluate_spec_under_cpcv
from quant.research.validation.cpcv import CombinatorialPurgedCV

_T0 = datetime(2026, 1, 1, tzinfo=IST)


def _records(n: int, *, drift_sign: float) -> list[EventReactionRecord]:
    """n events alternating surprise sign, drift in ``drift_sign``*surprise direction."""
    rng = np.random.default_rng(5)
    recs: list[EventReactionRecord] = []
    for i in range(n):
        surprise = 0.2 if i % 2 == 0 else -0.2
        drift = drift_sign * np.sign(surprise) * (0.03 + 0.01 * rng.standard_normal())
        recs.append(
            EventReactionRecord(
                symbol=f"S{i % 7}",
                event_time=_T0 + timedelta(days=7 * i),
                surprise=surprise,
                pre_return=0.0,
                reaction_return=0.02,
                drift_return=float(drift),
            )
        )
    return recs


def test_spec_builds_signed_net_returns() -> None:
    spec = PeadSpec(_records(8, drift_sign=1.0), round_trip_cost=0.0022, drift_window_days=20)
    assert spec.n_events == 8
    assert (spec.label_times.to_numpy() > spec.label_times.index.to_numpy()).all()
    # Drift aligned with surprise (drift_sign=+1) -> positive after cost.
    assert spec.event_returns(np.arange(8, dtype=np.intp)).mean() > 0.0


def test_drift_against_surprise_is_negative() -> None:
    spec = PeadSpec(_records(8, drift_sign=-1.0), round_trip_cost=0.0022)
    assert spec.event_returns(np.arange(8, dtype=np.intp)).mean() < 0.0


def test_runs_through_existing_cpcv_harness() -> None:
    spec = PeadSpec(_records(24, drift_sign=1.0), round_trip_cost=0.0022)
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(spec, cpcv, periods_per_year=DEFAULT_PERIODS_PER_YEAR)
    assert ev.distribution.num_paths == 3
    assert ev.annualised_median_sharpe > 0.0


def test_surprise_filter_data_gate() -> None:
    # All |surprise| = 0.2; a 0.5 filter keeps nothing -> data gate.
    with pytest.raises(MechanismDataError, match="no recorded earnings event clears"):
        PeadSpec(_records(8, drift_sign=1.0), round_trip_cost=0.0022, min_abs_surprise=0.5)


def test_rejects_degenerate_config() -> None:
    recs = _records(8, drift_sign=1.0)
    with pytest.raises(SpecError, match="round_trip_cost must be non-negative"):
        PeadSpec(recs, round_trip_cost=-0.1)
    with pytest.raises(SpecError, match="drift_window_days must be positive"):
        PeadSpec(recs, round_trip_cost=0.0022, drift_window_days=0)
