"""Labeling: CUSUM event sampling, triple-barrier, meta-labels, and sample weighting.

P2.3 ships the event-sampled, volatility-scaled primary label (Deep Dive #2 §3.2-3.3):
the symmetric CUSUM event sampler (:mod:`~quant.research.labeling.cusum`) and the
triple-barrier labeler (:mod:`~quant.research.labeling.triple_barrier`), whose
``label_times`` (event ``t0`` -> resolution ``t1``) feed the purged CV / CPCV splitters and
whose ``label`` is the primary side.

P2.4 adds sample weighting for non-IID labels (§3.5): concurrency / average-uniqueness and
return-attribution weights plus time-decay (:mod:`~quant.research.labeling.weights`), and
the uniqueness-aware sequential bootstrap (:mod:`~quant.research.labeling.bootstrap`).
Meta-labeling (P2.5) builds on this output.
"""

from quant.research.labeling.bootstrap import (
    average_uniqueness_of_sample,
    sequential_bootstrap,
)
from quant.research.labeling.cusum import cusum_events
from quant.research.labeling.errors import LabelingError, LabelingInputError
from quant.research.labeling.triple_barrier import (
    BARRIER,
    EVENT_TIME,
    EXIT_TIME,
    LABEL,
    LabelSet,
    TripleBarrierLabeler,
)
from quant.research.labeling.weights import SampleWeights, time_decay_weights

__all__ = [
    "BARRIER",
    "EVENT_TIME",
    "EXIT_TIME",
    "LABEL",
    "LabelSet",
    "LabelingError",
    "LabelingInputError",
    "SampleWeights",
    "TripleBarrierLabeler",
    "average_uniqueness_of_sample",
    "cusum_events",
    "sequential_bootstrap",
    "time_decay_weights",
]
