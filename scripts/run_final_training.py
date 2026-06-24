#!/usr/bin/env python
r"""Runnable entry point for the P2A.6 final P2.7 training run.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.research.pipeline.cli` (Ground Rule 3). Train + register the production ensemble +
regime-gate model on the real backfilled universe, logged to persistent MLflow, e.g. (in the
research env, ``MLFLOW_TRACKING_URI`` set)::

    uv run --python .venv-research python scripts/run_final_training.py \
        --start 2021-06-24 --end 2026-06-23 --tracker mlflow

Exits non-zero only if the reloaded registry artifact does not predict identically to the
in-memory model (the round-trip check). See ``docs/operator_runbooks/P2A.6_final_run.md``.
"""

from quant.research.pipeline.cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
