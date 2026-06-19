"""``KiteTickerTransport`` - the Kite WebSocket behind the ``TickerTransport`` port.

The live-stream consumer (``data/ingest/stream.py``) programs against the
:class:`~quant.core.interfaces.TickerTransport` Protocol; this is the Kite
implementation, and the *only* place ``kiteconnect.KiteTicker`` is touched (Ground
Rule 1 / Deep Dive #1 §0.3). The SDK is imported lazily in
:func:`create_kite_ticker_transport`, so importing this package never pulls in the
ticker's ``twisted``/``autobahn`` stack until a live transport is actually built.

KiteTicker delivers events via assignable callbacks with a ``(ws, ...)`` signature
and manages its own exponential-backoff auto-reconnect. This transport adapts those
callbacks to the SDK-agnostic :class:`~quant.core.interfaces.StreamListener` and
exposes the small lifecycle surface the consumer needs.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from quant.core.interfaces import StreamListener

__all__ = ["KiteTickerTransport", "RawTicker", "create_kite_ticker_transport"]


class RawTicker(Protocol):
    """The ``kiteconnect.KiteTicker`` surface this transport uses.

    Callbacks are assignable attributes (the SDK calls them as ``cb(ws, ...)``);
    the methods mirror the SDK so the real ticker satisfies this structurally.
    """

    on_connect: Callable[..., Any]
    on_ticks: Callable[..., Any]
    on_close: Callable[..., Any]
    on_error: Callable[..., Any]
    on_reconnect: Callable[..., Any]

    def connect(self, threaded: bool = ...) -> None:
        """Open the WebSocket; ``threaded=True`` runs the reactor in a thread."""
        ...

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        """Subscribe to the given instrument tokens."""
        ...

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        """Set the streaming mode (e.g. ``full``) for the given tokens."""
        ...

    def stop(self) -> None:
        """Stop the reactor and disable auto-reconnect."""
        ...


class KiteTickerTransport:
    """Adapts ``kiteconnect.KiteTicker`` to the ``TickerTransport`` Protocol."""

    def __init__(self, ticker: RawTicker, *, mode: str = "full") -> None:
        """Wrap a ticker and wire its callbacks to this transport's forwarders.

        Args:
            ticker: A ``KiteTicker``-like object (the real SDK client, or a fake).
            mode: Streaming mode set on subscribe (``full`` for 5-level depth).
        """
        self._ticker = ticker
        self._mode = mode
        self._listener: StreamListener | None = None
        ticker.on_connect = self._forward_connect
        ticker.on_ticks = self._forward_ticks
        ticker.on_close = self._forward_close
        ticker.on_error = self._forward_error
        ticker.on_reconnect = self._forward_reconnect

    def set_listener(self, listener: StreamListener) -> None:
        """Register the listener that receives ticks and lifecycle callbacks."""
        self._listener = listener

    def start(self) -> None:
        """Open the connection on a background thread (non-blocking)."""
        self._ticker.connect(threaded=True)

    def stop(self) -> None:
        """Stop streaming and disable auto-reconnect."""
        self._ticker.stop()

    def subscribe(self, tokens: Sequence[int]) -> None:
        """Subscribe to ``tokens`` and set the configured (full) mode for them."""
        token_list = list(tokens)
        self._ticker.subscribe(token_list)
        self._ticker.set_mode(self._mode, token_list)

    # ----- SDK callback forwarders (translate (ws, ...) -> StreamListener) -----
    def _forward_connect(self, ws: Any, response: Any) -> None:
        if self._listener is not None:
            self._listener.on_connect()

    def _forward_ticks(self, ws: Any, ticks: Sequence[Mapping[str, Any]]) -> None:
        if self._listener is not None:
            self._listener.on_ticks(ticks)

    def _forward_reconnect(self, ws: Any, attempts_count: int) -> None:
        if self._listener is not None:
            self._listener.on_reconnect(attempts_count)

    def _forward_close(self, ws: Any, code: int | None, reason: str | None) -> None:
        if self._listener is not None:
            self._listener.on_close(code, reason)

    def _forward_error(self, ws: Any, code: int | None, reason: str | None) -> None:
        if self._listener is not None:
            self._listener.on_error(code, reason)


def create_kite_ticker_transport(
    api_key: str,
    access_token: str,
    *,
    mode: str = "full",
    reconnect_max_tries: int = 50,
    reconnect_max_delay_seconds: int = 60,
    connect_timeout_seconds: int = 30,
    root: str | None = None,
) -> KiteTickerTransport:
    """Build a live :class:`KiteTickerTransport` (the one ``KiteTicker`` import site).

    Args:
        api_key: Kite Connect API key.
        access_token: Today's seeded access token (see ``KiteAuthenticator``).
        mode: Streaming mode (``full`` for 5-level depth).
        reconnect_max_tries: Max auto-reconnect attempts (SDK exponential backoff).
        reconnect_max_delay_seconds: Cap on the backoff delay between attempts.
        connect_timeout_seconds: Initial connection timeout.
        root: Optional WebSocket root override.

    Returns:
        A transport ready to be driven by a ``TickStreamConsumer``.
    """
    from kiteconnect import KiteTicker

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "access_token": access_token,
        "reconnect": True,
        "reconnect_max_tries": reconnect_max_tries,
        "reconnect_max_delay": reconnect_max_delay_seconds,
        "connect_timeout": connect_timeout_seconds,
    }
    if root is not None:
        kwargs["root"] = root
    return KiteTickerTransport(cast(RawTicker, KiteTicker(**kwargs)), mode=mode)
