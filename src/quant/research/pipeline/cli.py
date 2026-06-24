"""Command-line wiring for the final P2.7 run (``scripts/run_final_training.py``).

Keeps the runnable orchestration in the importable package (Ground Rule 3): the pure parts —
argument/date parsing, repository/tracker/registry selection, and the :func:`main` flow — run
under test with fakes, so the only operator-only piece is the real MLflow + Parquet I/O at run
time. Mirrors the backfill CLI (P1.4) and reuses its date/symbol/repository helpers so the data
plumbing stays in lock-step.

Usage (operator, in the research env with persistent MLflow — see the P2A.6 runbook)::

    python scripts/run_final_training.py --start 2021-06-24 --end 2026-06-23 --tracker mlflow

``--symbols`` defaults to the configured universe; ``--tier`` to the Parquet archive;
``--registry-dir`` / ``--experiment`` to their ``pipeline`` config defaults. ``--tracker mlflow``
(the default) requires ``mlflow`` installed in a ``pandas<3`` env and ``MLFLOW_TRACKING_URI`` set
— persistent tracking is a P2A.6 acceptance criterion, not optional (Part II auto-trigger).
"""

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quant.core.config import Config, load_config
from quant.core.interfaces import Repository
from quant.core.logging import configure_logging, get_logger
from quant.data.ingest.backfill_cli import (
    DEFAULT_TIER,
    build_repository,
    parse_ist_date,
    resolve_symbols,
)
from quant.research.models.registry import FileModelRegistry, ModelRegistry
from quant.research.models.tracking import (
    ExperimentTracker,
    InMemoryExperimentTracker,
    create_mlflow_tracker,
)
from quant.research.pipeline.final_run import train_final_model

_logger = get_logger(__name__)

#: Tier choices (the backfill's; Parquet archive is the canonical research source).
_TIERS = ("parquet", "arctic", "redis")
#: Tracker choices: persistent MLflow (the auto-trigger requirement) or the in-memory default.
_TRACKERS = ("mlflow", "memory")
#: Default MLflow experiment for the P2A.6 final run.
DEFAULT_EXPERIMENT = "p2a6-final-run"

#: Builds the destination repository from config + tier (injected in tests with a fake).
RepositoryFactory = Callable[[Config, str], Repository]
#: Builds the model registry from its root directory (injected in tests with a fake).
RegistryFactory = Callable[[Path], ModelRegistry]
#: Builds the experiment tracker from (kind, experiment) (injected in tests with a fake).
TrackerFactory = Callable[[str, str], ExperimentTracker]


def default_tracker(kind: str, experiment: str) -> ExperimentTracker:
    """Build the experiment tracker: persistent MLflow, or the in-memory default.

    Raises:
        ModelDependencyError: If ``kind == "mlflow"`` but ``mlflow`` is not installed (it pins
            pandas<3; install it in the research env, or use ``--tracker memory`` for a smoke run).
        ValueError: If ``kind`` is not a known tracker.
    """
    if kind == "mlflow":
        return create_mlflow_tracker(experiment)
    if kind == "memory":
        return InMemoryExperimentTracker()
    raise ValueError(f"unknown tracker {kind!r}; choose one of {', '.join(_TRACKERS)}")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``run_final_training`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="run_final_training",
        description="Train + register the final ensemble + regime-gate model on real data (P2A.6).",
    )
    parser.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD (IST)")
    parser.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD (IST)")
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="symbols to pool (default: the universe)"
    )
    parser.add_argument("--tier", choices=_TIERS, default=DEFAULT_TIER, help="source storage tier")
    parser.add_argument(
        "--tracker",
        choices=_TRACKERS,
        default="mlflow",
        help="experiment tracker (mlflow = persistent, the auto-trigger requirement)",
    )
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT, help="MLflow experiment name")
    parser.add_argument(
        "--registry-dir", default=None, help="model-registry root (default: pipeline config)"
    )
    parser.add_argument(
        "--run-name", default=None, help="tracker run name (default: model version)"
    )
    parser.add_argument("--env", default=None, help="config environment (dev | paper | live)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    repository_factory: RepositoryFactory = build_repository,
    registry_factory: RegistryFactory = FileModelRegistry,
    tracker_factory: TrackerFactory = default_tracker,
) -> int:
    """Run the final training from CLI arguments; return a process exit code.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
        environ: Environment mapping for config (injected in tests).
        repository_factory: Builds the source repository (injected in tests with a fake).
        registry_factory: Builds the model registry (injected in tests with a fake).
        tracker_factory: Builds the experiment tracker (injected in tests with a fake).

    Returns:
        ``0`` if training + registration + the round-trip check all pass; ``1`` if the reloaded
        artifact does not predict identically to the in-memory model.
    """
    args = _build_arg_parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    config = load_config(env=args.env, environ=environ)
    configure_logging(config)
    start = parse_ist_date(args.start, end=False)
    end = parse_ist_date(args.end, end=True)
    symbols = resolve_symbols(args.symbols, environ=environ)
    registry_root = (
        Path(args.registry_dir) if args.registry_dir else Path(config.pipeline.registry_dir)
    )

    result = train_final_model(
        config,
        repository_factory(config, args.tier),
        symbols,
        start,
        end,
        registry=registry_factory(registry_root),
        tracker=tracker_factory(args.tracker, args.experiment),
        run_name=args.run_name,
    )
    if not result.roundtrip_ok:
        _logger.error(
            "final run FAILED — reloaded artifact does not predict identically",
            extra={"model_id": result.card.model_id, "diff": result.roundtrip_max_abs_diff},
        )
        return 1
    _logger.info(
        f"final run PASSED — registered {result.card.model_id}; round-trip exact",
        extra={
            "model_id": result.card.model_id,
            "data_version": result.data_version,
            "feature_set_version": result.feature_set_version,
            "label_version": result.label_version,
            "n_obs": result.n_obs,
            "symbols": list(result.symbols),
            "regime_multipliers": list(result.regime_multipliers),
            "metrics": result.metrics,
        },
    )
    return 0
