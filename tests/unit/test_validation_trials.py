"""Tests for honest trial-count tracking (P2.2, Deep Dive #2 §4b.3)."""

import numpy as np
import pytest

from quant.research.validation.metrics import deflated_sharpe_ratio
from quant.research.validation.trials import Trial, TrialTracker


def test_records_and_counts_trials() -> None:
    tracker = TrialTracker()
    tracker.record("momentum", 0.12)
    tracker.record("reversion", 0.08)
    assert tracker.count == 2
    assert set(tracker.sharpes) == {0.12, 0.08}


def test_rerunning_a_named_trial_is_not_a_new_trial() -> None:
    tracker = TrialTracker()
    tracker.record("cfg-a", 0.1)
    tracker.record("cfg-a", 0.2)  # same config re-run -> overwrite, not a new trial
    assert tracker.count == 1
    assert tracker.sharpes.tolist() == [0.2]


def test_record_returns_computes_and_stores_sharpe() -> None:
    tracker = TrialTracker()
    sharpe = tracker.record_returns("cfg", [1.0, 2.0, 3.0])
    assert sharpe == pytest.approx(2.0)  # mean 2 / sample-std 1
    assert tracker.count == 1


def test_sharpe_variance_is_sample_variance() -> None:
    tracker = TrialTracker()
    for name, value in [("a", 0.1), ("b", 0.3), ("c", 0.2)]:
        tracker.record(name, value)
    assert tracker.sharpe_variance == pytest.approx(float(np.var([0.1, 0.3, 0.2], ddof=1)))


def test_variance_is_zero_below_two_trials() -> None:
    tracker = TrialTracker()
    assert tracker.sharpe_variance == 0.0  # empty
    tracker.record("only", 0.5)
    assert tracker.sharpe_variance == 0.0  # single trial


def test_trials_returns_records() -> None:
    tracker = TrialTracker()
    tracker.record("x", 0.4)
    assert list(tracker.trials()) == [Trial(name="x", sharpe=0.4)]


def test_feeds_the_deflated_sharpe_ratio() -> None:
    # The tracker's count and variance are exactly the DSR's N and V.
    tracker = TrialTracker()
    rng = np.random.default_rng(5)
    for i in range(30):
        tracker.record(f"trial-{i}", float(rng.normal(0.05, 0.1)))
    dsr = deflated_sharpe_ratio(
        observed_sharpe=0.18,
        n_obs=750,
        skewness=0.0,
        kurtosis=3.0,
        sharpe_variance=tracker.sharpe_variance,
        n_trials=tracker.count,
    )
    assert 0.0 <= dsr <= 1.0
