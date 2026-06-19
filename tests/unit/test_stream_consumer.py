"""Tests for the live-stream consumer + tick parsing (P1.2)."""

from datetime import datetime
from queue import Queue
from zoneinfo import ZoneInfo

import pytest

from quant.core.interfaces import StreamListener, TickerTransport
from quant.core.types import DepthLevel, MarketUpdate
from quant.data.ingest.stream import TickStreamConsumer, parse_market_update
from tests.unit.brokers_fakes import INFY_TOKEN, RELIANCE_TOKEN, FakeClock
from tests.unit.stream_fakes import FakeTickerTransport, sample_full_tick, sample_ltp_tick

IST = ZoneInfo("Asia/Kolkata")
FIXED_NOW = datetime(2026, 6, 18, 9, 17, 0, tzinfo=IST)
TOKEN_TO_SYMBOL = {RELIANCE_TOKEN: "RELIANCE", INFY_TOKEN: "INFY"}


def _consumer(
    *, queue: Queue[MarketUpdate] | None = None, stale: float = 60.0
) -> tuple[TickStreamConsumer, FakeTickerTransport, FakeClock]:
    transport = FakeTickerTransport()
    clock = FakeClock()
    consumer = TickStreamConsumer(
        transport,
        TOKEN_TO_SYMBOL,
        queue=queue,
        stale_timeout_seconds=stale,
        clock=clock.monotonic,
        now=lambda: FIXED_NOW,
    )
    return consumer, transport, clock


# ------------------------------------------------------------------- parsing
def test_parse_full_tick_yields_tick_and_depth() -> None:
    update = parse_market_update(sample_full_tick(), "RELIANCE")

    assert update.symbol == "RELIANCE"
    assert update.tick.last_price == 101.5
    assert update.tick.last_quantity == 12
    assert update.tick.volume == 250000
    # naive IST timestamp from the SDK is localised to IST.
    assert update.tick.timestamp == datetime(2026, 6, 18, 9, 16, tzinfo=IST)

    assert update.depth is not None
    assert len(update.depth.bids) == 5
    assert len(update.depth.asks) == 5
    assert update.depth.bids[0] == DepthLevel(price=101.45, quantity=100, orders=3)
    assert update.depth.best_bid is not None and update.depth.best_bid.price == 101.45
    assert update.depth.best_ask is not None and update.depth.best_ask.price == 101.5
    # MarketUpdate delegates symbol/timestamp to its tick.
    assert update.symbol == update.tick.symbol
    assert update.timestamp == update.tick.timestamp


def test_parse_uses_wallclock_when_no_timestamp() -> None:
    # No exchange timestamp and no injected fallback -> the default IST wall clock.
    update = parse_market_update(sample_ltp_tick(), "INFY")
    assert update.depth is None
    assert update.tick.timestamp.tzinfo is not None


def test_parse_rejects_non_datetime_timestamp() -> None:
    raw = sample_ltp_tick()
    raw["timestamp"] = "2026-06-18T09:16:00"  # a string, not a datetime
    with pytest.raises(TypeError, match="datetime"):
        parse_market_update(raw, "INFY")


def test_parse_ltp_tick_has_no_depth_and_uses_fallback_time() -> None:
    update = parse_market_update(sample_ltp_tick(), "INFY", fallback_now=lambda: FIXED_NOW)

    assert update.depth is None
    assert update.tick.last_price == 1500.0
    assert update.tick.last_quantity == 0  # absent in ltp payload -> default
    assert update.tick.volume == 0
    assert update.tick.timestamp == FIXED_NOW  # no exchange timestamp -> receipt time


def test_parse_tolerates_volume_traded_key() -> None:
    raw = sample_ltp_tick()
    raw["volume_traded"] = 777  # older SDK key
    assert parse_market_update(raw, "INFY", fallback_now=lambda: FIXED_NOW).tick.volume == 777


# ------------------------------------------------------------- protocol wiring
def test_consumer_is_a_stream_listener() -> None:
    consumer, _, _ = _consumer()
    assert isinstance(consumer, StreamListener)


def test_fake_transport_is_a_ticker_transport() -> None:
    assert isinstance(FakeTickerTransport(), TickerTransport)


def test_start_registers_listener_and_opens_transport() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    assert transport.started
    assert transport.listener is consumer
    assert consumer.seconds_since_last_activity(now=0.0) == 0.0


def test_stop_closes_transport() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    consumer.stop()
    assert transport.stopped


# ------------------------------------------------------- subscribe / resubscribe
def test_subscribes_full_token_set_on_connect() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    transport.fire_connect()
    assert transport.subscribed == [[RELIANCE_TOKEN, INFY_TOKEN]]


def test_resubscribes_on_each_reconnect() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    transport.fire_connect()  # initial
    transport.fire_reconnect(1)  # auto-reconnect attempt (logs only)
    transport.fire_connect()  # reconnected -> resubscribe
    assert transport.subscribed == [
        [RELIANCE_TOKEN, INFY_TOKEN],
        [RELIANCE_TOKEN, INFY_TOKEN],
    ]


# ------------------------------------------------------------------- ticks -> queue
def test_ticks_are_parsed_and_enqueued() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    transport.fire_ticks([sample_full_tick(RELIANCE_TOKEN)])

    update = consumer.queue.get_nowait()
    assert update.symbol == "RELIANCE"
    assert update.depth is not None
    assert consumer.queue.empty()


def test_unknown_token_is_dropped_and_counted() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    transport.fire_ticks([sample_full_tick(999999)])  # not in the token map
    assert consumer.queue.empty()
    assert consumer.unknown_tokens == 1


def test_full_queue_drops_loudly_without_blocking() -> None:
    bounded: Queue[MarketUpdate] = Queue(maxsize=1)
    consumer, transport, _ = _consumer(queue=bounded)
    consumer.start()
    transport.fire_ticks([sample_full_tick(RELIANCE_TOKEN), sample_full_tick(INFY_TOKEN)])
    assert bounded.qsize() == 1
    assert consumer.dropped == 1


def test_close_and_error_callbacks_do_not_raise() -> None:
    consumer, transport, _ = _consumer()
    consumer.start()
    transport.fire_close(1006, "abnormal")
    transport.fire_error(0, "boom")  # smoke: must not propagate


# ------------------------------------------------------------------- heartbeat
def test_not_stale_before_start() -> None:
    consumer, _, _ = _consumer(stale=30.0)
    assert consumer.seconds_since_last_activity(now=100.0) is None
    assert consumer.is_stale(now=100.0) is False


def test_staleness_tracks_last_activity() -> None:
    consumer, transport, clock = _consumer(stale=30.0)
    consumer.start()  # activity at clock()=0
    assert consumer.is_stale(now=10.0) is False
    assert consumer.is_stale(now=31.0) is True

    clock.now = 20.0  # a tick arrives later -> resets the window
    transport.fire_ticks([sample_full_tick(RELIANCE_TOKEN)])
    assert consumer.is_stale(now=40.0) is False  # 40 - 20 = 20 < 30
    assert consumer.is_stale(now=51.0) is True  # 51 - 20 = 31 > 30


def test_check_heartbeat_returns_staleness() -> None:
    consumer, _, _ = _consumer(stale=30.0)
    consumer.start()
    assert consumer.check_heartbeat(now=10.0) is False
    assert consumer.check_heartbeat(now=31.0) is True
