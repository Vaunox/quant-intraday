"""Labeling: CUSUM event sampling, triple-barrier, meta-labels, and sample weighting.

P2.3 ships the event-sampled, volatility-scaled primary label (Deep Dive #2 §3.2-3.3):
the symmetric CUSUM event sampler (:mod:`~quant.research.labeling.cusum`) and the
triple-barrier labeler (:mod:`~quant.research.labeling.triple_barrier`), whose
``label_times`` (event ``t0`` -> resolution ``t1``) feed the purged CV / CPCV splitters and
whose ``label`` is the primary side. Meta-labeling (P2.5) and sample weighting (P2.4) build
on this output.
"""

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

__all__ = [
    "BARRIER",
    "EVENT_TIME",
    "EXIT_TIME",
    "LABEL",
    "LabelSet",
    "LabelingError",
    "LabelingInputError",
    "TripleBarrierLabeler",
    "cusum_events",
]
