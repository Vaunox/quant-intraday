"""Data-quality dashboard (Layer 1, P1.9): visibility into dataset health.

Aggregates the hygiene signals (gaps, bad-tick counts), session-level coverage, and
live-feed latency into a :class:`~quant.data.quality.report.DataQualityReport` that can be
rendered as a plain-text dashboard. Built via
:func:`~quant.data.quality.dashboard.create_data_quality_dashboard`.
"""

from quant.data.quality.dashboard import (
    DataQualityDashboard,
    create_data_quality_dashboard,
    summarize_feed_latency,
)
from quant.data.quality.report import (
    CoverageStats,
    DataQualityReport,
    FeedLatencyStats,
    SymbolQuality,
)

__all__ = [
    "CoverageStats",
    "DataQualityDashboard",
    "DataQualityReport",
    "FeedLatencyStats",
    "SymbolQuality",
    "create_data_quality_dashboard",
    "summarize_feed_latency",
]
