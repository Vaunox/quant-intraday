#!/usr/bin/env python
r"""Runnable entry point for the P2A.2 daily Kite morning-auth seed.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.data.brokers.morning_auth` (Ground Rule 3 — production logic in ``src/quant``,
scripts stay thin). Run it each trading morning in the project directory, e.g.::

    uv run python scripts/kite_morning_auth.py

It prints the Kite login URL, takes the one-time ``request_token`` you paste from the redirect,
exchanges it for a fresh ``access_token``, and persists the token to the secrets interface
(``kite_access_token``). Only the token's last 4 characters are logged. See
``docs/operator_runbooks/P2A.2_daily_auth.md``.
"""

from quant.data.brokers.morning_auth import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
