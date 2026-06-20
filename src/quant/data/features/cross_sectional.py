"""Cross-sectional features (Deep Dive #1 §2.2.F).

*"Rank a name's return/volume/volatility relative to its universe at each timestamp
(sector-neutral standardization). Cross-sectional signals (this stock vs its peers right
now) are often more robust intraday than pure time-series signals because they cancel
market-wide moves."*

These operate on a **panel**: a wide DataFrame indexed by timestamp with one column per
symbol, holding some metric (e.g. a return). They standardize *across symbols within each
timestamp* — contemporaneous, never forward-looking, so point-in-time correct (a row uses
only time-*t* values across names).
"""

from collections.abc import Mapping

import pandas as pd


def cross_sectional_rank(panel: pd.DataFrame) -> pd.DataFrame:
    """Return each symbol's cross-sectional percentile rank per timestamp, centred on 0.

    For every row (timestamp) the symbols are ranked into ``(-0.5, 0.5]`` (highest metric
    → ~+0.5). ``NaN`` metrics are left ``NaN`` (excluded from the ranking).
    """
    return panel.rank(axis=1, pct=True) - 0.5


def sector_neutral_zscore(panel: pd.DataFrame, sectors: Mapping[str, str]) -> pd.DataFrame:
    """Return the sector-neutral cross-sectional z-score per timestamp.

    Within each sector, at each timestamp, the metric is standardized
    ``(x - sector_mean) / sector_std`` across that sector's symbols — so the result
    measures a name relative to its *peers*, with market- and sector-wide moves removed.
    A sector with a single name (or a flat row) yields ``NaN`` (no dispersion to scale by).

    Args:
        panel: Wide metric frame (index = timestamp, columns = symbols).
        sectors: Map of every panel symbol to its sector.

    Raises:
        ValueError: If any panel column has no sector mapping.
    """
    missing = [symbol for symbol in panel.columns if symbol not in sectors]
    if missing:
        raise ValueError(f"symbols missing a sector mapping: {sorted(missing)}")

    result = pd.DataFrame(index=panel.index, columns=panel.columns, dtype="float64")
    members: dict[str, list[str]] = {}
    for symbol in panel.columns:
        members.setdefault(sectors[symbol], []).append(symbol)
    for symbols in members.values():
        block = panel[symbols]
        mean = block.mean(axis=1)
        std = block.std(axis=1)
        result[symbols] = block.sub(mean, axis=0).div(std.where(std != 0), axis=0)
    return result
