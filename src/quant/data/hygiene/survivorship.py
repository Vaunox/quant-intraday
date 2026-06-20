"""Survivorship-bias control via point-in-time index constituents (Deep Dive #1 §1.3.3).

*"Use point-in-time index constituents — the Nifty-50 of June 2019 is not today's
Nifty-50. Include delisted/merged/renamed symbols in historical sets. If your training
universe is 'today's liquid names,' the model has literally never seen a company collapse,
and it will be blind to exactly the tail events that blow up intraday accounts."*

:class:`ConstituentRegistry` answers "which symbols were in the index as of date *D*?"
from a table of membership intervals, so historical universes include names that have
since been delisted or renamed. The membership data is operator-provided reference data
(like the holiday calendar); this module is the point-in-time query logic over it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from quant.core.logging import get_logger

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Membership:
    """One symbol's membership interval in the index (inclusive dates).

    Attributes:
        symbol: The (point-in-time) trading symbol.
        start: First date the symbol was a constituent (inclusive).
        end: Last date it was a constituent (inclusive), or ``None`` if still a member.

    Raises:
        ValueError: If ``end`` precedes ``start``.
    """

    symbol: str
    start: date
    end: date | None = None

    def __post_init__(self) -> None:
        """Validate the interval ordering (fail loud — Ground Rule 7)."""
        if self.end is not None and self.end < self.start:
            raise ValueError(f"{self.symbol} membership end {self.end} precedes start {self.start}")

    def covers(self, day: date) -> bool:
        """Return whether this membership is active on ``day`` (inclusive bounds)."""
        return self.start <= day and (self.end is None or day <= self.end)


class ConstituentRegistry:
    """Point-in-time index membership: which symbols were constituents on a given date."""

    def __init__(self, memberships: Sequence[Membership]) -> None:
        """Build the registry from membership intervals (one symbol may have several)."""
        self._memberships = tuple(memberships)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> "ConstituentRegistry":
        """Build from plain dict records (``symbol``, ``start``, optional ``end``).

        Dates may be ``date`` objects or ISO ``YYYY-MM-DD`` strings — convenient for
        loading operator-maintained reference data.
        """
        return cls([_membership_from_record(record) for record in records])

    def constituents_asof(self, asof: date) -> tuple[str, ...]:
        """Return the symbols that were constituents on ``asof``, sorted and de-duplicated."""
        members = {m.symbol for m in self._memberships if m.covers(asof)}
        return tuple(sorted(members))

    def is_member(self, symbol: str, asof: date) -> bool:
        """Return whether ``symbol`` was a constituent on ``asof``."""
        return any(m.symbol == symbol and m.covers(asof) for m in self._memberships)

    def all_symbols(self) -> tuple[str, ...]:
        """Return every symbol ever in the index — including since-delisted names.

        This is the survivorship-correct historical universe: building a training set
        from these (not from today's members) is what stops survivorship bias.
        """
        return tuple(sorted({m.symbol for m in self._memberships}))


def _membership_from_record(record: Mapping[str, Any]) -> Membership:
    """Build a :class:`Membership` from a dict record (ISO-string dates allowed)."""
    end = record.get("end")
    return Membership(
        symbol=str(record["symbol"]),
        start=_as_date(record["start"]),
        end=_as_date(end) if end is not None else None,
    )


def _as_date(value: Any) -> date:
    """Coerce a ``date`` or ISO ``YYYY-MM-DD`` string to a :class:`date`."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
