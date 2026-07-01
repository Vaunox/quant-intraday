"""The Phase-3T ETF baskets, loaded and validated from ``config/etf_universe.yaml``.

Two baskets run side by side (operator decision 2026-07-01): the SPEC §2 Rung-3 literal
composition and the already-ratified frozen basket. This module is the typed, validated
loader — the universe is **versioned config, not hard-coded** (Ground Rule 2), and the
operator backfill/verify shims (``scripts/backfill_etf.py``, ``scripts/check_etf_data.py``)
resolve their symbol lists from here so the config is the single source of truth.

Mirrors the ``load_universe`` convention in :mod:`quant.core.config` (pydantic ``frozen`` +
``extra='forbid'`` sections, config-dir discovery), scoped to ETF research.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from quant.core.config import discover_config_dir
from quant.research.etf.errors import EtfUniverseError

#: The independent risk driver a sleeve supplies (the diversification SPEC §2 relies on).
EtfRole = Literal["equity_in", "equity_us", "gold", "silver", "bond", "cash"]


class _Frozen(BaseModel):
    """Immutable, strict-schema base (unknown keys are a config error)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EtfSleeve(_Frozen):
    """One ETF leg of a basket."""

    symbol: str
    exchange: str = "NSE"
    exposure: str
    role: EtfRole


class EtfBasket(_Frozen):
    """A named ETF basket — an ordered, symbol-unique set of sleeves."""

    name: str
    sleeves: tuple[EtfSleeve, ...] = Field(min_length=1)

    @field_validator("sleeves")
    @classmethod
    def _unique_symbols(cls, sleeves: tuple[EtfSleeve, ...]) -> tuple[EtfSleeve, ...]:
        """Reject a basket that lists the same symbol twice (a config mistake)."""
        symbols = [sleeve.symbol for sleeve in sleeves]
        dupes = sorted({s for s in symbols if symbols.count(s) > 1})
        if dupes:
            raise ValueError(f"duplicate symbols in basket: {dupes}")
        return sleeves

    @property
    def symbols(self) -> tuple[str, ...]:
        """The basket's symbols, in declaration order."""
        return tuple(sleeve.symbol for sleeve in self.sleeves)


class EtfUniverse(_Frozen):
    """All ETF baskets defined for the sweep (name-unique)."""

    baskets: tuple[EtfBasket, ...] = Field(min_length=1)

    @field_validator("baskets")
    @classmethod
    def _unique_names(cls, baskets: tuple[EtfBasket, ...]) -> tuple[EtfBasket, ...]:
        """Reject two baskets sharing a name (the name is the selector key)."""
        names = [basket.name for basket in baskets]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate basket names: {dupes}")
        return baskets

    def basket(self, name: str) -> EtfBasket:
        """Return the basket named ``name``.

        Raises:
            EtfUniverseError: If no basket has that name.
        """
        for basket in self.baskets:
            if basket.name == name:
                return basket
        available = [basket.name for basket in self.baskets]
        raise EtfUniverseError(f"no ETF basket named {name!r}; have {available}")

    def union_symbols(self) -> tuple[str, ...]:
        """The de-duplicated union of every basket's symbols, in first-seen order."""
        seen: dict[str, None] = {}
        for basket in self.baskets:
            for symbol in basket.symbols:
                seen.setdefault(symbol, None)
        return tuple(seen)


def load_etf_universe(
    config_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> EtfUniverse:
    """Load and validate the ETF baskets from ``etf_universe.yaml``.

    Args:
        config_dir: Directory holding ``etf_universe.yaml``. Defaults to discovery
            (``$QUANT_CONFIG_DIR`` then the repo's ``config/``), as ``load_universe`` does.
        environ: Environment mapping (injected for tests). Defaults to ``os.environ``.

    Raises:
        EtfUniverseError: If the file is missing, not a mapping, or fails validation.
    """
    environ = os.environ if environ is None else environ
    directory = Path(config_dir) if config_dir is not None else discover_config_dir(environ)
    path = directory / "etf_universe.yaml"
    if not path.is_file():
        raise EtfUniverseError(f"ETF universe file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise EtfUniverseError(f"{path} must contain a mapping at the top level")
    try:
        return EtfUniverse.model_validate(data)
    except ValidationError as exc:
        raise EtfUniverseError(f"invalid ETF universe definition:\n{exc}") from exc


def basket_symbols(universe: EtfUniverse, which: str) -> tuple[str, ...]:
    """Resolve a basket selector to its symbol list.

    Args:
        universe: The loaded ETF universe.
        which: A basket name (e.g. ``"frozen"``, ``"spec_literal"``) or ``"both"`` for the
            de-duplicated union across every basket (what the operator backfills once).

    Raises:
        EtfUniverseError: If ``which`` is a name with no matching basket.
    """
    if which == "both":
        return universe.union_symbols()
    return universe.basket(which).symbols
