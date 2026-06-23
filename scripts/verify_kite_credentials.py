#!/usr/bin/env python
r"""Runnable entry point for the P2A.1 read-only Kite credential check.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.data.brokers.verify` (Ground Rule 3 — production logic in ``src/quant``,
scripts stay thin). Run it in the shell where the Kite credentials are present in the
environment (the secrets interface), e.g.::

    uv run python scripts/verify_kite_credentials.py

It reports only the api_key's last 4 characters and the instrument count — never a
credential value. See ``docs/operator_runbooks/P2A.1_kite_signup.md``.
"""

from quant.data.brokers.verify import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
