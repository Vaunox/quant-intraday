"""Symbol → instrument-token resolution from the Kite instruments dump.

Kite's market-data endpoints are keyed by an integer ``instrument_token``, not by a
trading symbol. The instruments dump (``KiteClient.instruments``) maps each
``(exchange, tradingsymbol)`` to its token. :class:`InstrumentRegistry` indexes that
dump once so the adapter can resolve a human symbol (e.g. ``RELIANCE`` on ``NSE``)
to its token on every historical fetch.

The dump is large (tens of thousands of rows) and refreshes daily; building the
registry from a cached/period-fetched dump is the caller's responsibility (the
nightly/pre-open refresh is wired in later phases). Here we only index and query.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from quant.data.brokers.client import KiteClient
from quant.data.brokers.errors import InstrumentNotFoundError


class InstrumentRegistry:
    """An index of ``(exchange, tradingsymbol) → instrument_token``."""

    def __init__(self, instruments: Iterable[Mapping[str, Any]]) -> None:
        """Build the registry from an instruments dump.

        Args:
            instruments: Rows from ``KiteClient.instruments`` (each a mapping with at
                least ``exchange``, ``tradingsymbol``, and ``instrument_token``).
        """
        self._by_symbol: dict[tuple[str, str], int] = {}
        for row in instruments:
            key = (str(row["exchange"]), str(row["tradingsymbol"]))
            self._by_symbol[key] = int(row["instrument_token"])

    @classmethod
    def from_client(cls, client: KiteClient, exchange: str | None = None) -> "InstrumentRegistry":
        """Fetch the instruments dump via ``client`` and build a registry.

        Args:
            client: The Kite SDK client.
            exchange: Restrict the dump to one exchange (recommended; the full dump
                spans every segment).
        """
        return cls(client.instruments(exchange))

    def token_for(self, tradingsymbol: str, exchange: str) -> int:
        """Return the instrument token for ``tradingsymbol`` on ``exchange``.

        Raises:
            InstrumentNotFoundError: If the pair is not in the dump.
        """
        try:
            return self._by_symbol[(exchange, tradingsymbol)]
        except KeyError:
            raise InstrumentNotFoundError(
                f"No instrument token for {tradingsymbol!r} on {exchange!r}. "
                "Is the symbol correct and the instruments dump current?"
            ) from None

    def __len__(self) -> int:
        """Return the number of indexed instruments."""
        return len(self._by_symbol)
