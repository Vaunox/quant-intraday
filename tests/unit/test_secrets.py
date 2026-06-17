"""Tests for the secrets interface (P0.2)."""

import pytest

from quant.core.secrets import EnvSecrets, MissingSecretError, Secrets


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
