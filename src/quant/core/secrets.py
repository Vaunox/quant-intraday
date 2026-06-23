"""Single interface for retrieving (and writing) secrets.

Ground Rule 2: secrets (API keys, tokens, credentials) are NEVER stored in code or
config files, never committed, and never logged. They come only from a secrets
manager / environment variables / a local secret store, accessed exclusively
through the :class:`Secrets` interface so the rest of the system never reads
``os.environ`` (or a file) for credentials directly.

Two backing sources, in precedence order:

1. **Environment variables** (highest precedence) under a fixed prefix — how prod
   (AWS Secrets Manager) and CI inject secrets without touching disk.
2. A **file-backed store** at ``~/.quant-intraday/secrets.json`` — the cross-platform
   fallback for the dev box, written by :meth:`Secrets.set` (e.g. the daily Kite
   access token from the morning-auth helper, P2A.2). Created on first write with
   ``0600`` permissions on POSIX, gitignored, never committed.

This is the repository pattern (cf. the P1.3 storage ``Repository``): the dev-time
file store and a future prod-time AWS Secrets Manager backend are two implementations
behind one interface, so the Phase-5.2 / Phase-8 swap is a backend change, not a
caller change. A missing secret fails loudly with a clear, actionable error that names
the source(s) to set - but never the value.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

#: Prefix applied to logical secret names to form the backing environment variable.
#: e.g. logical name ``kite_api_secret`` -> env var ``QUANT_SECRET_KITE_API_SECRET``.
DEFAULT_SECRET_PREFIX = "QUANT_SECRET_"


class MissingSecretError(RuntimeError):
    """Raised when a required secret is not present in any configured source."""


class SecretStoreError(RuntimeError):
    """Raised when the file-backed secret store is corrupt or cannot be written."""


@runtime_checkable
class Secrets(Protocol):
    """Interface for secret retrieval/storage (inject this; never touch os.environ)."""

    def get(self, name: str) -> str:
        """Return the secret ``name`` or raise :class:`MissingSecretError`."""
        ...

    def get_optional(self, name: str) -> str | None:
        """Return the secret ``name`` or ``None`` if it is not set."""
        ...

    def set(self, name: str, value: str) -> None:
        """Persist ``name`` to the writable backing store (raises if none configured)."""
        ...


@dataclass(frozen=True)
class FileSecretStore:
    """A JSON file-backed secret store (the cross-platform dev-box fallback).

    Keys are the (lowercased) logical secret names; values are the secret strings. The
    file is created on first :meth:`set` with restrictive permissions (``0600`` on POSIX;
    on Windows the default ACL applies — keep the home directory off shared drives, see the
    P2A.2 runbook). Reads tolerate a missing file (returns nothing) but **fail loud** on a
    malformed file rather than silently masking a corrupt credential store (Ground Rule 7).
    """

    path: Path

    @classmethod
    def default(cls) -> "FileSecretStore":
        """The standard location: ``~/.quant-intraday/secrets.json`` (outside any repo)."""
        return cls(Path.home() / ".quant-intraday" / "secrets.json")

    def get(self, name: str) -> str | None:
        """Return the stored value for ``name`` (case-insensitive), or ``None``."""
        value = self._read_all().get(name.lower())
        return value if value else None

    def set(self, name: str, value: str) -> None:
        """Write ``name = value`` to the store, preserving other keys (atomic, ``0600``)."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = self._read_all()
        data[name.lower()] = value
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(0o600)  # effective on POSIX; a no-op-ish default on Windows
        tmp.replace(self.path)  # atomic swap into place (cross-platform)

    def _read_all(self) -> dict[str, str]:
        """Return the full ``{name: value}`` map (``{}`` if absent; raises if malformed)."""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError(
                f"secret store at {self.path} is unreadable/malformed: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise SecretStoreError(f"secret store at {self.path} must contain a JSON object")
        return {str(key).lower(): str(value) for key, value in data.items()}


@dataclass(frozen=True)
class EnvSecrets:
    """Read secrets from environment variables, falling back to a file store.

    The backing variable for a logical name is ``f"{prefix}{name.upper()}"``. An unset or
    empty variable is treated as "missing", at which point the optional ``file_store`` (if
    configured) is consulted - so env vars always win over the file (prod/CI injection beats
    the dev-box file). :meth:`set` writes to the ``file_store`` (a process cannot persist an
    env var for other processes).

    ``environ`` and ``file_store`` are injectable for testing; ``environ`` is excluded from
    ``repr`` so secret values can never leak into logs or tracebacks.
    """

    prefix: str = DEFAULT_SECRET_PREFIX
    environ: Mapping[str, str] | None = field(default=None, repr=False)
    file_store: FileSecretStore | None = None

    def _env(self) -> Mapping[str, str]:
        """Return the active environment mapping (live ``os.environ`` by default)."""
        return os.environ if self.environ is None else self.environ

    def env_var_name(self, name: str) -> str:
        """Return the backing environment-variable name for a logical secret name."""
        return f"{self.prefix}{name.upper()}"

    def get_optional(self, name: str) -> str | None:
        """Return the secret value (env first, then file store), or ``None`` if unset."""
        value = self._env().get(self.env_var_name(name))
        if value:
            return value
        if self.file_store is not None:
            return self.file_store.get(name)
        return None

    def get(self, name: str) -> str:
        """Return the secret value.

        Raises:
            MissingSecretError: If the secret is unset/empty in every source. The message
                names the source(s) to set, never the value.
        """
        value = self.get_optional(name)
        if value is None:
            hint = f"Provide it via the {self.env_var_name(name)} environment variable"
            if self.file_store is not None:
                hint += f" or the file secret store ({self.file_store.path})"
            raise MissingSecretError(f"Required secret {name!r} is not set. {hint}.")
        return value

    def set(self, name: str, value: str) -> None:
        """Persist ``name`` to the file store.

        Raises:
            SecretStoreError: If no ``file_store`` is configured (env vars cannot be set
                persistently for other processes from here - use :func:`default_secrets`).
        """
        if self.file_store is None:
            raise SecretStoreError(
                "no writable secret store configured; construct via default_secrets() "
                "or pass a file_store to persist secrets"
            )
        self.file_store.set(name, value)


def default_secrets(environ: Mapping[str, str] | None = None) -> EnvSecrets:
    """The standard secrets object: env vars (higher precedence) over the local file store.

    Use this where a process must read or write the dev-box file-backed secrets (e.g. the
    daily Kite access token, P2A.2). Prod/CI keep injecting via env vars, which win.
    """
    return EnvSecrets(environ=environ, file_store=FileSecretStore.default())
