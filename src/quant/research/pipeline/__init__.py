"""Research training pipeline: real bars -> pooled matrix -> registry-promotable model (P2A.6).

The orchestration that completes the deferred final P2.7 run on real data. It assembles the
backfilled Parquet bars (P2A.3) into one pooled, cross-sectional training matrix
(:mod:`~quant.research.pipeline.dataset`), trains the P2.7 ensemble + regime-gate stack on it,
and writes the artifact + model card into the registry, logged to persistent MLflow
(:mod:`~quant.research.pipeline.final_run`). It adds no model maths — only the wiring and the
deliverable composition (:class:`~quant.research.pipeline.model.GatedEnsembleModel`).
"""

from quant.research.pipeline.dataset import (
    REGIME_FEATURES,
    PooledDataset,
    PoolSegment,
    SymbolDataset,
    build_pooled_dataset,
    build_symbol_dataset,
    data_version,
    label_version,
    pool_datasets,
    resample_bars,
)
from quant.research.pipeline.errors import PipelineError
from quant.research.pipeline.final_run import FinalRunResult, train_final_model
from quant.research.pipeline.model import GatedEnsembleModel

__all__ = [
    "REGIME_FEATURES",
    "FinalRunResult",
    "GatedEnsembleModel",
    "PipelineError",
    "PoolSegment",
    "PooledDataset",
    "SymbolDataset",
    "build_pooled_dataset",
    "build_symbol_dataset",
    "data_version",
    "label_version",
    "pool_datasets",
    "resample_bars",
    "train_final_model",
]
