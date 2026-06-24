"""Tests for the GatedEnsembleModel (the P2A.6 registry artifact: ensemble + regime gate)."""

import pickle
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant.research.models.ensemble import build_ensemble
from quant.research.models.estimators import LogisticEstimator
from quant.research.models.evaluation import probability_to_position
from quant.research.models.regime import fit_regime_gate
from quant.research.pipeline.dataset import REGIME_FEATURES
from quant.research.pipeline.model import GatedEnsembleModel

IST = ZoneInfo("Asia/Kolkata")


def _gated_model(
    n: int = 200, *, seed: int = 0
) -> tuple[GatedEnsembleModel, pd.DataFrame, pd.DataFrame]:
    """Build a small fitted GatedEnsembleModel plus its features and regime features."""
    rng = np.random.default_rng(seed)
    index = pd.DatetimeIndex(
        [datetime(2024, 1, 2, 9, 15, tzinfo=IST) + timedelta(minutes=15 * i) for i in range(n)]
    )
    signal = rng.normal(size=n)
    features = pd.DataFrame({"signal": signal, "noise": rng.normal(size=n)}, index=index)
    labels = pd.Series(
        (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-2 * signal))).astype("int64"), index=index
    )
    regime = pd.DataFrame(
        {
            REGIME_FEATURES[0]: np.abs(rng.normal(1.0, 0.3, n)),
            REGIME_FEATURES[1]: rng.normal(0, 1, n),
        },
        index=index,
    )
    ensemble = build_ensemble([LogisticEstimator()], features, labels)
    returns = probability_to_position(ensemble.predict_proba(features)) * rng.normal(0, 0.01, n)
    gate = fit_regime_gate(regime, 2, returns=returns, random_seed=1)
    return GatedEnsembleModel(ensemble, gate, REGIME_FEATURES), features, regime


def test_predict_proba_matches_underlying_ensemble() -> None:
    model, features, _ = _gated_model()
    np.testing.assert_array_equal(
        model.predict_proba(features), model.ensemble.predict_proba(features)
    )


def test_predict_single_row_satisfies_model_contract() -> None:
    model, features, _ = _gated_model()
    row = {str(name): float(value) for name, value in features.iloc[0].items()}
    assert model.predict(row) == model.ensemble.predict(row)
    assert 0.0 <= model.predict(row) <= 1.0


def test_gated_position_applies_regime_multiplier() -> None:
    model, features, regime = _gated_model()
    position = probability_to_position(model.predict_proba(features))
    expected = position * model.regime_gate.regime_multiplier(regime[list(REGIME_FEATURES)])
    np.testing.assert_allclose(model.gated_position(features, regime), expected)


def test_gated_position_selects_named_regime_columns() -> None:
    # Extra/re-ordered regime columns must not break the gate (it selects by name).
    model, features, regime = _gated_model()
    noisy = regime.assign(extra=1.0)[["trend_strength", "extra", "vol_regime"]]
    np.testing.assert_allclose(
        model.gated_position(features, noisy), model.gated_position(features, regime)
    )


def test_pickle_round_trip_predicts_identically() -> None:
    model, features, _ = _gated_model()
    restored = pickle.loads(pickle.dumps(model))
    np.testing.assert_array_equal(restored.predict_proba(features), model.predict_proba(features))
