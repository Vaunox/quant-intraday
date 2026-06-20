"""Tests for the data-quality dashboard (P1.9) — surfaces issues on sample data."""

from datetime import date, datetime

import pandas as pd
import pytest

from quant.core.calendar import NSECalendar
from quant.core.config import load_config
from quant.data.hygiene.bad_ticks import BadTickFilter
from quant.data.hygiene.gaps import GapDetector
from quant.data.ingest.backfill import day_end, day_start
from quant.data.quality import (
    DataQualityDashboard,
    DataQualityReport,
    SymbolQuality,
    create_data_quality_dashboard,
    summarize_feed_latency,
)
from tests.unit.hygiene_fakes import at, bar, frame, good

# Mon / Tue / Wed — three consecutive trading days.
D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
D3 = date(2024, 6, 5)
START = day_start(D1)
END = day_end(D3)
CALENDAR = NSECalendar(frozenset())


def _dashboard() -> DataQualityDashboard:
    return DataQualityDashboard(
        CALENDAR, GapDetector(CALENDAR, interval_minutes=1), BadTickFilter(max_move_pct=20.0)
    )


def _clean_bars() -> pd.DataFrame:
    """Three full sessions, contiguous minute bars — no quality issues."""
    bars = []
    for day in (D1, D2, D3):
        bars += [good("GOOD", at(day, 9, 15 + i), 100.0 + i) for i in range(3)]
    return frame(bars)


def _problem_bars() -> pd.DataFrame:
    """D2 missing entirely; an intraday gap on D1; a bad (zero-price) tick on D3."""
    return frame(
        [
            good("BAD", at(D1, 9, 15), 100.0),
            good("BAD", at(D1, 9, 17), 100.0),  # 09:16 missing -> intraday gap
            good("BAD", at(D3, 9, 15), 100.0),
            bar("BAD", at(D3, 9, 16), o=100, h=100, lo=0, c=0, v=10),  # zero price -> bad tick
        ]
    )


def _by_symbol(report: DataQualityReport) -> dict[str, SymbolQuality]:
    return {symbol.symbol: symbol for symbol in report.symbols}


# ---------------------------------------------------------------- clean vs issues


def test_clean_data_has_no_issues() -> None:
    report = _dashboard().assess({"GOOD": _clean_bars()}, start=START, end=END)
    assert report.ok
    good_quality = _by_symbol(report)["GOOD"]
    assert not good_quality.has_issues
    assert good_quality.coverage.is_complete
    assert good_quality.coverage.observed_sessions == 3
    assert good_quality.intraday_gaps == 0
    assert good_quality.bad_ticks == 0


def test_surfaces_all_issue_kinds() -> None:
    report = _dashboard().assess({"BAD": _problem_bars()}, start=START, end=END)
    assert not report.ok
    bad = _by_symbol(report)["BAD"]
    assert bad.has_issues
    assert bad.coverage.expected_sessions == 3
    assert bad.coverage.observed_sessions == 2  # D2 absent
    assert bad.missing_days == 1  # D2
    assert bad.intraday_gaps == 1  # 09:16 on D1
    assert bad.bad_ticks == 1  # the zero-price bar on D3


def test_report_aggregates_and_lists_issue_symbols() -> None:
    report = _dashboard().assess(
        {"GOOD": _clean_bars(), "BAD": _problem_bars()}, start=START, end=END
    )
    assert [s.symbol for s in report.symbols] == ["BAD", "GOOD"]  # sorted
    assert [s.symbol for s in report.symbols_with_issues] == ["BAD"]
    assert report.total_intraday_gaps == 1
    assert report.total_missing_days == 1
    assert report.total_bad_ticks == 1


def test_empty_symbol_is_incomplete_coverage() -> None:
    report = _dashboard().assess({"EMPTY": frame([])}, start=START, end=END)
    empty = _by_symbol(report)["EMPTY"]
    assert empty.coverage.observed_sessions == 0
    assert empty.coverage.observed_bars == 0
    assert empty.coverage.first_bar is None
    assert empty.has_issues  # nothing where three sessions were expected


# --------------------------------------------------------------------- coverage


def test_coverage_fraction() -> None:
    report = _dashboard().assess({"BAD": _problem_bars()}, start=START, end=END)
    coverage = _by_symbol(report)["BAD"].coverage
    assert coverage.session_coverage == pytest.approx(2 / 3)
    assert coverage.first_bar == at(D1, 9, 15)
    assert coverage.last_bar == at(D3, 9, 16)


def test_no_expected_sessions_is_full_coverage() -> None:
    # A window with no trading days (a weekend) expects nothing -> trivially complete.
    saturday, sunday = date(2024, 6, 1), date(2024, 6, 2)
    report = _dashboard().assess({"X": frame([])}, start=day_start(saturday), end=day_end(sunday))
    coverage = _by_symbol(report)["X"].coverage
    assert coverage.expected_sessions == 0
    assert coverage.session_coverage == 1.0
    assert coverage.is_complete
    assert report.ok


# ---------------------------------------------------------------- feed latency


def test_summarize_feed_latency_stats() -> None:
    stats = summarize_feed_latency([0.1, 0.2, 0.3, 0.4])
    assert stats is not None
    assert stats.samples == 4
    assert stats.mean_seconds == pytest.approx(0.25)
    assert stats.max_seconds == pytest.approx(0.4)


def test_summarize_feed_latency_empty_is_none() -> None:
    assert summarize_feed_latency(None) is None
    assert summarize_feed_latency([]) is None


def test_assess_includes_feed_latency() -> None:
    report = _dashboard().assess(
        {"GOOD": _clean_bars()}, start=START, end=END, latency_samples=[0.1, 0.2, 0.5]
    )
    assert report.feed_latency is not None
    assert report.feed_latency.samples == 3


# ------------------------------------------------------------------- rendering


def test_render_dashboard_text() -> None:
    report = _dashboard().assess(
        {"GOOD": _clean_bars(), "BAD": _problem_bars()},
        start=START,
        end=END,
        latency_samples=[0.1, 0.2],
    )
    rendered = report.render()
    assert "Data Quality Report" in rendered
    assert "BAD" in rendered and "ISSUES" in rendered
    assert "GOOD" in rendered and "ok" in rendered
    assert "feed latency:" in rendered


# ------------------------------------------------------------------- validation


def test_naive_bounds_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _dashboard().assess({"GOOD": _clean_bars()}, start=datetime(2024, 6, 3), end=END)


def test_start_after_end_rejected() -> None:
    with pytest.raises(ValueError, match="after end"):
        _dashboard().assess({"GOOD": _clean_bars()}, start=END, end=START)


# ---------------------------------------------------------------------- factory


def test_factory_builds_from_config() -> None:
    dashboard = create_data_quality_dashboard(load_config(environ={}), NSECalendar(frozenset()))
    report = dashboard.assess({"GOOD": _clean_bars()}, start=START, end=END)
    assert report.ok


def test_expected_sessions_skips_weekend() -> None:
    # Fri -> Mon spans a weekend: only 2 trading days expected.
    friday, monday = date(2024, 5, 31), date(2024, 6, 3)
    bars = frame([good("X", at(friday, 9, 15), 100.0), good("X", at(monday, 9, 15), 100.0)])
    report = _dashboard().assess({"X": bars}, start=day_start(friday), end=day_end(monday))
    coverage = _by_symbol(report)["X"].coverage
    assert coverage.expected_sessions == 2  # Sat/Sun excluded
    assert coverage.is_complete
