"""Cross-sectional forward-return labeling (Phase 3X.3).

The label this monthly factor strategy actually predicts — it replaces the intraday
triple-barrier (no CUSUM, no barriers). At each monthly rebalance date *d*, for every name in
the **point-in-time universe** as of *d*:

* **forward total return** over the next ``horizon`` sessions (``close[d+h]/close[d] - 1``) — the
  regression target;
* its **cross-sectional decile rank** within that date's universe — the classification target.

The labels are strictly forward-looking (they use prices *after* the decision close, exactly like
the triple-barrier's own resolution — the leakage rule constrains *features*, not labels) and the
cross-sectional rank is computed **only within the point-in-time universe** so a name is never
ranked against peers it could not have been compared to on the day. ``label_times`` records each
rebalance's span ``t0 = d -> t1 = d + horizon`` so the purged/embargoed splitters (P3X.5) can
remove the overlap between consecutive monthly labels (AFML ch. 3-4; sample weighting still
applies to the overlapping spans).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.research.labeling.errors import LabelingInputError


@dataclass(frozen=True, slots=True)
class CrossSectionalLabels:
    """Monthly cross-sectional labels for a price panel.

    All three frames/series are indexed by the **valid** rebalance dates (those with a full
    ``horizon`` of forward data); ``forward_return`` / ``decile_rank`` columns are the panel's
    symbols, ``NaN`` outside the point-in-time universe or where forward data is missing.
    """

    forward_return: pd.DataFrame  # index=rebalance date, cols=symbol; horizon-session fwd return
    decile_rank: pd.DataFrame  # index=rebalance date, cols=symbol; 0..n_quantiles-1 within universe
    label_times: pd.Series  # index=t0 (rebalance date) -> value=t1 (exit date), for purge/embargo
    horizon: int
    n_quantiles: int

    @property
    def rebalance_dates(self) -> pd.DatetimeIndex:
        """The valid rebalance dates (t0) carried by the labels."""
        return pd.DatetimeIndex(self.forward_return.index)


def month_end_rebalance_dates(trading_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the last trading session of each calendar month in ``trading_dates``.

    Raises:
        LabelingInputError: If ``trading_dates`` is not a sorted, unique DatetimeIndex.
    """
    if not isinstance(trading_dates, pd.DatetimeIndex):
        raise LabelingInputError("trading_dates must be a DatetimeIndex")
    if not trading_dates.is_monotonic_increasing or not trading_dates.is_unique:
        raise LabelingInputError("trading_dates must be sorted and unique")
    positions = pd.Series(np.arange(len(trading_dates)), index=trading_dates)
    last_pos = positions.groupby([trading_dates.year, trading_dates.month]).max()
    return trading_dates[np.sort(last_pos.to_numpy())]


def forward_total_return(
    close_panel: pd.DataFrame, rebalance_dates: pd.DatetimeIndex, *, horizon: int
) -> pd.DataFrame:
    """Forward ``horizon``-session total return per ``(rebalance_date, symbol)``.

    Value = ``close[d+horizon] / close[d] - 1``. Rebalance dates without a full ``horizon`` of
    forward data (the last ones in the sample) yield an all-``NaN`` row.

    Raises:
        LabelingInputError: If ``horizon < 1``, the panel index is not sorted/unique, or any
            rebalance date is not a panel row.
    """
    if horizon < 1:
        raise LabelingInputError(f"horizon must be >= 1, got {horizon}")
    index = close_panel.index
    if not isinstance(index, pd.DatetimeIndex):
        raise LabelingInputError("close_panel must be indexed by a DatetimeIndex")
    if not index.is_monotonic_increasing or not index.is_unique:
        raise LabelingInputError("close_panel index must be sorted and unique")
    pos = index.get_indexer(rebalance_dates)
    if (pos < 0).any():
        raise LabelingInputError("every rebalance date must be a row in close_panel")

    n = len(index)
    exit_pos = pos + horizon
    valid = exit_pos < n
    values = close_panel.to_numpy(dtype="float64")
    entry = values[pos]
    exit_rows = values[np.clip(exit_pos, 0, n - 1)]
    fwd = exit_rows / entry - 1.0
    fwd[~valid] = np.nan  # no full forward window at the tail
    return pd.DataFrame(fwd, index=pd.DatetimeIndex(rebalance_dates), columns=close_panel.columns)


def cross_sectional_decile(panel: pd.DataFrame, *, n_quantiles: int = 10) -> pd.DataFrame:
    """Return each row's cross-sectional decile (``0 = lowest`` .. ``n_quantiles-1 = highest``).

    Ranks are computed within each row over its non-``NaN`` entries only (i.e. within the
    point-in-time universe, once non-members are masked to ``NaN``); ``NaN`` entries stay ``NaN``.
    A row with fewer than ``n_quantiles`` valid names still bins by percentile rank.

    Raises:
        LabelingInputError: If ``n_quantiles < 2``.
    """
    if n_quantiles < 2:
        raise LabelingInputError(f"n_quantiles must be >= 2, got {n_quantiles}")
    pct = panel.rank(axis=1, pct=True).to_numpy()  # (0, 1] within each row's valid entries
    decile = np.clip(np.ceil(pct * n_quantiles) - 1.0, 0.0, float(n_quantiles - 1))
    return pd.DataFrame(decile, index=panel.index, columns=panel.columns)


def build_cross_sectional_labels(
    close_panel: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    horizon: int = 21,
    n_quantiles: int = 10,
    universe_mask: pd.DataFrame | None = None,
) -> CrossSectionalLabels:
    """Assemble forward-return + decile-rank labels at each rebalance date, within the PIT universe.

    Args:
        close_panel: (adjusted) close prices, index = sorted trading dates, columns = symbols.
        rebalance_dates: the monthly decision dates (a subset of ``close_panel`` rows).
        horizon: forward holding horizon in sessions (the label window; default 21 ≈ 1 month).
        n_quantiles: cross-sectional buckets for the rank target (default 10 = deciles).
        universe_mask: optional (rebalance_date x symbol) bool — ``True`` where the symbol is in
            the point-in-time universe at that date. Non-members are masked to ``NaN`` *before*
            ranking, so the decile is computed within the universe only. If omitted, every name
            with a defined forward return is in-universe.

    Returns:
        A :class:`CrossSectionalLabels` over the rebalance dates that have a full forward window.

    Raises:
        LabelingInputError: On a misaligned universe mask or an empty valid set.
    """
    fwd = forward_total_return(close_panel, rebalance_dates, horizon=horizon)

    if universe_mask is not None:
        aligned = universe_mask.reindex(index=fwd.index, columns=fwd.columns)
        if bool(aligned.isna().all().all()):
            raise LabelingInputError(
                "universe_mask does not align to the rebalance dates / symbols"
            )
        fwd = fwd.where(aligned.fillna(False).to_numpy())

    # Keep only rebalance dates with at least one labelable name (drops the no-forward-data tail).
    valid_rows = fwd.notna().any(axis=1)
    fwd = fwd.loc[valid_rows]
    if fwd.empty:
        raise LabelingInputError("no rebalance date has a full forward window with universe names")

    decile = cross_sectional_decile(fwd, n_quantiles=n_quantiles)

    index = close_panel.index
    pos = index.get_indexer(pd.DatetimeIndex(fwd.index))
    exit_dates = index[pos + horizon]
    label_times = pd.Series(exit_dates, index=pd.DatetimeIndex(fwd.index), name="t1")

    return CrossSectionalLabels(
        forward_return=fwd,
        decile_rank=decile,
        label_times=label_times,
        horizon=horizon,
        n_quantiles=n_quantiles,
    )
