"""The Protocols every layer programs against (Ground Rule 1).

Defining these contracts up front lets each layer be built and tested against the
interface, and lets implementations be swapped without touching callers:

* :class:`BrokerAdapter` - Kite today, another broker tomorrow.
* :class:`Repository` - Parquet / ArcticDB / Redis behind one interface.
* :class:`Model`, :class:`PortfolioConstructor`, :class:`Sizer`, :class:`RiskEngine`.

Nothing here imports a concrete SDK; concrete implementations live in their own
packages (``data/brokers``, ``data/store``, ``research/models``, ``capital/...``).
All Protocols are ``runtime_checkable`` so fakes can be asserted in tests, but the
authoritative conformance check is static (mypy), via the signatures below.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from quant.core.types import Margins, Order, OrderRequest, Position, RiskDecision, Signal


@runtime_checkable
class BrokerAdapter(Protocol):
    """Abstraction over the broker for market data and order management."""

    def fetch_historical(
        self, symbol: str, start: datetime, end: datetime, interval: str
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars for ``symbol`` within ``[start, end]``.

        Returns a DataFrame in the canonical bars schema
        (:data:`quant.core.frames.BAR_COLUMNS`) - bulk series are pandas, by design.
        """
        ...

    def place_order(self, request: OrderRequest) -> str:
        """Place an order and return the broker order id (an id, not a fill)."""
        ...

    def modify_order(self, order_id: str, request: OrderRequest) -> None:
        """Modify an open order to match ``request``."""
        ...

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order."""
        ...

    def get_order(self, order_id: str) -> Order:
        """Return the current state of a single order."""
        ...

    def get_orders(self) -> Sequence[Order]:
        """Return all known orders for the session."""
        ...

    def get_positions(self) -> Sequence[Position]:
        """Return current open positions."""
        ...

    def margins(self) -> Margins:
        """Return the account's current margin snapshot."""
        ...


@runtime_checkable
class Repository(Protocol):
    """Abstraction over the storage tier for time-series bars."""

    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        """Persist a bars DataFrame for ``symbol`` (idempotent on re-write)."""
        ...

    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Read a bars DataFrame for ``symbol`` within ``[start, end]`` in time order."""
        ...

    def list_symbols(self) -> Sequence[str]:
        """Return the symbols held in the store."""
        ...


@runtime_checkable
class Model(Protocol):
    """Abstraction over an alpha model's inference path."""

    def predict(self, features: Mapping[str, float]) -> float:
        """Return a score/probability for a point-in-time feature vector."""
        ...


@runtime_checkable
class PortfolioConstructor(Protocol):
    """Turns ranked signals into target portfolio weights by symbol."""

    def construct(self, signals: Sequence[Signal]) -> Mapping[str, float]:
        """Return target weights keyed by symbol (gross within configured caps)."""
        ...


@runtime_checkable
class Sizer(Protocol):
    """Converts a target weight into an integer share quantity."""

    def size(self, symbol: str, target_weight: float, equity: float, price: float) -> int:
        """Return the share quantity for ``symbol`` given equity and price."""
        ...


@runtime_checkable
class RiskEngine(Protocol):
    """The un-overridable risk authority: vet orders and gate trading."""

    def evaluate(
        self, order: OrderRequest, equity: float, positions: Sequence[Position]
    ) -> RiskDecision:
        """Approve or veto a proposed order against the hard limits."""
        ...

    def is_trading_halted(self) -> bool:
        """Whether trading is halted (daily-loss / drawdown / kill-switch)."""
        ...
