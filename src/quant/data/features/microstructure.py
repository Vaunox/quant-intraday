"""Microstructure / order-flow features (Deep Dive #1 §2.2.A — highest empirical value).

*"SHAP studies on microstructure data consistently rank order-flow imbalance as the
single most informative family, with spread and VWAP-deviation close behind."*

These features come from the **5-level order book** (a sequence of
:class:`~quant.core.types.DepthSnapshot`) and the **trade tape** (a sequence of
:class:`~quant.core.types.Tick`), not from OHLCV bars. :func:`depth_to_frame` /
:func:`trades_to_frame` lift the typed objects into canonical frames the vectorized
feature functions operate on.

Every function is **causal**: per-snapshot features use only the current book; OFI uses
the current and *previous* snapshot; signed volume uses the trade and the *previous*
trade (the tick rule). Nothing peeks forward (§2.1).
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from quant.core.types import DepthSnapshot, Tick

#: Number of order-book levels in Kite's ``full`` mode (Deep Dive #1 §0.1).
DEPTH_LEVELS = 5
#: Time column shared with the bars schema.
TIME_COLUMN = "timestamp"


def _level_columns() -> list[str]:
    """Return the ordered depth-frame columns (timestamp + per-level price/qty, both sides)."""
    columns = [TIME_COLUMN]
    for side in ("bid", "ask"):
        for level in range(1, DEPTH_LEVELS + 1):
            columns += [f"{side}_price_{level}", f"{side}_qty_{level}"]
    return columns


#: Canonical depth-frame columns.
DEPTH_COLUMNS: tuple[str, ...] = tuple(_level_columns())
#: Canonical trades-frame columns.
TRADE_COLUMNS: tuple[str, ...] = (TIME_COLUMN, "price", "quantity")


def depth_to_frame(snapshots: Sequence[DepthSnapshot]) -> pd.DataFrame:
    """Convert depth snapshots to a canonical depth frame (one row per snapshot).

    Missing levels (a thin book) are filled with ``NaN`` price and ``0`` quantity, so a
    short book contributes no size rather than breaking the schema.
    """
    rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        row: dict[str, object] = {TIME_COLUMN: snapshot.timestamp}
        for side, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
            for index in range(DEPTH_LEVELS):
                level = levels[index] if index < len(levels) else None
                row[f"{side}_price_{index + 1}"] = level.price if level else np.nan
                row[f"{side}_qty_{index + 1}"] = level.quantity if level else 0
        rows.append(row)
    return pd.DataFrame(rows, columns=list(DEPTH_COLUMNS))


def trades_to_frame(ticks: Sequence[Tick]) -> pd.DataFrame:
    """Convert trade ticks to a canonical trades frame (timestamp, price, quantity)."""
    rows = [
        {TIME_COLUMN: tick.timestamp, "price": tick.last_price, "quantity": tick.last_quantity}
        for tick in ticks
    ]
    return pd.DataFrame(rows, columns=list(TRADE_COLUMNS))


def bid_ask_spread(depth: pd.DataFrame) -> pd.Series:
    """Return the absolute top-of-book spread: ``ask_price_1 - bid_price_1``."""
    return (depth["ask_price_1"] - depth["bid_price_1"]).rename("spread")


def relative_spread(depth: pd.DataFrame) -> pd.Series:
    """Return the spread relative to the mid (in basis points)."""
    mid = (depth["ask_price_1"] + depth["bid_price_1"]) / 2.0
    spread = depth["ask_price_1"] - depth["bid_price_1"]
    return (spread / mid.where(mid != 0) * 1e4).rename("rel_spread_bps")


def depth_imbalance(depth: pd.DataFrame, *, levels: int = DEPTH_LEVELS) -> pd.Series:
    """Return book imbalance ``(ΣbidQty - ΣaskQty) / (ΣbidQty + ΣaskQty)`` over ``levels``.

    Ranges in ``[-1, 1]``: positive when bids outweigh asks (buying pressure). Where the
    book is empty on both sides the value is ``NaN``.

    Raises:
        ValueError: If ``levels`` is outside ``1..DEPTH_LEVELS``.
    """
    _validate_levels(levels)
    bid_qty = depth[[f"bid_qty_{level}" for level in range(1, levels + 1)]].sum(axis=1)
    ask_qty = depth[[f"ask_qty_{level}" for level in range(1, levels + 1)]].sum(axis=1)
    total = bid_qty + ask_qty
    return ((bid_qty - ask_qty) / total.where(total != 0)).rename("depth_imbalance")


def order_flow_imbalance(depth: pd.DataFrame, *, levels: int = DEPTH_LEVELS) -> pd.Series:
    """Return the multi-level Order Flow Imbalance (Cont-Kukanov-Stoikov), summed over levels.

    For each level the bid/ask contributions between consecutive snapshots are::

        e_bid  =  qbid_t * 1[Pbid_t >= Pbid_{t-1}]  -  qbid_{t-1} * 1[Pbid_t <= Pbid_{t-1}]
        e_ask  =  qask_t * 1[Pask_t <= Pask_{t-1}]  -  qask_{t-1} * 1[Pask_t >= Pask_{t-1}]
        OFI    =  sum_levels (e_bid - e_ask)

    Positive OFI = net buying pressure. The first row is ``NaN`` (no previous snapshot);
    the measure is causal (uses only the current and previous book).

    Raises:
        ValueError: If ``levels`` is outside ``1..DEPTH_LEVELS``.
    """
    _validate_levels(levels)
    total = pd.Series(0.0, index=depth.index)
    for level in range(1, levels + 1):
        total = total + _level_ofi(depth, level)
    # The first row has no predecessor -> undefined, not zero.
    result = total.copy()
    if len(result) > 0:
        result.iloc[0] = np.nan
    return result.rename("ofi")


def signed_volume(trades: pd.DataFrame) -> pd.Series:
    """Return tick-rule signed trade volume aligned to ``trades``.

    Lee-Ready tick rule: a trade printed above the previous trade price is buyer-initiated
    (``+quantity``), below is seller-initiated (``-quantity``), and an unchanged price
    carries the previous sign forward. The first trade has no predecessor and is signed
    ``0`` (undetermined). Causal — uses only the trade and prior trades.
    """
    if trades.empty:
        return pd.Series(dtype="float64", name="signed_volume")
    price = trades["price"]
    direction = pd.Series(np.sign(price.diff()), index=trades.index)
    direction = direction.replace(0.0, np.nan).ffill().fillna(0.0)
    signed = direction * trades["quantity"]
    return signed.rename("signed_volume")


def _level_ofi(depth: pd.DataFrame, level: int) -> pd.Series:
    """Return the single-level OFI contribution (e_bid - e_ask) for ``level``."""
    bid_price = depth[f"bid_price_{level}"]
    bid_qty = depth[f"bid_qty_{level}"]
    ask_price = depth[f"ask_price_{level}"]
    ask_qty = depth[f"ask_qty_{level}"]
    prev_bid_price, prev_bid_qty = bid_price.shift(1), bid_qty.shift(1)
    prev_ask_price, prev_ask_qty = ask_price.shift(1), ask_qty.shift(1)

    e_bid = bid_qty.where(bid_price >= prev_bid_price, 0.0) - prev_bid_qty.where(
        bid_price <= prev_bid_price, 0.0
    )
    e_ask = ask_qty.where(ask_price <= prev_ask_price, 0.0) - prev_ask_qty.where(
        ask_price >= prev_ask_price, 0.0
    )
    return e_bid - e_ask


def _validate_levels(levels: int) -> None:
    """Raise if ``levels`` is outside the available ``1..DEPTH_LEVELS`` range."""
    if not 1 <= levels <= DEPTH_LEVELS:
        raise ValueError(f"levels must be in 1..{DEPTH_LEVELS}, got {levels!r}")
