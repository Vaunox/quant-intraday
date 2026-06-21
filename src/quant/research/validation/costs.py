"""The full Indian intraday (MIS) transaction-cost model (Deep Dive #2 §4b.6).

*"No gross-only backtests."* Every simulated fill pays the exact, itemised cost an
intraday equity order incurs on the NSE, so the backtest's P&L is net — the only honest
basis for the kill-gate (Inviolable Rule 4). The components, applied **per executed
order** (one fill = one order for brokerage purposes):

* **Brokerage** — the lower of ``brokerage_rate * turnover`` or a flat ``brokerage_cap``
  (Rs.20), per order. The cap is why larger positions are proportionally cheaper.
* **STT** — securities transaction tax, on the **sell side only** for intraday equity.
* **Exchange transaction charges** — per side.
* **SEBI charges** — per side (tiny: Rs.10 / crore).
* **Stamp duty** — on the **buy side only**.
* **GST** — 18% on (brokerage + exchange transaction + SEBI charges).

-> all-in **~0.12-0.20% round trip** for a liquid name; lower where the Rs.20 cap
dominates. A round trip is two fills (a buy and a sell), so the model is applied per
fill and summed — entry and exit each carry their own one-sided taxes.

Every rate lives in :class:`~quant.core.config.CostConfig` (Ground Rule 2): *"Pull exact
numbers from a current brokerage calculator — these change"* (§4b.6). The model is a pure
function of ``(side, price, quantity)`` and the configured rates — no hidden state.
"""

from dataclasses import dataclass

from quant.core.config import CostConfig
from quant.core.types import Side
from quant.research.validation.errors import CostModelError


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """The itemised cost of a single fill, in INR. ``total`` sums the components.

    Kept itemised (not just a total) so monitoring and the implementation-shortfall
    analysis (P4.7) can attribute cost drag to its sources, and so a test can pin each
    line against the broker's schedule.
    """

    brokerage: float
    stt: float
    exchange_txn: float
    sebi_charges: float
    stamp_duty: float
    gst: float

    @property
    def total(self) -> float:
        """Total cost of the fill (sum of all components), in INR."""
        return (
            self.brokerage
            + self.stt
            + self.exchange_txn
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
        )


class IndianCostModel:
    """Computes the itemised Indian MIS transaction cost of a single fill.

    Stateless and pure: constructed from the configured rate schedule, then
    :meth:`cost_for_fill` maps ``(side, price, quantity)`` to a :class:`CostBreakdown`.
    """

    def __init__(self, config: CostConfig) -> None:
        """Build the model from the configured Indian cost-rate schedule."""
        self._config = config

    def cost_for_fill(self, side: Side, price: float, quantity: int) -> CostBreakdown:
        """Return the itemised cost of filling ``quantity`` shares at ``price`` on ``side``.

        Args:
            side: ``BUY`` or ``SELL`` — selects the one-sided taxes (STT on sell, stamp
                duty on buy).
            price: The executed price per share (INR), > 0.
            quantity: Shares filled (> 0).

        Returns:
            The :class:`CostBreakdown` for this single executed order.

        Raises:
            CostModelError: If ``price`` or ``quantity`` is not positive (a fill must move
                a positive number of shares at a positive price — fail loud, Rule 7).
        """
        if price <= 0:
            raise CostModelError(f"price must be positive, got {price!r}")
        if quantity <= 0:
            raise CostModelError(f"quantity must be positive, got {quantity!r}")

        cfg = self._config
        turnover = price * quantity

        # Brokerage is capped per order — the lower of the percentage and the flat cap.
        brokerage = min(cfg.brokerage_rate * turnover, cfg.brokerage_cap_inr)
        # One-sided taxes: STT on the sell leg, stamp duty on the buy leg.
        stt = cfg.stt_sell_rate * turnover if side is Side.SELL else 0.0
        stamp_duty = cfg.stamp_duty_buy_rate * turnover if side is Side.BUY else 0.0
        # Per-side charges.
        exchange_txn = cfg.exchange_txn_rate * turnover
        sebi_charges = cfg.sebi_charges_rate * turnover
        # GST applies to brokerage + exchange transaction + SEBI charges (§4b.6).
        gst = cfg.gst_rate * (brokerage + exchange_txn + sebi_charges)

        return CostBreakdown(
            brokerage=brokerage,
            stt=stt,
            exchange_txn=exchange_txn,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            gst=gst,
        )
