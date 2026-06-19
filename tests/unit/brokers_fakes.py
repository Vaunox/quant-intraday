"""Shared fakes and sample data for the broker-adapter unit tests.

These let the whole P1.1 surface be exercised with no ``kiteconnect`` install, no
credentials, and no network: a :class:`FakeKiteClient` stands in for the SDK (behind
the ``KiteClient`` Protocol), a :class:`FakeClock` drives the rate limiter without
real time, and the sample builders provide recorded-shape instrument/candle rows.

Not a ``test_*`` module, so pytest does not collect it; imported by the broker tests.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

#: Real NSE instrument tokens for two liquid names (realistic fixture values).
RELIANCE_TOKEN = 738561
INFY_TOKEN = 408065


class FakeClock:
    """A deterministic monotonic clock whose ``sleep`` advances time."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class CountingRateLimiter:
    """A no-op rate limiter that records how many times it was acquired."""

    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


class FakeKiteClient:
    """A fake ``KiteClient``: canned responses, records calls, no SDK/network."""

    def __init__(
        self,
        *,
        instruments: list[dict[str, Any]] | None = None,
        candles: list[dict[str, Any]] | None = None,
        login_url: str = "https://kite.zerodha.com/connect/login?api_key=fake&v=3",
        session: dict[str, Any] | None = None,
    ) -> None:
        self._instruments = instruments if instruments is not None else sample_instruments()
        self._candles = candles if candles is not None else sample_candles()
        self._login_url = login_url
        self._session = session or {
            "access_token": "access-token-xyz",
            "user_id": "AB1234",
            "login_time": "2026-06-19 07:30:00",
        }
        self.access_token: str | None = None
        self.generate_session_calls: list[tuple[str, str]] = []
        self.historical_calls: list[dict[str, Any]] = []
        self.instruments_calls: list[str | None] = []

    def login_url(self) -> str:
        return self._login_url

    def generate_session(self, request_token: str, api_secret: str) -> dict[str, Any]:
        self.generate_session_calls.append((request_token, api_secret))
        return dict(self._session)

    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]:
        self.historical_calls.append(
            {
                "instrument_token": instrument_token,
                "from_date": from_date,
                "to_date": to_date,
                "interval": interval,
                "continuous": continuous,
                "oi": oi,
            }
        )
        return [dict(candle) for candle in self._candles]

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        self.instruments_calls.append(exchange)
        return [dict(row) for row in self._instruments]


def sample_instruments() -> list[dict[str, Any]]:
    """Return a small, recorded-shape NSE instruments dump (RELIANCE, INFY)."""
    return [
        {
            "instrument_token": RELIANCE_TOKEN,
            "exchange_token": "2885",
            "tradingsymbol": "RELIANCE",
            "name": "RELIANCE INDUSTRIES",
            "exchange": "NSE",
            "segment": "NSE",
            "instrument_type": "EQ",
            "lot_size": 1,
            "tick_size": 0.05,
        },
        {
            "instrument_token": INFY_TOKEN,
            "exchange_token": "1594",
            "tradingsymbol": "INFY",
            "name": "INFOSYS",
            "exchange": "NSE",
            "segment": "NSE",
            "instrument_type": "EQ",
            "lot_size": 1,
            "tick_size": 0.05,
        },
    ]


def sample_candles() -> list[dict[str, Any]]:
    """Return three recorded-shape minute candles with tz-aware IST timestamps."""
    base = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
    return [
        {"date": base, "open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0, "volume": 12000},
        {
            "date": base + timedelta(minutes=1),
            "open": 101.0,
            "high": 102.0,
            "low": 100.5,
            "close": 101.8,
            "volume": 9000,
        },
        {
            "date": base + timedelta(minutes=2),
            "open": 101.8,
            "high": 102.5,
            "low": 101.0,
            "close": 102.2,
            "volume": 15000,
        },
    ]
