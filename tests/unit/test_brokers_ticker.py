"""Tests for KiteTickerTransport and its factory (P1.2, SDK-confined)."""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from quant.core.interfaces import TickerTransport
from quant.data.brokers.ticker import KiteTickerTransport, create_kite_ticker_transport
from tests.unit.brokers_fakes import INFY_TOKEN, RELIANCE_TOKEN
from tests.unit.stream_fakes import FakeRawTicker


class SpyListener:
    """Records the listener callbacks the transport forwards."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def on_connect(self) -> None:
        self.events.append(("connect",))

    def on_ticks(self, raw_ticks: Sequence[Mapping[str, Any]]) -> None:
        self.events.append(("ticks", list(raw_ticks)))

    def on_reconnect(self, attempt: int) -> None:
        self.events.append(("reconnect", attempt))

    def on_close(self, code: int | None, reason: str | None) -> None:
        self.events.append(("close", code, reason))

    def on_error(self, code: int | None, reason: str | None) -> None:
        self.events.append(("error", code, reason))


def test_transport_conforms_to_protocol() -> None:
    assert isinstance(KiteTickerTransport(FakeRawTicker()), TickerTransport)


def test_start_connects_on_background_thread() -> None:
    raw = FakeRawTicker()
    KiteTickerTransport(raw).start()
    assert raw.connected is True
    assert raw.threaded is True


def test_stop_stops_ticker() -> None:
    raw = FakeRawTicker()
    KiteTickerTransport(raw).stop()
    assert raw.stopped is True


def test_subscribe_sets_full_mode_for_tokens() -> None:
    raw = FakeRawTicker()
    KiteTickerTransport(raw).subscribe([RELIANCE_TOKEN, INFY_TOKEN])
    assert raw.subscribed == [[RELIANCE_TOKEN, INFY_TOKEN]]
    assert raw.modes == [("full", [RELIANCE_TOKEN, INFY_TOKEN])]


def test_subscribe_uses_configured_mode() -> None:
    raw = FakeRawTicker()
    KiteTickerTransport(raw, mode="quote").subscribe([RELIANCE_TOKEN])
    assert raw.modes == [("quote", [RELIANCE_TOKEN])]


def test_sdk_callbacks_forward_to_listener() -> None:
    raw = FakeRawTicker()
    transport = KiteTickerTransport(raw)
    spy = SpyListener()
    transport.set_listener(spy)

    # The SDK invokes its callbacks as cb(ws, ...); the transport drops ws and
    # translates to the listener's SDK-agnostic signature.
    raw.on_connect(raw, {"type": "connect"})
    raw.on_ticks(raw, [{"instrument_token": 1}])
    raw.on_reconnect(raw, 3)
    raw.on_close(raw, 1006, "abnormal")
    raw.on_error(raw, 0, "boom")

    assert spy.events == [
        ("connect",),
        ("ticks", [{"instrument_token": 1}]),
        ("reconnect", 3),
        ("close", 1006, "abnormal"),
        ("error", 0, "boom"),
    ]


def test_callbacks_are_safe_before_a_listener_is_set() -> None:
    raw = FakeRawTicker()
    KiteTickerTransport(raw)  # wires forwarders but no listener yet
    raw.on_connect(raw, {})  # must not raise
    raw.on_ticks(raw, [])


def test_factory_builds_ticker_with_reconnect_config(monkeypatch: pytest.MonkeyPatch) -> None:
    kite = pytest.importorskip("kiteconnect")
    captured: dict[str, Any] = {}

    class FakeKiteTicker:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(kite, "KiteTicker", FakeKiteTicker)
    transport = create_kite_ticker_transport(
        "api-key",
        "access-token",
        reconnect_max_tries=10,
        reconnect_max_delay_seconds=15,
        connect_timeout_seconds=20,
    )
    assert isinstance(transport, KiteTickerTransport)
    assert captured == {
        "api_key": "api-key",
        "access_token": "access-token",
        "reconnect": True,
        "reconnect_max_tries": 10,
        "reconnect_max_delay": 15,
        "connect_timeout": 20,
    }


def test_factory_passes_root_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    kite = pytest.importorskip("kiteconnect")
    captured: dict[str, Any] = {}

    class FakeKiteTicker:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(kite, "KiteTicker", FakeKiteTicker)
    create_kite_ticker_transport("k", "tok", root="wss://ws.example")
    assert captured["root"] == "wss://ws.example"
