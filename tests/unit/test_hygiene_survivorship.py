"""Tests for survivorship control (P1.5) — delisted names included in historical sets."""

from datetime import date

import pytest

from quant.data.hygiene.survivorship import ConstituentRegistry, Membership

# OLDCO: a member 2019-2020 then delisted; CURRENT: still a member; NEWCO: joined 2021.
OLDCO = Membership("OLDCO", date(2019, 1, 1), date(2020, 12, 31))
CURRENT = Membership("CURRENT", date(2019, 1, 1), None)
NEWCO = Membership("NEWCO", date(2021, 1, 1), None)
REGISTRY = ConstituentRegistry([OLDCO, CURRENT, NEWCO])


def test_constituents_are_point_in_time() -> None:
    assert REGISTRY.constituents_asof(date(2019, 6, 1)) == ("CURRENT", "OLDCO")
    assert REGISTRY.constituents_asof(date(2024, 6, 1)) == ("CURRENT", "NEWCO")  # OLDCO gone


def test_membership_bounds_are_inclusive() -> None:
    assert REGISTRY.is_member("OLDCO", date(2019, 1, 1))  # first day in
    assert REGISTRY.is_member("OLDCO", date(2020, 12, 31))  # last day in
    assert not REGISTRY.is_member("OLDCO", date(2018, 12, 31))  # before
    assert not REGISTRY.is_member("OLDCO", date(2021, 1, 1))  # after delisting


def test_all_symbols_includes_delisted() -> None:
    # The survivorship-correct universe: OLDCO is present though long delisted.
    assert REGISTRY.all_symbols() == ("CURRENT", "NEWCO", "OLDCO")


def test_open_ended_membership_extends_indefinitely() -> None:
    assert REGISTRY.is_member("CURRENT", date(2099, 1, 1))


def test_from_records_accepts_iso_strings() -> None:
    registry = ConstituentRegistry.from_records(
        [
            {"symbol": "A", "start": "2020-01-01", "end": "2020-06-30"},
            {"symbol": "B", "start": "2020-01-01"},  # open-ended (no end)
        ]
    )
    assert registry.constituents_asof(date(2020, 3, 1)) == ("A", "B")
    assert registry.constituents_asof(date(2020, 9, 1)) == ("B",)


def test_from_records_accepts_date_objects() -> None:
    registry = ConstituentRegistry.from_records(
        [{"symbol": "A", "start": date(2020, 1, 1), "end": date(2020, 6, 30)}]
    )
    assert registry.is_member("A", date(2020, 3, 1))
    assert not registry.is_member("A", date(2020, 7, 1))


def test_multiple_intervals_for_one_symbol() -> None:
    # A name can leave and rejoin the index; both intervals count point-in-time.
    registry = ConstituentRegistry(
        [
            Membership("X", date(2019, 1, 1), date(2019, 12, 31)),
            Membership("X", date(2022, 1, 1), None),
        ]
    )
    assert registry.is_member("X", date(2019, 6, 1))
    assert not registry.is_member("X", date(2020, 6, 1))  # the gap year
    assert registry.is_member("X", date(2023, 6, 1))


def test_membership_end_before_start_rejected() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        Membership("BAD", date(2020, 6, 1), date(2020, 1, 1))


def test_empty_registry_has_no_constituents() -> None:
    empty = ConstituentRegistry([])
    assert empty.constituents_asof(date(2024, 1, 1)) == ()
    assert empty.all_symbols() == ()
