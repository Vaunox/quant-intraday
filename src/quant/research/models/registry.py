"""The model registry (Deep Dive #2 §4 output contract; Layer 5 MLOps registry).

*"Output contract of Module 4: a versioned, calibrated … model pipeline … — **every artifact
tagged with the data + feature + label versions it was trained on.**"* This module is that
registry: it versions a trained model together with the exact data/feature/label/model
versions behind it, so any registered model is reproducible and auditable, and (in Phase 5)
champion/challenger promotion and **instant rollback** have concrete versions to act on.

Design mirrors the rest of the storage layer (Ground Rule 1): a narrow :class:`ModelRegistry`
Protocol with two implementations behind it — :class:`InMemoryModelRegistry` (the test/in-process
default) and :class:`FileModelRegistry` (a JSON card + a pickled artifact under a directory
tree, all paths via :mod:`pathlib` for OS-portability per Ground Rule 2). The registry is
storage, not training: it persists whatever fitted object it is given (baseline, ensemble, or
a fake in tests) plus its :class:`ModelCard`, and assigns the version + an integrity
fingerprint. It imports no model library, so it stays decoupled from LightGBM/XGBoost.
"""

import hashlib
import json
import pickle
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from quant.core.calendar import IST
from quant.core.logging import get_logger
from quant.research.models.errors import ModelError

_logger = get_logger(__name__)

#: A clock returning the registration time (injectable for deterministic tests).
Clock = Callable[[], datetime]

#: Artifact filenames inside a file-registry version directory.
_CARD_FILE = "card.json"
_MODEL_FILE = "model.pkl"


def _default_clock() -> datetime:
    """Return the current instant in IST (the system's canonical timezone)."""
    return datetime.now(IST)


class RegistryError(ModelError):
    """A model-registry operation failed (unknown id, missing version tag, corrupt store)."""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """The reproducibility record stored alongside every registered model.

    The four version tags are the §4 output contract — a registered model always records the
    data, feature, label, and model definitions it was trained on. ``model_id`` and ``version``
    are assigned by the registry at registration; ``fingerprint`` is the SHA-256 of the pickled
    artifact (tamper/identity check). ``metrics``/``params``/``importances``/``tags`` carry the
    purged-CV evaluation so a card is self-describing without re-loading the model.
    """

    model_id: str
    model_version: str
    version: int
    data_version: str
    feature_set_version: str
    label_version: str
    created_at: datetime
    fingerprint: str = ""
    metrics: Mapping[str, float] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    importances: Mapping[str, float] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (``created_at`` as an ISO-8601 string)."""
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "version": self.version,
            "data_version": self.data_version,
            "feature_set_version": self.feature_set_version,
            "label_version": self.label_version,
            "created_at": self.created_at.isoformat(),
            "fingerprint": self.fingerprint,
            "metrics": dict(self.metrics),
            "params": dict(self.params),
            "importances": dict(self.importances),
            "tags": dict(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelCard":
        """Rebuild a card from its :meth:`to_dict` form."""
        return cls(
            model_id=payload["model_id"],
            model_version=payload["model_version"],
            version=int(payload["version"]),
            data_version=payload["data_version"],
            feature_set_version=payload["feature_set_version"],
            label_version=payload["label_version"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            fingerprint=payload.get("fingerprint", ""),
            metrics=dict(payload.get("metrics", {})),
            params=dict(payload.get("params", {})),
            importances=dict(payload.get("importances", {})),
            tags=dict(payload.get("tags", {})),
        )


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A model retrieved from the registry: the fitted object plus its :class:`ModelCard`."""

    model: Any
    card: ModelCard


@runtime_checkable
class ModelRegistry(Protocol):
    """Versioned store for trained models + their reproducibility cards."""

    def register(
        self,
        model: object,
        *,
        model_version: str,
        data_version: str,
        feature_set_version: str,
        label_version: str,
        metrics: Mapping[str, float] | None = None,
        params: Mapping[str, Any] | None = None,
        importances: Mapping[str, float] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> ModelCard:
        """Persist ``model`` with its version tags; return the completed, versioned card."""
        ...

    def get(self, model_id: str) -> RegisteredModel:
        """Return the model + card for ``model_id`` (raises if unknown)."""
        ...

    def latest(self, model_version: str) -> RegisteredModel | None:
        """Return the highest-version model for ``model_version`` (``None`` if none)."""
        ...

    def cards(self) -> Sequence[ModelCard]:
        """Return every registered card (registration order not guaranteed)."""
        ...


def _fingerprint(model_bytes: bytes) -> str:
    """Return the SHA-256 hex digest of the serialized model (integrity/identity)."""
    return hashlib.sha256(model_bytes).hexdigest()


def _build_card(
    *,
    model_version: str,
    version: int,
    fingerprint: str,
    data_version: str,
    feature_set_version: str,
    label_version: str,
    created_at: datetime,
    metrics: Mapping[str, float] | None,
    params: Mapping[str, Any] | None,
    importances: Mapping[str, float] | None,
    tags: Mapping[str, str] | None,
) -> ModelCard:
    """Assemble a completed :class:`ModelCard` (shared by both registry implementations)."""
    return ModelCard(
        model_id=f"{model_version}-{version:04d}",
        model_version=model_version,
        version=version,
        data_version=data_version,
        feature_set_version=feature_set_version,
        label_version=label_version,
        created_at=created_at,
        fingerprint=fingerprint,
        metrics=dict(metrics or {}),
        params=dict(params or {}),
        importances=dict(importances or {}),
        tags=dict(tags or {}),
    )


class InMemoryModelRegistry:
    """An in-process :class:`ModelRegistry` — the default, and what the tests assert against."""

    def __init__(self, *, clock: Clock = _default_clock) -> None:
        """Start empty; ``clock`` stamps ``created_at`` (injectable for determinism)."""
        self._clock = clock
        self._models: dict[str, RegisteredModel] = {}
        self._versions: dict[str, int] = {}  # model_version -> highest version assigned

    def register(
        self,
        model: object,
        *,
        model_version: str,
        data_version: str,
        feature_set_version: str,
        label_version: str,
        metrics: Mapping[str, float] | None = None,
        params: Mapping[str, Any] | None = None,
        importances: Mapping[str, float] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> ModelCard:
        """Assign the next version for ``model_version`` and store the model + card."""
        version = self._versions.get(model_version, 0) + 1
        card = _build_card(
            model_version=model_version,
            version=version,
            fingerprint=_fingerprint(pickle.dumps(model)),
            data_version=data_version,
            feature_set_version=feature_set_version,
            label_version=label_version,
            created_at=self._clock(),
            metrics=metrics,
            params=params,
            importances=importances,
            tags=tags,
        )
        self._versions[model_version] = version
        self._models[card.model_id] = RegisteredModel(model=model, card=card)
        _logger.info("model registered", extra={"model_id": card.model_id, "version": version})
        return card

    def get(self, model_id: str) -> RegisteredModel:
        """Return the stored model + card for ``model_id``."""
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise RegistryError(f"no model registered under id {model_id!r}") from exc

    def latest(self, model_version: str) -> RegisteredModel | None:
        """Return the highest-version model for ``model_version`` (``None`` if none)."""
        version = self._versions.get(model_version)
        if version is None:
            return None
        return self._models[f"{model_version}-{version:04d}"]

    def cards(self) -> Sequence[ModelCard]:
        """Return every registered card."""
        return [registered.card for registered in self._models.values()]


class FileModelRegistry:
    """A :class:`ModelRegistry` persisting cards + pickled artifacts under a directory tree.

    Layout (all paths via :mod:`pathlib`): ``root / <model_version> / <NNNN> / card.json`` +
    ``model.pkl``. Each registration is its own version directory, so the store is append-only
    and the next version is just ``max(existing) + 1`` — durable across processes/sessions, the
    property the registry needs for rollback (Layer 5).
    """

    def __init__(self, root: Path, *, clock: Clock = _default_clock) -> None:
        """Bind the registry to ``root`` (created on first write); ``clock`` stamps cards."""
        self._root = Path(root)
        self._clock = clock

    def register(
        self,
        model: object,
        *,
        model_version: str,
        data_version: str,
        feature_set_version: str,
        label_version: str,
        metrics: Mapping[str, float] | None = None,
        params: Mapping[str, Any] | None = None,
        importances: Mapping[str, float] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> ModelCard:
        """Write the next version directory for ``model_version`` (card.json + model.pkl)."""
        model_bytes = pickle.dumps(model)
        version = self._next_version(model_version)
        card = _build_card(
            model_version=model_version,
            version=version,
            fingerprint=_fingerprint(model_bytes),
            data_version=data_version,
            feature_set_version=feature_set_version,
            label_version=label_version,
            created_at=self._clock(),
            metrics=metrics,
            params=params,
            importances=importances,
            tags=tags,
        )
        version_dir = self._version_dir(model_version, version)
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / _MODEL_FILE).write_bytes(model_bytes)
        (version_dir / _CARD_FILE).write_text(
            json.dumps(card.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        _logger.info(
            "model registered", extra={"model_id": card.model_id, "path": str(version_dir)}
        )
        return card

    def get(self, model_id: str) -> RegisteredModel:
        """Load the model + card for ``model_id`` (``<model_version>-<NNNN>``)."""
        model_version, version = _parse_model_id(model_id)
        version_dir = self._version_dir(model_version, version)
        if not (version_dir / _CARD_FILE).exists():
            raise RegistryError(f"no model registered under id {model_id!r}")
        return self._load(version_dir)

    def latest(self, model_version: str) -> RegisteredModel | None:
        """Return the highest-version model for ``model_version`` (``None`` if none)."""
        versions = self._existing_versions(model_version)
        if not versions:
            return None
        return self._load(self._version_dir(model_version, max(versions)))

    def cards(self) -> Sequence[ModelCard]:
        """Return every card under the registry root."""
        if not self._root.exists():
            return []
        return [
            ModelCard.from_dict(json.loads(card_path.read_text(encoding="utf-8")))
            for card_path in sorted(self._root.glob(f"*/*/{_CARD_FILE}"))
        ]

    def _load(self, version_dir: Path) -> RegisteredModel:
        """Load and integrity-check the artifact + card in ``version_dir``."""
        card = ModelCard.from_dict(
            json.loads((version_dir / _CARD_FILE).read_text(encoding="utf-8"))
        )
        model_bytes = (version_dir / _MODEL_FILE).read_bytes()
        if card.fingerprint and _fingerprint(model_bytes) != card.fingerprint:
            raise RegistryError(f"fingerprint mismatch for {card.model_id} (artifact corrupted)")
        return RegisteredModel(model=pickle.loads(model_bytes), card=card)

    def _next_version(self, model_version: str) -> int:
        """Return ``max(existing version) + 1`` for ``model_version`` (1 if none yet)."""
        existing = self._existing_versions(model_version)
        return (max(existing) + 1) if existing else 1

    def _existing_versions(self, model_version: str) -> list[int]:
        """Return the version numbers already present for ``model_version``."""
        parent = self._root / _safe_name(model_version)
        if not parent.exists():
            return []
        return [int(child.name) for child in parent.iterdir() if child.name.isdigit()]

    def _version_dir(self, model_version: str, version: int) -> Path:
        """Return the directory path for one version of one model."""
        return self._root / _safe_name(model_version) / f"{version:04d}"


def _safe_name(model_version: str) -> str:
    """Reject a model version that is unsafe as a directory name (fail loud, no traversal)."""
    if (
        not model_version
        or "/" in model_version
        or "\\" in model_version
        or model_version in {".", ".."}
    ):
        raise RegistryError(f"invalid model_version for a path segment: {model_version!r}")
    return model_version


def _parse_model_id(model_id: str) -> tuple[str, int]:
    """Split ``<model_version>-<NNNN>`` into its parts (raises on a malformed id)."""
    base, _, suffix = model_id.rpartition("-")
    if not base or not suffix.isdigit():
        raise RegistryError(f"malformed model_id {model_id!r} (expected '<model_version>-NNNN')")
    return base, int(suffix)
