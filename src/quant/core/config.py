"""Layered, typed, validated configuration loader.

Loading order (lowest to highest precedence):

1. ``config/default.yaml`` - the base.
2. ``config/env/<env>.yaml`` - the environment override (``dev`` | ``paper`` | ``live``),
   selected by the ``env`` argument or the ``QUANT_ENV`` environment variable.
3. ``QUANT__<section>__<key>`` environment variables - scalar overrides, highest
   precedence (e.g. ``QUANT__execution__max_orders_per_second=8``).

The merged mapping is validated into the immutable :class:`Config` model, so callers
get typed attribute access (``config.execution.max_orders_per_second``) and invalid
configuration fails loudly at load time rather than deep inside a trading decision.

Secrets are deliberately NOT handled here - they never live in config files. Use
:mod:`quant.core.secrets` for credentials.

Everything is dependency-injectable (``config_dir``, ``environ``) so it is fully
unit-testable without touching the real filesystem or process environment.
"""

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

#: Environment variable that selects the active environment.
ENV_SELECT_VAR = "QUANT_ENV"
#: Environment variable that overrides the config directory location.
CONFIG_DIR_VAR = "QUANT_CONFIG_DIR"
#: Prefix marking a config-override environment variable. The remainder is a
#: ``__``-delimited path into the config tree (e.g. ``QUANT__risk__max_positions``).
ENV_OVERRIDE_PREFIX = "QUANT__"
#: Default environment when none is specified.
DEFAULT_ENV = "dev"
#: The valid environments.
VALID_ENVS: tuple[str, ...] = ("dev", "paper", "live")

EnvName = Literal["dev", "paper", "live"]


class ConfigError(RuntimeError):
    """Raised when configuration cannot be located, parsed, or validated."""


class _Section(BaseModel):
    """Base for all config sections: immutable and strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectConfig(_Section):
    """Top-level project identity."""

    name: str
    base_currency: str = "INR"


class MarketConfig(_Section):
    """What and how often we trade."""

    exchange: str
    segment: str
    product: str
    decision_frequency_minutes: int = Field(gt=0)
    bar_interval_minutes: int = Field(gt=0)
    depth_levels: int = Field(gt=0, le=20)


class BrokerRateLimits(_Section):
    """Broker REST/throughput limits."""

    data_requests_per_second: int = Field(gt=0)
    # Hard SEBI ceiling for a sub-10-OPS personal user; never exceed 10.
    order_requests_per_second: int = Field(gt=0, le=10)
    max_orders_per_day: int = Field(gt=0)


class BrokerWebsocket(_Section):
    """Broker streaming limits, mode, and connection-resilience tuning."""

    mode: Literal["ltp", "quote", "full"]
    max_instruments_per_connection: int = Field(gt=0)
    max_connections: int = Field(gt=0)
    # Auto-reconnect/backoff (handed to the SDK's exponential-backoff reconnect).
    reconnect_max_tries: int = Field(default=50, gt=0)
    reconnect_max_delay_seconds: int = Field(default=60, ge=5)  # SDK floor is 5s
    connect_timeout_seconds: int = Field(default=30, gt=0)
    # Feed-staleness watchdog: warn if no ticks arrive for this long while connected.
    stale_timeout_seconds: float = Field(default=60.0, gt=0)


class BrokerConfig(_Section):
    """Broker connectivity (endpoints + limits). No secrets here."""

    name: str
    api_base_url: str
    login_url: str
    rate_limits: BrokerRateLimits
    websocket: BrokerWebsocket


class ExecutionConfig(_Section):
    """Order-placement behaviour and compliance throttles."""

    order_type_preference: str
    market_protection_percent: float = Field(ge=0)
    # Self-throttle ceiling; capped at the 10-OPS SEBI limit.
    max_orders_per_second: int = Field(gt=0, le=10)
    max_modifications_per_order: int = Field(gt=0)
    max_slices: int = Field(gt=0, le=10)
    iceberg_min_value_inr: float = Field(gt=0)
    self_square_off_time: str

    @field_validator("self_square_off_time")
    @classmethod
    def _validate_hh_mm(cls, value: str) -> str:
        """Ensure the square-off time is a valid ``HH:MM`` string."""
        try:
            # A wall-clock time-of-day, not an instant, so no timezone is involved.
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError(f"must be 'HH:MM', got {value!r}") from exc
        return value


class CostConfig(_Section):
    """Indian transaction-cost model rates (fractions of turnover unless noted)."""

    brokerage_rate: float = Field(ge=0)
    brokerage_cap_inr: float = Field(ge=0)
    stt_sell_rate: float = Field(ge=0)
    exchange_txn_rate: float = Field(ge=0)
    stamp_duty_buy_rate: float = Field(ge=0)
    gst_rate: float = Field(ge=0)
    sebi_charges_rate: float = Field(ge=0)


class SlippageConfig(_Section):
    """Slippage model bounds (basis points)."""

    model: str
    min_bps: float = Field(ge=0)
    max_bps: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "SlippageConfig":
        """min_bps must not exceed max_bps."""
        if self.min_bps > self.max_bps:
            raise ValueError("slippage.min_bps must be <= slippage.max_bps")
        return self


class RiskConfig(_Section):
    """Hard risk limits (consumed by the un-overridable risk engine, P3.1)."""

    max_daily_loss_pct: float = Field(gt=0)
    max_drawdown_pct: float = Field(gt=0)
    risk_per_trade_pct: float = Field(gt=0)
    max_position_pct: float = Field(gt=0)
    # India MIS allows up to ~5x; v1 default is 1.0 (no leverage).
    max_gross_exposure: float = Field(gt=0, le=5)
    max_positions: int = Field(gt=0)
    consecutive_loss_limit: int = Field(gt=0)


class SizingConfig(_Section):
    """Position-sizing parameters."""

    vol_target_annual_pct: float = Field(gt=0)
    kelly_fraction: float = Field(gt=0, le=1)
    max_position_leverage: float = Field(gt=0, le=5)


class PortfolioConfig(_Section):
    """Portfolio construction method and constraints."""

    method: Literal["equal_weight", "inverse_vol", "hrp"]
    no_trade_band_pct: float = Field(ge=0)
    max_weight_per_name_pct: float = Field(gt=0)
    sector_cap_pct: float = Field(gt=0)


class StorageConfig(_Section):
    """Storage tier locations and tuning (Layer 1, P1.3).

    Three tiers behind the ``Repository`` interface: an immutable Parquet raw archive
    (cold), a versioned ArcticDB research store (warm), and a Redis hot/live store.
    """

    data_root: str
    parquet_path: str
    arctic_uri: str
    arctic_library: str = "bars"  # ArcticDB library name for the bars dataset
    redis_url: str
    redis_key_prefix: str = "quant"  # namespaces this system's keys in a shared Redis
    # Hot-tier rolling window: the live store keeps only the most recent N bars per
    # symbol (a bounded, fast cache for live decisions), trimming older ones on write.
    live_max_bars_per_symbol: int = Field(default=1000, gt=0)
    # Optional Redis TTL on each symbol's key (seconds); 0 disables time-based expiry
    # and retention is by count only.
    live_ttl_seconds: int = Field(default=0, ge=0)


class IngestConfig(_Section):
    """Historical-backfill ingestion parameters (Layer 1, P1.4).

    The backfill paginates history into ``backfill_chunk_days``-wide windows because
    the broker caps the date span of a single historical request (~60 days for minute
    candles; Deep Dive #1 §0.2). The window is configuration, not a literal, because
    that cap differs by interval and broker (Ground Rule 2) — tune it down if a coarser
    cap is hit, never hard-code it in the job.
    """

    # Inclusive calendar-day span fetched per paginated request (must clear the
    # broker's per-request cap; 60 is Kite's minute-candle limit).
    backfill_chunk_days: int = Field(gt=0)
    # Candle interval to backfill (the research substrate; e.g. ``minute``). The broker
    # adapter is the authority on valid intervals, so this stays a free string here.
    backfill_interval: str
    # Resume-state filename, resolved relative to ``storage.data_root`` by the job.
    backfill_checkpoint_file: str = "backfill_checkpoint.json"


class HygieneConfig(_Section):
    """Data-hygiene thresholds (Layer 1 hygiene, P1.5).

    Liquidity/eligibility thresholds live with the universe (``UniverseEligibility``);
    this section holds the cross-cutting hygiene knobs not tied to the universe file.
    """

    # A bar whose close moves more than this percent from the previous valid bar is
    # flagged as a bad tick: beyond the widest NSE circuit band (~20%), an intraday
    # jump is almost certainly an erroneous print, not a real move.
    bad_tick_max_move_pct: float = Field(gt=0)


class LoggingConfig(_Section):
    """Logging configuration (the logger itself is wired up in P0.3)."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    format: Literal["json", "text"]
    timezone: str


class Config(_Section):
    """The fully-merged, validated system configuration (immutable)."""

    environment: EnvName
    project: ProjectConfig
    market: MarketConfig
    broker: BrokerConfig
    execution: ExecutionConfig
    costs: CostConfig
    slippage: SlippageConfig
    risk: RiskConfig
    sizing: SizingConfig
    portfolio: PortfolioConfig
    storage: StorageConfig
    ingest: IngestConfig
    hygiene: HygieneConfig
    logging: LoggingConfig


class Instrument(_Section):
    """A single tradable instrument in the universe."""

    symbol: str
    exchange: str = "NSE"
    name: str | None = None
    sector: str | None = None


class UniverseEligibility(_Section):
    """Liquidity/eligibility thresholds applied when refreshing the universe."""

    min_adv_inr: float = Field(gt=0)
    max_spread_bps: float = Field(gt=0)
    exclude_esm_t2t: bool = True


class Universe(_Section):
    """The tradable universe definition."""

    eligibility: UniverseEligibility
    instruments: tuple[Instrument, ...] = Field(min_length=1)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file that must contain a top-level mapping.

    Args:
        path: File to read.

    Returns:
        The parsed mapping (an empty file yields ``{}``).

    Raises:
        ConfigError: If the file is missing or its top level is not a mapping.
    """
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} must contain a mapping at the top level, got {type(data).__name__}"
        )
    return data


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` (override wins; lists are replaced)."""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(value, Mapping) and isinstance(existing, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _env_overrides(environ: Mapping[str, str], prefix: str = ENV_OVERRIDE_PREFIX) -> dict[str, Any]:
    """Build a nested override mapping from ``QUANT__section__key`` variables.

    The remainder after the prefix is lower-cased and split on ``__`` to form the
    path into the config tree. Values stay as strings; the schema coerces them.
    """
    overrides: dict[str, Any] = {}
    for raw_key, raw_value in environ.items():
        if not raw_key.startswith(prefix):
            continue
        path = raw_key[len(prefix) :].lower().split("__")
        if any(segment == "" for segment in path):
            continue  # malformed (e.g. trailing/double separator); skip rather than guess
        cursor = overrides
        for segment in path[:-1]:
            nxt = cursor.get(segment)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[segment] = nxt
            cursor = nxt
        cursor[path[-1]] = raw_value
    return overrides


def discover_config_dir(environ: Mapping[str, str]) -> Path:
    """Locate the config directory.

    Honours ``QUANT_CONFIG_DIR`` if set, otherwise walks up from this file until a
    directory containing ``config/default.yaml`` is found (works for the editable
    install during development).

    Raises:
        ConfigError: If no config directory can be found.
    """
    override = environ.get(CONFIG_DIR_VAR)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / "config" / "default.yaml").is_file():
            return parent / "config"
    raise ConfigError(f"Could not locate the config directory; set {CONFIG_DIR_VAR} to its path.")


def _resolve_env(env: str | None, environ: Mapping[str, str]) -> EnvName:
    """Resolve and validate the active environment name."""
    resolved = env or environ.get(ENV_SELECT_VAR) or DEFAULT_ENV
    if resolved not in VALID_ENVS:
        raise ConfigError(
            f"Unknown environment {resolved!r}; expected one of {', '.join(VALID_ENVS)}."
        )
    return resolved  # type: ignore[return-value]  # membership checked against VALID_ENVS


def load_config(
    env: str | None = None,
    config_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Load and validate the layered configuration.

    Args:
        env: Environment to load (``dev`` | ``paper`` | ``live``). Defaults to
            ``$QUANT_ENV`` then :data:`DEFAULT_ENV`.
        config_dir: Directory holding ``default.yaml`` and ``env/``. Defaults to
            ``$QUANT_CONFIG_DIR`` then auto-discovery.
        environ: Environment mapping (injected for tests). Defaults to ``os.environ``.

    Returns:
        The immutable, validated :class:`Config`.

    Raises:
        ConfigError: If config cannot be located, parsed, or validated.
    """
    environ = os.environ if environ is None else environ
    resolved_env = _resolve_env(env, environ)
    directory = Path(config_dir) if config_dir is not None else discover_config_dir(environ)

    merged = _load_yaml_mapping(directory / "default.yaml")
    env_path = directory / "env" / f"{resolved_env}.yaml"
    if env_path.is_file():
        merged = _deep_merge(merged, _load_yaml_mapping(env_path))
    merged = _deep_merge(merged, _env_overrides(environ))
    # The active environment is authoritative regardless of file contents.
    merged["environment"] = resolved_env

    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration for env {resolved_env!r}:\n{exc}") from exc


def load_universe(
    config_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Universe:
    """Load and validate the tradable universe from ``universe.yaml``.

    Args:
        config_dir: Directory holding ``universe.yaml``. Defaults to discovery.
        environ: Environment mapping (injected for tests). Defaults to ``os.environ``.

    Returns:
        The immutable, validated :class:`Universe`.

    Raises:
        ConfigError: If the universe file cannot be located, parsed, or validated.
    """
    environ = os.environ if environ is None else environ
    directory = Path(config_dir) if config_dir is not None else discover_config_dir(environ)
    data = _load_yaml_mapping(directory / "universe.yaml")
    try:
        return Universe.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid universe definition:\n{exc}") from exc
