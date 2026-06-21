"""Honest trial-count tracking for the Deflated Sharpe Ratio (Deep Dive #2 §4b.3).

*"You must honestly track your trial count — every backtest variant counts, even the ones
you discarded. A raw Sharpe of 2 from 500 trials can deflate to insignificance."* The DSR
needs two numbers from the search you ran: **how many** strategies/configurations you
tried (``N``) and the **variance of their Sharpes** (``V``). This lightweight in-memory
log records both as you go; the model-tracking integration (MLflow) lands in P2.6.

**Units.** Record **non-annualised, per-observation** Sharpes here, so the variance is in
the same units as the observed Sharpe the DSR consumes (the DSR's ``√(T-1)`` term carries
the sample-length scaling). Trials are de-duplicated by name — re-running the same
configuration is the *same* trial, not a new one (double-counting would wrongly inflate
the deflation).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from quant.research.validation.metrics import ReturnsLike, sharpe_ratio


@dataclass(frozen=True, slots=True)
class Trial:
    """One recorded trial: a named configuration and its (non-annualised) Sharpe."""

    name: str
    sharpe: float


class TrialTracker:
    """An in-memory log of trial Sharpes, de-duplicated by name.

    Provides the trial count ``N`` and Sharpe variance ``V`` the
    :func:`~quant.research.validation.metrics.deflated_sharpe_ratio` needs.
    """

    def __init__(self) -> None:
        """Start an empty trial log."""
        self._sharpes: dict[str, float] = {}

    def record(self, name: str, sharpe: float) -> None:
        """Record (or overwrite) the ``sharpe`` of the trial identified by ``name``."""
        self._sharpes[name] = sharpe

    def record_returns(
        self, name: str, returns: ReturnsLike, periods_per_year: float | None = None
    ) -> float:
        """Compute a trial's Sharpe from its ``returns``, record it, and return it.

        Leave ``periods_per_year`` ``None`` (per-observation Sharpe) when the log feeds the
        DSR, so the trial variance matches the observed Sharpe's units.
        """
        sharpe = sharpe_ratio(returns, periods_per_year)
        self.record(name, sharpe)
        return sharpe

    @property
    def count(self) -> int:
        """Number of distinct trials recorded (the DSR's ``N``)."""
        return len(self._sharpes)

    @property
    def sharpes(self) -> npt.NDArray[np.float64]:
        """The recorded trial Sharpes, as an array."""
        return np.asarray(list(self._sharpes.values()), dtype="float64")

    @property
    def sharpe_variance(self) -> float:
        """Variance of the trial Sharpes (``ddof=1``); 0 with fewer than two trials."""
        if self.count < 2:
            return 0.0
        return float(np.var(self.sharpes, ddof=1))

    def trials(self) -> Sequence[Trial]:
        """Return the recorded trials as immutable ``Trial`` records."""
        return [Trial(name=name, sharpe=sharpe) for name, sharpe in self._sharpes.items()]
