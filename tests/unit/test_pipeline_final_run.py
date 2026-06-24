"""Tests for the P2A.6 final run: train -> fit gate -> register -> round-trip verify.

The end-to-end test drives the *real* P2.7 stack (LightGBM + XGBoost + logistic ensemble, GMM
regime gate, FileModelRegistry) over a small synthetic two-symbol universe, asserting the
acceptance criteria: an artifact is registered with the §4 version tags, the run is logged, and
the reloaded artifact predicts identically to the in-memory model.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant.research.models.ensemble import build_ensemble
from quant.research.models.estimators import LogisticEstimator
from quant.research.models.registry import FileModelRegistry
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.dataset import PooledDataset, SymbolDataset, pool_datasets
from quant.research.pipeline.final_run import _fit_gate, train_final_model
from quant.research.pipeline.model import GatedEnsembleModel
from tests.unit.pipeline_fakes import (
    FakeRepository,
    minute_bars,
    pipeline_config,
    synthetic_symbol_dataset,
)

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2024, 1, 1, tzinfo=IST)
END = datetime(2024, 12, 31, tzinfo=IST)


def _repo() -> FakeRepository:
    return FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=35, minutes=120, seed=1, drift=0.00005),
            "BBB": minute_bars("BBB", sessions=35, minutes=120, seed=2, drift=-0.00003),
        }
    )


def test_train_final_model_registers_and_round_trips(tmp_path: Path) -> None:
    config = pipeline_config()
    registry = FileModelRegistry(tmp_path / "registry")
    tracker = InMemoryExperimentTracker()
    result = train_final_model(
        config, _repo(), ["AAA", "BBB"], START, END, registry=registry, tracker=tracker
    )

    # An artifact exists and the reloaded copy predicts identically (the acceptance criterion).
    assert result.roundtrip_ok
    assert result.roundtrip_max_abs_diff == 0.0
    assert result.card.model_id == "ensemble-regime-v1-0001"
    assert result.n_obs > 0
    assert result.symbols == ("AAA", "BBB")
    assert len(result.regime_multipliers) == config.pipeline.n_regimes

    # The card carries the §4 reproducibility version tags.
    card = result.card
    assert card.model_version == "ensemble-regime-v1"
    assert card.feature_set_version == config.features.feature_set_version
    assert card.data_version == result.data_version
    assert card.label_version.startswith("tb-cusum")
    assert "oos_calibrated_logloss" in card.metrics

    # The reloaded artifact is the gated model and satisfies the Model contract.
    reloaded = registry.get(card.model_id).model
    assert isinstance(reloaded, GatedEnsembleModel)
    zero_row = dict.fromkeys(reloaded.ensemble.feature_names, 0.0)
    assert 0.0 <= reloaded.predict(zero_row) <= 1.0


def test_train_final_model_logs_run_with_version_tags(tmp_path: Path) -> None:
    config = pipeline_config()
    tracker = InMemoryExperimentTracker()
    train_final_model(
        config,
        _repo(),
        ["AAA", "BBB"],
        START,
        END,
        registry=FileModelRegistry(tmp_path / "r"),
        tracker=tracker,
        run_name="custom-run",
    )
    assert len(tracker.runs) == 1
    run = tracker.last_run
    assert run is not None
    assert run.run_name == "custom-run"
    assert run.tags["model_version"] == "ensemble-regime-v1"
    assert run.tags["data_version"].startswith("15min-2sym")
    assert run.tags["n_symbols"] == "2"


def test_train_final_model_empty_verify_rows_is_trivially_ok(tmp_path: Path) -> None:
    # verify_rows=0 exercises the empty-sample short-circuit of the round-trip check.
    result = train_final_model(
        pipeline_config(),
        _repo(),
        ["AAA", "BBB"],
        START,
        END,
        registry=FileModelRegistry(tmp_path / "r"),
        tracker=InMemoryExperimentTracker(),
        verify_rows=0,
    )
    assert result.roundtrip_max_abs_diff == 0.0
    assert result.roundtrip_ok


def test_fit_gate_warns_when_every_regime_switched_off(caplog: pytest.LogCaptureFixture) -> None:
    # All forward returns negative + a model that always goes long => every regime's strategy
    # return is non-positive => the gate switches everything off (an honest, logged outcome).
    config = pipeline_config()
    pooled = _as_pooled(synthetic_symbol_dataset("AAA", 120, seed=3, forward_loc=-0.02))
    always_long = build_ensemble(
        [LogisticEstimator()], pooled.features, pd.Series(1, index=pooled.features.index)
    )
    with caplog.at_level("WARNING"):
        gate = _fit_gate(config, pooled, always_long)
    assert all(multiplier == 0.0 for multiplier in gate.multipliers)
    assert "switched every regime off" in caplog.text


def _as_pooled(dataset: SymbolDataset) -> PooledDataset:
    """Wrap a single synthetic SymbolDataset as a one-segment PooledDataset (for _fit_gate)."""
    return pool_datasets([dataset], gap=pd.Timedelta(days=1))
