"""Models: baseline, ensemble, regime gate, registry, and calibration.

P2.6 shipped the **LightGBM baseline under proper discipline** (Deep Dive #2 §4.1-4.2): a
single gradient-boosted classifier (:mod:`~quant.research.models.baseline`) evaluated only
under purged CV, with permutation/MDA importance (:mod:`~quant.research.models.importance`,
*not* MDI), isotonic probability calibration (:mod:`~quant.research.models.calibration`),
purged-CV hyperparameter tuning (:mod:`~quant.research.models.tuning`), and experiment
tracking (:mod:`~quant.research.models.tracking`) — MLflow when installed, in-memory by default.

P2.7 adds the **production model stack** (§4.1 Steps 2-4):

* :mod:`~quant.research.models.estimators` — the cross-family base learners (LightGBM,
  XGBoost, hand-rolled logistic) behind one tiny ``fit``/``predict_proba`` contract.
* :mod:`~quant.research.models.ensemble` — the calibrated cross-family blend (rank-averaging
  or stacking), trained OOF under purged CV.
* :mod:`~quant.research.models.regime` — a Gaussian-mixture **regime gate** that switches the
  signal on/off (or sizes it down) by volatility/trend regime.
* :mod:`~quant.research.models.evaluation` — the ensemble + regime gate evaluated under CPCV
  (the path-Sharpe distribution the kill-gate reads).
* :mod:`~quant.research.models.registry` — a versioned **model registry**: every artifact
  tagged with the data/feature/label/model versions it was trained on.
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
from quant.research.models.ensemble import (
    Combiner,
    EnsembleModel,
    EnsembleResult,
    EnsembleTrainer,
    RankAverageCombiner,
    StackCombiner,
    base_proba_matrix,
    build_ensemble,
    fit_base_models,
)
from quant.research.models.errors import (
    CalibrationError,
    ModelDependencyError,
    ModelError,
    ModelTrainingError,
    ScoringError,
)
from quant.research.models.estimators import (
    Estimator,
    FittedEstimator,
    FittedLightGBM,
    FittedLogistic,
    FittedXGBoost,
    LightGBMEstimator,
    LogisticEstimator,
    XGBoostEstimator,
    xgb_params_from_config,
)
from quant.research.models.evaluation import (
    CPCVEvaluation,
    evaluate_ensemble_under_cpcv,
    probability_to_position,
)
from quant.research.models.importance import permutation_importance
from quant.research.models.regime import (
    FittedGaussianMixture,
    GaussianMixtureModel,
    RegimeGate,
    fit_regime_gate,
    regime_returns,
    select_regime_multipliers,
)
from quant.research.models.registry import (
    FileModelRegistry,
    InMemoryModelRegistry,
    ModelCard,
    ModelRegistry,
    RegisteredModel,
    RegistryError,
)
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
    "CPCVEvaluation",
    "CalibrationError",
    "Combiner",
    "EnsembleModel",
    "EnsembleResult",
    "EnsembleTrainer",
    "Estimator",
    "ExperimentTracker",
    "FileModelRegistry",
    "FittedEstimator",
    "FittedGaussianMixture",
    "FittedLightGBM",
    "FittedLogistic",
    "FittedXGBoost",
    "GaussianMixtureModel",
    "HyperparameterTuner",
    "InMemoryExperimentTracker",
    "InMemoryModelRegistry",
    "IsotonicCalibrator",
    "LightGBMBaseline",
    "LightGBMEstimator",
    "LogisticEstimator",
    "MLflowExperimentTracker",
    "ModelCard",
    "ModelDependencyError",
    "ModelError",
    "ModelRegistry",
    "ModelTrainingError",
    "ParamGrid",
    "RankAverageCombiner",
    "RegimeGate",
    "RegisteredModel",
    "RegistryError",
    "RunRecord",
    "Scorer",
    "ScoringError",
    "StackCombiner",
    "TuningResult",
    "TuningTrial",
    "XGBoostEstimator",
    "accuracy",
    "base_proba_matrix",
    "booster_proba",
    "brier_score",
    "build_ensemble",
    "create_mlflow_tracker",
    "default_param_grid",
    "evaluate_ensemble_under_cpcv",
    "fit_base_models",
    "fit_booster",
    "fit_isotonic",
    "fit_regime_gate",
    "log_loss",
    "neg_log_loss",
    "params_from_config",
    "permutation_importance",
    "probability_to_position",
    "regime_returns",
    "roc_auc",
    "select_regime_multipliers",
    "xgb_params_from_config",
]
