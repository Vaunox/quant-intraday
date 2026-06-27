"""Price-only cross-sectional equity factors (Phase 3X.2, Phase A).

The most replicated, cost-robust, *price-based* edges in equities — buildable entirely from the
OHLCV the existing Kite pipeline already provides. Each factor is a **pure, causal, per-symbol
time-series transform**: the value at bar ``t`` uses only bars at or before ``t``, so it is
point-in-time correct and warms up with leading ``NaN``s (the P1.8 leakage suite proves the
forward-shift invariance). Cross-sectional scoring (sector-neutral z-score / rank within the
point-in-time universe) is the *combination* step (P3X.4) applied on top of these raw values, not
done here — keeping each factor a single-responsibility transform.

Sign convention: each factor is oriented so that **higher = more attractive long** where there is
a standard direction (momentum high, recent losers for reversal, low realized vol). Amihud
illiquidity is returned as the raw illiquidity level (higher = more illiquid); the combiner picks
its sign. Phase B fundamentals (value, quality) are deferred — they need a point-in-time
fundamentals feed and must not be faked from price.
"""

import pandas as pd


def _close(bars: pd.DataFrame) -> pd.Series:
    """Return the close column as a float64 Series indexed by the bars index."""
    return bars["close"].astype("float64")


def _simple_returns(bars: pd.DataFrame) -> pd.Series:
    """Per-bar simple returns of the close (leading bar ``NaN``); causal."""
    return _close(bars).pct_change(fill_method=None)


def momentum_12_1(bars: pd.DataFrame, *, lookback: int = 252, skip: int = 21) -> pd.Series:
    """Return 12-1 momentum: cumulative return from ``t-lookback`` to ``t-skip``.

    The most-recent ``skip`` bars (≈ one month) are skipped to avoid the short-term reversal
    contamination. Value at ``t`` = ``close[t-skip] / close[t-lookback] - 1``, using only past
    prices (causal). Higher = stronger momentum.

    Raises:
        ValueError: If not ``0 <= skip < lookback``.
    """
    if not (0 <= skip < lookback):
        raise ValueError(f"require 0 <= skip < lookback, got skip={skip}, lookback={lookback}")
    close = _close(bars)
    mom = close.shift(skip) / close.shift(lookback) - 1.0
    return mom.rename("momentum_12_1")


def short_term_reversal(bars: pd.DataFrame, *, window: int = 21) -> pd.Series:
    """Return short-term reversal: ``-1 *`` the return over the last ``window`` bars (contrarian).

    Recent losers score high (mean-reversion premium). Value at ``t`` =
    ``-(close[t] / close[t-window] - 1)``; uses the current close and a past close (causal).

    Raises:
        ValueError: If ``window < 1``.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    close = _close(bars)
    return (-(close / close.shift(window) - 1.0)).rename("short_term_reversal")


def low_volatility(bars: pd.DataFrame, *, window: int = 252) -> pd.Series:
    """Return the low-volatility factor: ``-1 *`` trailing realized vol of daily returns.

    The low-volatility anomaly: low-vol names earn higher risk-adjusted returns. Negating the
    trailing standard deviation of daily simple returns orients it so **low-vol ranks high**.
    Causal (trailing rolling window).

    Raises:
        ValueError: If ``window < 2``.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    vol = _simple_returns(bars).rolling(window, min_periods=window).std()
    return (-vol).rename("low_volatility")


def amihud_illiquidity(bars: pd.DataFrame, *, window: int = 252) -> pd.Series:
    """Return Amihud illiquidity: trailing mean of ``|return| / traded-value``.

    Amihud (2002): average daily price impact per rupee traded. Value at ``t`` is the trailing
    ``window``-bar mean of ``|simple_return| / (close * volume)``. Higher = more illiquid (the
    combiner chooses the sign — illiquidity carries a premium but is costly to trade). Bars with
    zero traded value contribute ``NaN`` (no divide-by-zero). Causal.

    Raises:
        ValueError: If ``window < 1``.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    abs_ret = _simple_returns(bars).abs()
    traded_value = _close(bars) * bars["volume"].astype("float64")
    daily = abs_ret / traded_value.where(traded_value > 0)
    amihud = daily.rolling(window, min_periods=window).mean()
    return amihud.rename("amihud_illiquidity")


def residual_momentum(
    bars: pd.DataFrame,
    market_returns: pd.Series,
    *,
    lookback: int = 252,
    skip: int = 21,
    beta_window: int = 252,
) -> pd.Series:
    """Return residual (idiosyncratic) 12-1 momentum — less crash-prone than raw momentum.

    Regress the symbol's daily returns on the market's over a trailing ``beta_window`` (a rolling
    market-model), take the residual return each bar, then form 12-1 momentum on the cumulative
    residual. The market-model coefficients are estimated on the window ending at the *previous*
    bar (``shift(1)``) and applied to the current bar, so the residual at ``t`` uses no
    same-bar-future information; the cumulative sum is taken over ``[t-lookback, t-skip]`` (causal).

    Args:
        bars: One symbol's canonical bars.
        market_returns: The market's per-bar simple returns, aligned to ``bars``' index.
        lookback: Start of the 12-1 window — cumulative residual measured from ``t-lookback``.
        skip: Most-recent bars skipped — the cumulative residual window ends at ``t-skip``.
        beta_window: Rolling window for the market-model regression.

    Raises:
        ValueError: If ``0 <= skip < lookback`` is violated, ``beta_window < 2``, or
            ``market_returns`` is not aligned to ``bars``.
    """
    if not (0 <= skip < lookback):
        raise ValueError(f"require 0 <= skip < lookback, got skip={skip}, lookback={lookback}")
    if beta_window < 2:
        raise ValueError(f"beta_window must be >= 2, got {beta_window}")
    r = _simple_returns(bars)
    m = market_returns.astype("float64")
    if not r.index.equals(m.index):
        m = m.reindex(r.index)
        if bool(m.isna().all()):
            raise ValueError("market_returns must align to the bars index")

    # Rolling market-model estimated on the window ending at t-1 (shift(1) = strictly trailing).
    cov = r.rolling(beta_window, min_periods=beta_window).cov(m).shift(1)
    var = m.rolling(beta_window, min_periods=beta_window).var().shift(1)
    beta = cov / var.where(var > 0)
    alpha = r.rolling(beta_window, min_periods=beta_window).mean().shift(1) - beta * m.rolling(
        beta_window, min_periods=beta_window
    ).mean().shift(1)
    residual = r - (alpha + beta * m)

    # 12-1 momentum on the cumulative residual return: sum residuals over [t-lookback, t-skip].
    cum_residual = residual.rolling(lookback - skip, min_periods=lookback - skip).sum().shift(skip)
    return cum_residual.rename("residual_momentum")
