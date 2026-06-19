"""Tests for the Kite session auth flow and token store (P1.1)."""

import pytest

from quant.core.secrets import EnvSecrets, MissingSecretError
from quant.data.brokers.auth import (
    KITE_API_SECRET_SECRET,
    InMemoryTokenStore,
    KiteAuthenticator,
    TokenStore,
)
from quant.data.brokers.errors import SessionNotSeededError
from tests.unit.brokers_fakes import FakeKiteClient


def _secrets(**env: str) -> EnvSecrets:
    return EnvSecrets(environ=env)


def test_in_memory_token_store_roundtrip() -> None:
    store: TokenStore = InMemoryTokenStore()
    assert isinstance(store, TokenStore)
    assert store.get_access_token() is None
    store.set_access_token("abc")
    assert store.get_access_token() == "abc"
    store.clear()
    assert store.get_access_token() is None


def test_default_secret_name_matches_env_convention() -> None:
    # Resolves to QUANT_SECRET_KITE_API_SECRET via the secrets interface.
    assert KITE_API_SECRET_SECRET == "kite_api_secret"
    assert EnvSecrets().env_var_name(KITE_API_SECRET_SECRET) == "QUANT_SECRET_KITE_API_SECRET"


def test_login_url_delegates_to_client() -> None:
    client = FakeKiteClient(login_url="https://login.example/connect")
    auth = KiteAuthenticator(client, _secrets(), InMemoryTokenStore())
    assert auth.login_url() == "https://login.example/connect"


def test_seed_session_exchanges_and_stores_token() -> None:
    client = FakeKiteClient(session={"access_token": "tok-123", "user_id": "AB1234"})
    store = InMemoryTokenStore()
    auth = KiteAuthenticator(client, _secrets(QUANT_SECRET_KITE_API_SECRET="s3cr3t"), store)

    assert not auth.is_seeded()
    auth.seed_session("req-token-xyz")

    assert auth.is_seeded()
    assert auth.access_token() == "tok-123"
    assert store.get_access_token() == "tok-123"
    assert client.access_token == "tok-123"  # also set on the client for immediate use
    # The api_secret was read from secrets and passed to the SDK exchange.
    assert client.generate_session_calls == [("req-token-xyz", "s3cr3t")]


def test_access_token_before_seed_raises() -> None:
    auth = KiteAuthenticator(FakeKiteClient(), _secrets(), InMemoryTokenStore())
    with pytest.raises(SessionNotSeededError):
        auth.access_token()


def test_seed_session_missing_secret_raises() -> None:
    auth = KiteAuthenticator(FakeKiteClient(), _secrets(), InMemoryTokenStore())  # no secret set
    with pytest.raises(MissingSecretError):
        auth.seed_session("req-token")


def test_seed_session_never_logs_secrets(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeKiteClient(session={"access_token": "super-secret-token", "user_id": "AB1234"})
    auth = KiteAuthenticator(
        client, _secrets(QUANT_SECRET_KITE_API_SECRET="my-api-secret"), InMemoryTokenStore()
    )
    with caplog.at_level("INFO"):
        auth.seed_session("req-token")
    blob = " ".join(record.getMessage() for record in caplog.records)
    blob += " " + " ".join(str(record.__dict__) for record in caplog.records)
    assert "super-secret-token" not in blob
    assert "my-api-secret" not in blob
