"""Signal combination — factors -> one score per name (Phase 3X.4).

Turns the raw per-symbol factor panels (P3X.2) into a single cross-sectional **score** per
``(rebalance_date, symbol)`` that the portfolio construction (P3X.7) ranks into a book. Each
factor is first **sector-neutral z-scored** at each date (reusing the P1.7 cross-sectional
primitive), so no factor is an accidental sector bet, then the z-scores are averaged across
factors.

Two combiners behind one :class:`SignalCombiner` interface:

* :class:`EqualWeightComposite` — the **baseline**: an equal-weight average of the sector-neutral
  factor z-scores, **zero free parameters**. This is the candidate that must clear the kill-gate
  first (no tuning, nothing to overfit).
* :class:`WeightedComposite` — configurable factor weights. Any non-uniform weight vector is a
  *choice* that must be charged against the honest DSR trial count (P3X.5); use only after the
  baseline clears.

The ML ensemble combiner (LightGBM/XGBoost/logistic predicting the P3X.3 rank/return from the
factor panel) is trained *per CPCV fold* and therefore lives in the evaluation layer (P3X.5),
where each configuration it tries increments the trial count — it is not a free transform here.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from quant.data.features.cross_sectional import sector_neutral_zscore
from quant.research.factors.errors import FactorError


def sector_neutral_composite(
    factor_panels: Mapping[str, pd.DataFrame],
    sectors: Mapping[str, str],
    *,
    weights: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Combine factor panels into one composite score per ``(date, symbol)``.

    Each factor panel (index = rebalance date, columns = symbol) is sector-neutral z-scored at
    each date, then the z-scores are combined as a weighted average (equal weight by default).
    A ``(date, symbol)`` cell is the weighted mean of whichever factor z-scores are defined there
    (``NaN`` factors are skipped, not treated as zero); a cell with no defined factor stays ``NaN``.

    Args:
        factor_panels: ``{factor_name -> panel}``; panels are aligned to their union grid.
        sectors: ``symbol -> sector`` for the sector-neutral z-score.
        weights: optional ``factor_name -> weight`` (default equal). Non-uniform weights are a
            tuned choice — charge them against the DSR trial count.

    Raises:
        FactorError: If ``factor_panels`` is empty or the weights are degenerate/misnamed.
    """
    if not factor_panels:
        raise FactorError("need at least one factor panel to combine")
    names = list(factor_panels)
    if weights is None:
        weight = dict.fromkeys(names, 1.0)
    else:
        missing = [name for name in names if name not in weights]
        if missing:
            raise FactorError(f"weights missing for factors: {sorted(missing)}")
        weight = {name: float(weights[name]) for name in names}
    if sum(abs(w) for w in weight.values()) == 0.0:
        raise FactorError("factor weights sum to zero")

    zscores = {name: sector_neutral_zscore(factor_panels[name], sectors) for name in names}
    index = zscores[names[0]].index
    columns = zscores[names[0]].columns
    for name in names[1:]:
        index = index.union(zscores[name].index)
        columns = columns.union(zscores[name].columns)

    aligned = [
        zscores[name].reindex(index=index, columns=columns).to_numpy(dtype="float64")
        for name in names
    ]
    stacked = np.stack(aligned)
    weight_vector = np.asarray([weight[name] for name in names], dtype="float64").reshape(-1, 1, 1)
    defined = ~np.isnan(stacked)
    weighted_sum = np.nansum(stacked * weight_vector, axis=0)
    weight_norm = np.sum(defined * np.abs(weight_vector), axis=0)
    composite = np.divide(
        weighted_sum, weight_norm, out=np.full_like(weighted_sum, np.nan), where=weight_norm > 0
    )
    return pd.DataFrame(composite, index=index, columns=columns)


class SignalCombiner(Protocol):
    """Combines factor panels into one score panel (index = date, columns = symbol)."""

    def combine(self, factor_panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Return the composite score per ``(date, symbol)``."""
        ...


@dataclass(frozen=True)
class EqualWeightComposite:
    """The zero-parameter baseline: equal-weight average of sector-neutral factor z-scores."""

    sectors: Mapping[str, str]

    def combine(self, factor_panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Return the equal-weight sector-neutral composite score."""
        return sector_neutral_composite(factor_panels, self.sectors)


@dataclass(frozen=True)
class WeightedComposite:
    """A configurable-weight composite — each non-uniform weight vector is a charged trial."""

    sectors: Mapping[str, str]
    weights: Mapping[str, float]

    def combine(self, factor_panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Return the weighted sector-neutral composite score."""
        return sector_neutral_composite(factor_panels, self.sectors, weights=self.weights)
