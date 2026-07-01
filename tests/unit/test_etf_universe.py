"""Unit tests for the Phase-3T ETF universe loader (P3T.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quant.research.etf.errors import EtfUniverseError
from quant.research.etf.universe import basket_symbols, load_etf_universe

_VALID = """
baskets:
  - name: frozen
    sleeves:
      - { symbol: NIFTYBEES, exchange: NSE, exposure: "India large-cap", role: equity_in }
      - { symbol: GOLDBEES,  exchange: NSE, exposure: "Gold",            role: gold }
  - name: spec_literal
    sleeves:
      - { symbol: NIFTYBEES,  exchange: NSE, exposure: "Nifty 50",   role: equity_in }
      - { symbol: GSEC10IETF, exchange: NSE, exposure: "10y G-Sec",  role: bond }
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "etf_universe.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_loads_the_repo_config_with_both_baskets() -> None:
    # The real committed config/etf_universe.yaml, via auto-discovery.
    universe = load_etf_universe()
    names = {basket.name for basket in universe.baskets}
    assert names == {"frozen", "spec_literal"}
    frozen = universe.basket("frozen")
    assert frozen.symbols == (
        "NIFTYBEES",
        "BANKBEES",
        "MON100",
        "GOLDBEES",
        "SILVERBEES",
        "LIQUIDBEES",
    )
    spec = universe.basket("spec_literal")
    assert spec.symbols == ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "GSEC10IETF", "MON100")
    # The spec-literal basket carries a genuine bond (duration) sleeve.
    assert any(sleeve.role == "bond" for sleeve in spec.sleeves)


def test_union_symbols_dedupes_shared_legs() -> None:
    universe = load_etf_universe()
    union = basket_symbols(universe, "both")
    assert len(union) == len(set(union))  # no duplicates
    # NIFTYBEES/GOLDBEES/MON100 are shared across both baskets → counted once.
    assert union.count("NIFTYBEES") == 1
    assert set(union) == set(universe.basket("frozen").symbols) | set(
        universe.basket("spec_literal").symbols
    )


def test_basket_symbols_selects_by_name(tmp_path: Path) -> None:
    universe = load_etf_universe(config_dir=_write(tmp_path, _VALID))
    assert basket_symbols(universe, "frozen") == ("NIFTYBEES", "GOLDBEES")
    assert basket_symbols(universe, "spec_literal") == ("NIFTYBEES", "GSEC10IETF")
    assert basket_symbols(universe, "both") == ("NIFTYBEES", "GOLDBEES", "GSEC10IETF")


def test_unknown_basket_name_raises(tmp_path: Path) -> None:
    universe = load_etf_universe(config_dir=_write(tmp_path, _VALID))
    with pytest.raises(EtfUniverseError):
        universe.basket("nope")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(EtfUniverseError):
        load_etf_universe(config_dir=tmp_path)


def test_duplicate_symbol_in_a_basket_is_rejected(tmp_path: Path) -> None:
    bad = """
baskets:
  - name: frozen
    sleeves:
      - { symbol: NIFTYBEES, exposure: "a", role: equity_in }
      - { symbol: NIFTYBEES, exposure: "b", role: gold }
"""
    with pytest.raises(EtfUniverseError):
        load_etf_universe(config_dir=_write(tmp_path, bad))


def test_unknown_role_or_extra_key_is_rejected(tmp_path: Path) -> None:
    bad_role = """
baskets:
  - name: frozen
    sleeves:
      - { symbol: NIFTYBEES, exposure: "a", role: crypto }
"""
    with pytest.raises(EtfUniverseError):
        load_etf_universe(config_dir=_write(tmp_path, bad_role))

    extra_key = """
baskets:
  - name: frozen
    sleeves:
      - { symbol: NIFTYBEES, exposure: "a", role: gold, weight: 0.5 }
"""
    with pytest.raises(EtfUniverseError):
        load_etf_universe(config_dir=_write(tmp_path, extra_key))
