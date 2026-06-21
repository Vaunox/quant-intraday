"""Models: baseline, ensemble, regime gate, meta-model, and calibration.

P2.6 ships the **LightGBM baseline under proper discipline** (Deep Dive #2 §4.1-4.2): a
single gradient-boosted classifier (:mod:`~quant.research.models.baseline`) evaluated only
under purged CV, with permutation/MDA importance (:mod:`~quant.research.models.importance`,
*not* MDI), isotonic probability calibration (:mod:`~quant.research.models.calibration`),
purged-CV hyperparameter tuning (:mod:`~quant.research.models.tuning`), and experiment
tracking (:mod:`~quant.research.models.tracking`) — MLflow when installed, in-memory by
default. The ensemble, regime gate, registry, and meta-model land in P2.7.
"""

from quant.research.models.baseline import (
    BaselineResult,
    BaselineTrainer,
    LightGBMBaseline,
    booster_proba,
    fit_booster,
    params_from_config,
)
from quant.research.models.calibration import IsotonicCalibrator, fit_isotonic
from quant.research.models.errors import (
    CalibrationError,
    ModelDependencyError,
    ModelError,
    ModelTrainingError,
    ScoringError,
)
from quant.research.models.importance import permutation_importance
from quant.research.models.scoring import (
    Scorer,
    accuracy,
    brier_score,
    log_loss,
    neg_log_loss,
    roc_auc,
)
from quant.research.models.tracking import (
    ExperimentTracker,
    InMemoryExperimentTracker,
    MLflowExperimentTracker,
    RunRecord,
    create_mlflow_tracker,
)
from quant.research.models.tuning import (
    HyperparameterTuner,
    ParamGrid,
    TuningResult,
    TuningTrial,
    default_param_grid,
)

__all__ = [
    "BaselineResult",
    "BaselineTrainer",
    "CalibrationError",
    "ExperimentTracker",
    "HyperparameterTuner",
    "InMemoryExperimentTracker",
    "IsotonicCalibrator",
    "LightGBMBaseline",
    "MLflowExperimentTracker",
    "ModelDependencyError",
    "ModelError",
    "ModelTrainingError",
    "ParamGrid",
    "RunRecord",
    "Scorer",
    "ScoringError",
    "TuningResult",
    "TuningTrial",
    "accuracy",
    "booster_proba",
    "brier_score",
    "create_mlflow_tracker",
    "default_param_grid",
    "fit_booster",
    "fit_isotonic",
    "log_loss",
    "neg_log_loss",
    "params_from_config",
    "permutation_importance",
    "roc_auc",
]
