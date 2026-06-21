"""Sequential bootstrap by uniqueness (Deep Dive #2 §3.5, AFML §4.5.3).

*"When bagging, draw samples in proportion to uniqueness rather than uniformly, so each
bootstrap sample carries more independent information."* Standard bootstrap draws labels
uniformly with replacement, which over-samples redundant, overlapping labels. The
**sequential bootstrap** draws one label at a time, each time re-weighting the draw
probabilities by each candidate's **average uniqueness *given the labels already drawn***
— so a candidate that heavily overlaps the running sample becomes unlikely to be picked
again.

Mechanically, with the (bars x labels) indicator matrix: maintain the running per-bar
concurrency of the already-drawn labels; a candidate's average uniqueness is the mean over
its active bars of ``1 / (concurrency + 1)`` (the ``+1`` is the candidate itself). Drawing
proportional to that, repeatedly, yields a sample whose average uniqueness is materially
higher than a uniform draw's — *why* a uniqueness-aware bagged ensemble generalizes better.

The RNG is injected (a seeded :class:`numpy.random.Generator`) so every draw is reproducible
(Ground Rule 7: seed all RNGs).
"""

import numpy as np
import numpy.typing as npt

from quant.core.logging import get_logger
from quant.research.labeling.errors import LabelingInputError

_logger = get_logger(__name__)


def sequential_bootstrap(
    indicator_matrix: npt.NDArray[np.int8],
    n_samples: int | None = None,
    *,
    rng: np.random.Generator,
) -> npt.NDArray[np.intp]:
    """Draw ``n_samples`` label indices by sequential (uniqueness-aware) bootstrap.

    Args:
        indicator_matrix: The (bars x labels) activity matrix from
            :attr:`~quant.research.labeling.weights.SampleWeights.indicator_matrix`.
        n_samples: Number of labels to draw (with replacement). Defaults to the number of
            labels (the standard bootstrap size).
        rng: A seeded :class:`numpy.random.Generator` (injected for reproducibility).

    Returns:
        An array of drawn label indices (positions into the matrix' columns), length
        ``n_samples``. Indices may repeat (it is a bootstrap).

    Raises:
        LabelingInputError: If the matrix is not 2-D with at least one label, a label spans
            no bars, or ``n_samples`` is not positive.
    """
    matrix = np.asarray(indicator_matrix, dtype="float64")
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise LabelingInputError(f"indicator_matrix must be (bars, labels>=1), got {matrix.shape}")
    n_labels = matrix.shape[1]
    active_bars = matrix.sum(axis=0)
    if bool((active_bars <= 0).any()):
        raise LabelingInputError("every label must span at least one bar")
    if n_samples is None:
        n_samples = n_labels
    if n_samples <= 0:
        raise LabelingInputError(f"n_samples must be positive, got {n_samples}")

    concurrency = np.zeros(matrix.shape[0], dtype="float64")
    drawn = np.empty(n_samples, dtype=np.intp)
    for draw in range(n_samples):
        # Average uniqueness of each candidate if it were added next: mean over its active
        # bars of 1 / (current concurrency + 1).
        inverse = 1.0 / (concurrency + 1.0)
        average_uniqueness = (matrix.T @ inverse) / active_bars
        probability = average_uniqueness / average_uniqueness.sum()
        choice = int(rng.choice(n_labels, p=probability))
        drawn[draw] = choice
        concurrency += matrix[:, choice]  # the drawn label now overlaps future candidates

    _logger.debug("sequential bootstrap", extra={"labels": n_labels, "drawn": n_samples})
    return drawn


def average_uniqueness_of_sample(
    indicator_matrix: npt.NDArray[np.int8], sample: npt.NDArray[np.intp]
) -> float:
    """Mean average-uniqueness of a drawn (multiset) ``sample`` — the bootstrap's quality.

    Higher means more independent information. A sequential-bootstrap sample scores higher
    than a uniform-random one on an overlapping label set (the property §4.5.3 promises).

    Raises:
        LabelingInputError: If ``sample`` is empty.
    """
    if len(sample) == 0:
        raise LabelingInputError("sample must contain at least one drawn label")
    drawn = np.asarray(indicator_matrix, dtype="float64")[:, sample]  # (bars x drawn)
    concurrency = drawn.sum(axis=1)
    inverse = np.divide(1.0, concurrency, out=np.zeros_like(concurrency), where=concurrency > 0)
    per_label = (drawn.T @ inverse) / drawn.sum(axis=0)
    return float(per_label.mean())
