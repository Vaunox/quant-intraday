"""The registry-promotable deliverable: a calibrated ensemble bundled with its regime gate.

P2A.6's artifact is *"the ensemble + regime-gate model"* (Deep Dive #2 §4.1, Steps 3-4). P2.7
ships the two pieces separately — :class:`~quant.research.models.ensemble.EnsembleModel` (the
calibrated cross-family blend, the live inference path) and
:class:`~quant.research.models.regime.RegimeGate` (the per-regime on/off/size-down multiplier).
This thin, frozen, picklable wrapper composes them into the one object the registry stores and
P2.8/P2.9 judge, without re-implementing either (Ground Rule 4):

* :meth:`predict` / :meth:`predict_proba` are the ungated calibrated conviction — the wrapper
  *is-a* :class:`~quant.core.interfaces.Model`, so research and live share one object.
* :meth:`gated_position` applies the regime gate to the directional position, the form the
  Capital Layer (Deep Dive #3) and the P2.8 backtests size from.

Keeping the gate alongside (rather than baking it into the probability) preserves the
distinction the kill-gate needs: the *signal* (calibrated probability) and the *regime
decision* (criterion 7) are separately inspectable.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.models.ensemble import EnsembleModel
from quant.research.models.evaluation import probability_to_position
from quant.research.models.regime import RegimeGate


@dataclass(frozen=True, slots=True)
class GatedEnsembleModel:
    """A fitted cross-family ensemble plus its regime gate (the P2A.6 registry artifact)."""

    ensemble: EnsembleModel
    regime_gate: RegimeGate
    regime_feature_names: tuple[str, ...]

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the calibrated (ungated) ``P(y=1)`` per row (the conviction for sizing)."""
        return self.ensemble.predict_proba(features)

    def predict(self, features: Mapping[str, float]) -> float:
        """Return the calibrated ``P(y=1)`` for one feature vector (the live Model contract)."""
        return self.ensemble.predict(features)

    def gated_position(
        self, features: pd.DataFrame, regime_features: pd.DataFrame
    ) -> npt.NDArray[np.float64]:
        """Return the regime-gated directional position (``2·p - 1`` scaled by the gate).

        Maps the calibrated probability to a position in ``[-1, 1]`` (long when bullish, short
        when bearish) and scales it by the active regime's multiplier — the §4.1 "switched on or
        off, or sized down, by regime" behaviour. ``regime_features`` must align row-for-row with
        ``features`` and carry the :attr:`regime_feature_names` columns.
        """
        position = probability_to_position(self.ensemble.predict_proba(features))
        return self.regime_gate.gate(position, regime_features[list(self.regime_feature_names)])
