"""Data ingestion: historical backfill and the live stream consumer.

The live stream consumer (:class:`~quant.data.ingest.stream.TickStreamConsumer`)
programs against the :class:`~quant.core.interfaces.TickerTransport` Protocol and
imports no broker SDK; the Kite WebSocket implementation lives in
:mod:`quant.data.brokers.ticker`.

The historical backfill (:class:`~quant.data.ingest.backfill.BackfillJob`) is
paginated and resumable and writes through the :class:`~quant.core.interfaces.Repository`
interface, so it is broker- and store-agnostic.
"""

from quant.data.ingest.backfill import (
    BackfillCheckpoint,
    BackfillJob,
    BackfillReport,
    JsonBackfillCheckpoint,
    SymbolBackfill,
)
from quant.data.ingest.stream import TickStreamConsumer, parse_market_update

__all__ = [
    "BackfillCheckpoint",
    "BackfillJob",
    "BackfillReport",
    "JsonBackfillCheckpoint",
    "SymbolBackfill",
    "TickStreamConsumer",
    "parse_market_update",
]
