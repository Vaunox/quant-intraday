"""NSE bhavcopy ingest — survivorship-bias-free daily EOD bars, including delisted names.

The Kite historical API resolves a symbol against the *live* instruments dump, so a
delisted/restructured name (HDFC, TATAMOTORS, LTIM, …) returns ``InstrumentNotFoundError``
and its history is unreachable — fatal for a factor backtest, whose whole premise is sorting on
the past. The daily **bhavcopy** is the opposite: a date-partitioned EOD archive in which a
delisted stock's bars live permanently in the files from the days it actually traded. Walking the
bhavcopy archive therefore reconstructs the full, survivorship-correct daily panel for free.

Two historical layouts are auto-detected by header:

* **legacy** (until ~2024-07): ``cm<DD><MON><YYYY>bhav.csv`` — ``SYMBOL, SERIES, OPEN…ISIN``.
* **UDiFF** (2024-07 on): ``BhavCopy_NSE_CM_…_F_0000.csv`` — ``TckrSymb, SctySrs, OpnPric…``.

Both carry **ISIN**, the identifier that survives ticker renames — the panel builder keys on it so
a renamed company stays one continuous series. The network fetch is confined behind an injected
opener (Ground Rule 1), so parsing is pure and unit-tested on real fixtures with no network.
"""

import io
import time as wallclock
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from datetime import date, datetime, time
from typing import Protocol, runtime_checkable

import pandas as pd

from quant.core.calendar import IST
from quant.core.frames import BAR_COLUMNS
from quant.core.logging import get_logger
from quant.data.ingest.errors import BhavcopyError
from quant.data.store import serde

_logger = get_logger(__name__)

#: The cutover date: UDiFF became the primary cash-market bhavcopy, legacy was retired. The fetcher
#: still falls back to the other layout on a 404, so a boundary mismatch self-heals.
UDIFF_CUTOVER = date(2024, 7, 8)

#: The daily bar's stamped close time (tz-aware IST), so the time axis matches intraday bars.
MARKET_CLOSE = time(15, 30)

#: Columns of the rich parsed frame (a superset of the canonical bars schema).
BHAVCOPY_COLUMNS: tuple[str, ...] = (
    "symbol",
    "isin",
    "series",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "trades",
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: A URL opener: returns the body bytes, or ``None`` when the resource is absent (HTTP 404).
UrlOpener = Callable[[str, float], bytes | None]


def _udiff_url(trade_date: date) -> str:
    """The UDiFF (2024-07+) bhavcopy URL for ``trade_date``."""
    return (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
    )


def _legacy_url(trade_date: date) -> str:
    """The legacy ``cm<DD><MON><YYYY>bhav.csv.zip`` URL for ``trade_date``."""
    mon = trade_date.strftime("%b").upper()
    return (
        "https://archives.nseindia.com/content/historical/EQUITIES/"
        f"{trade_date:%Y}/{mon}/cm{trade_date:%d}{mon}{trade_date:%Y}bhav.csv.zip"
    )


def bhavcopy_url(trade_date: date) -> str:
    """Return the date-appropriate bhavcopy URL (UDiFF on/after the cutover, else legacy)."""
    return _udiff_url(trade_date) if trade_date >= UDIFF_CUTOVER else _legacy_url(trade_date)


@runtime_checkable
class BhavcopyFetcher(Protocol):
    """Fetches the raw bhavcopy zip for a trading day, or ``None`` if NSE has no file."""

    def fetch(self, trade_date: date) -> bytes | None:
        """Return the bhavcopy zip bytes for ``trade_date``, or ``None`` (holiday/weekend)."""
        ...


class HttpBhavcopyFetcher:
    """Downloads bhavcopy zips from the NSE archive (browser UA + retry; layout fallback).

    The network call is delegated to an injected ``opener`` (default: a small ``urllib`` opener
    that sends a browser User-Agent — NSE 403s without one), so the fetcher is testable with a
    fake opener and no network. A 404 on the date-appropriate layout falls back to the other
    layout before concluding the day has no file.
    """

    def __init__(
        self,
        *,
        opener: UrlOpener | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_wait: float = 2.0,
    ) -> None:
        """Build the fetcher (all knobs optional; defaults suit a polite archive crawl)."""
        self._opener = opener if opener is not None else _urllib_opener
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._retry_wait = retry_wait

    def fetch(self, trade_date: date) -> bytes | None:
        """Return the bhavcopy zip for ``trade_date`` (trying both layouts), or ``None``."""
        primary = bhavcopy_url(trade_date)
        body = self._get(primary)
        if body is not None:
            return body
        fallback = (
            _legacy_url(trade_date) if trade_date >= UDIFF_CUTOVER else _udiff_url(trade_date)
        )
        return self._get(fallback)

    def _get(self, url: str) -> bytes | None:
        """GET ``url`` with retry on transient errors; ``None`` on 404; raise on exhaustion."""
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._opener(url, self._timeout)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                last = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = exc
            if attempt + 1 < self._max_retries:
                wallclock.sleep(self._retry_wait * (attempt + 1))
        raise BhavcopyError(f"failed to fetch {url} after {self._max_retries} attempts: {last}")


def parse_bhavcopy(
    zip_bytes: bytes, trade_date: date, *, series: Sequence[str] = ("EQ",)
) -> pd.DataFrame:
    """Parse a bhavcopy zip into a rich tidy frame (one row per traded equity name).

    Auto-detects the legacy vs UDiFF layout, keeps only the requested ``series`` (default the
    rolling-settlement ``EQ`` segment), and stamps every row's ``timestamp`` from the
    authoritative ``trade_date`` (not the file's own text date).

    Returns:
        A frame with :data:`BHAVCOPY_COLUMNS` (``symbol, isin, series, timestamp, OHLC, volume,
        value, trades``).

    Raises:
        BhavcopyError: If the zip holds no CSV or matches neither known schema.
    """
    raw = _read_csv_from_zip(zip_bytes)
    raw.columns = [str(c).strip() for c in raw.columns]
    if "TckrSymb" in raw.columns:
        frame = _parse_udiff(raw)
    elif "SYMBOL" in raw.columns and "SERIES" in raw.columns:
        frame = _parse_legacy(raw)
    else:
        raise BhavcopyError(f"unrecognised bhavcopy schema; columns={list(raw.columns)[:8]}")

    frame = frame[frame["series"].astype("string").str.strip().isin(set(series))].copy()
    frame["symbol"] = frame["symbol"].astype("string").str.strip()
    frame["isin"] = frame["isin"].astype("string").str.strip()
    frame["timestamp"] = datetime.combine(trade_date, MARKET_CLOSE, tzinfo=IST)
    for column in ("open", "high", "low", "close", "value"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")
    frame["trades"] = pd.to_numeric(frame["trades"], errors="coerce").fillna(0).astype("int64")
    return frame.loc[:, list(BHAVCOPY_COLUMNS)].reset_index(drop=True)


def to_canonical_bars(rich: pd.DataFrame) -> pd.DataFrame:
    """Narrow a rich bhavcopy frame (one symbol) to the canonical bars schema for the repo."""
    bars = rich.loc[:, ["symbol", *(c for c in BAR_COLUMNS if c != "symbol")]].copy()
    bars["symbol"] = bars["symbol"].astype("object")
    return serde.ensure_bars_schema(bars)


def _read_csv_from_zip(zip_bytes: bytes) -> pd.DataFrame:
    """Read the single CSV member of a bhavcopy zip into a DataFrame."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise BhavcopyError(f"bhavcopy zip has no CSV member: {archive.namelist()}")
            with archive.open(members[0]) as handle:
                return pd.read_csv(handle)
    except zipfile.BadZipFile as exc:
        raise BhavcopyError(f"corrupt bhavcopy zip: {exc}") from exc


def _parse_udiff(raw: pd.DataFrame) -> pd.DataFrame:
    """Map UDiFF (2024-07+) columns to the rich-frame names."""
    return pd.DataFrame(
        {
            "symbol": raw["TckrSymb"],
            "isin": raw["ISIN"],
            "series": raw["SctySrs"],
            "open": raw["OpnPric"],
            "high": raw["HghPric"],
            "low": raw["LwPric"],
            "close": raw["ClsPric"],
            "volume": raw["TtlTradgVol"],
            "value": raw["TtlTrfVal"],
            "trades": raw["TtlNbOfTxsExctd"],
        }
    )


def _parse_legacy(raw: pd.DataFrame) -> pd.DataFrame:
    """Map legacy ``cm…bhav.csv`` columns to the rich-frame names."""
    return pd.DataFrame(
        {
            "symbol": raw["SYMBOL"],
            "isin": raw["ISIN"],
            "series": raw["SERIES"],
            "open": raw["OPEN"],
            "high": raw["HIGH"],
            "low": raw["LOW"],
            "close": raw["CLOSE"],
            "volume": raw["TOTTRDQTY"],
            "value": raw["TOTTRDVAL"],
            "trades": raw["TOTALTRADES"],
        }
    )


def _urllib_opener(url: str, timeout: float) -> bytes | None:
    """Default opener: GET ``url`` with a browser UA; ``None`` on 404, raising otherwise."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
