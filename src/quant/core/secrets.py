"""Single interface for retrieving secrets.

Ground Rule 2: secrets (API keys, tokens, credentials) are NEVER stored in code or
config files, never committed, and never logged. They come only from the process
environment (populated by a secrets manager / the operator), accessed exclusively
through the :class:`Secrets` interface so the rest of the system never reads
``os.environ`` for credentials directly.

A missing secret fails loudly with a clear, actionable error that names the
environment variable to set - but never the value.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: Prefix applied to logical secret names to form the backing environment variable.
#: e.g. logical name ``kite_api_secret`` -> env var ``QUANT_SECRET_KITE_API_SECRET``.
DEFAULT_SECRET_PREFIX = "QUANT_SECRET_"


class MissingSecretError(RuntimeError):
    """Raised when a required secret is not present in the environment."""


@runtime_checkable
class Secrets(Protocol):
    """Interface for secret retrieval (inject this; do not read os.environ directly)."""

    def get(self, name: str) -> str:
        """Return the secret ``name`` or raise :class:`MissingSecretError`."""
        ...

    def get_optional(self, name: str) -> str | None:
        """Return the secret ``name`` or ``None`` if it is not set."""
        ...


@dataclass(frozen=True)
class EnvSecrets:
    """Read secrets from environment variables under a fixed prefix.

    The backing variable for a logical name is ``f"{prefix}{name.upper()}"``. An
    unset or empty variable is treated as "missing".

    The ``environ`` mapping is injectable for testing and is excluded from ``repr``
    so secret values can never leak into logs or tracebacks.
    """

    prefix: str = DEFAULT_SECRET_PREFIX
    environ: Mapping[str, str] | None = field(default=None, repr=False)

    def _env(self) -> Mapping[str, str]:
        """Return the active environment mapping (live ``os.environ`` by default)."""
        return os.environ if self.environ is None else self.environ

    def env_var_name(self, name: str) -> str:
        """Return the backing environment-variable name for a logical secret name."""
        return f"{self.prefix}{name.upper()}"

    def get_optional(self, name: str) -> str | None:
        """Return the secret value, or ``None`` if unset/empty."""
        value = self._env().get(self.env_var_name(name))
        return value if value else None

    def get(self, name: str) -> str:
        """Return the secret value.

        Raises:
            MissingSecretError: If the secret is unset or empty. The message names
                the environment variable to set, never the value.
        """
        value = self.get_optional(name)
        if value is None:
            raise MissingSecretError(
                f"Required secret {name!r} is not set. "
                f"Provide it via the {self.env_var_name(name)} environment variable."
            )
        return value
