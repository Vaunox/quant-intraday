"""Shared domain types: the value objects every layer passes around.

All types are immutable (``frozen``) and slotted - cheap to create on the hot path
(ticks/bars/depth). They are pure data carriers: validation of business invariants
(order sizing, risk limits, price/trigger presence) is the responsibility of the
layer that constructs them, not of these types. Documented invariants below say who
enforces what.

Prices are ``float`` (as the broker reports them); share quantities/volumes are
``int``. Timestamps are timezone-aware (IST) - see :mod:`quant.core.calendar`.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    """Order side (a placed order is always a buy or a sell).

    Deriving a side from a target-position delta (e.g. a future ``Side.from_delta``) is
    position-aware and deferred to the capital/execution layer (P3/P4).
    """

    BUY = "buy"
    SELL = "sell"


class SignalDirection(str, Enum):
    """A model signal's directional view: long, short, or flat (no position).

    Distinct from the order :class:`Side` (BUY/SELL). ``FLAT`` is a first-class
    prediction ("model ran, no edge") and stays distinguishable from the *absence* of a
    signal ("model didn't run"). The view -> order-side translation is position-dependent
    (see :meth:`to_target_sign`) and lives in the capital/execution layer (P3/P4).
    """

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

    def to_target_sign(self) -> int:
        """Target position sign for this directional view: +1 long, 0 flat, -1 short.

        This is the ONLY pure mapping off direction. The order ``Side`` (BUY/SELL) is
        deliberately NOT derived here: it is position-dependent - exiting a long is a
        SELL, covering a short is a BUY, and trimming a long while still long is also a
        SELL - so it is computed downstream in the capital/execution layer from
        (target position - current position).
        """
        return {SignalDirection.LONG: 1, SignalDirection.FLAT: 0, SignalDirection.SHORT: -1}[self]


class OrderType(str, Enum):
    """Order types (Kite)."""

    MARKET = "market"
    LIMIT = "limit"
    SL = "sl"  # stop-loss limit (trigger + price)
    SL_M = "sl_m"  # stop-loss market (trigger only)


class Product(str, Enum):
    """Product / margin type."""

    MIS = "mis"  # intraday margin (this system's default)
    CNC = "cnc"  # delivery
    NRML = "nrml"  # normal (F&O / overnight)


class OrderStatus(str, Enum):
    """Order lifecycle states (the Layer-4 state machine)."""

    PENDING_RECEIVED = "put_order_req_received"
    VALIDATION_PENDING = "validation_pending"
    OPEN_PENDING = "open_pending"
    TRIGGER_PENDING = "trigger_pending"
    OPEN = "open"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Bar:
    """An OHLCV price bar. ``timestamp`` is the bar's close time (tz-aware IST)."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class Tick:
    """A single market tick (last trade). ``timestamp`` is tz-aware IST."""

    symbol: str
    timestamp: datetime
    last_price: float
    last_quantity: int
    volume: int


@dataclass(frozen=True, slots=True)
class DepthLevel:
    """One price level of the order book."""

    price: float
    quantity: int
    orders: int


@dataclass(frozen=True, slots=True)
class DepthSnapshot:
    """A point-in-time order-book snapshot (up to 5 levels per side)."""

    symbol: str
    timestamp: datetime
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]

    @property
    def best_bid(self) -> DepthLevel | None:
        """The top bid level, or ``None`` if the book side is empty."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> DepthLevel | None:
        """The top ask level, or ``None`` if the book side is empty."""
        return self.asks[0] if self.asks else None


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An intent to place an order (pre-broker).

    Invariants (enforced by the router/risk layer, not here): ``quantity`` > 0;
    LIMIT/SL require ``price``; SL/SL_M require ``trigger_price``. ``client_order_id``
    is the local idempotency key recorded before the broker call.
    """

    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    product: Product = Product.MIS
    price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None
    client_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class Order:
    """A broker-acknowledged order and its current state."""

    order_id: str
    symbol: str
    side: Side
    quantity: int
    filled_quantity: int
    order_type: OrderType
    product: Product
    status: OrderStatus
    price: float | None = None
    trigger_price: float | None = None
    average_price: float | None = None
    tag: str | None = None
    client_order_id: str | None = None
    timestamp: datetime | None = None

    @property
    def is_complete(self) -> bool:
        """Whether the order is fully filled (COMPLETE)."""
        return self.status is OrderStatus.COMPLETE

    @property
    def remaining_quantity(self) -> int:
        """Quantity not yet filled."""
        return self.quantity - self.filled_quantity


@dataclass(frozen=True, slots=True)
class Position:
    """A net position. ``quantity`` is signed: positive long, negative short."""

    symbol: str
    quantity: int
    average_price: float
    product: Product = Product.MIS

    @property
    def is_flat(self) -> bool:
        """Whether the position is flat (zero quantity)."""
        return self.quantity == 0

    @property
    def side(self) -> Side | None:
        """The position's side, or ``None`` if flat."""
        if self.quantity > 0:
            return Side.BUY
        if self.quantity < 0:
            return Side.SELL
        return None


@dataclass(frozen=True, slots=True)
class Signal:
    """A model's view on a symbol at a point in time.

    ``direction`` is the primary model's call (long / short / flat); ``strength`` is a
    calibrated conviction in ``[0, 1]`` (e.g. a meta-probability); ``asof`` is the
    decision time (tz-aware IST), and execution happens next bar.
    """

    symbol: str
    asof: datetime
    direction: SignalDirection
    strength: float


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The risk engine's verdict on a proposed order."""

    approved: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Margins:
    """A typed snapshot of account margins (the broker's margins call).

    Used by the pre-open gate (margin sufficiency + peak-margin buffer) and sizing.
    All amounts are in the account's base currency (INR).
    """

    available_cash: float
    available_margin: float
    used_margin: float
    net: float
