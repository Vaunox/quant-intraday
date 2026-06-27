"""Cluster-selection SignalCombiner (Phase 3X.4b — A/B variant).

A drop-in alternative to the baseline equal-weight z-score combiner (P3X.4
:class:`~quant.research.factors.combine.EqualWeightComposite`), porting the one genuinely novel
idea from the Luchkata teaching notebook: **K-Means clustering for cross-sectional stock
selection** — rebuilt to be look-ahead-free so it can be judged by the *same* benchmark-relative
seven-point kill-gate as everything else (P3X.5/P3X.8).

WHAT THE TEACHING REPO DOES (and why it inflates)
-------------------------------------------------
It clusters stocks each month, then trades the cluster that *performed best* — i.e. it picks the
target cluster using realized forward returns. That is selection on the outcome: the exact bias
DSR/PBO exist to punish. Its equity curve looks great and deflates hard under CPCV.

WHAT THIS MODULE DOES (the honest version)
------------------------------------------
At each rebalance date the per-date scorer (:class:`ClusterSelectionCombiner`):
  1. Fits K-Means on the *point-in-time* sector-neutral factor panel (features known at the
     decision; NO forward returns ever enter).
  2. Selects the target cluster by an **ex-ante thesis rule**: the cluster whose centroid projects
     highest onto a pre-specified factor-direction vector ``w`` (e.g. +momentum, +low-vol,
     +residual-momentum). Decided from features alone, before any return is observed.
  3. Emits a continuous, rankable score per name = the negative distance from the name's feature
     vector to the target centroid, so the unchanged downstream top-quintile + inverse-vol/HRP
     construction works as-is.

INTERFACE
---------
The real P3X.4 :class:`~quant.research.factors.combine.SignalCombiner` is **multi-date**:
``combine({factor -> (date x symbol) panel}) -> (date x symbol) composite``. The clustering itself
is a **per-date** transform, so this module keeps both, with the selection logic in one place:

* :class:`ClusterSelectionCombiner` — the per-date scorer (``combine(cross_section) -> scores``),
  exactly the look-ahead-free clustering described above. This is what the leakage tests exercise.
* :class:`ClusterCompositeCombiner` — the thin adapter that **is** a real ``SignalCombiner``: it
  sector-neutral z-scores each factor (reusing the P1.7 primitive, identical to the baseline), then
  applies the per-date scorer date by date and assembles the composite panel. This is what plugs
  into the unchanged gate alongside the baseline.

HONESTY GUARANTEES (the reason this is testable, not decorative)
---------------------------------------------------------------
- The per-date ``combine()`` is a pure function of the single-date cross-section passed in. It holds
  no state across calls and never receives forward returns -> forward-shift invariant by
  construction (verified by the P1.8-style suite).
- Deterministic: K-Means is seeded (``random_state``, fixed ``n_init``).
- ``k`` and ``w`` are PRE-COMMITTED in ``config/factor_default.yaml``, not tuned to the sample.
  Sweeping them is a multiple-testing search: every value tested increments the honest DSR trial
  count ``N``. Do not grid-search ``k`` to hit the bar.

Stack: numpy / pandas / scikit-learn (KMeans). Python 3.12, typed for mypy strict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.cluster import KMeans

from quant.data.features.cross_sectional import sector_neutral_zscore
from quant.research.factors.errors import FactorError

# --------------------------------------------------------------------------- #
# Per-date cluster-selection scorer (the selection logic — do not change)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClusterSelectionCombiner:
    """K-Means cluster-selection scorer with ex-ante (look-ahead-free) target cluster selection.

    Parameters
    ----------
    k:
        Number of clusters. PRE-COMMIT this; do not tune it to the sample. 4-6 is a reasonable
        default for a Nifty-500-scale monthly cross-section.
    thesis_weights:
        Mapping ``{factor_name -> weight}`` defining the ex-ante "ideal profile" direction ``w``.
        Factors MUST be sign-aligned upstream so that higher = more desirable (e.g. momentum as-is,
        low-vol entered as ``-volatility``). Defaults to equal weight on every column of the panel.
    random_state:
        Seed for K-Means — determinism is required for reproducible CPCV paths.
    n_init:
        K-Means restarts (stability). Fixed, not tuned.
    min_names_per_cluster_factor:
        If the cross-section has fewer than ``k * this`` names, fall back to the pure
        thesis-projection score (no clustering) rather than fit a degenerate K-Means. Keeps
        early/illiquid dates well-behaved.
    """

    k: int = 5
    thesis_weights: Mapping[str, float] | None = None
    random_state: int = 7
    n_init: int = 10
    min_names_per_cluster_factor: int = 3
    # internal sentinel; not a tunable
    _eps: float = field(default=1e-12, repr=False)

    def combine(self, panel: pd.DataFrame) -> pd.Series:
        """Score one date's sector-neutral factor cross-section (index = symbol, cols = factor)."""
        # ---- guard rails: point-in-time, no NaN leakage ------------------- #
        if panel.empty:
            return pd.Series(dtype=float)

        # Only score names with a complete factor vector at THIS date. Never impute from other
        # dates (that would be cross-sectional look-ahead).
        feat = panel.dropna(axis=0, how="any")
        if feat.shape[0] == 0:
            return pd.Series(index=panel.index, dtype=float)

        w = self._thesis_vector(feat.columns)
        X = feat.to_numpy(dtype=float)  # noqa: N806 - X is the idiomatic feature-matrix name

        # ---- fallback for thin cross-sections ----------------------------- #
        min_names = self.k * self.min_names_per_cluster_factor
        if feat.shape[0] < min_names or self.k < 2:
            scores = X @ w  # pure ex-ante thesis projection, rankable
            return self._reindex(pd.Series(scores, index=feat.index), panel.index)

        # ---- 1. cluster the point-in-time cross-section ------------------- #
        km = KMeans(
            n_clusters=self.k,
            random_state=self.random_state,
            n_init=self.n_init,
        )
        labels = km.fit_predict(X)
        centroids = km.cluster_centers_  # (k, n_factors)

        # ---- 2. EX-ANTE target cluster: highest centroid projection on w --- #
        # This is the only selection step, and it uses features only.
        centroid_desirability = centroids @ w  # (k,)
        target = int(np.argmax(centroid_desirability))
        target_centroid = centroids[target]

        # ---- 3. continuous, rankable score = -dist to target centroid ----- #
        # Names inside the target cluster sit closest -> highest score.
        dist = np.linalg.norm(X - target_centroid, axis=1)
        scores = -dist

        # Optional: hard-gate to target-cluster membership for a "trade only the cluster" variant.
        # Left off by default so downstream quintile + weight logic stays continuous. Uncomment to
        # A/B the strict version:
        # in_target = (labels == target).astype(float)
        # scores = in_target * (scores - scores.min() + self._eps)
        _ = labels  # the soft (continuous) variant does not use the membership labels

        return self._reindex(pd.Series(scores, index=feat.index), panel.index)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _thesis_vector(self, columns: pd.Index) -> npt.NDArray[np.float64]:
        """Build the unit thesis-direction vector ``w`` over the panel columns."""
        if self.thesis_weights is None:
            w = np.ones(len(columns), dtype=float)
        else:
            missing = set(self.thesis_weights) - set(columns)
            if missing:
                raise KeyError(f"thesis_weights references unknown factors: {missing}")
            w = np.array([self.thesis_weights.get(c, 0.0) for c in columns], dtype=float)
        norm = float(np.linalg.norm(w))
        if norm < self._eps:
            raise ValueError("thesis_weights vector has ~zero norm; cannot define a direction")
        return w / norm

    @staticmethod
    def _reindex(scores: pd.Series, full_index: pd.Index) -> pd.Series:
        """Re-index to all names: those dropped for a missing factor get NaN, never a fake score."""
        return scores.reindex(full_index)


# --------------------------------------------------------------------------- #
# Multi-date adapter — IS a real P3X.4 SignalCombiner
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClusterCompositeCombiner:
    """A real :class:`~quant.research.factors.combine.SignalCombiner` backed by per-date clustering.

    Sector-neutral z-scores each factor panel (identical to the baseline composite — same P1.7
    primitive, same grid), then applies the per-date :class:`ClusterSelectionCombiner` scorer date
    by date, assembling one composite score per ``(date, symbol)``. Plugs into the unchanged gate
    in place of :class:`~quant.research.factors.combine.EqualWeightComposite`.
    """

    sectors: Mapping[str, str]
    scorer: ClusterSelectionCombiner

    def combine(self, factor_panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        """Return the cluster-selection composite score per ``(date, symbol)``.

        Args:
            factor_panels: ``{factor_name -> (date x symbol) panel}`` (the same input the baseline
                combiner takes; factors sign-aligned so higher = more desirable).

        Raises:
            FactorError: If ``factor_panels`` is empty.
        """
        if not factor_panels:
            raise FactorError("need at least one factor panel to combine")
        names = list(factor_panels)
        zscores = {name: sector_neutral_zscore(factor_panels[name], self.sectors) for name in names}

        index = zscores[names[0]].index
        columns = zscores[names[0]].columns
        for name in names[1:]:
            index = index.union(zscores[name].index)
            columns = columns.union(zscores[name].columns)
        aligned = {name: zscores[name].reindex(index=index, columns=columns) for name in names}

        rows: dict[pd.Timestamp, pd.Series] = {}
        for date in index:
            # The per-date cross-section: index = symbol, columns = factor (sector-neutral z-score).
            cross_section = pd.DataFrame({name: aligned[name].loc[date] for name in names})
            rows[date] = self.scorer.combine(cross_section).reindex(columns)
        composite = pd.DataFrame.from_dict(rows, orient="index")
        composite.index = index
        return composite
