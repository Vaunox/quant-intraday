"""Tests for the optional QuantStats tearsheet hook (P2.9).

QuantStats is a research-env tool absent from the engine/CI env, so the writer is injected: a
fake backend exercises the write path, and the default path fails loud with a clear dependency
error rather than silently skipping (the kill-gate verdict never depends on it).
"""

from pathlib import Path

import pandas as pd
import pytest

from quant.research.reports.errors import ReportDependencyError
from quant.research.reports.tearsheet import write_quantstats_tearsheet


def _returns() -> pd.Series:
    index = pd.date_range("2024-01-02", periods=5, freq="D", tz="Asia/Kolkata")
    return pd.Series([0.01, -0.005, 0.02, float("nan"), -0.01], index=index)


def test_write_tearsheet_uses_injected_writer(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_writer(returns: pd.Series, output_path: Path) -> None:
        captured["n"] = len(returns)  # NaNs dropped before the writer sees them
        captured["path"] = output_path
        output_path.write_text("<html>tearsheet</html>", encoding="utf-8")

    out = tmp_path / "nested" / "tearsheet.html"
    result = write_quantstats_tearsheet(_returns(), out, writer=fake_writer)
    assert result == out
    assert out.exists()  # parent dirs created
    assert captured["n"] == 4  # the NaN row was dropped
    assert captured["path"] == out


def test_write_tearsheet_without_quantstats_raises(tmp_path: Path) -> None:
    # No injected writer + QuantStats absent in the engine/CI env => fail loud.
    with pytest.raises(ReportDependencyError, match="QuantStats is not installed"):
        write_quantstats_tearsheet(_returns(), tmp_path / "t.html")
