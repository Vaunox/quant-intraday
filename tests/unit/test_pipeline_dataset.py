"""Tests for the P2A.6 dataset assembly (resample, per-symbol build, cross-symbol pooling).

The cross-symbol pooling carries the operator's correctness constraint (Option 1): the pooled
synthetic timeline must be sorted + unique, preserve each symbol's intra-symbol time deltas, and
**never let a label window from one symbol overlap another symbol's segment** — asserted directly
here from the segment spans.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant.core.frames import bars_to_frame
from quant.data.store import serde
from quant.research.pipeline.dataset import (
    PooledDataset,
    SymbolDataset,
    build_pooled_dataset,
    build_symbol_dataset,
    data_version,
    label_version,
    pool_datasets,
    resample_bars,
)
from quant.research.pipeline.errors import PipelineError
from tests.unit.hygiene_fakes import bar, frame
from tests.unit.pipeline_fakes import (
    FakeRepository,
    flat_bars,
    minute_bars,
    pipeline_config,
    synthetic_symbol_dataset,
)

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2024, 1, 1, tzinfo=IST)
END = datetime(2024, 12, 31, tzinfo=IST)


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


# --------------------------------------------------------------------------- resample_bars


def test_resample_aggregates_ohlcv_per_bucket() -> None:
    day = date(2024, 1, 2)
    bars = frame(
        [
            bar("X", _at(day, 9, 15), o=100.0, h=101.0, lo=99.0, c=100.5, v=10),
            bar("X", _at(day, 9, 20), o=100.5, h=102.0, lo=100.0, c=101.5, v=20),
            bar("X", _at(day, 9, 29), o=101.5, h=101.8, lo=98.5, c=99.5, v=30),
            bar("X", _at(day, 9, 30), o=99.5, h=100.0, lo=99.0, c=99.8, v=40),  # next bucket
        ]
    )
    out = resample_bars(bars, 15)
    assert len(out) == 2
    first = out.iloc[0]
    assert first["timestamp"] == _at(day, 9, 15)
    assert (first["open"], first["high"], first["low"], first["close"]) == (
        100.0,
        102.0,
        98.5,
        99.5,
    )
    assert first["volume"] == 60  # 10 + 20 + 30
    assert out.iloc[1]["timestamp"] == _at(day, 9, 30)
    assert out.iloc[1]["volume"] == 40


def test_resample_is_session_safe_no_overnight_bucket() -> None:
    bars = minute_bars("X", sessions=2, minutes=120, seed=3)
    out = resample_bars(bars, 15)
    times = pd.DatetimeIndex(out["timestamp"])
    # Two sessions of 120 minutes -> 8 fifteen-minute bars each, none straddling the gap.
    assert len(out) == 16
    assert times.normalize().nunique() == 2
    within_session = times.to_series().diff().dropna()
    assert (within_session > pd.Timedelta(minutes=15)).sum() == 1  # exactly one overnight jump


def test_resample_empty_in_empty_out() -> None:
    out = resample_bars(bars_to_frame([]), 15)
    assert out.empty
    assert list(out.columns) == list(serde.ensure_bars_schema(out).columns)


def test_resample_rejects_non_positive_minutes() -> None:
    with pytest.raises(PipelineError, match="positive minutes"):
        resample_bars(minute_bars("X", sessions=1), 0)


# ----------------------------------------------------------------------- build_symbol_dataset


def test_build_symbol_dataset_produces_aligned_labeled_rows() -> None:
    config = pipeline_config()
    dataset = build_symbol_dataset("X", minute_bars("X", sessions=30, minutes=120, seed=5), config)
    assert isinstance(dataset, SymbolDataset)
    assert len(dataset) > 0
    # Every component shares the one event-time index.
    index = dataset.features.index
    for component in (
        dataset.labels,
        dataset.label_times,
        dataset.forward_returns,
        dataset.regime_features,
        dataset.weights,
    ):
        assert component.index.equals(index)
    assert set(dataset.labels.unique()) == {0, 1}  # both classes present
    assert not dataset.features.isna().to_numpy().any()  # warm-up rows dropped
    assert not dataset.regime_features.isna().to_numpy().any()
    assert tuple(dataset.regime_features.columns) == ("vol_regime", "trend_strength")
    # The binary label is "the long side won": label 1 <=> positive realized return.
    assert (dataset.forward_returns[dataset.labels == 1] > 0).all()


def test_build_symbol_dataset_empty_bars() -> None:
    dataset = build_symbol_dataset("X", bars_to_frame([]), pipeline_config())
    assert len(dataset) == 0


def test_build_symbol_dataset_flat_bars_no_events() -> None:
    # Constant prices -> CUSUM never fires -> no labels at all (the len(labels) == 0 path).
    dataset = build_symbol_dataset("X", flat_bars("X", sessions=20, minutes=120), pipeline_config())
    assert len(dataset) == 0


def test_build_symbol_dataset_all_events_in_warmup() -> None:
    # Volatile first session (events fire early, within the regime warm-up) then flat sessions:
    # labels exist but every one is dropped for an undefined feature/regime vector.
    volatile = minute_bars("X", sessions=1, minutes=120, seed=9, vol=0.01)
    later_flat = flat_bars("X", sessions=8, minutes=120, start_day=date(2024, 1, 2))
    bars = serde.concat_bars([volatile, later_flat])
    dataset = build_symbol_dataset("X", bars, pipeline_config())
    assert len(dataset) == 0


# --------------------------------------------------------------------------- pool_datasets


def test_pool_datasets_builds_sorted_unique_gapped_timeline() -> None:
    gap = pd.Timedelta(days=2)
    datasets = [
        synthetic_symbol_dataset("BBB", 40, seed=1),
        synthetic_symbol_dataset("AAA", 50, seed=2),
    ]
    pooled = pool_datasets(datasets, gap=gap)
    assert isinstance(pooled, PooledDataset)
    assert pooled.n_obs == 90
    assert pooled.symbols == ("AAA", "BBB")  # deterministic sorted-name order
    assert pooled.label_times.index.is_monotonic_increasing
    assert pooled.label_times.index.is_unique
    # Aligned components.
    for component in (
        pooled.labels,
        pooled.forward_returns,
        pooled.regime_features,
        pooled.weights,
    ):
        assert component.index.equals(pooled.features.index)


def test_pool_datasets_has_no_cross_symbol_label_overlap() -> None:
    # The operator constraint: a label window must never span two symbols. With the gap strictly
    # larger than any (synthetic) label horizon, each segment starts after the previous resolves.
    gap = pd.Timedelta(days=2)
    pooled = pool_datasets(
        [synthetic_symbol_dataset(s, 30, seed=i) for i, s in enumerate(("AAA", "BBB", "CCC"))],
        gap=gap,
    )
    for earlier, later in zip(pooled.segments, pooled.segments[1:], strict=False):
        assert later.synthetic_start > earlier.synthetic_end
        # The gap is exactly the configured separation beyond the previous resolution.
        assert later.synthetic_start == earlier.synthetic_end + gap


def test_pool_datasets_preserves_intra_symbol_deltas() -> None:
    dataset = synthetic_symbol_dataset("AAA", 20, seed=7, step_minutes=15)
    pooled = pool_datasets([dataset], gap=pd.Timedelta(days=2))
    # A single symbol gets a zero offset, so its synthetic timeline equals the real one.
    assert pooled.segments[0].offset == pd.Timedelta(0)
    real_deltas = dataset.features.index.to_series().diff().dropna()
    pooled_deltas = pooled.features.index.to_series().diff().dropna()
    assert (real_deltas.to_numpy() == pooled_deltas.to_numpy()).all()


def test_pool_datasets_rejects_empty_and_bad_gap() -> None:
    with pytest.raises(PipelineError, match="no symbol datasets"):
        pool_datasets([], gap=pd.Timedelta(days=1))
    with pytest.raises(PipelineError, match="gap must be positive"):
        pool_datasets([synthetic_symbol_dataset("A", 5)], gap=pd.Timedelta(0))


# ----------------------------------------------------------------------- build_pooled_dataset


def test_build_pooled_dataset_reads_and_pools_from_repository() -> None:
    config = pipeline_config()
    repo = FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=30, minutes=120, seed=1, drift=0.00005),
            "BBB": minute_bars("BBB", sessions=30, minutes=120, seed=2, drift=-0.00003),
        }
    )
    pooled = build_pooled_dataset(config, repo, ["AAA", "BBB"], START, END)
    assert pooled.symbols == ("AAA", "BBB")
    assert pooled.n_obs > 0
    assert pooled.feature_names[0] == "ret_1"


def test_build_pooled_dataset_skips_empty_symbols() -> None:
    config = pipeline_config()
    repo = FakeRepository({"AAA": minute_bars("AAA", sessions=30, minutes=120, seed=1)})
    # MISSING has no bars; FLAT has bars but no labelable events — both skipped, AAA remains.
    repo.write_bars("FLAT", flat_bars("FLAT", sessions=20, minutes=120))
    pooled = build_pooled_dataset(config, repo, ["AAA", "MISSING", "FLAT"], START, END)
    assert pooled.symbols == ("AAA",)


def test_build_pooled_dataset_raises_when_all_empty() -> None:
    config = pipeline_config()
    repo = FakeRepository({"FLAT": flat_bars("FLAT", sessions=20, minutes=120)})
    with pytest.raises(PipelineError, match="no symbol produced any labeled events"):
        build_pooled_dataset(config, repo, ["FLAT", "MISSING"], START, END)


# --------------------------------------------------------------------------- version tags


def test_data_version_is_deterministic_and_order_independent() -> None:
    a = data_version(["AAA", "BBB"], START, END, "15min")
    b = data_version(["BBB", "AAA"], START, END, "15min")
    assert a == b  # symbol order does not matter
    assert a.startswith("15min-2sym-20240101-20241231-")
    assert a != data_version(["AAA", "CCC"], START, END, "15min")  # different universe


def test_label_version_encodes_barrier_params() -> None:
    config = pipeline_config()
    tag = label_version(config.labeling)
    assert tag.startswith("tb-cusum")
    other = label_version(config.labeling.model_copy(update={"barrier_upper_multiple": 3.0}))
    assert tag != other
