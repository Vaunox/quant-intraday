"""Liquidity-ranked, survivorship-correct investable universe (P3X.1c).

No point-in-time Nifty-500 membership table exists for free (the official record is a
company-name-keyed change-log that is dense only 2015-2020 and stops there), so the universe is
defined transparently from the price data itself: at each monthly rebalance, the **top-N names by
trailing median daily traded value (ADV)**. Built from bhavcopy, it includes delisted names for as
long as they actually traded — survivorship-correct — and needs no external membership file.

It is Nifty-500-*like* (a large/mid-cap, liquidity-screened cross-section) rather than the exact
official index. Factor premia (momentum, low-vol, reversal) are universe-robust, so this supports a
trustworthy go/no-go verdict; the exact official membership is a fidelity upgrade to invest in only
if the cheap test looks promising.
"""

import pandas as pd

from quant.research.factors.errors import FactorError


def average_daily_value(value_panel: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Trailing median daily traded value per name — the liquidity measure (ADV).

    Median (not mean) so a single block deal does not inflate a thin name into the universe.

    Args:
        value_panel: ``date x symbol`` panel of daily traded value (₹) from bhavcopy.
        window: trailing window in sessions (e.g. 126 ≈ 6 months).

    Raises:
        FactorError: If ``window`` is not positive.
    """
    if window <= 0:
        raise FactorError(f"window must be positive, got {window}")
    return value_panel.rolling(window, min_periods=max(1, window // 2)).median()


def liquidity_universe(
    value_panel: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    top_n: int,
    adv_window: int = 126,
    min_history_sessions: int = 252,
) -> pd.DataFrame:
    """Boolean eligibility panel (``rebalance_dates x symbols``): the top-N by ADV each month.

    A name is eligible at a rebalance when it (a) has traded on at least ``min_history_sessions``
    sessions to date (so the factors have warm-up) and (b) ranks in the top ``top_n`` by trailing
    ADV among the names that clear (a). History-screening happens *before* ranking, so the result
    holds up to ``top_n`` genuinely-liquid, sufficiently-seasoned names (fewer only if the market
    had fewer that day — early in the sample).

    Args:
        value_panel: ``date x symbol`` daily traded value (NaN where a name did not trade).
        rebalance_dates: the month-end rebalance dates to evaluate eligibility on.
        top_n: universe size (e.g. 500 for a Nifty-500-like cross-section).
        adv_window: trailing window for the ADV measure, in sessions.
        min_history_sessions: minimum traded sessions to date before a name is eligible.

    Returns:
        A boolean ``DataFrame`` indexed by ``rebalance_dates`` over all ``value_panel`` columns.

    Raises:
        FactorError: If ``top_n`` is not positive.
    """
    if top_n <= 0:
        raise FactorError(f"top_n must be positive, got {top_n}")
    adv = average_daily_value(value_panel, window=adv_window)
    traded_to_date = value_panel.notna().cumsum()

    adv_at_reb = adv.reindex(rebalance_dates)
    history_at_reb = traded_to_date.reindex(rebalance_dates)
    seasoned = adv_at_reb.where(history_at_reb >= min_history_sessions)
    ranks = seasoned.rank(axis=1, ascending=False, method="first")
    eligible: pd.DataFrame = (ranks <= top_n).fillna(False)
    return eligible


def load_sector_map(
    csv_path: str, *, symbol_col: str = "Symbol", sector_col: str = "Industry"
) -> dict[str, str]:
    """Load a ``symbol -> sector`` map from an NSE constituent CSV (e.g. ``ind_nifty500list``).

    Drives the sector-neutral z-score and the ≤25% sector cap. Names absent from the file (delisted
    or outside the current list) get sector ``"Other"`` downstream; the caller decides.

    Raises:
        FactorError: If the expected columns are missing.
    """
    frame = pd.read_csv(csv_path)
    missing = {symbol_col, sector_col} - set(frame.columns)
    if missing:
        raise FactorError(
            f"sector CSV missing columns {sorted(missing)}; has {list(frame.columns)}"
        )
    symbols = frame[symbol_col].astype("string").str.strip()
    sectors = frame[sector_col].astype("string").str.strip()
    return {sym: sec for sym, sec in zip(symbols, sectors, strict=True) if sym and sec}
