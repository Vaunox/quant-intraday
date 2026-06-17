"""Append-only, tamper-evident audit log (Ground Rule 8; Layer 5 platform).

The audit trail is the system's immutable record of every event that matters - a
debugging substrate and the SEBI traceability requirement. Entries are only ever
appended (never modified or deleted) and are linked with SHA-256 hashes, so any
later edit to history is detectable via :meth:`FileAuditLog.verify`.

Secrets are redacted on the way in (the audit log is still a log), and each entry
carries the current correlation id and an IST timestamp.
"""

import hashlib
import json
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from quant.core.logging import Redactor, get_correlation_id

#: Hash that precedes the first entry (the chain genesis).
GENESIS_HASH = "0" * 64

#: Timezone for audit timestamps (IST).
DEFAULT_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True)
class AuditEntry:
    """One immutable audit record (serialised as a single JSON line)."""

    seq: int
    timestamp: str
    correlation_id: str | None
    action: str
    data: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Return the entry as a JSON-serialisable dict."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "action": self.action,
            "data": self.data,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


def _hash_entry(
    seq: int,
    timestamp: str,
    correlation_id: str | None,
    action: str,
    data: Mapping[str, Any],
    prev_hash: str,
) -> str:
    """Compute the chained SHA-256 hash over an entry's contents."""
    canonical = json.dumps(
        {
            "seq": seq,
            "timestamp": timestamp,
            "correlation_id": correlation_id,
            "action": action,
            "data": data,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@runtime_checkable
class AuditLog(Protocol):
    """Append-only audit log interface (inject this; depend on the Protocol)."""

    def append(self, action: str, data: Mapping[str, Any] | None = None) -> AuditEntry:
        """Append an event and return the created entry."""
        ...

    def __iter__(self) -> Iterator[AuditEntry]:
        """Iterate entries in append order."""
        ...

    def verify(self) -> bool:
        """Return whether the chain is intact (append-only, untampered)."""
        ...


class FileAuditLog:
    """A file-backed, append-only, hash-chained audit log (JSON lines).

    Thread-safe. Opening an existing log continues its chain, so the append-only
    guarantee and tamper-evidence hold across process restarts.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        redactor: Redactor | None = None,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        """Open (or create) the audit log at ``path`` and resume its chain."""
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._redactor = redactor if redactor is not None else Redactor()
        self._tz = ZoneInfo(timezone)
        self._lock = threading.Lock()
        last = self._last_entry()
        self._last_seq = last.seq if last is not None else 0
        self._last_hash = last.entry_hash if last is not None else GENESIS_HASH

    def _last_entry(self) -> AuditEntry | None:
        last: AuditEntry | None = None
        for entry in self:
            last = entry
        return last

    def append(self, action: str, data: Mapping[str, Any] | None = None) -> AuditEntry:
        """Append an event, stamping it with the current correlation id + IST time.

        Secret-looking fields in ``data`` are redacted before persistence.
        """
        redacted = self._redactor.redact_mapping(dict(data or {}))
        with self._lock:
            seq = self._last_seq + 1
            timestamp = datetime.now(self._tz).isoformat()
            correlation_id = get_correlation_id()
            prev_hash = self._last_hash
            entry_hash = _hash_entry(seq, timestamp, correlation_id, action, redacted, prev_hash)
            entry = AuditEntry(
                seq=seq,
                timestamp=timestamp,
                correlation_id=correlation_id,
                action=action,
                data=redacted,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")
            self._last_seq = seq
            self._last_hash = entry_hash
            return entry

    def __iter__(self) -> Iterator[AuditEntry]:
        """Iterate persisted entries in append order."""
        if not self._path.is_file():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                raw = json.loads(stripped)
                yield AuditEntry(
                    seq=raw["seq"],
                    timestamp=raw["timestamp"],
                    correlation_id=raw["correlation_id"],
                    action=raw["action"],
                    data=raw["data"],
                    prev_hash=raw["prev_hash"],
                    entry_hash=raw["entry_hash"],
                )

    def verify(self) -> bool:
        """Return whether the on-disk chain is intact, ordered, and untampered."""
        prev_hash = GENESIS_HASH
        expected_seq = 1
        for entry in self:
            if entry.seq != expected_seq or entry.prev_hash != prev_hash:
                return False
            recomputed = _hash_entry(
                entry.seq,
                entry.timestamp,
                entry.correlation_id,
                entry.action,
                entry.data,
                entry.prev_hash,
            )
            if recomputed != entry.entry_hash:
                return False
            prev_hash = entry.entry_hash
            expected_seq += 1
        return True
