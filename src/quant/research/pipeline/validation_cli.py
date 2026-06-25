"""Command-line wiring for the P2.9 validation report + kill-gate (``run_validation_report``).

Mirrors the robustness/final-run CLIs: the pure parts — argument/date parsing, repository/tracker/
registry selection, and the :func:`main` flow — run under test with fakes, so the only
operator-only piece is the real MLflow + Parquet I/O at run time.

Usage (operator, in the research env with persistent MLflow — see the P2.9 runbook)::

    python scripts/run_validation_report.py --start 2021-06-24 --end 2026-06-23 \
        --tracker mlflow --output docs/iteration_log/cycle-1_verdict.txt

The report **always generates** (exit 0 on success) and emits a PASS/KILL verdict — a KILL is the
expected, successful outcome for most candidates (Inviolable Rule 7), not a process failure.
``--output`` writes the rendered report to a file; ``--tracker mlflow`` (the default) logs the run
to persistent MLflow (the auto-trigger requirement: every validation run counts toward the honest
trial count).
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
from quant.research.pipeline.validation import build_validation_report
from quant.research.reports.report import ValidationReport

_logger = get_logger(__name__)

_TIERS = ("parquet", "arctic", "redis")
_TRACKERS = ("mlflow", "memory")
#: Default MLflow experiment for the P2.9 kill-gate report.
DEFAULT_EXPERIMENT = "p2.9-killgate"

RepositoryFactory = Callable[[Config, str], Repository]
RegistryFactory = Callable[[Path], ModelRegistry]
TrackerFactory = Callable[[str, str], ExperimentTracker]


def default_tracker(kind: str, experiment: str) -> ExperimentTracker:
    """Build the experiment tracker: persistent MLflow, or the in-memory default.

    Raises:
        ModelDependencyError: If ``kind == "mlflow"`` but ``mlflow`` is not installed.
        ValueError: If ``kind`` is not a known tracker.
    """
    if kind == "mlflow":
        return create_mlflow_tracker(experiment)
    if kind == "memory":
        return InMemoryExperimentTracker()
    raise ValueError(f"unknown tracker {kind!r}; choose one of {', '.join(_TRACKERS)}")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``run_validation_report`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="run_validation_report",
        description="Generate the validation report + seven-point kill-gate verdict (P2.9).",
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
    parser.add_argument("--output", default=None, help="write the rendered report to this path")
    parser.add_argument("--run-name", default="p2.9-killgate", help="tracker run name")
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
    """Generate the validation report from CLI arguments; return a process exit code.

    Returns:
        ``0`` once the report generates and the verdict is emitted (a KILL is a *successful*
        report, not an error). Exceptions (no data, no artifact) propagate as a non-zero exit.
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

    report = build_validation_report(
        config,
        repository_factory(config, args.tier),
        symbols,
        start,
        end,
        registry=registry_factory(registry_root),
        tracker=tracker_factory(args.tracker, args.experiment),
        run_name=args.run_name,
    )
    rendered = report.render()
    if args.output:
        _write_output(Path(args.output), rendered)
    _log_verdict(report, rendered)
    return 0


def _write_output(path: Path, rendered: str) -> None:
    """Write the rendered report to ``path`` (parent dirs created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    _logger.info("validation report written", extra={"path": str(path)})


def _log_verdict(report: ValidationReport, rendered: str) -> None:
    """Emit the verdict at INFO (the audit record of the trade/don't-trade decision)."""
    _logger.info(
        f"validation report emitted — VERDICT {report.verdict.verdict}",
        extra={
            "model_id": report.model_id,
            "verdict": report.verdict.verdict,
            "failed_criteria": [c.number for c in report.verdict.failed_criteria],
            "cpcv_median_sharpe": report.cpcv_median_sharpe,
            "deflated_sharpe_ratio": report.deflated_sharpe_ratio,
            "pbo": report.pbo,
        },
    )
    # The full rendered report goes to the log at INFO too, so a headless run leaves a record.
    for line in rendered.splitlines():
        _logger.info(line)
