"""Read-only Kite credential verification (P2A.1 operator runbook helper).

Run by the operator *after* recording their Kite credentials in the secrets interface, this is a
one-shot check that:

* the ``api_key`` and ``api_secret`` are present (read via the
  :class:`~quant.core.secrets.Secrets` interface; never printed), and
* the ``api_key`` and the network path work — via a single **read-only** ``instruments`` call.

It reports only the **last four characters** of the ``api_key`` (so the operator can confirm
*which* key is loaded) and the instrument count — never a credential value. The ``api_secret``
is fully validated later by P2A.2's session exchange (the SHA-256 checksum fails on a wrong
secret), so a green result here means "key + plumbing + reachability are good", not "the secret
is correct".

The logic lives here (importable, unit-tested against a fake client);
``scripts/verify_kite_credentials.py`` is the thin shim (Ground Rule 3).
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from quant.core.config import Config, load_config
from quant.core.logging import configure_logging, get_logger
from quant.core.secrets import EnvSecrets, MissingSecretError, Secrets
from quant.data.brokers.auth import KITE_API_KEY_SECRET, KITE_API_SECRET_SECRET
from quant.data.brokers.client import KiteClient, create_kite_client

_logger = get_logger(__name__)

#: Builds a Kite client from an ``api_key`` (injected so tests can supply a fake).
ClientFactory = Callable[[str], KiteClient]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The outcome of a read-only credential check (carries no credential values)."""

    api_key_suffix: str  # the last 4 characters of the api_key only
    instrument_count: int


def verify_credentials(
    secrets: Secrets,
    client_factory: ClientFactory,
    *,
    exchange: str = "NSE",
) -> VerificationResult:
    """Confirm both credentials are present and the api_key + connectivity work.

    Reads ``api_key`` and ``api_secret`` through ``secrets`` (the secret's *presence* is checked,
    but the secret itself is not used until P2A.2), builds a client via ``client_factory``, and
    makes one read-only ``instruments(exchange)`` call.

    Args:
        secrets: The secrets interface providing the credentials.
        client_factory: Builds a :class:`KiteClient` from the ``api_key`` (injected for tests).
        exchange: Exchange whose instrument dump to fetch for the read-only check.

    Returns:
        A :class:`VerificationResult` with the api_key's last 4 chars and the instrument count.

    Raises:
        MissingSecretError: If either credential is absent from the secrets interface.
    """
    api_key = secrets.get(KITE_API_KEY_SECRET)
    secrets.get(KITE_API_SECRET_SECRET)  # presence check only; the secret is used in P2A.2
    client = client_factory(api_key)
    instrument_count = len(client.instruments(exchange))
    result = VerificationResult(api_key_suffix=api_key[-4:], instrument_count=instrument_count)
    _logger.info(
        "kite credential verification ok",
        extra={
            "api_key_suffix": result.api_key_suffix,
            "instrument_count": result.instrument_count,
            "exchange": exchange,
        },
    )
    return result


def _live_client_factory(config: Config) -> ClientFactory:  # pragma: no cover - needs SDK+network
    """Return a factory building the real Kite SDK client (the operator path)."""
    return lambda api_key: create_kite_client(api_key, root=config.broker.api_base_url)


def main(
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> int:
    """Run the read-only credential check; return a process exit code (``0`` = passed).

    Args:
        environ: Environment mapping for config/secrets (injected in tests; defaults to
            ``os.environ``).
        client_factory: Builds the Kite client (injected in tests with a fake; defaults to the
            real SDK client).

    Returns:
        ``0`` if both credentials are present and the read-only call succeeds; ``1`` if a
        credential is missing.
    """
    environ = os.environ if environ is None else environ
    config = load_config(env=environ.get("QUANT_ENV") or "dev", environ=environ)
    configure_logging(config)  # so the operator actually sees the INFO result line
    secrets = EnvSecrets(environ=environ)
    factory = client_factory if client_factory is not None else _live_client_factory(config)
    try:
        result = verify_credentials(secrets, factory, exchange=config.market.exchange)
    except MissingSecretError as exc:
        _logger.error("kite credential verification FAILED", extra={"error": str(exc)})
        return 1
    _logger.info(
        f"kite credential verification PASSED — api_key ending {result.api_key_suffix}, "
        f"fetched {result.instrument_count} {config.market.exchange} instruments",
    )
    return 0
