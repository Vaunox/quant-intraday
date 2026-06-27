#!/usr/bin/env python
"""P3X.1e — fetch NSE corporate actions (splits & bonuses) for panel back-adjustment.

The split/bonus *adjustment factor* is read from the price series itself (P3X.1e adjuster); this
script only needs the **list of ex-dates** that are splits or bonuses. It pulls them from NSE's
corporate-actions JSON API (cookie-seeded, queried in quarter windows so no window is truncated),
keeps the rows whose ``subject`` says "split"/"bonus", and writes
``data/nifty_panel/corporate_actions.csv`` (git-ignored). Dividends/interest are ignored — they are
small and price-momentum factors are computed on price, not total return.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HOME = "https://www.nseindia.com/"
_API = "https://www.nseindia.com/api/corporates-corporateActions"


def make_opener() -> urllib.request.OpenerDirector:
    """Build a cookie-seeded opener (the homepage 403s but still sets the auth cookie)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", _USER_AGENT),
        ("Accept", "application/json"),
        ("Referer", _HOME),
    ]
    with contextlib.suppress(urllib.error.HTTPError):
        opener.open(_HOME, timeout=20).read()  # 403 expected; the cookie is set regardless
    return opener


def quarter_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into calendar-quarter windows (the API truncates long ranges)."""
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, 1 + 3 * ((start.month - 1) // 3), 1)
    while cursor <= end:
        q_end_month = cursor.month + 2
        q_end = date(cursor.year + (q_end_month // 12), (q_end_month % 12) + 1, 1)
        last_day = min(end, date.fromordinal(q_end.toordinal() - 1))
        windows.append((max(start, cursor), last_day))
        cursor = q_end
    return windows


def fetch_window(
    opener: urllib.request.OpenerDirector, start: date, end: date
) -> list[dict[str, Any]]:
    """Fetch the equities corporate-action rows for one window."""
    url = f"{_API}?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"
    with opener.open(url, timeout=40) as response:
        payload = json.loads(response.read())
    return payload if isinstance(payload, list) else []


def main() -> int:
    """Fetch all split/bonus ex-dates over the window and write the corporate-actions CSV."""
    parser = argparse.ArgumentParser(
        description="Fetch NSE split/bonus corporate actions (P3X.1e)."
    )
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument(
        "--out", default=str(_REPO_ROOT / "data" / "nifty_panel" / "corporate_actions.csv")
    )
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    opener = make_opener()

    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    windows = quarter_windows(start, end)
    for i, (w_start, w_end) in enumerate(windows):
        if i and i % 8 == 0:
            opener = make_opener()  # refresh the cookie periodically
        try:
            events = fetch_window(opener, w_start, w_end)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  [WARN] {w_start}..{w_end} failed: {exc}; retrying with fresh cookie")
            opener = make_opener()
            try:
                events = fetch_window(opener, w_start, w_end)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc2:
                print(f"  [WARN] {w_start}..{w_end} failed again: {exc2}; skipping")
                continue
        for event in events:
            subject = str(event.get("subject", "")).strip()
            lowered = subject.lower()
            action = "split" if "split" in lowered else "bonus" if "bonus" in lowered else None
            if action is None:
                continue
            symbol = str(event.get("symbol", "")).strip()
            ex_raw = str(event.get("exDate", "")).strip()
            try:
                ex_iso = _to_iso(ex_raw)
            except ValueError:
                continue
            rows[(symbol, ex_iso, action)] = {
                "symbol": symbol,
                "isin": str(event.get("isin", "")).strip(),
                "ex_date": ex_iso,
                "action": action,
                "subject": subject,
            }
        print(
            f"  {w_start}..{w_end}: {len(events)} events, {len(rows)} split/bonus so far",
            flush=True,
        )
        time.sleep(args.delay)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["ex_date"], r["symbol"]))
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["symbol", "isin", "ex_date", "action", "subject"]
        )
        writer.writeheader()
        writer.writerows(ordered)
    print(f"wrote {len(ordered)} split/bonus events -> {out_path}")
    return 0


def _to_iso(nse_date: str) -> str:
    """Convert an NSE ``DD-Mon-YYYY`` ex-date to ISO ``YYYY-MM-DD``."""
    return time.strftime("%Y-%m-%d", time.strptime(nse_date, "%d-%b-%Y"))


if __name__ == "__main__":
    raise SystemExit(main())
