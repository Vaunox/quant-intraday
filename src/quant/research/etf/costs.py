"""Step 2 ETF cost model (multi-ETF rotation track).

Pure, testable transaction + holding cost model for SPEC_MultiETF_Rotation.md Section 6,
populated with published Zerodha charge rates and **conservative, provisional bid-ask spread
estimates** (web/liquidity-tier priors, NOT live-measured — flagged in the Step 2 doc and
owed before any trusted net Sharpe).

The decisive economics at the ``Rs 1 lakh`` scale: STT is negligible (resolved in Step 1)
and the dominant per-rebalance cost is the **flat DP charge** (Rs 13.5 + GST per leg sold),
which is regressive — on a ~Rs 16k leg it is ~9-10 bps by itself, dwarfing the few-bps spread.
The model therefore takes the *trade value* so the flat fee is expressed correctly in bps.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class LegProfile:
    """Per-ETF cost inputs.

    Attributes:
        symbol: Ticker.
        spread_bps: Full quoted bid-ask spread (round-trip crossing cost), in bps. PROVISIONAL
            web/liquidity-tier estimate until live-measured.
        expense_ratio_annual: Fund TER as an annual fraction (continuous NAV drag).
        stt_sell_bps: STT on the sell side in bps (0.1 for equity ETFs, 0 for gold/silver/
            liquid/international per the Step 1 resolution).
    """

    symbol: str
    spread_bps: float
    expense_ratio_annual: float
    stt_sell_bps: float


@dataclass(frozen=True, slots=True)
class ChargeSchedule:
    """Account-level statutory/broker charges (Zerodha published rates, 2026).

    Attributes:
        brokerage_per_order: Brokerage per order (Rs). 0 for Zerodha ETF delivery.
        exchange_txn_rate: NSE cash exchange transaction charge, fraction of turnover.
        sebi_rate: SEBI turnover fee, fraction of turnover.
        stamp_buy_rate: Stamp duty, fraction of turnover, buy side only.
        gst_rate: GST on (brokerage + exchange txn + SEBI).
        dp_charge_per_sell: Flat DP charge per scrip per sell day (Rs, GST-inclusive).
    """

    brokerage_per_order: float = 0.0
    exchange_txn_rate: float = 0.0000325  # 0.00325%
    sebi_rate: float = 0.000001  # 0.0001% (Rs 10/cr)
    stamp_buy_rate: float = 0.00015  # 0.015% buy side
    gst_rate: float = 0.18
    dp_charge_per_sell: float = 15.93  # Rs 13.50 + 18% GST


@dataclass(frozen=True, slots=True)
class TradeCost:
    """Itemised cost of one side of a trade (Rs)."""

    spread: float
    brokerage: float
    stt: float
    exchange_txn: float
    sebi: float
    stamp: float
    gst: float
    dp: float

    @property
    def total(self) -> float:
        """Sum of all components (Rs)."""
        return (
            self.spread
            + self.brokerage
            + self.stt
            + self.exchange_txn
            + self.sebi
            + self.stamp
            + self.gst
            + self.dp
        )


@dataclass(frozen=True, slots=True)
class ETFCostModel:
    """Transaction + holding cost model over a set of ETF legs.

    Attributes:
        legs: Per-symbol :class:`LegProfile`.
        charges: Account-level :class:`ChargeSchedule`.
    """

    legs: Mapping[str, LegProfile]
    charges: ChargeSchedule = field(default_factory=ChargeSchedule)

    def trade_cost(self, symbol: str, value: float, *, side: Side) -> TradeCost:
        """Cost of trading ``value`` rupees of ``symbol`` on one ``side``.

        Crossing the spread once costs half the quoted spread (buy at the ask, sell at the
        bid), so a buy+sell pair sums to the full spread. STT is sell-side, stamp is
        buy-side, the DP charge applies on the sell.

        Args:
            symbol: A leg in :attr:`legs`.
            value: Rupee notional of the trade.
            side: ``"buy"`` or ``"sell"``.

        Returns:
            The itemised :class:`TradeCost`.
        """
        leg = self.legs[symbol]
        sched = self.charges
        spread = value * (leg.spread_bps / 2) / 1e4
        brokerage = sched.brokerage_per_order
        exchange_txn = value * sched.exchange_txn_rate
        sebi = value * sched.sebi_rate
        stt = value * leg.stt_sell_bps / 1e4 if side == "sell" else 0.0
        stamp = value * sched.stamp_buy_rate if side == "buy" else 0.0
        dp = sched.dp_charge_per_sell if side == "sell" else 0.0
        gst = sched.gst_rate * (brokerage + exchange_txn + sebi)
        return TradeCost(
            spread=spread,
            brokerage=brokerage,
            stt=stt,
            exchange_txn=exchange_txn,
            sebi=sebi,
            stamp=stamp,
            gst=gst,
            dp=dp,
        )

    def round_trip_bps(self, symbol: str, value: float) -> float:
        """Total round-trip (buy then sell) cost of ``value`` rupees, in bps of ``value``.

        Args:
            symbol: A leg in :attr:`legs`.
            value: Rupee notional traded each way.

        Returns:
            Round-trip cost in basis points.

        Raises:
            ValueError: If ``value`` is not positive.
        """
        if value <= 0:
            raise ValueError("trade value must be positive")
        total = (
            self.trade_cost(symbol, value, side="buy").total
            + self.trade_cost(symbol, value, side="sell").total
        )
        return total / value * 1e4

    def holding_cost_bps(self, symbol: str, days: float) -> float:
        """Expense-ratio drag over ``days`` held, in bps of position value.

        Args:
            symbol: A leg in :attr:`legs`.
            days: Calendar days held.

        Returns:
            Holding drag in basis points.
        """
        return self.legs[symbol].expense_ratio_annual * days / 365.0 * 1e4


#: Provisional, conservative leg profiles for the frozen Step 1 universe. Spreads are
#: web/liquidity-tier estimates rounded UP (a robust NO-GO if the edge dies under inflated
#: costs); TERs are approximate published values; STT per the Step 1 resolution. Replace
#: spreads with live measurements before trusting any net Sharpe.
DEFAULT_LEGS: dict[str, LegProfile] = {
    "NIFTYBEES": LegProfile(
        "NIFTYBEES", spread_bps=3.0, expense_ratio_annual=0.0004, stt_sell_bps=0.1
    ),
    "BANKBEES": LegProfile(
        "BANKBEES", spread_bps=4.0, expense_ratio_annual=0.0019, stt_sell_bps=0.1
    ),
    "MON100": LegProfile("MON100", spread_bps=20.0, expense_ratio_annual=0.0058, stt_sell_bps=0.0),
    "GOLDBEES": LegProfile(
        "GOLDBEES", spread_bps=5.0, expense_ratio_annual=0.0082, stt_sell_bps=0.0
    ),
    "SILVERBEES": LegProfile(
        "SILVERBEES", spread_bps=5.0, expense_ratio_annual=0.0050, stt_sell_bps=0.0
    ),
    "LIQUIDBEES": LegProfile(
        "LIQUIDBEES", spread_bps=2.0, expense_ratio_annual=0.0027, stt_sell_bps=0.0
    ),
}


def default_cost_model() -> ETFCostModel:
    """Build the provisional cost model for the frozen universe (see :data:`DEFAULT_LEGS`)."""
    return ETFCostModel(legs=DEFAULT_LEGS)
