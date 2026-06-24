#!/usr/bin/env python
r"""Runnable entry point for the P2.8 robustness battery + two-engine reconciliation.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.research.pipeline.robustness_cli` (Ground Rule 3). Stress the registered ensemble +
regime-gate strategy (parameter sensitivity, Monte Carlo trade shuffle, noise injection,
cross-symbol, synthetic-data) and reconcile a sample strategy across two independent backtest
engines, logged to persistent MLflow, e.g. (in the research env, ``MLFLOW_TRACKING_URI`` set)::

    uv run --python .venv-research python scripts/run_robustness.py \
        --start 2021-06-24 --end 2026-06-23 --tracker mlflow

Exits non-zero only if the two engines fail to reconcile within tolerance (an implementation
bug). A weak edge is reported, not a failure — the kill-gate verdict is P2.9's. See
``docs/operator_runbooks/P2.8_robustness.md``.
"""

from quant.research.pipeline.robustness_cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
