"""Shared fakes and sample data for the ingestion (backfill) unit tests.

A :class:`FakeHistoricalAdapter` stands in for a :class:`~quant.core.interfaces.BrokerAdapter`
(canned, deterministic candles per calendar day; records every fetch; can be told to
fail to simulate an interruption), and :class:`InMemoryBackfillCheckpoint` is a dict-
backed resume store — so the whole backfill surface runs with no SDK, no network, and
no filesystem.

Not a ``test_*`` module, so pytest does not collect it; imported by the backfill tests.
"""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.types import Bar, Margins, Order, OrderRequest, Position

IST = ZoneInfo("Asia/Kolkata")


class FakeHistoricalAdapter:
    """A :class:`BrokerAdapter` whose ``fetch_historical`` returns deterministic candles.

    For any requested ``[start, end]`` window it generates ``bars_per_day`` minute bars
    per calendar day (at 09:15, 09:16, ...), restricted to the window — so the candles
    for a given day are identical no matter which chunk requests them (mirroring real
    immutable history, which is what makes re-fetch idempotent). Every call is recorded
    in :attr:`calls`; ``raise_on_symbol`` / ``fail_after_calls`` simulate interruptions.
    """

    def __init__(
        self,
        *,
        bars_per_day: int = 3,
        raise_on_symbol: str | None = None,
        fail_after_calls: int | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._bars_per_day = bars_per_day
        self._raise_on_symbol = raise_on_symbol
        self._fail_after_calls = fail_after_calls

    def fetch_historical(
        self, symbol: str, start: datetime, end: datetime, interval: str
    ) -> pd.DataFrame:
        """Return generated candles for ``symbol`` within ``[start, end]`` (recording the call)."""
        self.calls.append({"symbol": symbol, "start": start, "end": end, "interval": interval})
        if self._raise_on_symbol is not None and symbol == self._raise_on_symbol:
            raise RuntimeError(f"simulated fetch failure for {symbol}")
        if self._fail_after_calls is not None and len(self.calls) > self._fail_after_calls:
            raise RuntimeError("simulated transient fetch failure")
        return self._generate(symbol, start, end)

    def calls_for(self, symbol: str) -> list[dict[str, object]]:
        """Return the recorded fetch calls for ``symbol``."""
        return [call for call in self.calls if call["symbol"] == symbol]

    def _generate(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Build the deterministic candle frame for one window."""
        bars: list[Bar] = []
        day = start.astimezone(IST).date()
        last_day = end.astimezone(IST).date()
        while day <= last_day:
            base = datetime.combine(day, time(9, 15), tzinfo=IST)
            for i in range(self._bars_per_day):
                stamp = base + timedelta(minutes=i)
                if start <= stamp <= end:
                    bars.append(
                        Bar(
                            symbol=symbol,
                            timestamp=stamp,
                            open=100.0 + i,
                            high=101.0 + i,
                            low=99.0 + i,
                            close=100.5 + i,
                            volume=1000 + i,
                        )
                    )
            day += timedelta(days=1)
        return bars_to_frame(bars)

    # --- unused BrokerAdapter surface (the job only fetches history) -----------
    def place_order(self, request: OrderRequest) -> str:
        raise NotImplementedError

    def modify_order(self, order_id: str, request: OrderRequest) -> None:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    def get_order(self, order_id: str) -> Order:
        raise NotImplementedError

    def get_orders(self) -> Sequence[Order]:
        raise NotImplementedError

    def get_positions(self) -> Sequence[Position]:
        raise NotImplementedError

    def margins(self) -> Margins:
        raise NotImplementedError


class InMemoryBackfillCheckpoint:
    """A dict-backed :class:`BackfillCheckpoint` for unit tests."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], date] = {}

    def completed_through(self, symbol: str, interval: str) -> date | None:
        return self._state.get((symbol, interval))

    def mark_completed(self, symbol: str, interval: str, through: date) -> None:
        self._state[(symbol, interval)] = through
