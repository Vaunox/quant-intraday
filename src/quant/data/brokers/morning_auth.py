"""The daily Kite morning-auth seed (P2A.2 operator runbook helper).

Kite's ``access_token`` is flushed every morning and the exchange mandates a manual login
once per day (Inviolable Rule 6). This is the operator-facing wrapper around the already-built
:class:`~quant.data.brokers.auth.KiteAuthenticator`: it prints the login URL, takes the
one-time ``request_token`` the operator copies from the post-login redirect, exchanges it for a
fresh ``access_token`` (the SDK computes ``SHA-256(api_key + request_token + api_secret)`` -
which is where a wrong ``api_secret`` finally fails), and **persists the token to the secrets
interface** (``Secrets.set`` -> the file-backed store on the dev box; AWS Secrets Manager later)
so the engine/research read it back via the same interface.

Only the **last 4 characters** of the new token are logged (the safe visibility pattern shared
with the P2A.1 verifier) - never the token itself. The TOTP is **not** automated; manual entry
by the operator is the compliant path. Logic lives here (importable, unit-tested with a fake
client); ``scripts/kite_morning_auth.py`` is the thin shim (Ground Rule 3).
"""

import os
from collections.abc import Callable, Mapping

from quant.core.config import Config, load_config
from quant.core.logging import configure_logging, get_logger
from quant.core.secrets import MissingSecretError, Secrets, default_secrets
from quant.data.brokers.auth import (
    KITE_ACCESS_TOKEN_SECRET,
    KITE_API_KEY_SECRET,
    InMemoryTokenStore,
    KiteAuthenticator,
)
from quant.data.brokers.client import KiteClient, create_kite_client

_logger = get_logger(__name__)

#: Builds a Kite client from an ``api_key`` (injected so tests can supply a fake).
ClientFactory = Callable[[str], KiteClient]
#: Given the login URL, returns the operator's pasted ``request_token`` (injected in tests).
RequestTokenProvider = Callable[[str], str]


def seed_and_persist(
    secrets: Secrets,
    client_factory: ClientFactory,
    request_token_provider: RequestTokenProvider,
) -> str:
    """Run the manual seed and persist the fresh access token; return its last 4 chars.

    Reads ``api_key`` from ``secrets``, builds a client, gets the ``request_token`` from
    ``request_token_provider`` (the login URL is passed to it), exchanges it via
    :meth:`KiteAuthenticator.seed_session` (which reads ``api_secret`` from ``secrets`` and
    computes the checksum), then writes the resulting ``access_token`` to the secrets interface
    under :data:`KITE_ACCESS_TOKEN_SECRET`.

    Returns:
        The last 4 characters of the new access token (for safe logging/confirmation).

    Raises:
        MissingSecretError: If ``api_key``/``api_secret`` are absent from ``secrets``.
    """
    api_key = secrets.get(KITE_API_KEY_SECRET)
    authenticator = KiteAuthenticator(client_factory(api_key), secrets, InMemoryTokenStore())
    request_token = request_token_provider(authenticator.login_url())
    authenticator.seed_session(request_token)
    token = authenticator.access_token()
    secrets.set(KITE_ACCESS_TOKEN_SECRET, token)
    suffix = token[-4:]
    _logger.info(
        "kite session seeded",
        extra={"access_token_suffix": suffix, "secret_name": KITE_ACCESS_TOKEN_SECRET},
    )
    return suffix


def _interactive_request_token(login_url: str) -> str:  # pragma: no cover - interactive I/O
    """Print the login URL and read the operator's pasted ``request_token`` from stdin."""
    print(
        "Open this URL, log in with your Zerodha ID + password + TOTP, then copy the "
        f"`request_token` from the redirect URL's address bar:\n\n  {login_url}\n"
    )
    return input("request_token: ").strip()


def _live_client_factory(config: Config) -> ClientFactory:  # pragma: no cover - needs SDK+network
    """Return a factory building the real Kite SDK client (the operator path)."""
    return lambda api_key: create_kite_client(api_key, root=config.broker.api_base_url)


def main(
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Secrets | None = None,
    client_factory: ClientFactory | None = None,
    request_token_provider: RequestTokenProvider | None = None,
) -> int:
    """Run the daily morning seed; return a process exit code (``0`` = a token was seeded).

    Args:
        environ: Environment mapping for config/secrets (injected in tests; defaults to
            ``os.environ``).
        secrets: The secrets interface (injected in tests; defaults to :func:`default_secrets`
            so the token persists to the file-backed store).
        client_factory: Builds the Kite client (injected in tests with a fake; defaults to the
            real SDK client).
        request_token_provider: Supplies the ``request_token`` given the login URL (injected in
            tests; defaults to the interactive stdin prompt).

    Returns:
        ``0`` on a successful seed; ``1`` if a required credential is missing.
    """
    environ = os.environ if environ is None else environ
    config = load_config(env=environ.get("QUANT_ENV") or "dev", environ=environ)
    configure_logging(config)  # so the operator sees the INFO result line
    secrets = secrets if secrets is not None else default_secrets(environ=environ)
    factory = client_factory if client_factory is not None else _live_client_factory(config)
    provider = (
        request_token_provider if request_token_provider is not None else _interactive_request_token
    )
    try:
        suffix = seed_and_persist(secrets, factory, provider)
    except MissingSecretError as exc:
        _logger.error("kite morning auth FAILED", extra={"error": str(exc)})
        return 1
    _logger.info(
        f"kite morning auth PASSED — access_token ending {suffix}; persisted to the secrets "
        f"interface ({KITE_ACCESS_TOKEN_SECRET})",
    )
    return 0
