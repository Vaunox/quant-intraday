"""Tests for symbol -> instrument-token resolution (P1.1)."""

import pytest

from quant.data.brokers.errors import InstrumentNotFoundError
from quant.data.brokers.instruments import InstrumentRegistry
from tests.unit.brokers_fakes import INFY_TOKEN, RELIANCE_TOKEN, FakeKiteClient, sample_instruments


def test_resolves_known_symbols() -> None:
    registry = InstrumentRegistry(sample_instruments())
    assert registry.token_for("RELIANCE", "NSE") == RELIANCE_TOKEN
    assert registry.token_for("INFY", "NSE") == INFY_TOKEN
    assert len(registry) == 2


def test_unknown_symbol_raises() -> None:
    registry = InstrumentRegistry(sample_instruments())
    with pytest.raises(InstrumentNotFoundError, match="NOPE"):
        registry.token_for("NOPE", "NSE")


def test_wrong_exchange_raises() -> None:
    registry = InstrumentRegistry(sample_instruments())
    with pytest.raises(InstrumentNotFoundError):
        registry.token_for("RELIANCE", "BSE")


def test_from_client_fetches_and_indexes() -> None:
    client = FakeKiteClient(instruments=sample_instruments())
    registry = InstrumentRegistry.from_client(client, exchange="NSE")
    assert registry.token_for("RELIANCE", "NSE") == RELIANCE_TOKEN
    assert client.instruments_calls == ["NSE"]  # restricted to the requested exchange


def test_duplicate_rows_last_wins() -> None:
    rows = [
        {"exchange": "NSE", "tradingsymbol": "DUP", "instrument_token": 1},
        {"exchange": "NSE", "tradingsymbol": "DUP", "instrument_token": 2},
    ]
    registry = InstrumentRegistry(rows)
    assert registry.token_for("DUP", "NSE") == 2
