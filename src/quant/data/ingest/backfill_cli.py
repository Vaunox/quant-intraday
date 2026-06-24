r"""Command-line wiring for the historical backfill (``scripts/run_backfill.py``).

Keeps the runnable orchestration in the importable package (Ground Rule 3: production
logic lives in ``src/quant``; ``scripts/`` is a thin entry point), so the wiring is
unit-testable. The pure parts — argument parsing, date parsing, symbol resolution,
repository selection, and the :func:`main` orchestration — run under test with a fake
adapter; only :func:`build_adapter` (which constructs the live Kite SDK client and
hits the network) is operator-only and excluded from coverage.

Usage (operator, on the static-IP engine host after the morning session seed)::

    python scripts/run_backfill.py --start 2024-01-01 --end 2024-12-31 \
        --request-token <today's request_token> --tier parquet

``--symbols`` defaults to the configured universe; ``--interval`` / ``--chunk-days``
default to ``config.ingest``. The run is resumable: re-running skips symbols already
backfilled through ``--end`` (state lives in ``storage.data_root``).
"""

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from quant.core.config import Config, load_config, load_universe
from quant.core.interfaces import BrokerAdapter, Repository
from quant.core.logging import get_logger
from quant.core.secrets import Secrets, default_secrets
from quant.data.brokers.auth import (
    KITE_ACCESS_TOKEN_SECRET,
    KITE_API_KEY_SECRET,
    InMemoryTokenStore,
    KiteAuthenticator,
    TokenStore,
)
from quant.data.brokers.client import KiteClient, create_kite_client
from quant.data.brokers.errors import SessionNotSeededError
from quant.data.brokers.instruments import InstrumentRegistry
from quant.data.brokers.kite import KiteAdapter
from quant.data.brokers.rate_limit import TokenBucketRateLimiter
from quant.data.ingest.backfill import (
    BackfillJob,
    BackfillReport,
    JsonBackfillCheckpoint,
    day_end,
    day_start,
)
from quant.data.store.arctic import create_arctic_repository
from quant.data.store.parquet import create_parquet_archive
from quant.data.store.redis_store import create_redis_live_store

_logger = get_logger(__name__)

#: Storage tiers the backfill can target, mapped to their repository factories. The
#: default is ``parquet`` — the immutable raw archive is the backfill's canonical
#: destination (Deep Dive #1 §1.2: cold/immutable raw); the others are opt-in.
_TIERS = ("parquet", "arctic", "redis")
DEFAULT_TIER = "parquet"

#: Adapter factory signature — injected in tests so :func:`main` runs end-to-end
#: against a fake broker (the real one needs the SDK, credentials, and a network).
AdapterFactory = Callable[[Config, Secrets, str | None], BrokerAdapter]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``run_backfill`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="run_backfill",
        description="Paginated, resumable historical market-data backfill into storage.",
    )
    parser.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD (IST)")
    parser.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD (IST)")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="symbols to backfill (default: the configured universe)",
    )
    parser.add_argument("--interval", default=None, help="candle interval (default: config.ingest)")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=None,
        help="calendar days fetched per request (default: config.ingest)",
    )
    parser.add_argument(
        "--tier", choices=_TIERS, default=DEFAULT_TIER, help="destination storage tier"
    )
    parser.add_argument("--env", default=None, help="config environment (dev | paper | live)")
    parser.add_argument(
        "--request-token",
        default=None,
        help="today's Kite request_token, to seed the session for this run",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="resume-state file path (default: under storage.data_root)",
    )
    return parser


def parse_ist_date(value: str, *, end: bool) -> datetime:
    """Parse a ``YYYY-MM-DD`` string into an IST day boundary.

    ``end=False`` returns the start of the day (00:00); ``end=True`` returns the end of
    the day (23:59:59.999999) so the whole end date is included in the range.

    Raises:
        ValueError: If ``value`` is not an ISO date.
    """
    day = date.fromisoformat(value)
    return day_end(day) if end else day_start(day)


def resolve_symbols(
    symbols: Sequence[str] | None,
    *,
    config_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Return the symbols to backfill: the CLI list, or the configured universe."""
    if symbols:
        return list(symbols)
    universe = load_universe(config_dir=config_dir, environ=environ)
    return [instrument.symbol for instrument in universe.instruments]


def build_repository(config: Config, tier: str) -> Repository:
    """Construct the destination repository for ``tier`` from configuration.

    Raises:
        OptionalDependencyError: If the tier's backend (arcticdb/redis) is not installed.
        ValueError: If ``tier`` is not a known storage tier.
    """
    if tier == "parquet":
        return create_parquet_archive(config.storage)
    if tier == "arctic":
        return create_arctic_repository(config.storage)
    if tier == "redis":
        return create_redis_live_store(config.storage)
    raise ValueError(f"unknown storage tier {tier!r}; choose one of {', '.join(_TIERS)}")


def apply_session_token(
    client: KiteClient,
    token_store: TokenStore,
    secrets: Secrets,
    request_token: str | None,
) -> None:
    """Make today's access token available on ``client`` and ``token_store``.

    Two paths: if a ``request_token`` is given, run the OAuth exchange
    (:meth:`~quant.data.brokers.auth.KiteAuthenticator.seed_session`); otherwise load today's
    ``access_token`` from the secrets interface (``kite_access_token``, seeded by the P2A.2
    morning helper). This lets the backfill run off the daily-seeded token with no
    ``--request-token`` to paste each run.

    Raises:
        SessionNotSeededError: If neither a ``request_token`` nor a stored ``access_token`` is
            available.
    """
    if request_token:
        KiteAuthenticator(client, secrets, token_store).seed_session(request_token)
        return
    access_token = secrets.get_optional(KITE_ACCESS_TOKEN_SECRET)
    if access_token is None:
        raise SessionNotSeededError(
            "no Kite access token available: seed today's session with the morning helper "
            "(scripts/kite_morning_auth.py), or pass --request-token to seed inline"
        )
    client.set_access_token(access_token)
    token_store.set_access_token(access_token)


def build_adapter(
    config: Config, secrets: Secrets, request_token: str | None
) -> BrokerAdapter:  # pragma: no cover - constructs the live Kite SDK client + network calls
    """Construct a live :class:`KiteAdapter` (operator path; needs SDK + credentials).

    Builds the SDK client, applies today's session token (from ``request_token`` or the secrets
    interface via :func:`apply_session_token`), indexes the instruments dump, and wires the
    data-endpoint rate limiter. Excluded from coverage: it requires the live Kite Connect SDK,
    real credentials, and network access, none of which exist in CI. Tests inject a fake adapter
    via :func:`main` and cover the token logic via :func:`apply_session_token`.
    """
    api_key = secrets.get(KITE_API_KEY_SECRET)
    client = create_kite_client(api_key, root=config.broker.api_base_url)
    token_store = InMemoryTokenStore()
    apply_session_token(client, token_store, secrets, request_token)
    instruments = InstrumentRegistry.from_client(client, config.market.exchange)
    rate_limiter = TokenBucketRateLimiter(config.broker.rate_limits.data_requests_per_second)
    return KiteAdapter(
        client, token_store, instruments, rate_limiter, exchange=config.market.exchange
    )


def _checkpoint_path(config: Config, override: str | None) -> Path:
    """Resolve the resume-checkpoint path (CLI override, else under ``data_root``)."""
    if override:
        return Path(override)
    return Path(config.storage.data_root) / config.ingest.backfill_checkpoint_file


def _log_report(report: BackfillReport) -> None:
    """Emit a concise INFO/ERROR summary of the run."""
    for result in report.results:
        _logger.info(
            "backfill result",
            extra={
                "symbol": result.symbol,
                "bars_written": result.bars_written,
                "chunks_fetched": result.chunks_fetched,
                "already_complete": result.already_complete,
                "succeeded": result.succeeded,
            },
        )
    if not report.ok:
        _logger.error(
            "backfill completed with failures",
            extra={"failed": [result.symbol for result in report.failed]},
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    adapter_factory: AdapterFactory = build_adapter,
) -> int:
    """Run the backfill from CLI arguments; return a process exit code (0 = clean).

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
        environ: Environment mapping for config/secrets (injected in tests).
        adapter_factory: Builds the broker adapter (injected in tests with a fake).

    Returns:
        ``0`` if every symbol succeeded, ``1`` if any symbol failed.
    """
    args = build_arg_parser().parse_args(argv)
    environ = os.environ if environ is None else environ

    config = load_config(env=args.env, environ=environ)
    secrets = default_secrets(
        environ=environ
    )  # env vars + the file-backed store (kite_access_token)
    start = parse_ist_date(args.start, end=False)
    end = parse_ist_date(args.end, end=True)
    interval = args.interval or config.ingest.backfill_interval
    chunk_days = args.chunk_days or config.ingest.backfill_chunk_days
    symbols = resolve_symbols(args.symbols, environ=environ)

    repository = build_repository(config, args.tier)
    checkpoint = JsonBackfillCheckpoint(_checkpoint_path(config, args.checkpoint))
    adapter = adapter_factory(config, secrets, args.request_token)

    job = BackfillJob(adapter, repository, checkpoint, interval=interval, chunk_days=chunk_days)
    report = job.run(symbols, start, end)
    _log_report(report)
    return 0 if report.ok else 1
