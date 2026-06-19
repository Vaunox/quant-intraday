"""The narrow Kite SDK surface we depend on, plus the SDK construction seam.

Ground Rule 1 / Deep Dive #1 §0.3: *nothing outside this package may import the
``kiteconnect`` SDK.* We honour that two ways:

* :class:`KiteClient` is a structural :class:`~typing.Protocol` describing only the
  handful of SDK methods we actually call. The rest of the package (and the tests)
  program against this Protocol, never the concrete SDK, so a fake client can stand
  in with no SDK installed.
* :func:`create_kite_client` is the *single* place the real SDK is imported, and it
  imports it lazily (inside the function), so importing this package never pulls in
  ``kiteconnect`` (and its heavy ``twisted``/``autobahn`` tick-stream dependencies)
  until an operator actually constructs a live client.
"""

from datetime import datetime
from typing import Any, Protocol, cast

from quant.data.brokers.errors import UnsupportedIntervalError

#: Candle intervals Kite accepts, mapped from our accepted spelling to the SDK's.
#: The SDK's own spelling maps to itself; a couple of common aliases are accepted
#: so callers can't trip on "1minute" vs "minute" or "hour" vs "60minute".
_INTERVAL_ALIASES: dict[str, str] = {
    "minute": "minute",
    "1minute": "minute",
    "3minute": "3minute",
    "5minute": "5minute",
    "10minute": "10minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "60minute": "60minute",
    "hour": "60minute",
    "day": "day",
}

#: The canonical Kite interval strings (the values of the alias map).
KITE_INTERVALS: frozenset[str] = frozenset(_INTERVAL_ALIASES.values())


def normalize_interval(interval: str) -> str:
    """Return the canonical Kite interval string for ``interval``.

    Accepts the Kite spellings (``minute``, ``5minute``, ``15minute``, ``day``, ...)
    plus a few aliases, case-insensitively.

    Raises:
        UnsupportedIntervalError: If ``interval`` is not a recognised interval.
    """
    key = interval.strip().lower()
    try:
        return _INTERVAL_ALIASES[key]
    except KeyError:
        supported = ", ".join(sorted(KITE_INTERVALS))
        raise UnsupportedIntervalError(
            f"Unsupported interval {interval!r}; expected one of: {supported}."
        ) from None


class KiteClient(Protocol):
    """The subset of ``kiteconnect.KiteConnect`` this package uses.

    Method names and shapes mirror the official Python SDK (v4) so the real
    ``KiteConnect`` instance satisfies this Protocol structurally.
    """

    def login_url(self) -> str:
        """Return the Kite login URL the operator visits to obtain a request token."""
        ...

    def generate_session(self, request_token: str, api_secret: str) -> dict[str, Any]:
        """Exchange a request token for a session dict containing ``access_token``."""
        ...

    def set_access_token(self, access_token: str) -> None:
        """Set the access token used to sign subsequent requests on this client."""
        ...

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]:
        """Return historical candles as dicts with date/open/high/low/close/volume."""
        ...

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        """Return the instruments dump (optionally for a single exchange)."""
        ...


def create_kite_client(
    api_key: str, *, root: str | None = None, timeout: int | None = None
) -> KiteClient:
    """Construct a real ``kiteconnect.KiteConnect`` client (the one SDK import site).

    The SDK is imported here, lazily, so the rest of the system never imports it.

    Args:
        api_key: The Kite Connect API key (from the secrets interface; not a secret
            that needs masking, but it identifies the app).
        root: Optional API root override (e.g. ``config.broker.api_base_url``).
        timeout: Optional per-request timeout in seconds (SDK default is 7).

    Returns:
        A live client typed as :class:`KiteClient`.
    """
    from kiteconnect import KiteConnect

    kwargs: dict[str, Any] = {"api_key": api_key}
    if root is not None:
        kwargs["root"] = root
    if timeout is not None:
        kwargs["timeout"] = timeout
    # The SDK is untyped; cast to our Protocol so callers get a precise type.
    return cast(KiteClient, KiteConnect(**kwargs))
