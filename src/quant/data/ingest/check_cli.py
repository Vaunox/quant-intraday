"""Post-backfill data-quality check (P2A.3 verifier).

Reads the backfilled bars back through the :class:`~quant.core.interfaces.Repository` and runs
the P1.5 gap detection + the P1.9 :class:`~quant.data.quality.dashboard.DataQualityDashboard`
over them, logging per-symbol coverage / gaps / bad-ticks and the report summary. A **read-only**
companion to the backfill (``scripts/check_backfill.py`` is the thin shim, Ground Rule 3): it
touches no broker and no network, only what landed on disk. It exits non-zero only when a symbol
has **no data at all** (a real backfill failure); intraday gaps / missing days are reported for
review, not auto-failed (the "under tolerance" judgement is the operator's).

Reuses the backfill CLI's public helpers (argument/date parsing, symbol resolution, repository
selection) so the two stay in lock-step.
"""

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from quant.core.config import Config, load_config
from quant.core.interfaces import Repository
from quant.core.logging import configure_logging, get_logger
from quant.data.ingest.backfill_cli import (
    DEFAULT_TIER,
    build_repository,
    parse_ist_date,
    resolve_symbols,
)
from quant.data.quality.dashboard import create_data_quality_dashboard
from quant.data.quality.report import DataQualityReport

_logger = get_logger(__name__)

#: Builds the destination repository from config + tier (injected in tests with a fake).
RepositoryFactory = Callable[[Config, str], Repository]


@dataclass(frozen=True, slots=True)
class BackfillCheck:
    """The verifier's outcome: the full quality report + any symbols that came back empty."""

    report: DataQualityReport
    empty_symbols: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True when every requested symbol has at least some data (none empty)."""
        return not self.empty_symbols


def check_backfill(
    config: Config,
    repository: Repository,
    symbols: Sequence[str],
    *,
    start: datetime,
    end: datetime,
) -> BackfillCheck:
    """Read each symbol back from ``repository`` and assess its quality over ``[start, end]``.

    Args:
        config: System config (drives the dashboard's interval + bad-tick threshold).
        repository: The store to read the backfilled bars from (Parquet by default).
        symbols: The symbols to check (the configured universe at the call site).
        start: Inclusive window start (tz-aware IST).
        end: Inclusive window end (tz-aware IST).

    Returns:
        A :class:`BackfillCheck` with the report and the list of symbols that returned no bars.
    """
    bars_by_symbol = {symbol: repository.read_bars(symbol, start, end) for symbol in symbols}
    report = create_data_quality_dashboard(config).assess(bars_by_symbol, start=start, end=end)
    empty = tuple(s.symbol for s in report.symbols if s.coverage.observed_bars == 0)
    return BackfillCheck(report=report, empty_symbols=empty)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``check_backfill`` argument parser (mirrors the backfill's range/tier flags)."""
    parser = argparse.ArgumentParser(
        prog="check_backfill",
        description="Read a backfill back from storage and report its data quality (P1.5/P1.9).",
    )
    parser.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD (IST)")
    parser.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD (IST)")
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="symbols to check (default: the universe)"
    )
    parser.add_argument(
        "--tier", choices=("parquet", "arctic", "redis"), default=DEFAULT_TIER, help="storage tier"
    )
    parser.add_argument("--env", default=None, help="config environment (dev | paper | live)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    repository_factory: RepositoryFactory = build_repository,
) -> int:
    """Run the post-backfill check; return a process exit code (``0`` = every symbol has data).

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
        environ: Environment mapping for config (injected in tests).
        repository_factory: Builds the repository (injected in tests with a fake).

    Returns:
        ``0`` if every symbol has data; ``1`` if any symbol came back empty.
    """
    args = _build_arg_parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    config = load_config(env=args.env, environ=environ)
    configure_logging(config)
    start = parse_ist_date(args.start, end=False)
    end = parse_ist_date(args.end, end=True)
    symbols = resolve_symbols(args.symbols, environ=environ)

    check = check_backfill(
        config, repository_factory(config, args.tier), symbols, start=start, end=end
    )
    for symbol in check.report.symbols:
        _logger.info(
            "symbol quality",
            extra={
                "symbol": symbol.symbol,
                "observed_sessions": symbol.coverage.observed_sessions,
                "expected_sessions": symbol.coverage.expected_sessions,
                "observed_bars": symbol.coverage.observed_bars,
                "intraday_gaps": symbol.intraday_gaps,
                "missing_days": symbol.missing_days,
                "bad_ticks": symbol.bad_ticks,
            },
        )
    if not check.ok:
        _logger.error(
            f"backfill check FAILED — {check.report.render()}",
            extra={"empty_symbols": list(check.empty_symbols)},
        )
        return 1
    _logger.info(f"backfill check PASSED — every symbol has data; {check.report.render()}")
    return 0
