"""``KiteAdapter`` — the Zerodha Kite implementation of :class:`BrokerAdapter`.

This is the only adapter the rest of the system sees for Kite. P1.1 delivers the
**market-data** path (historical candles) and the **session** plumbing; the trading
and account methods are explicitly deferred to their own subtasks (they raise a
clear ``NotImplementedError`` naming the subtask, per Ground Rule 4 — a tracked
deferral, not a buried TODO).

Collaborators are injected (Ground Rule 1): the SDK client (behind
:class:`KiteClient`), the :class:`TokenStore` holding today's access token, the
:class:`InstrumentRegistry` for symbol→token resolution, and the
:class:`RateLimiter` that keeps us under Kite's data-endpoint rate limit. None of
them require credentials or a network to construct, so the adapter is unit-testable
with fakes and recorded fixtures.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.logging import get_logger
from quant.core.types import Bar, Margins, Order, OrderRequest, Position
from quant.data.brokers.auth import TokenStore
from quant.data.brokers.client import KiteClient, normalize_interval
from quant.data.brokers.errors import SessionNotSeededError
from quant.data.brokers.instruments import InstrumentRegistry
from quant.data.brokers.rate_limit import RateLimiter

_logger = get_logger(__name__)


class KiteAdapter:
    """Market-data + session adapter over the Kite Connect SDK (behind ``BrokerAdapter``)."""

    def __init__(
        self,
        client: KiteClient,
        token_store: TokenStore,
        instruments: InstrumentRegistry,
        rate_limiter: RateLimiter,
        *,
        exchange: str,
    ) -> None:
        """Build the adapter.

        Args:
            client: The Kite SDK client (behind :class:`KiteClient`).
            token_store: Holds today's seeded access token.
            instruments: Resolves ``(symbol, exchange)`` to an instrument token.
            rate_limiter: Throttles data requests under Kite's limit.
            exchange: Default exchange for symbol resolution (e.g. ``NSE``), from
                ``config.market.exchange`` — never hard-coded here (Ground Rule 2).
        """
        self._client = client
        self._token_store = token_store
        self._instruments = instruments
        self._rate_limiter = rate_limiter
        self._exchange = exchange

    # ----------------------------------------------------------------- market data
    def fetch_historical(
        self, symbol: str, start: datetime, end: datetime, interval: str
    ) -> pd.DataFrame:
        """Fetch historical OHLCV candles for ``symbol`` within ``[start, end]``.

        Resolves the symbol to its instrument token, ensures the session is seeded,
        throttles to the data-endpoint rate limit, calls the SDK, and maps the
        result to the canonical bars schema (:data:`quant.core.frames.BAR_COLUMNS`).

        Args:
            symbol: Trading symbol on the adapter's default exchange (e.g. ``RELIANCE``).
            start: Inclusive range start (tz-aware IST).
            end: Inclusive range end (tz-aware IST).
            interval: Candle interval (``minute``, ``5minute``, ``15minute``, ``day``, ...).

        Returns:
            A canonical-schema bars DataFrame in time order (empty if no candles).

        Raises:
            SessionNotSeededError: If no access token has been seeded today.
            InstrumentNotFoundError: If the symbol is unknown on the exchange.
            UnsupportedIntervalError: If the interval is not a Kite interval.
        """
        kite_interval = normalize_interval(interval)
        instrument_token = self._instruments.token_for(symbol, self._exchange)
        self._ensure_authenticated()
        self._rate_limiter.acquire()
        candles = self._client.historical_data(instrument_token, start, end, kite_interval)
        _logger.info(
            "fetched historical candles",
            extra={
                "symbol": symbol,
                "exchange": self._exchange,
                "interval": kite_interval,
                "candles": len(candles),
            },
        )
        return self._candles_to_frame(symbol, candles)

    @staticmethod
    def _candles_to_frame(symbol: str, candles: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
        """Map Kite candle dicts to a canonical-schema bars DataFrame.

        Routing through :class:`~quant.core.types.Bar` and
        :func:`~quant.core.frames.bars_to_frame` keeps the bars schema defined in one
        place, so this adapter can never silently drift from it. The timestamp is
        type-guarded (a bad type there would silently corrupt a :class:`Bar`); the
        OHLCV ``float()``/``int()`` coercions raise loudly on malformed values.
        """
        bars = [
            Bar(
                symbol=symbol,
                timestamp=_as_datetime(candle["date"]),
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=int(candle["volume"]),
            )
            for candle in candles
        ]
        return bars_to_frame(bars)

    def _ensure_authenticated(self) -> None:
        """Set the current access token on the client, or fail loud if unseeded."""
        token = self._token_store.get_access_token()
        if token is None:
            raise SessionNotSeededError(
                "Kite session is not seeded. Run the morning login flow before "
                "fetching data; see docs/runbooks/kite_session.md."
            )
        # Idempotent: keeps the client aligned with the store, so a refreshed token
        # (P5.2) is picked up transparently on the next call.
        self._client.set_access_token(token)

    # --------------------------------------------------------------- trading (P4)
    def place_order(self, request: OrderRequest) -> str:
        """Not implemented in P1.1 — order placement is delivered in P4.3."""
        raise NotImplementedError("Order placement is delivered in P4.3 (execution/router).")

    def modify_order(self, order_id: str, request: OrderRequest) -> None:
        """Not implemented in P1.1 — order modification is delivered in P4.3."""
        raise NotImplementedError("Order modification is delivered in P4.3 (execution/router).")

    def cancel_order(self, order_id: str) -> None:
        """Not implemented in P1.1 — order cancellation is delivered in P4.3."""
        raise NotImplementedError("Order cancellation is delivered in P4.3 (execution/router).")

    def get_order(self, order_id: str) -> Order:
        """Not implemented in P1.1 — order-state reads are delivered in P4.2."""
        raise NotImplementedError(
            "Order-state reads are delivered in P4.2 (order-update ingestion)."
        )

    def get_orders(self) -> Sequence[Order]:
        """Not implemented in P1.1 — order-state reads are delivered in P4.2."""
        raise NotImplementedError(
            "Order-state reads are delivered in P4.2 (order-update ingestion)."
        )

    # --------------------------------------------------------------- account (P4/P5)
    def get_positions(self) -> Sequence[Position]:
        """Not implemented in P1.1 — position reads are delivered in P4.5."""
        raise NotImplementedError("Position reads are delivered in P4.5 (reconciliation loop).")

    def margins(self) -> Margins:
        """Not implemented in P1.1 — margin reads are delivered with the pre-open gate in P5.1."""
        raise NotImplementedError("Margin reads are delivered in P5.1 (pre-open gate).")


def _as_datetime(value: object) -> datetime:
    """Return ``value`` as a ``datetime`` or fail loud.

    Kite returns tz-aware ``datetime`` objects for candle timestamps; this guards the
    contract at the boundary (Ground Rule 7) rather than letting a bad type leak into
    a :class:`~quant.core.types.Bar`.
    """
    if isinstance(value, datetime):
        return value
    raise TypeError(f"Expected a datetime candle timestamp, got {type(value).__name__}: {value!r}")
