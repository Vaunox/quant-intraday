"""Data ingestion: historical backfill and the live stream consumer.

The live stream consumer (:class:`~quant.data.ingest.stream.TickStreamConsumer`)
programs against the :class:`~quant.core.interfaces.TickerTransport` Protocol and
imports no broker SDK; the Kite WebSocket implementation lives in
:mod:`quant.data.brokers.ticker`.
"""

from quant.data.ingest.stream import TickStreamConsumer, parse_market_update

__all__ = ["TickStreamConsumer", "parse_market_update"]
