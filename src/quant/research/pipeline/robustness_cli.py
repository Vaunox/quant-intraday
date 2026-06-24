"""Command-line wiring for the P2.8 robustness battery (``scripts/run_robustness.py``).

Mirrors the final-run CLI (P2A.6): the pure parts — argument/date parsing, repository/tracker/
registry selection, and the :func:`main` flow — run under test with fakes, so the only
operator-only piece is the real MLflow + Parquet I/O at run time. Reuses the backfill CLI's
date/symbol/repository helpers so the data plumbing stays in lock-step.

Usage (operator, in the research env with persistent MLflow — see the P2.8 runbook)::

    python scripts/run_robustness.py --start 2021-06-24 --end 2026-06-23 --tracker mlflow

``--symbols`` defaults to the configured universe; ``--tier`` to the Parquet archive;
``--registry-dir`` / ``--experiment`` to their config defaults. ``--tracker mlflow`` (the
default) requires ``mlflow`` installed in a ``pandas<3`` env and ``MLFLOW_TRACKING_URI`` set —
persistent tracking is a P2.8 acceptance criterion, not optional (Part II auto-trigger). The
exit code is ``0`` when every stress test ran and the two engines reconciled, ``1`` if the
reconciliation failed (the engines disagree — an implementation bug, not a weak edge).
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
from quant.research.pipeline.robustness import RobustnessBatteryReport, run_robustness_battery

_logger = get_logger(__name__)

#: Source storage tiers (the backfill's; Parquet archive is the canonical research source).
_TIERS = ("parquet", "arctic", "redis")
#: Tracker choices: persistent MLflow (the auto-trigger requirement) or the in-memory default.
_TRACKERS = ("mlflow", "memory")
#: Default MLflow experiment for the P2.8 robustness battery.
DEFAULT_EXPERIMENT = "p2.8-robustness"

#: Builds the source repository from config + tier (injected in tests with a fake).
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
    """Build the ``run_robustness`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="run_robustness",
        description="Run the P2.8 robustness battery + two-engine reconciliation on real data.",
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
    parser.add_argument("--run-name", default="p2.8-robustness", help="base tracker run name")
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
    """Run the robustness battery from CLI arguments; return a process exit code.

    Returns:
        ``0`` if every stress test ran and the two engines reconciled within tolerance; ``1`` if
        the reconciliation failed (the engines disagree — an implementation bug to fix before any
        capital rides on the backtest). A weak edge is *not* a failure here: the battery reports
        it, and the kill-gate verdict is P2.9's to emit.
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

    report = run_robustness_battery(
        config,
        repository_factory(config, args.tier),
        symbols,
        start,
        end,
        registry=registry_factory(registry_root),
        tracker=tracker_factory(args.tracker, args.experiment),
        run_name=args.run_name,
    )
    _log_report(report)
    return 0 if report.reconciliation.reconciled else 1


def _log_report(report: RobustnessBatteryReport) -> None:
    """Emit the consolidated battery verdict (and per-test summary) at INFO."""
    level = "PASSED" if report.reconciliation.reconciled else "FAILED — engines disagree"
    _logger.info(
        f"robustness battery {level}",
        extra={
            "model_id": report.model_id,
            "n_obs": report.n_obs,
            "symbols": list(report.symbols),
            "battery_passes": report.passes,
            "parameter_sensitivity_knife_edge": report.parameter_sensitivity.is_knife_edge,
            "param_baseline_median": report.parameter_sensitivity.baseline_median,
            "noise_edge_persists": report.noise_injection.edge_persists,
            "monte_carlo_percentile_rank": report.monte_carlo.percentile_rank,
            "cross_symbol_median": report.cross_symbol.median,
            "cross_symbol_generalizes": report.cross_symbol.generalizes,
            "synthetic_mean_median": report.synthetic.mean_median,
            "synthetic_edge_detected": report.synthetic.edge_detected,
            "reconcile_max_money_diff": report.reconciliation.max_money_diff,
            "reconciled": report.reconciliation.reconciled,
        },
    )
