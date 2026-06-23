"""Tests for the P2A.1 read-only Kite credential verification (`verify.py`).

Exercises the pure logic against a fake client (no SDK, no network): the result carries only
the api_key's last 4 chars and the instrument count (never the full key), a missing credential
fails loud, and `main` returns the right exit code with deps injected.
"""

import pytest

from quant.core.secrets import EnvSecrets, MissingSecretError
from quant.data.brokers.verify import VerificationResult, main, verify_credentials
from tests.unit.brokers_fakes import FakeKiteClient

_API_KEY = "abcdef0123456789"  # 16 chars, the shape of a real Kite api_key
_API_SECRET = "s" * 32


def _env(**overrides: str) -> dict[str, str]:
    base = {"QUANT_SECRET_KITE_API_KEY": _API_KEY, "QUANT_SECRET_KITE_API_SECRET": _API_SECRET}
    base.update(overrides)
    return base


def test_verify_credentials_returns_suffix_and_count() -> None:
    client = FakeKiteClient()
    result = verify_credentials(EnvSecrets(environ=_env()), lambda _key: client, exchange="NSE")
    assert isinstance(result, VerificationResult)
    assert result.api_key_suffix == "6789"  # last 4 of _API_KEY
    assert result.instrument_count == 2  # FakeKiteClient's sample dump (RELIANCE, INFY)
    assert client.instruments_calls == ["NSE"]  # exactly one read-only call, for the exchange


def test_verify_credentials_never_exposes_the_full_key() -> None:
    result = verify_credentials(EnvSecrets(environ=_env()), lambda _key: FakeKiteClient())
    assert len(result.api_key_suffix) == 4
    assert _API_KEY not in result.api_key_suffix


def test_verify_credentials_requires_the_secret_present() -> None:
    # api_key present but api_secret missing: the presence check must fail loud.
    secrets = EnvSecrets(environ={"QUANT_SECRET_KITE_API_KEY": _API_KEY})
    with pytest.raises(MissingSecretError):
        verify_credentials(secrets, lambda _key: FakeKiteClient())


def test_main_passes_with_both_credentials_present() -> None:
    assert main(environ=_env(), client_factory=lambda _key: FakeKiteClient()) == 0


def test_main_fails_when_a_credential_is_missing() -> None:
    environ = {"QUANT_SECRET_KITE_API_KEY": _API_KEY}  # no api_secret
    assert main(environ=environ, client_factory=lambda _key: FakeKiteClient()) == 1
