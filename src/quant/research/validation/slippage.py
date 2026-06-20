"""Size/depth-aware slippage model (Deep Dive #2 §4b.6).

*"Slippage model: 0.05-0.20% for liquid names, wider in volatile windows and near the
open; scale with order size vs available depth … Be conservative."* Placement ≠
execution: a market order walks the book, so the realised price is worse than the
reference (a buy fills higher, a sell lower). This model turns an order's **size
relative to the liquidity available to it** into that adverse price move.

**The participation curve.** Let ``participation = quantity / available_liquidity``,
clamped to ``[0, 1]``. Slippage interpolates linearly from the configured floor to the
ceiling::

    slippage_bps = min_bps + (max_bps - min_bps) · participation

A tiny order in deep liquidity pays the ``min_bps`` floor (the irreducible spread cost of
a liquid name); an order that would consume all the visible liquidity pays the ``max_bps``
ceiling. With **no** liquidity (``available_liquidity <= 0`` — e.g. a halt bar) it pays
the ceiling, the conservative worst case.

**The liquidity proxy.** True ``available_liquidity`` is the resting size on the 5-level
book (Deep Dive #1). In a bars-only backtest the book is absent, so the backtest core
passes the **fill bar's volume** as the proxy — the order's size as a fraction of what
actually traded that bar. This is data we have, monotonic in the right direction, and
conservative for large orders. The bounds live in
:class:`~quant.core.config.SlippageConfig` (Ground Rule 2). Widening near the open / in
volatile windows (§4b.6) is a documented follow-up that multiplies this base once the
volatility input is wired.
"""

from quant.core.config import SlippageConfig
from quant.core.types import Side

#: Basis points per unit fraction (1 bp = 0.01% = 1e-4). Named once (Ground Rule 2).
_BPS_PER_UNIT = 1e4


class DepthAwareSlippage:
    """Maps an order's size-vs-liquidity to an adverse fill price.

    Stateless and pure: constructed from the configured ``[min_bps, max_bps]`` band, then
    :meth:`slippage_bps` / :meth:`adjusted_fill_price` apply the participation curve.
    """

    def __init__(self, config: SlippageConfig) -> None:
        """Build the model from the configured slippage band (``min_bps`` ≤ ``max_bps``)."""
        # SlippageConfig validates min_bps <= max_bps and both >= 0 at load time (P0.2).
        self._min_bps = config.min_bps
        self._max_bps = config.max_bps

    def slippage_bps(self, quantity: int, available_liquidity: float) -> float:
        """Return the adverse slippage, in basis points, for this order.

        Args:
            quantity: Shares being filled (> 0).
            available_liquidity: Shares of liquidity available to the order (the book
                depth, or the bar volume proxy). ``<= 0`` means no liquidity → the
                conservative ``max_bps`` ceiling.

        Returns:
            Slippage in basis points, within ``[min_bps, max_bps]``.
        """
        if available_liquidity <= 0:
            return self._max_bps
        participation = min(quantity / available_liquidity, 1.0)
        return self._min_bps + (self._max_bps - self._min_bps) * participation

    def adjusted_fill_price(
        self, side: Side, reference_price: float, quantity: int, available_liquidity: float
    ) -> float:
        """Apply adverse slippage to ``reference_price`` for a fill.

        A buy fills **above** the reference, a sell **below** it (slippage is always a
        cost), by the basis points from :meth:`slippage_bps`.

        Args:
            side: ``BUY`` (price moves up) or ``SELL`` (price moves down).
            reference_price: The pre-slippage price (the next bar's open in the backtest).
            quantity: Shares being filled (> 0).
            available_liquidity: Shares of liquidity available to the order.

        Returns:
            The slippage-adjusted execution price per share (INR).
        """
        fraction = self.slippage_bps(quantity, available_liquidity) / _BPS_PER_UNIT
        signed = fraction if side is Side.BUY else -fraction
        return reference_price * (1.0 + signed)
