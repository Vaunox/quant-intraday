"""The QuantStats tearsheet (Deep Dive #2 §4b.8 — "Tearsheets: QuantStats / pyfolio").

The validation report's optional companion: a rich HTML tearsheet (30+ metrics, drawdowns,
rolling stats) over the walk-forward equity curve. QuantStats is an **operator-installed,
research-env** tool — like MLflow and ArcticDB it is heavy and pins its own deps, so it is
**lazy-imported behind a single function** and is never a declared engine dependency. The
trade/don't-trade decision (the kill-gate verdict) never depends on it; the tearsheet is
supplementary colour for the operator's review.
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from quant.core.logging import get_logger
from quant.research.reports.errors import ReportDependencyError

_logger = get_logger(__name__)

#: A tearsheet writer: ``(periodic returns, output html path) -> None``.
TearsheetWriter = Callable[[pd.Series, Path], None]


def write_quantstats_tearsheet(
    returns: pd.Series,
    output_path: Path,
    *,
    writer: TearsheetWriter | None = None,
    title: str = "strategy",
) -> Path:
    """Write an HTML tearsheet of ``returns`` to ``output_path``; return the path.

    Args:
        returns: The strategy's periodic returns (e.g. the walk-forward equity curve's per-bar
            returns), indexed by timestamp.
        output_path: Where the HTML tearsheet is written (parent dirs created).
        writer: The backend writer (injected in tests). Defaults to the real QuantStats writer,
            which is the single, lazy ``quantstats`` import site.
        title: The tearsheet title.

    Returns:
        ``output_path``.

    Raises:
        ReportDependencyError: If ``writer`` is omitted and ``quantstats`` is not installed.
    """
    backend = writer or _quantstats_writer(title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backend(returns.dropna(), output_path)
    _logger.info("tearsheet written", extra={"path": str(output_path), "title": title})
    return output_path


def _quantstats_writer(title: str) -> TearsheetWriter:
    """Return the real QuantStats HTML writer — the single, lazy ``quantstats`` import site."""
    try:
        import quantstats
    except ImportError as exc:
        # Reachable (and tested) in the engine/CI env, where QuantStats is absent.
        raise ReportDependencyError(
            "QuantStats is not installed. It is an optional, research-env tearsheet backend "
            "(like MLflow/ArcticDB); install it in the research env to emit the HTML tearsheet, "
            "or skip it — the kill-gate verdict does not depend on it."
        ) from exc

    def write(returns: pd.Series, output_path: Path) -> None:  # pragma: no cover - needs quantstats
        quantstats.reports.html(returns, output=str(output_path), title=title)

    return write  # pragma: no cover - needs quantstats
