"""Permutation (Mean-Decrease-Accuracy) feature importance (Deep Dive #2 §4.2).

*"Use Mean-Decrease-Accuracy (permutation importance) or SHAP, **not** MDI. MDI (the default
``feature_importances_``) is biased toward high-cardinality features and distorted by
substitution effects among correlated features — and compute it **within the purged CV** so
the importance isn't itself leaking."*

This module is the MDA half: shuffle one feature column on a **held-out** fold and measure
how far the score falls. A large drop means the model genuinely relied on that feature; a
drop near zero (or negative) means it carried no out-of-sample signal. The score is any
higher-is-better :data:`~quant.research.models.scoring.Scorer`. Computing this on each purged
*test* fold (never the training data) is what keeps the importance honest — the caller in
:mod:`~quant.research.models.baseline` averages the per-fold importances. The shuffle RNG is
an injected, seeded ``Generator`` (Ground Rule 7: determinism), never a global.
"""

from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.models.errors import ModelTrainingError
from quant.research.models.scoring import Scorer, accuracy

#: A fitted model's batch probability path: ``X -> P(y=1)`` per row.
PredictProba = Callable[[pd.DataFrame], npt.NDArray[np.float64]]


def permutation_importance(
    predict_proba: PredictProba,
    features: pd.DataFrame,
    labels: npt.NDArray[np.float64] | pd.Series,
    *,
    n_repeats: int,
    rng: np.random.Generator,
    scorer: Scorer = accuracy,
) -> dict[str, float]:
    """Return per-feature MDA importance: the mean score drop when each column is shuffled.

    Args:
        predict_proba: The fitted model's batch ``X -> P(y=1)`` path. Called once for the
            baseline score and ``n_repeats`` times per feature.
        features: The **held-out** fold's feature matrix (columns = feature names).
        labels: The fold's binary outcomes ``{0, 1}``, aligned to ``features``' rows.
        n_repeats: Independent shuffles per feature, averaged (>= 1). More repeats reduce
            the Monte-Carlo noise in the estimate.
        rng: Seeded generator for the shuffles (injected for reproducibility).
        scorer: A higher-is-better score; defaults to :func:`~...scoring.accuracy` (the "A"
            in MDA). Pass ``roc_auc`` / ``neg_log_loss`` for a threshold-free measure.

    Returns:
        ``{feature_name: importance}`` — positive means the feature helped out of sample.

    Raises:
        ModelTrainingError: If ``n_repeats < 1``, ``features`` is empty, or labels do not
            align to ``features``' rows.
    """
    if n_repeats < 1:
        raise ModelTrainingError(f"n_repeats must be >= 1, got {n_repeats}")
    if features.shape[0] == 0 or features.shape[1] == 0:
        raise ModelTrainingError("cannot compute importance on an empty feature matrix")
    truth = np.asarray(labels, dtype="float64").ravel()
    if truth.shape[0] != features.shape[0]:
        raise ModelTrainingError(
            f"labels ({truth.shape[0]}) do not align to features ({features.shape[0]} rows)"
        )

    baseline_score = scorer(truth, predict_proba(features))
    importances: dict[str, float] = {}
    for column in features.columns:
        original = features[column].to_numpy(copy=True)
        drops = np.empty(n_repeats, dtype="float64")
        permuted = features.copy()
        for repeat in range(n_repeats):
            permuted[column] = rng.permutation(original)
            drops[repeat] = baseline_score - scorer(truth, predict_proba(permuted))
        importances[str(column)] = float(drops.mean())
    return importances
