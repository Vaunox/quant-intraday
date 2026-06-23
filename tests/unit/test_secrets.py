"""Tests for the secrets interface (P0.2; file-backed fallback added in P2A.2)."""

import sys
from pathlib import Path

import pytest

from quant.core.secrets import (
    EnvSecrets,
    FileSecretStore,
    MissingSecretError,
    Secrets,
    SecretStoreError,
    default_secrets,
)


def test_get_returns_value() -> None:
    secrets = EnvSecrets(environ={"QUANT_SECRET_KITE_API_KEY": "abc123"})
    assert secrets.get("KITE_API_KEY") == "abc123"


def test_logical_name_is_case_insensitive() -> None:
    secrets = EnvSecrets(environ={"QUANT_SECRET_KITE_API_KEY": "abc123"})
    assert secrets.get("kite_api_key") == "abc123"


def test_get_optional_returns_none_when_missing() -> None:
    assert EnvSecrets(environ={}).get_optional("NOPE") is None


def test_missing_secret_raises_clear_error_naming_env_var() -> None:
    secrets = EnvSecrets(environ={})
    with pytest.raises(MissingSecretError) as excinfo:
        secrets.get("KITE_API_SECRET")
    message = str(excinfo.value)
    assert "QUANT_SECRET_KITE_API_SECRET" in message  # tells the operator what to set


def test_empty_value_is_treated_as_missing() -> None:
    secrets = EnvSecrets(environ={"QUANT_SECRET_X": ""})
    assert secrets.get_optional("X") is None
    with pytest.raises(MissingSecretError):
        secrets.get("X")


def test_repr_does_not_leak_secret_values() -> None:
    secrets = EnvSecrets(environ={"QUANT_SECRET_KITE_API_SECRET": "supersecret"})
    assert "supersecret" not in repr(secrets)


def test_custom_prefix() -> None:
    secrets = EnvSecrets(prefix="MYAPP_", environ={"MYAPP_FOO": "bar"})
    assert secrets.get("FOO") == "bar"
    assert secrets.env_var_name("FOO") == "MYAPP_FOO"


def test_envsecrets_satisfies_protocol() -> None:
    assert isinstance(EnvSecrets(environ={}), Secrets)


# --------------------------------------------------------------------------- #
# File-backed fallback (P2A.2)
# --------------------------------------------------------------------------- #
def test_env_overrides_file_when_both_present(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("x", "from-file")
    secrets = EnvSecrets(environ={"QUANT_SECRET_X": "from-env"}, file_store=store)
    assert secrets.get("X") == "from-env"  # env always wins (prod/CI injection)


def test_falls_back_to_file_when_env_missing(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("x", "from-file")
    assert EnvSecrets(environ={}, file_store=store).get("X") == "from-file"


def test_set_through_envsecrets_round_trips_via_the_file(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / ".quant-intraday" / "secrets.json")
    secrets = EnvSecrets(environ={}, file_store=store)
    secrets.set("kite_access_token", "tok123")
    assert secrets.get("kite_access_token") == "tok123"
    assert store.path.exists()


def test_set_preserves_other_keys(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("a", "1")
    store.set("b", "2")
    assert (store.get("a"), store.get("b")) == ("1", "2")


def test_file_store_is_case_insensitive(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("KITE_ACCESS_TOKEN", "tok")
    assert store.get("kite_access_token") == "tok"


def test_empty_file_value_is_treated_as_missing(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("x", "")
    assert store.get("x") is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "absent" / "secrets.json")
    assert store.get("anything") is None
    assert EnvSecrets(environ={}, file_store=store).get_optional("anything") is None


def test_malformed_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(SecretStoreError, match="malformed"):
        FileSecretStore(path).get("x")


def test_non_object_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text('["a", "b"]', encoding="utf-8")
    with pytest.raises(SecretStoreError, match="JSON object"):
        FileSecretStore(path).get("x")


def test_set_without_file_store_raises() -> None:
    with pytest.raises(SecretStoreError, match="no writable secret store"):
        EnvSecrets(environ={}).set("x", "y")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file mode; Windows uses ACLs")
def test_set_creates_file_with_0600_permissions(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / ".quant-intraday" / "secrets.json")
    store.set("kite_access_token", "tok")
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_default_secrets_points_at_the_home_store() -> None:
    secrets = default_secrets()
    assert secrets.file_store is not None
    assert secrets.file_store.path == Path.home() / ".quant-intraday" / "secrets.json"


def test_missing_secret_error_names_both_sources_when_file_configured(tmp_path: Path) -> None:
    secrets = EnvSecrets(environ={}, file_store=FileSecretStore(tmp_path / "secrets.json"))
    with pytest.raises(MissingSecretError) as excinfo:
        secrets.get("kite_access_token")
    message = str(excinfo.value)
    assert "QUANT_SECRET_KITE_ACCESS_TOKEN" in message  # env var named
    assert "secrets.json" in message  # file store named
