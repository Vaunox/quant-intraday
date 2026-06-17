"""Quant Intraday - Indian cash-equity intraday algorithmic trading system.

Top-level package. The codebase is organised into the six layers described in
``MASTER_BLUEPRINT_Claude_Build_Handoff.md``:

* ``core``      - shared domain types, interfaces (Protocols), config, secrets,
  logging, the NSE calendar, and constants.
* ``data``      - Layer 1: data ingestion, storage, hygiene, and the
  point-in-time feature library.
* ``research``  - Layer 2: labeling, models, the validation engine, and reports.
* ``capital``   - Layer 3: signal combination, portfolio construction, sizing,
  and the hard-limit risk engine.
* ``execution`` - Layer 4: OMS, order routing, reconciliation, safety, and
  implementation-shortfall measurement.
* ``ops``       - Layer 5: scheduling, monitoring, attribution, drift, MLOps,
  and platform plumbing.
* ``control``   - Layer 6: the control API gateway backing the mobile app.

Nothing is exported at the top level yet; import the specific subpackage you
need. ``__version__`` is the single source of truth for the package version.
"""

__version__ = "0.0.0"
