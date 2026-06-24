"""Tests for the backfill CLI wiring (``scripts/run_backfill.py`` → backfill_cli).

The live ``build_adapter`` (Kite SDK + network) is operator-only and excluded from
coverage; everything else — arg/date parsing, symbol resolution, repository selection,
and the :func:`main` orchestration — is exercised here against a fake adapter and an
injected environment, so the whole runnable path is tested without credentials.
"""

from datetime import date
from pathlib import Path

import pytest

from quant.core.config import load_config
from quant.core.interfaces import Repository
from quant.core.secrets import EnvSecrets, FileSecretStore
from quant.data.brokers.auth import KITE_ACCESS_TOKEN_SECRET, InMemoryTokenStore
from quant.data.brokers.errors import SessionNotSeededError
from quant.data.ingest import backfill_cli
from quant.data.ingest.backfill import day_end, day_start
from quant.data.ingest.backfill_cli import (
    apply_session_token,
    build_arg_parser,
    build_repository,
    main,
    parse_ist_date,
    resolve_symbols,
)
from quant.data.store.parquet import ParquetArchive
from tests.unit.brokers_fakes import FakeKiteClient
from tests.unit.ingest_fakes import FakeHistoricalAdapter

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


def _environ(tmp_path: Path) -> dict[str, str]:
    """A hermetic environment: real config dir, storage redirected under ``tmp_path``."""
    return {
        "QUANT_CONFIG_DIR": str(REPO_CONFIG),
        "QUANT__storage__parquet_path": str(tmp_path / "pq"),
        "QUANT__storage__data_root": str(tmp_path),
    }


# ------------------------------------------------------------------ arg parsing


def test_arg_parser_defaults() -> None:
    args = build_arg_parser().parse_args(["--start", "2024-01-01", "--end", "2024-01-05"])
    assert args.start == "2024-01-01"
    assert args.symbols is None
    assert args.interval is None
    assert args.chunk_days is None
    assert args.tier == "parquet"


def test_arg_parser_requires_start_and_end() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--end", "2024-01-05"])


def test_arg_parser_rejects_unknown_tier() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(
            ["--start", "2024-01-01", "--end", "2024-01-05", "--tier", "questdb"]
        )


# ------------------------------------------------------------------ date parsing


def test_parse_ist_date_boundaries() -> None:
    assert parse_ist_date("2024-01-01", end=False) == day_start(date(2024, 1, 1))
    assert parse_ist_date("2024-01-01", end=True) == day_end(date(2024, 1, 1))


def test_parse_ist_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_ist_date("not-a-date", end=False)


# -------------------------------------------------------------- symbol resolving


def test_resolve_symbols_uses_explicit_list() -> None:
    assert resolve_symbols(["RELIANCE", "INFY"]) == ["RELIANCE", "INFY"]


def test_resolve_symbols_falls_back_to_universe() -> None:
    symbols = resolve_symbols(None, config_dir=REPO_CONFIG, environ={})
    assert "RELIANCE" in symbols
    assert len(symbols) >= 1


# -------------------------------------------------------------- repository build


def test_build_repository_parquet_is_real(tmp_path: Path) -> None:
    config = load_config(environ={})
    config = config.model_copy(
        update={"storage": config.storage.model_copy(update={"parquet_path": str(tmp_path / "pq")})}
    )
    repo = build_repository(config, "parquet")
    assert isinstance(repo, ParquetArchive)
    assert isinstance(repo, Repository)


def test_build_repository_routes_optional_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Route without depending on whether arcticdb/redis are installed: stub the factories
    # to return sentinels and assert each tier reaches the right one (identity, not ==,
    # so mypy doesn't object to a Repository-vs-sentinel comparison).
    config = load_config(environ={})
    arctic_sentinel = object()
    redis_sentinel = object()
    monkeypatch.setattr(backfill_cli, "create_arctic_repository", lambda storage: arctic_sentinel)
    monkeypatch.setattr(backfill_cli, "create_redis_live_store", lambda storage: redis_sentinel)
    assert build_repository(config, "arctic") is arctic_sentinel
    assert build_repository(config, "redis") is redis_sentinel


def test_build_repository_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown storage tier"):
        build_repository(load_config(environ={}), "questdb")


# --------------------------------------------------------------------- main()


def test_main_backfills_and_exits_clean(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=3)
    code = main(
        [
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-05",
            "--symbols",
            "RELIANCE",
            "HDFCBANK",
            "--chunk-days",
            "2",
            "--tier",
            "parquet",
            "--env",
            "dev",
        ],
        environ=_environ(tmp_path),
        adapter_factory=lambda config, secrets, request_token: adapter,
    )
    assert code == 0
    archive = ParquetArchive(tmp_path / "pq")
    assert sorted(archive.list_symbols()) == ["HDFCBANK", "RELIANCE"]
    assert (tmp_path / "backfill_checkpoint.json").is_file()


def test_main_defaults_interval_and_chunk_days_from_config(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=3)
    code = main(
        ["--start", "2024-01-01", "--end", "2024-01-05", "--symbols", "RELIANCE"],
        environ=_environ(tmp_path),
        adapter_factory=lambda config, secrets, request_token: adapter,
    )
    assert code == 0
    # Defaults from config.ingest: minute interval, 60-day chunk -> one request.
    assert adapter.calls[0]["interval"] == "minute"
    assert len(adapter.calls_for("RELIANCE")) == 1


def test_main_passes_request_token_to_factory(tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}

    def factory(
        config: object, secrets: object, request_token: str | None
    ) -> FakeHistoricalAdapter:
        seen["request_token"] = request_token
        return FakeHistoricalAdapter(bars_per_day=1)

    main(
        [
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-01",
            "--symbols",
            "RELIANCE",
            "--request-token",
            "RT-123",
        ],
        environ=_environ(tmp_path),
        adapter_factory=factory,
    )
    assert seen["request_token"] == "RT-123"


def test_main_returns_nonzero_on_failure(tmp_path: Path) -> None:
    failing = FakeHistoricalAdapter(bars_per_day=3, raise_on_symbol="HDFCBANK")
    code = main(
        ["--start", "2024-01-01", "--end", "2024-01-05", "--symbols", "RELIANCE", "HDFCBANK"],
        environ=_environ(tmp_path),
        adapter_factory=lambda config, secrets, request_token: failing,
    )
    assert code == 1


def test_main_uses_checkpoint_override(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=1)
    checkpoint = tmp_path / "custom" / "state.json"
    code = main(
        [
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-01",
            "--symbols",
            "RELIANCE",
            "--checkpoint",
            str(checkpoint),
        ],
        environ=_environ(tmp_path),
        adapter_factory=lambda config, secrets, request_token: adapter,
    )
    assert code == 0
    assert checkpoint.is_file()  # resume state written at the override path


# ------------------------------------------------- apply_session_token (P2A.3)
_API_SECRET = "s" * 32


def test_apply_session_token_seeds_from_request_token() -> None:
    client = FakeKiteClient()
    token_store = InMemoryTokenStore()
    secrets = EnvSecrets(environ={"QUANT_SECRET_KITE_API_SECRET": _API_SECRET})
    apply_session_token(client, token_store, secrets, "req-token")
    assert token_store.get_access_token() == "access-token-xyz"  # FakeKiteClient session
    assert client.access_token == "access-token-xyz"
    assert client.generate_session_calls == [("req-token", _API_SECRET)]


def test_apply_session_token_loads_from_secrets_when_no_request_token(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set(KITE_ACCESS_TOKEN_SECRET, "today-token")
    client = FakeKiteClient()
    token_store = InMemoryTokenStore()
    apply_session_token(client, token_store, EnvSecrets(environ={}, file_store=store), None)
    assert token_store.get_access_token() == "today-token"
    assert client.access_token == "today-token"
    assert client.generate_session_calls == []  # no OAuth exchange when the token is on file


def test_apply_session_token_raises_when_nothing_available(tmp_path: Path) -> None:
    secrets = EnvSecrets(environ={}, file_store=FileSecretStore(tmp_path / "secrets.json"))
    with pytest.raises(SessionNotSeededError, match="no Kite access token"):
        apply_session_token(FakeKiteClient(), InMemoryTokenStore(), secrets, None)
