"""Kite daily session auth: the manual-seed-then-automate token flow.

Kite's access token expires every morning (flushed ~5:00-7:30 AM IST) and the
exchange mandates a manual login once per day. The compliant, robust pattern
(Deep Dive #5, "morning auth/token routine") is therefore:

1. The operator visits :meth:`KiteAuthenticator.login_url` and logs in (ID +
   password + TOTP), and is redirected with a one-time ``request_token``.
2. :meth:`KiteAuthenticator.seed_session` exchanges that ``request_token`` for an
   ``access_token``. The SDK signs the exchange with ``SHA-256(api_key +
   request_token + api_secret)`` internally; the ``api_secret`` comes only from the
   secrets interface and is never logged.
3. The ``access_token`` is held in a :class:`TokenStore` and served to every
   component for the rest of the session.

Persisting the token across process restarts and automating the morning seed are
the job of P5.2; here the default :class:`InMemoryTokenStore` keeps it for the life
of the process, behind the same Protocol a persistent store will implement.
"""

from typing import Protocol, runtime_checkable

from quant.core.logging import get_logger
from quant.core.secrets import Secrets
from quant.data.brokers.client import KiteClient
from quant.data.brokers.errors import SessionNotSeededError

_logger = get_logger(__name__)

#: Logical secret names (resolved by the secrets interface to the
#: ``QUANT_SECRET_KITE_API_KEY`` / ``QUANT_SECRET_KITE_API_SECRET`` env vars).
KITE_API_KEY_SECRET = "kite_api_key"
KITE_API_SECRET_SECRET = "kite_api_secret"


@runtime_checkable
class TokenStore(Protocol):
    """Holds the current daily access token; the seam P5.2 makes persistent."""

    def get_access_token(self) -> str | None:
        """Return the stored access token, or ``None`` if not seeded."""
        ...

    def set_access_token(self, access_token: str) -> None:
        """Store ``access_token`` as the current session token."""
        ...

    def clear(self) -> None:
        """Forget any stored token (e.g. on expiry or logout)."""
        ...


class InMemoryTokenStore:
    """A process-lifetime :class:`TokenStore` (the P1.1 default; persistence is P5.2)."""

    def __init__(self) -> None:
        """Create an empty (unseeded) store."""
        self._access_token: str | None = None

    def get_access_token(self) -> str | None:
        """Return the stored access token, or ``None`` if not seeded."""
        return self._access_token

    def set_access_token(self, access_token: str) -> None:
        """Store ``access_token`` as the current session token."""
        self._access_token = access_token

    def clear(self) -> None:
        """Forget any stored token."""
        self._access_token = None


class KiteAuthenticator:
    """Seeds and serves the daily Kite access token.

    Wires together the SDK client (for the OAuth exchange), the secrets interface
    (for the ``api_secret``), and a :class:`TokenStore` (where the token lives).
    Inject all three so the flow is fully testable with fakes — no credentials and
    no network are needed to exercise it.
    """

    def __init__(
        self,
        client: KiteClient,
        secrets: Secrets,
        token_store: TokenStore,
        *,
        api_secret_name: str = KITE_API_SECRET_SECRET,
    ) -> None:
        """Build the authenticator.

        Args:
            client: The Kite SDK client (behind :class:`KiteClient`).
            secrets: The secrets interface providing the ``api_secret``.
            token_store: Where the seeded access token is held.
            api_secret_name: Logical secret name for the API secret.
        """
        self._client = client
        self._secrets = secrets
        self._token_store = token_store
        self._api_secret_name = api_secret_name

    def login_url(self) -> str:
        """Return the Kite login URL for the operator's daily manual login."""
        return self._client.login_url()

    def seed_session(self, request_token: str) -> None:
        """Exchange a fresh ``request_token`` for an access token and store it.

        This is the ~30-second manual morning seed. The ``api_secret`` is read from
        the secrets interface and passed to the SDK, which computes the SHA-256
        checksum and performs the exchange. The resulting token is set on the client
        (so it can immediately make calls) and saved in the token store.

        Args:
            request_token: The one-time token from the post-login redirect.
        """
        api_secret = self._secrets.get(self._api_secret_name)
        session = self._client.generate_session(request_token, api_secret)
        access_token = str(session["access_token"])
        self._client.set_access_token(access_token)
        self._token_store.set_access_token(access_token)
        # Never log the token or secret; ``user_id`` (if present) aids traceability.
        _logger.info("Kite session seeded", extra={"user_id": session.get("user_id")})

    def is_seeded(self) -> bool:
        """Return whether a session token is currently available."""
        return self._token_store.get_access_token() is not None

    def access_token(self) -> str:
        """Return the current access token.

        Raises:
            SessionNotSeededError: If no session has been seeded yet today.
        """
        token = self._token_store.get_access_token()
        if token is None:
            raise SessionNotSeededError(
                "Kite session is not seeded. Run the morning login flow "
                "(KiteAuthenticator.seed_session); see docs/runbooks/kite_session.md."
            )
        return token
