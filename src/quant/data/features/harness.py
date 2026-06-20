"""The dual-path feature harness (Deep Dive #1 §2.4 — "compute once, serve identically").

This is the mechanism that **eliminates train/serve skew**: one feature library, two
callers that share the exact same code path —

* **Vectorized (backtest/training) path** — :func:`compute_feature_frame` computes every
  feature for every bar at once.
* **Incremental (live) path** — :func:`compute_features_asof` returns the feature vector
  for a single ``asof`` bar, computed by truncating history to ``<= asof`` and taking the
  last row of *the same* vectorized computation.

Because every feature is causal (uses only bars at or before its row), the incremental
vector at *t* is bit-identical to row *t* of the full vectorized frame. That equality is
the **skew tripwire** asserted in the tests (and, in CI, by the P1.8 leakage suite):
``compute_features_asof(bars, t) == compute_feature_frame(bars).loc[t]`` for every *t*.

Inputs are hygiene-clean, corporate-action *adjusted* bars (§1.3.2). Features are
computed at a bar's close; the decision they inform executes at the next bar's open
(§2.1), so using the current close is point-in-time correct.
"""

from datetime import datetime

import pandas as pd

from quant.core.config import FeaturesConfig
from quant.core.logging import get_logger
from quant.data.features import returns, volatility, vwap
from quant.data.features.errors import FeatureError
from quant.data.store import serde

_logger = get_logger(__name__)


def feature_names(config: FeaturesConfig) -> list[str]:
    """Return the ordered feature-column names produced for ``config``.

    Kept in lock-step with :func:`compute_feature_frame` (a test pins the two together),
    so consumers and the model registry can name the feature set without computing it.
    """
    names = [f"ret_{horizon}" for horizon in config.return_horizons]
    names += [
        f"rvol_{config.volatility_window}",
        f"atr_{config.atr_window}",
        f"parkinson_{config.parkinson_window}",
        "vwap_dev",
    ]
    return names


def compute_feature_frame(bars: pd.DataFrame, config: FeaturesConfig) -> pd.DataFrame:
    """Vectorized path: compute all core features for every bar in ``bars``.

    Args:
        bars: A canonical-schema bars DataFrame (one symbol; hygiene-clean + adjusted).
        config: Feature-library parameters (windows/horizons).

    Returns:
        A DataFrame indexed by bar timestamp (tz-aware IST), one column per feature in
        :func:`feature_names` order. Rows with insufficient trailing history are ``NaN``.

    Raises:
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    frame = serde.sort_bars(serde.ensure_bars_schema(bars))
    if frame.empty:
        # Empty input: return the well-typed empty feature frame (the feature functions
        # assume a non-empty datetime axis, so guard here as the hygiene jobs do).
        empty_index = pd.DatetimeIndex([], name=serde.TIME_COLUMN)
        return pd.DataFrame(
            {name: pd.Series(dtype="float64") for name in feature_names(config)}, index=empty_index
        )
    columns: dict[str, pd.Series] = {}
    for horizon in config.return_horizons:
        columns[f"ret_{horizon}"] = returns.log_return(frame, horizon)
    columns[f"rvol_{config.volatility_window}"] = volatility.realized_volatility(
        frame, config.volatility_window
    )
    columns[f"atr_{config.atr_window}"] = volatility.atr(frame, config.atr_window)
    columns[f"parkinson_{config.parkinson_window}"] = volatility.parkinson_volatility(
        frame, config.parkinson_window
    )
    columns["vwap_dev"] = vwap.vwap_deviation(frame)

    result = pd.DataFrame(columns)
    result.index = pd.DatetimeIndex(frame[serde.TIME_COLUMN], name=serde.TIME_COLUMN)
    _logger.debug(
        "computed feature frame",
        extra={"bars": len(frame), "features": len(result.columns)},
    )
    return result


def compute_features_asof(bars: pd.DataFrame, asof: datetime, config: FeaturesConfig) -> pd.Series:
    """Incremental/live path: the feature vector at ``asof`` from history up to ``asof``.

    Truncates to bars at or before ``asof`` and returns the last row of
    :func:`compute_feature_frame` — the *same* code path as the backtest, so there is no
    train/serve skew by construction.

    Args:
        bars: A canonical-schema bars DataFrame (one symbol's history through ``asof``).
        asof: The decision time (tz-aware IST); the vector is for the bar at ``asof``.
        config: Feature-library parameters.

    Returns:
        A Series of feature values for the ``asof`` bar (indexed by feature name, named
        with the bar's timestamp).

    Raises:
        FeatureError: If there is no bar at or before ``asof``.
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    frame = serde.sort_bars(serde.ensure_bars_schema(bars))
    history = frame[frame[serde.TIME_COLUMN] <= asof]
    if history.empty:
        raise FeatureError(f"no bars at or before asof {asof.isoformat()}")
    return compute_feature_frame(history, config).iloc[-1]
