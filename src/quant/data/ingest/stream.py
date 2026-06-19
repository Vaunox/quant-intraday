"""The live market-data stream consumer (Deep Dive #1, Module 0/1: WebSocket lifecycle).

Consumes Kite's ``full``-mode WebSocket feed - last-trade ticks plus 5-level depth -
behind the :class:`~quant.core.interfaces.TickerTransport` Protocol, so this module
never imports the broker SDK and is fully testable with a fake socket.

Responsibilities (the parts that carry logic and must be tested):

* **Parse** each raw broker tick into a typed :class:`~quant.core.types.MarketUpdate`
  (a :class:`~quant.core.types.Tick` + an optional 5-level
  :class:`~quant.core.types.DepthSnapshot`), with tz-aware IST timestamps.
* **Resubscribe on every (re)connect** - the transport's SDK handles reconnect with
  exponential backoff; this consumer re-subscribes its token set in full mode each
  time the socket (re)opens, so a dropped connection auto-recovers cleanly.
* **Push to a queue** for downstream consumers (Redis live store in P1.3). The queue
  is drained off the socket thread; a full queue drops with a loud WARNING rather
  than blocking the socket (never stall the feed).
* **Heartbeat** - track feed liveness so a stale feed (connected but no ticks) is
  detectable; escalation to the kill-switch is Layer 4/5.
"""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from queue import Full, Queue
from typing import Any
from zoneinfo import ZoneInfo

from quant.core.interfaces import TickerTransport
from quant.core.logging import get_logger
from quant.core.types import DepthLevel, DepthSnapshot, MarketUpdate, Tick

_logger = get_logger(__name__)

#: Kite streams naive datetimes in IST; we attach this zone (Ground Rule: IST always).
IST = ZoneInfo("Asia/Kolkata")


def _now_ist() -> datetime:
    """Return the current time as a tz-aware IST datetime."""
    return datetime.now(IST)


def _to_ist(value: datetime) -> datetime:
    """Return ``value`` as tz-aware IST (Kite tick datetimes arrive naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=IST)


def _event_timestamp(raw: Mapping[str, Any], fallback_now: Callable[[], datetime]) -> datetime:
    """Return the event time for a raw tick (exchange time preferred).

    Prefers the exchange ``timestamp``, then ``last_trade_time``; if neither is
    present (e.g. a bare LTP payload), uses ``fallback_now`` (receipt time). Naive
    datetimes from the SDK are localised to IST.
    """
    raw_ts = raw.get("timestamp") or raw.get("last_trade_time")
    if raw_ts is None:
        return fallback_now()
    if isinstance(raw_ts, datetime):
        return _to_ist(raw_ts)
    raise TypeError(f"Expected a datetime tick timestamp, got {type(raw_ts).__name__}: {raw_ts!r}")


def _parse_levels(levels: Sequence[Mapping[str, Any]]) -> tuple[DepthLevel, ...]:
    """Parse one side of the order book into typed depth levels."""
    return tuple(
        DepthLevel(
            price=float(lvl["price"]), quantity=int(lvl["quantity"]), orders=int(lvl["orders"])
        )
        for lvl in levels
    )


def _parse_depth(raw: Mapping[str, Any], symbol: str, timestamp: datetime) -> DepthSnapshot | None:
    """Parse the 5-level book from a full-mode tick, or ``None`` if absent."""
    depth = raw.get("depth")
    if not depth:
        return None
    return DepthSnapshot(
        symbol=symbol,
        timestamp=timestamp,
        bids=_parse_levels(depth.get("buy", ())),
        asks=_parse_levels(depth.get("sell", ())),
    )


def parse_market_update(
    raw: Mapping[str, Any], symbol: str, *, fallback_now: Callable[[], datetime] = _now_ist
) -> MarketUpdate:
    """Parse one raw Kite tick dict into a typed :class:`MarketUpdate`.

    Args:
        raw: A single Kite tick (``full`` mode carries depth; other modes do not).
        symbol: The trading symbol for the tick's instrument token.
        fallback_now: Receipt-time source used only when the tick has no timestamp.
    """
    timestamp = _event_timestamp(raw, fallback_now)
    tick = Tick(
        symbol=symbol,
        timestamp=timestamp,
        last_price=float(raw["last_price"]),
        last_quantity=int(raw.get("last_quantity", 0)),
        # v5 uses "volume"; tolerate the older "volume_traded" key.
        volume=int(raw.get("volume", raw.get("volume_traded", 0))),
    )
    return MarketUpdate(tick=tick, depth=_parse_depth(raw, symbol, timestamp))


class TickStreamConsumer:
    """Drives a :class:`TickerTransport` and turns its feed into queued updates.

    Implements :class:`~quant.core.interfaces.StreamListener`. Inject the transport
    (a fake in tests), the ``token -> symbol`` map for the instruments to stream, and
    optionally the output queue and clocks. Construction touches no SDK and no
    network.
    """

    def __init__(
        self,
        transport: TickerTransport,
        token_to_symbol: Mapping[int, str],
        *,
        queue: Queue[MarketUpdate] | None = None,
        stale_timeout_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _now_ist,
    ) -> None:
        """Build the consumer.

        Args:
            transport: The streaming transport (Kite WebSocket behind it).
            token_to_symbol: Instrument tokens to stream, mapped to their symbols.
            queue: Output queue for parsed updates (defaults to an unbounded queue).
            stale_timeout_seconds: Feed-staleness threshold for the heartbeat.
            clock: Monotonic clock for liveness timing (injected in tests).
            now: Wall-clock IST source for tick receipt-time fallback (injected in tests).
        """
        self._transport = transport
        self._token_to_symbol = dict(token_to_symbol)
        self._queue: Queue[MarketUpdate] = queue if queue is not None else Queue()
        self._stale_timeout = stale_timeout_seconds
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._last_activity: float | None = None
        self._dropped = 0
        self._unknown_tokens = 0

    @property
    def queue(self) -> Queue[MarketUpdate]:
        """The output queue parsed updates are pushed to."""
        return self._queue

    @property
    def dropped(self) -> int:
        """Number of updates dropped because the output queue was full."""
        with self._lock:
            return self._dropped

    @property
    def unknown_tokens(self) -> int:
        """Number of ticks discarded for an unrecognised instrument token."""
        with self._lock:
            return self._unknown_tokens

    def start(self) -> None:
        """Register as listener and open the stream (non-blocking)."""
        self._transport.set_listener(self)
        self._touch()
        self._transport.start()
        _logger.info("tick stream started", extra={"instruments": len(self._token_to_symbol)})

    def stop(self) -> None:
        """Close the stream (no auto-reconnect after)."""
        self._transport.stop()
        _logger.info("tick stream stopped")

    # ----------------------------------------------------------- StreamListener
    def on_connect(self) -> None:
        """(Re)subscribe the full token set in full mode on every (re)connection."""
        tokens = list(self._token_to_symbol)
        self._transport.subscribe(tokens)
        self._touch()
        _logger.info("subscribed (full mode)", extra={"instruments": len(tokens)})

    def on_ticks(self, raw_ticks: Sequence[Mapping[str, Any]]) -> None:
        """Parse a batch of raw ticks and enqueue the resulting updates."""
        self._touch()
        for raw in raw_ticks:
            token = raw.get("instrument_token")
            symbol = self._token_to_symbol.get(token) if isinstance(token, int) else None
            if symbol is None:
                with self._lock:
                    self._unknown_tokens += 1
                _logger.warning(
                    "tick for unknown instrument token", extra={"instrument_token": token}
                )
                continue
            self._enqueue(parse_market_update(raw, symbol, fallback_now=self._now))

    def on_reconnect(self, attempt: int) -> None:
        """Log an auto-reconnect attempt (resubscription happens in on_connect)."""
        _logger.warning("stream reconnecting", extra={"attempt": attempt})

    def on_close(self, code: int | None, reason: str | None) -> None:
        """Log a connection close (the transport may auto-reconnect)."""
        _logger.warning("stream closed", extra={"code": code, "reason": reason})

    def on_error(self, code: int | None, reason: str | None) -> None:
        """Log a transport error."""
        _logger.error("stream error", extra={"code": code, "reason": reason})

    # ----------------------------------------------------------------- heartbeat
    def seconds_since_last_activity(self, *, now: float | None = None) -> float | None:
        """Seconds since the last connect/tick, or ``None`` if not started yet."""
        with self._lock:
            last = self._last_activity
        if last is None:
            return None
        current = self._clock() if now is None else now
        return current - last

    def is_stale(self, *, now: float | None = None) -> bool:
        """Whether no ticks have arrived within the staleness window."""
        elapsed = self.seconds_since_last_activity(now=now)
        return elapsed is not None and elapsed > self._stale_timeout

    def check_heartbeat(self, *, now: float | None = None) -> bool:
        """Return whether the feed is stale, logging a WARNING when it is."""
        elapsed = self.seconds_since_last_activity(now=now)
        if elapsed is not None and elapsed > self._stale_timeout:
            _logger.warning("market-data feed stale", extra={"stale_seconds": round(elapsed, 1)})
            return True
        return False

    # ------------------------------------------------------------------ internals
    def _touch(self) -> None:
        """Record feed activity for the staleness heartbeat."""
        with self._lock:
            self._last_activity = self._clock()

    def _enqueue(self, update: MarketUpdate) -> None:
        """Enqueue an update without blocking the socket thread; drop loudly if full."""
        try:
            self._queue.put_nowait(update)
        except Full:
            with self._lock:
                self._dropped += 1
            _logger.warning(
                "market-data queue full; dropped update", extra={"symbol": update.symbol}
            )
