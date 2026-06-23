"""Tests for the P2A.2 daily morning-auth seed (`morning_auth.py`).

Exercises the seed against a fake client (no SDK, no network) with a temp file-backed secret
store: the freshly-issued access token is persisted to the secrets interface, only its last 4
chars are surfaced, the request_token + api_secret reach the SDK exchange, and `main` returns
the right exit code (including a missing-credential failure).
"""

from pathlib import Path

from quant.core.secrets import EnvSecrets, FileSecretStore
from quant.data.brokers.auth import KITE_ACCESS_TOKEN_SECRET
from quant.data.brokers.morning_auth import main, seed_and_persist
from tests.unit.brokers_fakes import FakeKiteClient

_API_KEY = "abcdef0123456789"
_API_SECRET = "s" * 32


def _secrets(tmp_path: Path, **env: str) -> EnvSecrets:
    base = {"QUANT_SECRET_KITE_API_KEY": _API_KEY, "QUANT_SECRET_KITE_API_SECRET": _API_SECRET}
    base.update(env)
    return EnvSecrets(environ=base, file_store=FileSecretStore(tmp_path / "secrets.json"))


def test_seed_and_persist_writes_token_and_returns_suffix(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    client = FakeKiteClient()  # canned session access_token = "access-token-xyz"
    suffix = seed_and_persist(secrets, lambda _key: client, lambda _url: "req-token-123")
    assert suffix == "-xyz"  # last 4 of "access-token-xyz"
    assert secrets.get(KITE_ACCESS_TOKEN_SECRET) == "access-token-xyz"  # persisted, readable back
    # The pasted request_token + the api_secret (from the secrets interface) drove the exchange.
    assert client.generate_session_calls == [("req-token-123", _API_SECRET)]


def test_seed_passes_the_client_login_url_to_the_provider(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def provider(login_url: str) -> str:
        captured["url"] = login_url
        return "req-token"

    seed_and_persist(_secrets(tmp_path), lambda _key: FakeKiteClient(), provider)
    assert "api_key=fake" in captured["url"]  # FakeKiteClient.login_url default


def test_main_returns_zero_and_persists_the_token(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    rc = main(
        secrets=secrets,
        client_factory=lambda _key: FakeKiteClient(),
        request_token_provider=lambda _url: "req-token",
    )
    assert rc == 0
    assert secrets.get(KITE_ACCESS_TOKEN_SECRET) == "access-token-xyz"


def test_main_returns_one_when_api_secret_missing(tmp_path: Path) -> None:
    # api_key present, api_secret absent from both env and the (empty) file store.
    secrets = EnvSecrets(
        environ={"QUANT_SECRET_KITE_API_KEY": _API_KEY},
        file_store=FileSecretStore(tmp_path / "secrets.json"),
    )
    rc = main(
        secrets=secrets,
        client_factory=lambda _key: FakeKiteClient(),
        request_token_provider=lambda _url: "req-token",
    )
    assert rc == 1
