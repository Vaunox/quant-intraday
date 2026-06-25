#!/usr/bin/env python
r"""Runnable entry point for the P2.9 validation report + seven-point kill-gate.

A thin shim: all logic lives in the importable, unit-tested
:mod:`quant.research.pipeline.validation_cli` (Ground Rule 3). Runs the full validation engine
(net-of-cost CPCV path distribution, Deflated Sharpe, PBO, walk-forward equity, robustness
battery, regime stability) against the registered artifact and emits the trade/don't-trade
verdict, logged to persistent MLflow, e.g. (in the research env, ``MLFLOW_TRACKING_URI`` set)::

    uv run --python .venv-research python scripts/run_validation_report.py \
        --start 2021-06-24 --end 2026-06-23 --tracker mlflow \
        --output docs/iteration_log/cycle-1_verdict.txt

Exit 0 once the report generates and the PASS/KILL verdict is emitted — a KILL is the expected,
successful outcome for most candidates (Inviolable Rule 7). See ``docs/operator_runbooks/
P2.9_killgate.md``.
"""

from quant.research.pipeline.validation_cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
