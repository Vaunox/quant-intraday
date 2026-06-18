"""Tests that trivial fakes satisfy each core Protocol (P0.5).

The typed annotations in ``test_fakes_conform_to_protocols`` are the static
(mypy) structural-conformance check the subtask requires; ``isinstance`` adds a
runtime check.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.interfaces import (
    BrokerAdapter,
    Model,
    PortfolioConstructor,
    Repository,
    RiskEngine,
    Sizer,
)
from quant.core.types import (
    Bar,
    Margins,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Product,
    RiskDecision,
    Side,
    Signal,
)

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
SAMPLE_ORDER = Order(
    order_id="O1",
    symbol="X",
    side=Side.BUY,
    quantity=1,
    filled_quantity=0,
    order_type=OrderType.MARKET,
    product=Product.MIS,
    status=OrderStatus.OPEN,
)
SAMPLE_REQUEST = OrderRequest(symbol="X", side=Side.BUY, quantity=1, order_type=OrderType.MARKET)


class FakeBroker:
    def fetch_historical(
        self, symbol: str, start: datetime, end: datetime, interval: str
    ) -> pd.DataFrame:
        return bars_to_frame([Bar("X", NOW, 1.0, 1.0, 1.0, 1.0, 1)])

    def place_order(self, request: OrderRequest) -> str:
        return SAMPLE_ORDER.order_id

    def modify_order(self, order_id: str, request: OrderRequest) -> None:
        return None

    def cancel_order(self, order_id: str) -> None:
        return None

    def get_order(self, order_id: str) -> Order:
        return SAMPLE_ORDER

    def get_orders(self) -> Sequence[Order]:
        return [SAMPLE_ORDER]

    def get_positions(self) -> Sequence[Position]:
        return []

    def margins(self) -> Margins:
        return Margins(available_cash=1.0, available_margin=1.0, used_margin=0.0, net=1.0)


class FakeRepository:
    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        return None

    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        return bars_to_frame([])

    def list_symbols(self) -> Sequence[str]:
        return ["X"]


class FakeModel:
    def predict(self, features: Mapping[str, float]) -> float:
        return 0.5


class FakePortfolioConstructor:
    def construct(self, signals: Sequence[Signal]) -> Mapping[str, float]:
        return {signal.symbol: 1.0 for signal in signals}


class FakeSizer:
    def size(self, symbol: str, target_weight: float, equity: float, price: float) -> int:
        return int((target_weight * equity) // price) if price > 0 else 0


class FakeRiskEngine:
    def evaluate(
        self, order: OrderRequest, equity: float, positions: Sequence[Position]
    ) -> RiskDecision:
        return RiskDecision(approved=True)

    def is_trading_halted(self) -> bool:
        return False


def test_fakes_conform_to_protocols() -> None:
    broker: BrokerAdapter = FakeBroker()
    repo: Repository = FakeRepository()
    model: Model = FakeModel()
    constructor: PortfolioConstructor = FakePortfolioConstructor()
    sizer: Sizer = FakeSizer()
    risk: RiskEngine = FakeRiskEngine()
    assert isinstance(broker, BrokerAdapter)
    assert isinstance(repo, Repository)
    assert isinstance(model, Model)
    assert isinstance(constructor, PortfolioConstructor)
    assert isinstance(sizer, Sizer)
    assert isinstance(risk, RiskEngine)


def test_fakes_behave() -> None:
    broker = FakeBroker()
    assert broker.place_order(SAMPLE_REQUEST) == "O1"
    assert broker.get_order("O1").symbol == "X"
    assert len(broker.fetch_historical("X", NOW, NOW, "minute")) == 1
    broker.modify_order("O1", SAMPLE_REQUEST)  # returns None by contract
    broker.cancel_order("O1")
    assert list(broker.get_orders()) == [SAMPLE_ORDER]
    assert broker.get_positions() == []
    assert broker.margins().net == 1.0

    assert FakeRepository().list_symbols() == ["X"]
    assert FakeRepository().read_bars("X", NOW, NOW).empty
    FakeRepository().write_bars("X", bars_to_frame([]))
    assert FakeModel().predict({"f": 1.0}) == 0.5
    assert FakePortfolioConstructor().construct([Signal("X", NOW, Side.BUY, 0.6)]) == {"X": 1.0}
    assert FakeSizer().size("X", 0.1, 100_000.0, 100.0) == 100
    assert FakeSizer().size("X", 0.1, 100_000.0, 0.0) == 0

    risk = FakeRiskEngine()
    assert risk.evaluate(SAMPLE_REQUEST, 100_000.0, []).approved
    assert risk.is_trading_halted() is False
