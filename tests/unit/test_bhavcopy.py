"""Tests for the NSE bhavcopy ingester (P3X.1b) — both historical layouts, on real rows."""

import io
import zipfile
from datetime import date, timedelta

import pandas as pd
import pytest

from quant.core.frames import BAR_COLUMNS
from quant.data.ingest.bhavcopy import (
    HttpBhavcopyFetcher,
    bhavcopy_url,
    parse_bhavcopy,
    to_canonical_bars,
)
from quant.data.store import serde

# Real rows lifted from the 2025-06-20 UDiFF and 2019-12-31 legacy bhavcopies, plus one
# fabricated non-EQ ("BE") row in each to prove the series filter drops it.
_UDIFF_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)
_UDIFF_CSV = "\n".join(
    [
        _UDIFF_HEADER,
        "2025-06-20,2025-06-20,CM,NSE,STK,16921,INE144J01027,20MICRONS,EQ,,,,,20 MICRONS LTD,"
        "225.29,227.99,221.17,224.00,224.65,225.29,,224.00,,,98100,22004616.78,3060,F1,1,,,,,",
        "2025-06-20,2025-06-20,CM,NSE,STK,4,INE253B01015,21STCENMGM,EQ,,,,,21ST CENTURY,"
        "66.74,67.40,65.00,66.37,65.10,66.08,,66.37,,,3861,256483.15,131,F1,1,,,,,",
        "2025-06-20,2025-06-20,CM,NSE,STK,9,INE000000000,TESTBE,BE,,,,,TEST BE LTD,"
        "10.0,11.0,9.0,10.5,10.4,10.0,,10.5,,,100,1000.0,5,F1,1,,,,,",
    ]
)
_LEGACY_HEADER = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,"
    "TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"
)
_LEGACY_CSV = "\n".join(
    [
        _LEGACY_HEADER,
        "20MICRONS,EQ,33.6,37.4,33.1,35.2,35.25,33.1,242285,8636712.9,31-DEC-2019,2089,INE144J01027,",
        "TESTBE,BE,10.0,11.0,9.0,10.5,10.4,10.0,100,1000.0,31-DEC-2019,5,INE000000000,",
    ]
)


def _zip(member: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    return buffer.getvalue()


def test_parse_udiff_real_row() -> None:
    parsed = parse_bhavcopy(_zip("BhavCopy_x.csv", _UDIFF_CSV), date(2025, 6, 20))
    row = parsed.set_index("symbol").loc["20MICRONS"]
    assert row["open"] == pytest.approx(225.29)
    assert row["high"] == pytest.approx(227.99)
    assert row["close"] == pytest.approx(224.00)
    assert row["volume"] == 98100
    assert row["trades"] == 3060
    assert row["isin"] == "INE144J01027"
    ts = row["timestamp"]
    assert ts.date() == date(2025, 6, 20)
    assert (ts.hour, ts.minute) == (15, 30)
    assert ts.utcoffset() == timedelta(hours=5, minutes=30)  # IST


def test_parse_legacy_real_row() -> None:
    parsed = parse_bhavcopy(_zip("cm31DEC2019bhav.csv", _LEGACY_CSV), date(2019, 12, 31))
    row = parsed.set_index("symbol").loc["20MICRONS"]
    assert row["open"] == pytest.approx(33.6)
    assert row["close"] == pytest.approx(35.2)
    assert row["volume"] == 242285
    assert row["isin"] == "INE144J01027"
    assert row["timestamp"].date() == date(2019, 12, 31)


@pytest.mark.parametrize(
    ("member", "csv"),
    [("BhavCopy_x.csv", _UDIFF_CSV), ("cm31DEC2019bhav.csv", _LEGACY_CSV)],
)
def test_series_filter_drops_non_eq(member: str, csv: str) -> None:
    parsed = parse_bhavcopy(_zip(member, csv), date(2020, 1, 1))
    assert "TESTBE" not in set(parsed["symbol"])  # the BE row is excluded
    assert set(parsed["series"]) == {"EQ"}


def test_to_canonical_bars_matches_schema() -> None:
    parsed = parse_bhavcopy(_zip("BhavCopy_x.csv", _UDIFF_CSV), date(2025, 6, 20))
    bars = to_canonical_bars(parsed)
    assert list(bars.columns) == list(BAR_COLUMNS)
    serde.ensure_bars_schema(bars)  # must not raise
    assert bars["volume"].dtype == "int64"
    assert isinstance(bars["timestamp"].dtype, pd.DatetimeTZDtype)


def test_bhavcopy_url_picks_layout_by_date() -> None:
    assert "BhavCopy_NSE_CM" in bhavcopy_url(date(2025, 6, 20))  # UDiFF era
    assert "cm31DEC2019bhav" in bhavcopy_url(date(2019, 12, 31))  # legacy era


def test_http_fetcher_falls_back_across_layouts() -> None:
    payload = _zip("BhavCopy_x.csv", _UDIFF_CSV)
    d = date(2025, 6, 20)
    primary = bhavcopy_url(d)

    def opener(url: str, timeout: float) -> bytes | None:
        return None if url == primary else payload  # 404 on UDiFF → fall back to legacy

    fetcher = HttpBhavcopyFetcher(opener=opener, retry_wait=0.0, max_retries=1)
    assert fetcher.fetch(d) == payload


def test_http_fetcher_returns_none_when_no_file() -> None:
    fetcher = HttpBhavcopyFetcher(opener=lambda url, timeout: None, retry_wait=0.0, max_retries=1)
    assert fetcher.fetch(date(2025, 6, 21)) is None  # Saturday — no bhavcopy
