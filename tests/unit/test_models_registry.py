"""Tests for the model registry (P2.7, Deep Dive #2 §4 output contract).

The registry must **version** models, record the **data/feature/label/model version tags** on
every artifact (the §4 contract), assign an integrity fingerprint, and retrieve by id / latest.
:class:`~quant.research.models.registry.FileModelRegistry` must additionally round-trip the
artifact through disk and catch corruption. A clock is injected so ``created_at`` is
deterministic. Tests use a trivial picklable model — the registry is generic over the artifact,
so it needs no GBM dependency (and stays confinement-clean).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from quant.research.models.registry import (
    FileModelRegistry,
    InMemoryModelRegistry,
    ModelCard,
    ModelRegistry,
    RegisteredModel,
    RegistryError,
)

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class _FakeModel:
    """A tiny picklable stand-in for a fitted model."""

    weights: tuple[float, ...]


def _fixed_clock() -> datetime:
    return datetime(2026, 6, 22, 9, 15, tzinfo=IST)


def _registries(tmp_path: Path) -> list[ModelRegistry]:
    return [
        InMemoryModelRegistry(clock=_fixed_clock),
        FileModelRegistry(tmp_path / "registry", clock=_fixed_clock),
    ]


def _register(registry: ModelRegistry, model: object, version: str = "ens-v1") -> ModelCard:
    return registry.register(
        model,
        model_version=version,
        data_version="data-2026-06",
        feature_set_version="core-v1",
        label_version="tb-v1",
    )


@pytest.mark.parametrize("make", [InMemoryModelRegistry, FileModelRegistry], ids=["memory", "file"])
def test_register_records_the_version_tags(make: type, tmp_path: Path) -> None:
    registry = (
        make(clock=_fixed_clock)
        if make is InMemoryModelRegistry
        else make(tmp_path / "r", clock=_fixed_clock)
    )
    card = _register(registry, _FakeModel((1.0, 2.0)))
    assert card.data_version == "data-2026-06"
    assert card.feature_set_version == "core-v1"
    assert card.label_version == "tb-v1"
    assert card.model_version == "ens-v1"
    assert card.created_at == _fixed_clock()
    assert len(card.fingerprint) == 64  # sha-256 hex digest


def test_registry_satisfies_the_protocol(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        assert isinstance(registry, ModelRegistry)


def test_versions_increment_per_model_version(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        first = _register(registry, _FakeModel((1.0,)))
        second = _register(registry, _FakeModel((2.0,)))
        assert first.version == 1 and first.model_id == "ens-v1-0001"
        assert second.version == 2 and second.model_id == "ens-v1-0002"


def test_distinct_model_versions_have_independent_counters(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        _register(registry, _FakeModel((1.0,)), version="ens-v1")
        other = _register(registry, _FakeModel((1.0,)), version="ens-v2")
        assert other.version == 1  # ens-v2 starts its own count


def test_get_returns_the_model_and_card(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        card = _register(registry, _FakeModel((3.0, 4.0)))
        retrieved = registry.get(card.model_id)
        assert isinstance(retrieved, RegisteredModel)
        assert retrieved.model == _FakeModel((3.0, 4.0))
        assert retrieved.card.model_id == card.model_id


def test_latest_returns_the_highest_version(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        _register(registry, _FakeModel((1.0,)))
        _register(registry, _FakeModel((2.0,)))
        latest = registry.latest("ens-v1")
        assert latest is not None
        assert latest.card.version == 2
        assert latest.model == _FakeModel((2.0,))


def test_latest_is_none_for_an_unknown_model_version(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        assert registry.latest("never-registered") is None


def test_cards_lists_every_registration(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        _register(registry, _FakeModel((1.0,)), version="ens-v1")
        _register(registry, _FakeModel((2.0,)), version="ens-v2")
        ids = {card.model_id for card in registry.cards()}
        assert ids == {"ens-v1-0001", "ens-v2-0001"}


def test_get_raises_on_unknown_id(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        with pytest.raises(RegistryError, match="no model registered"):
            registry.get("ens-v1-0099")


def test_metrics_and_importances_are_preserved(tmp_path: Path) -> None:
    for registry in _registries(tmp_path):
        card = registry.register(
            _FakeModel((1.0,)),
            model_version="ens-v1",
            data_version="d",
            feature_set_version="f",
            label_version="l",
            metrics={"oos_combined_auc": 0.83},
            importances={"signal": 0.4},
            params={"method": "rank_average"},
            tags={"stage": "ensemble"},
        )
        loaded = registry.get(card.model_id).card
        assert loaded.metrics["oos_combined_auc"] == pytest.approx(0.83)
        assert loaded.importances["signal"] == pytest.approx(0.4)
        assert loaded.params["method"] == "rank_average"
        assert loaded.tags["stage"] == "ensemble"


# --------------------------------------------------------------------------- #
# FileModelRegistry specifics
# --------------------------------------------------------------------------- #
def test_file_registry_persists_across_instances(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    card = _register(FileModelRegistry(root, clock=_fixed_clock), _FakeModel((5.0,)))
    # A fresh instance over the same root sees the prior registration (durable across sessions).
    reopened = FileModelRegistry(root)
    assert reopened.latest("ens-v1") is not None
    assert reopened.get(card.model_id).model == _FakeModel((5.0,))


def test_file_registry_writes_card_and_artifact(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    card = _register(FileModelRegistry(root, clock=_fixed_clock), _FakeModel((1.0,)))
    version_dir = root / "ens-v1" / "0001"
    assert (version_dir / "card.json").exists()
    assert (version_dir / "model.pkl").exists()
    _ = card  # the card mirrors the on-disk json


def test_file_registry_detects_a_corrupted_artifact(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    card = _register(FileModelRegistry(root, clock=_fixed_clock), _FakeModel((1.0,)))
    (root / "ens-v1" / "0001" / "model.pkl").write_bytes(b"tampered")
    with pytest.raises(RegistryError, match="fingerprint mismatch"):
        FileModelRegistry(root).get(card.model_id)


def test_file_registry_rejects_unsafe_model_version(tmp_path: Path) -> None:
    registry = FileModelRegistry(tmp_path / "registry")
    with pytest.raises(RegistryError, match="invalid model_version"):
        _register(registry, _FakeModel((1.0,)), version="../escape")


def test_file_registry_rejects_malformed_model_id(tmp_path: Path) -> None:
    registry = FileModelRegistry(tmp_path / "registry")
    with pytest.raises(RegistryError, match="malformed model_id"):
        registry.get("no-version-number")


def test_file_registry_cards_empty_when_root_absent(tmp_path: Path) -> None:
    assert FileModelRegistry(tmp_path / "does-not-exist").cards() == []


def test_fingerprint_changes_with_model_content(tmp_path: Path) -> None:
    registry = InMemoryModelRegistry(clock=_fixed_clock)
    a = _register(registry, _FakeModel((1.0,)))
    b = _register(registry, _FakeModel((9.0,)))
    assert a.fingerprint != b.fingerprint  # different artifacts → different digests


def test_default_clock_stamps_a_tz_aware_ist_time() -> None:
    # No clock injected → the real IST clock is used; created_at must be timezone-aware.
    card = InMemoryModelRegistry().register(
        _FakeModel((1.0,)),
        model_version="ens-v1",
        data_version="d",
        feature_set_version="f",
        label_version="l",
    )
    assert card.created_at.tzinfo is not None


def test_card_round_trips_through_dict() -> None:
    card = ModelCard(
        model_id="ens-v1-0001",
        model_version="ens-v1",
        version=1,
        data_version="d",
        feature_set_version="f",
        label_version="l",
        created_at=_fixed_clock(),
        fingerprint="abc",
        metrics={"auc": np.float64(0.9)},
        params={"method": "stack"},
    )
    restored = ModelCard.from_dict(card.to_dict())
    assert restored.created_at == card.created_at
    assert restored.metrics["auc"] == pytest.approx(0.9)
    assert restored.params["method"] == "stack"
