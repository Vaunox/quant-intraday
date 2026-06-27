"""Proprietary-data recorders (Part VI / Phase 9).

Slow-accruing inputs that turn the pipeline's inputs from **commodity to proprietary** over
months — the structural answer to the Cycle-3b constraint that historical depth / microstructure
data is unbuyable at retail (``FINDINGS.md`` §6). Run in parallel with the mechanism studies:

* **P9.1** — :class:`~quant.data.recorders.depth.DepthRecorder` forward-records live 5-level depth
  into an immutable, ``symbol/date``-partitioned Parquet archive.
* **P9.2** — :class:`~quant.data.recorders.events.EventReactionRecorder` accrues earnings
  surprise -> reaction -> drift records (the substrate for the P7.3 PEAD study).
"""

from quant.data.recorders.depth import (
    DepthRecorder,
    DepthSnapshotArchive,
    depth_snapshot_to_row,
)
from quant.data.recorders.errors import (
    DepthRecorderError,
    EventRecorderError,
    RecorderError,
)
from quant.data.recorders.events import (
    EarningsEvent,
    EventReactionRecord,
    EventReactionRecorder,
    ParquetEventReactionStore,
)

__all__ = [
    "DepthRecorder",
    "DepthRecorderError",
    "DepthSnapshotArchive",
    "EarningsEvent",
    "EventReactionRecord",
    "EventReactionRecorder",
    "EventRecorderError",
    "ParquetEventReactionStore",
    "RecorderError",
    "depth_snapshot_to_row",
]
