"""Fakes and sample ticks for the live-stream tests (P1.2).

A :class:`FakeTickerTransport` is the "fake socket" the consumer is driven by (it
exposes ``fire_*`` helpers to simulate connect/ticks/reconnect/close). A
:class:`FakeRawTicker` stands in for ``kiteconnect.KiteTicker`` when testing the
SDK-confined transport. Sample ticks mirror the real ``full``/``ltp`` payloads.

Not a ``test_*`` module, so pytest does not collect it.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from quant.core.interfaces import StreamListener
from tests.unit.brokers_fakes import INFY_TOKEN, RELIANCE_TOKEN

# Naive IST datetimes, exactly as KiteTicker delivers them.
_TS = datetime(2026, 6, 18, 9, 16, 0)
_LAST_TRADE_TS = datetime(2026, 6, 18, 9, 15, 59)


def _noop(*args: Any, **kwargs: Any) -> None:
    """Default callback before the transport wires its forwarders."""


class FakeTickerTransport:
    """A fake :class:`~quant.core.interfaces.TickerTransport` (the fake socket)."""

    def __init__(self) -> None:
        self.listener: StreamListener | None = None
        self.started = False
        self.stopped = False
        self.subscribed: list[list[int]] = []

    def set_listener(self, listener: StreamListener) -> None:
        self.listener = listener

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def subscribe(self, tokens: Sequence[int]) -> None:
        self.subscribed.append(list(tokens))

    # --- helpers to simulate the socket firing events at the listener ---
    def _bound(self) -> StreamListener:
        if self.listener is None:
            raise AssertionError("start() must be called before firing events")
        return self.listener

    def fire_connect(self) -> None:
        self._bound().on_connect()

    def fire_ticks(self, raw_ticks: Sequence[Mapping[str, Any]]) -> None:
        self._bound().on_ticks(raw_ticks)

    def fire_reconnect(self, attempt: int) -> None:
        self._bound().on_reconnect(attempt)

    def fire_close(self, code: int | None = None, reason: str | None = None) -> None:
        self._bound().on_close(code, reason)

    def fire_error(self, code: int | None = None, reason: str | None = None) -> None:
        self._bound().on_error(code, reason)


class FakeRawTicker:
    """A fake ``kiteconnect.KiteTicker`` (the RawTicker surface)."""

    def __init__(self) -> None:
        self.on_connect: Callable[..., Any] = _noop
        self.on_ticks: Callable[..., Any] = _noop
        self.on_close: Callable[..., Any] = _noop
        self.on_error: Callable[..., Any] = _noop
        self.on_reconnect: Callable[..., Any] = _noop
        self.connected = False
        self.threaded: bool | None = None
        self.stopped = False
        self.subscribed: list[list[int]] = []
        self.modes: list[tuple[str, list[int]]] = []

    def connect(self, threaded: bool = False) -> None:
        self.connected = True
        self.threaded = threaded

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.subscribed.append(list(instrument_tokens))

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.modes.append((mode, list(instrument_tokens)))

    def stop(self) -> None:
        self.stopped = True


def sample_full_tick(token: int = RELIANCE_TOKEN) -> dict[str, Any]:
    """A recorded-shape ``full``-mode tick: LTP fields + 5-level depth + timestamp."""
    return {
        "instrument_token": token,
        "mode": "full",
        "last_price": 101.5,
        "last_quantity": 12,
        "average_price": 101.2,
        "volume": 250000,
        "buy_quantity": 5000,
        "sell_quantity": 4800,
        "last_trade_time": _LAST_TRADE_TS,
        "timestamp": _TS,
        "depth": {
            "buy": [
                {"price": round(101.45 - i * 0.05, 2), "quantity": 100 + i, "orders": 3 + i}
                for i in range(5)
            ],
            "sell": [
                {"price": round(101.50 + i * 0.05, 2), "quantity": 90 + i, "orders": 2 + i}
                for i in range(5)
            ],
        },
    }


def sample_ltp_tick(token: int = INFY_TOKEN) -> dict[str, Any]:
    """A bare ``ltp`` tick: no depth and no timestamp (exercises the fallbacks)."""
    return {"instrument_token": token, "mode": "ltp", "last_price": 1500.0}
