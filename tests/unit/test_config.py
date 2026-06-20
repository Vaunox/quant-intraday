"""Tests for the layered configuration loader (P0.2)."""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from quant.core.config import (
    VALID_ENVS,
    Config,
    ConfigError,
    load_config,
    load_universe,
)

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"

# Secret-like keys must never appear in committed config files.
_SECRET_TOKENS = (
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "access_token",
    "private_key",
)


@pytest.fixture
def config_tree(tmp_path: Path) -> Path:
    """A writable copy of the real config dir, for hermetic mutation tests."""
    destination = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, destination)
    return destination


# --- shipped config is valid -------------------------------------------------


@pytest.mark.parametrize("env", VALID_ENVS)
def test_shipped_config_validates_for_each_env(env: str) -> None:
    cfg = load_config(env=env, environ={})
    assert isinstance(cfg, Config)
    assert cfg.environment == env
    assert cfg.project.name == "quant-intraday"
    assert cfg.market.decision_frequency_minutes == 15
    assert cfg.execution.max_orders_per_second <= 10  # SEBI ceiling


# --- environment selection ---------------------------------------------------


def test_default_env_is_dev_when_unset() -> None:
    assert load_config(environ={}).environment == "dev"


def test_env_selected_via_quant_env_var() -> None:
    cfg = load_config(environ={"QUANT_ENV": "paper"})
    assert cfg.environment == "paper"
    assert cfg.storage.redis_url.endswith("/1")  # from paper.yaml


def test_unknown_env_raises() -> None:
    with pytest.raises(ConfigError, match="Unknown environment"):
        load_config(env="prod", environ={})


# --- storage tiers (P1.3) ----------------------------------------------------


def test_storage_tier_config_loads() -> None:
    storage = load_config(environ={}).storage
    assert storage.parquet_path == "data/parquet"
    assert storage.arctic_uri.startswith("lmdb://")
    assert storage.arctic_library == "bars"
    assert storage.redis_key_prefix == "quant"
    assert storage.live_max_bars_per_symbol == 1000
    assert storage.live_ttl_seconds == 0


def test_storage_rejects_non_positive_window(config_tree: Path) -> None:
    base = config_tree / "default.yaml"
    data = yaml.safe_load(base.read_text())
    data["storage"]["live_max_bars_per_symbol"] = 0  # must be > 0
    base.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError):
        load_config(env="dev", config_dir=config_tree, environ={})


# --- ingest / backfill (P1.4) ------------------------------------------------


def test_ingest_config_loads() -> None:
    ingest = load_config(environ={}).ingest
    assert ingest.backfill_chunk_days == 60  # Kite minute-candle request cap
    assert ingest.backfill_interval == "minute"
    assert ingest.backfill_checkpoint_file == "backfill_checkpoint.json"


def test_ingest_rejects_non_positive_chunk_days() -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"QUANT__ingest__backfill_chunk_days": "0"})  # must be > 0


# --- hygiene (P1.5) ----------------------------------------------------------


def test_hygiene_config_loads() -> None:
    assert load_config(environ={}).hygiene.bad_tick_max_move_pct == 20.0


def test_hygiene_rejects_non_positive_move_threshold() -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"QUANT__hygiene__bad_tick_max_move_pct": "0"})  # must be > 0


# --- features (P1.6) ---------------------------------------------------------


def test_features_config_loads() -> None:
    features = load_config(environ={}).features
    assert features.return_horizons == (1, 3, 5, 15, 30, 60)
    assert features.volatility_window == 15
    assert features.feature_set_version == "core-v1"


def test_features_rejects_non_positive_horizon(config_tree: Path) -> None:
    base = config_tree / "default.yaml"
    data = yaml.safe_load(base.read_text())
    data["features"]["return_horizons"] = [1, 0, 5]  # 0 is invalid
    base.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError):
        load_config(env="dev", config_dir=config_tree, environ={})


# --- layered merge (default <- env file) -------------------------------------


def test_env_file_overrides_base() -> None:
    cfg = load_config(env="dev", environ={})
    assert cfg.logging.level == "DEBUG"  # dev.yaml overrides INFO
    assert cfg.logging.format == "text"


def test_deep_merge_preserves_unoverridden_siblings() -> None:
    cfg = load_config(env="live", environ={})
    assert cfg.risk.max_daily_loss_pct == 1.5  # live.yaml override
    assert cfg.risk.max_drawdown_pct == 15.0  # base value preserved by deep merge


# --- env-var overrides (highest precedence) ----------------------------------


def test_env_var_override_coerced_to_type() -> None:
    cfg = load_config(env="dev", environ={"QUANT__risk__max_positions": "3"})
    assert cfg.risk.max_positions == 3


def test_env_var_override_beats_env_file() -> None:
    cfg = load_config(env="dev", environ={"QUANT__logging__level": "WARNING"})
    assert cfg.logging.level == "WARNING"  # beats dev.yaml's DEBUG


def test_malformed_override_is_ignored() -> None:
    # Trailing separator -> malformed path -> skipped rather than guessed.
    cfg = load_config(env="dev", environ={"QUANT__risk__": "x"})
    assert cfg.risk.max_positions == 10


# --- validation / fail-loud --------------------------------------------------


def test_ops_above_sebi_ceiling_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env="dev", environ={"QUANT__execution__max_orders_per_second": "11"})


def test_slippage_min_above_max_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env="dev", environ={"QUANT__slippage__min_bps": "50"})


def test_unknown_key_rejected(config_tree: Path) -> None:
    default = config_tree / "default.yaml"
    default.write_text(default.read_text(encoding="utf-8") + "\nbogus_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(env="dev", config_dir=config_tree, environ={})


def test_missing_config_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(env="dev", config_dir=tmp_path / "nope", environ={})


# --- immutability ------------------------------------------------------------


def test_config_is_immutable() -> None:
    cfg = load_config(env="dev", environ={})
    with pytest.raises(ValidationError):
        cfg.market.depth_levels = 3


# --- universe ----------------------------------------------------------------


def test_universe_loads_and_validates() -> None:
    universe = load_universe(environ={})
    assert len(universe.instruments) >= 1
    assert universe.eligibility.exclude_esm_t2t is True
    assert "RELIANCE" in {instrument.symbol for instrument in universe.instruments}


# --- secrets never live in config files --------------------------------------


def _all_keys(node: object) -> list[str]:
    """Recursively collect every mapping key in a parsed YAML document."""
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_all_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_all_keys(item))
    return keys


def test_no_secret_like_keys_in_config_files() -> None:
    # Check keys only (YAML parsing drops comments), so policy comments mentioning
    # "secrets" don't trip this; what we forbid is a config key that *holds* a secret.
    for path in REPO_CONFIG.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in _all_keys(data):
            lowered = key.lower()
            for token in _SECRET_TOKENS:
                assert token not in lowered, f"{path} defines a secret-like key: {key!r}"


# --- additional fail-loud / edge paths ---------------------------------------


def test_invalid_square_off_time_rejected() -> None:
    with pytest.raises(ConfigError):
        load_config(env="dev", environ={"QUANT__execution__self_square_off_time": "25:99"})


def test_non_mapping_yaml_rejected(config_tree: Path) -> None:
    (config_tree / "default.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(env="dev", config_dir=config_tree, environ={})


def test_empty_env_file_falls_back_to_base(config_tree: Path) -> None:
    (config_tree / "env" / "dev.yaml").write_text("", encoding="utf-8")
    cfg = load_config(env="dev", config_dir=config_tree, environ={})
    assert cfg.logging.level == "INFO"  # base value, since the dev override is now empty


def test_missing_env_file_uses_base_only(config_tree: Path) -> None:
    (config_tree / "env" / "paper.yaml").unlink()
    cfg = load_config(env="paper", config_dir=config_tree, environ={})
    assert cfg.storage.redis_url.endswith("/0")  # base value, paper override removed


def test_invalid_universe_rejected(config_tree: Path) -> None:
    (config_tree / "universe.yaml").write_text(
        "eligibility:\n"
        "  min_adv_inr: 1.0\n"
        "  max_spread_bps: 1.0\n"
        "  exclude_esm_t2t: true\n"
        "instruments: []\n",  # empty -> violates min_length=1
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_universe(config_dir=config_tree, environ={})


def test_config_dir_env_var_override(config_tree: Path) -> None:
    cfg = load_config(env="dev", environ={"QUANT_CONFIG_DIR": str(config_tree)})
    assert cfg.project.name == "quant-intraday"
