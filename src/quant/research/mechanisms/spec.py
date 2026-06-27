"""Non-directional / event-driven strategy-specification layer (Part VI / P6.1).

The original program's thesis — a *directional*, ML-predicted edge from commodity bar-data
features — was tested to honest exhaustion and closed (``docs/FINDINGS.md``). Part VI pursues
a different thesis: retail-accessible alpha comes from **non-directional mechanical edges** —
structural flows, statistical relationships, event mechanics — judged by the **same**
seven-point kill-gate. **This module does not re-implement the judge** (Part VI mandate); it is
the thin adapter that lets any mechanism produce the position/return series the *existing*
Combinatorial-Purged-CV engine (:mod:`quant.research.validation.cpcv`) already consumes.

A mechanism is described by its **events** (when a trade triggers), its **entry / exit /
holding** window, and its per-event **weight** (sign + size). Concretely a :class:`StrategySpec`
exposes:

* ``label_times`` — event-indexed ``t0 -> t1`` spans (entry time → exit/resolution time),
  identical in contract to :class:`~quant.research.validation.splits.PurgedKFold` and CPCV, so
  the existing purge + embargo apply unchanged on the time axis.
* ``fit(train_positions)`` — optional in-sample calibration (e.g. the cointegration selection
  in P7.2). Rule-based mechanisms (e.g. index-rebalance flow) leave it a no-op. **Any in-sample
  search done here is a "thing tried" and must be charged to the trial count (P6.2).**
* ``event_returns(positions)`` — the **net, cost-inclusive** per-event return for the events at
  ``positions`` (integer positions into ``label_times``), indexed by those events' timestamps.

:func:`spec_backtest_fn` turns a spec into the ``BacktestFn`` the CPCV engine already takes, and
:func:`evaluate_spec_under_cpcv` runs it through that engine to reconstruct the φ path-Sharpe
distribution — exactly as :func:`~quant.research.validation.active.evaluate_active_under_cpcv`
does for the factor book, just on an arbitrary mechanism's per-event returns. The reference
:class:`SeriesStrategySpec` wraps a precomputed net-return series, the minimal spec that proves
the harness end-to-end and is reusable wherever a mechanism computes its returns elsewhere.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.mechanisms.errors import SpecError
from quant.research.mechanisms.trials import TrialCountSource, deflated_sharpe_auto
from quant.research.reports.killgate import KillGateEvidence
from quant.research.reports.report import profit_factor, regime_breakdown, trade_concentration
from quant.research.validation.cpcv import BacktestFn, CombinatorialPurgedCV, PathDistribution
from quant.research.validation.splits import _validate_label_times

_logger = get_logger(__name__)


@runtime_checkable
class StrategySpec(Protocol):
    """A non-directional / event-driven strategy, expressed as per-event net returns.

    Implementations describe a mechanism by its event timeline and the cost-inclusive return
    of each event; the harness plugs that into the existing CPCV + kill-gate. See the module
    docstring for the event / entry / exit / holding / weight semantics.
    """

    @property
    def name(self) -> str:
        """A short, stable identifier for the mechanism (used in logs and the trial count)."""
        ...

    @property
    def label_times(self) -> pd.Series:
        """Event-indexed ``t0 -> t1`` spans (entry → exit), the CPCV/purge timeline."""
        ...

    def fit(self, train_positions: npt.NDArray[np.intp]) -> None:
        """Optionally calibrate on the training events only (no-op for rule-based specs).

        Any in-sample selection here is a trial and must be charged to the trial count (P6.2).
        Must never touch events outside ``train_positions`` (point-in-time, Inviolable Rule 2).
        """
        ...

    def event_returns(self, positions: npt.NDArray[np.intp]) -> pd.Series:
        """Net (cost-inclusive) per-event returns for ``positions``, indexed by their timestamps."""
        ...


@dataclass(frozen=True, slots=True)
class SeriesStrategySpec:
    """The reference :class:`StrategySpec`: a precomputed net-return series + its label times.

    The minimal, honest spec — it wraps an already-computed, **net of cost** per-event return
    series (one value per event in ``label_times``). ``fit`` is a no-op (nothing is calibrated)
    and ``event_returns`` slices the series by position. This both proves the harness end-to-end
    (P6.1 done-when) and is genuinely reusable: a mechanism that computes its returns elsewhere
    (e.g. a vectorized index-rebalance backtest) adapts to the engine by wrapping its output here.
    """

    name: str
    times: pd.Series  # event-indexed t0 -> t1 spans (the CPCV timeline)
    net_returns: pd.Series  # event-indexed net per-event returns (same index as ``times``)

    def __post_init__(self) -> None:
        """Validate the return series aligns one-for-one with the label-time index."""
        if not self.net_returns.index.equals(self.times.index):
            raise SpecError(
                f"{self.name}: net_returns index must equal label_times index "
                f"({len(self.net_returns)} vs {len(self.times)} rows / mismatched order)"
            )

    @property
    def label_times(self) -> pd.Series:
        """The event ``t0 -> t1`` spans driving purge/embargo."""
        return self.times

    def fit(self, train_positions: npt.NDArray[np.intp]) -> None:
        """No-op: a precomputed series has nothing to calibrate."""
        return None

    def event_returns(self, positions: npt.NDArray[np.intp]) -> pd.Series:
        """Return the net per-event returns at ``positions`` (by integer position)."""
        return self.net_returns.iloc[positions]


def spec_backtest_fn(spec: StrategySpec) -> BacktestFn:
    """Adapt a :class:`StrategySpec` into the ``BacktestFn`` the CPCV engine already consumes.

    The returned callable matches :data:`~quant.research.validation.cpcv.BacktestFn`:
    ``(train_positions, test_positions) -> per-test-event net returns``. It fits the spec on the
    purged training events (a no-op for rule-based mechanisms) and returns the OOS net returns on
    the test events — **no change to the validation engine**, which is the whole point of P6.1.
    """

    def backtest(train: npt.NDArray[np.intp], test: npt.NDArray[np.intp]) -> pd.Series:
        spec.fit(train)
        return spec.event_returns(test)

    return backtest


@dataclass(frozen=True, slots=True)
class MechanismEvaluation:
    """The CPCV outcome for a mechanism: the per-observation path-Sharpe distribution + paths.

    ``distribution`` holds **per-observation** (non-annualised) path-Sharpes, so the DSR is
    computed in matching units; :attr:`annualised_median_sharpe` annualises the median for
    kill-gate criterion 1. ``representative_path`` is one full-timeline path (φ paths each tile
    the timeline once) — the per-event net series criteria 5 & 7 are read from, exactly as the
    P2.9 pipeline reads ``paths[0]``.
    """

    name: str
    distribution: PathDistribution
    paths: tuple[pd.Series, ...]
    combined: pd.Series  # the concatenated net returns across all φ CPCV paths
    periods_per_year: float

    @property
    def representative_path(self) -> pd.Series:
        """One full-timeline net per-event return path (NaNs dropped)."""
        return self.paths[0].dropna() if self.paths else pd.Series(dtype="float64")

    @property
    def annualised_median_sharpe(self) -> float:
        """Median path-Sharpe, annualised (kill-gate criterion 1)."""
        return float(self.distribution.median) * math.sqrt(self.periods_per_year)

    @property
    def fraction_negative(self) -> float:
        """Fraction of CPCV paths with a negative Sharpe (criterion 4)."""
        return float(self.distribution.fraction_negative)

    @property
    def worst_path_sharpe(self) -> float:
        """Worst path's annualised Sharpe (criterion 4)."""
        return float(self.distribution.minimum) * math.sqrt(self.periods_per_year)

    def deflated_sharpe(self, trial_source: TrialCountSource) -> float:
        """The DSR on the concatenated net returns at the **live cumulative** trial count (P6.2).

        Routes through :func:`~quant.research.mechanisms.trials.deflated_sharpe_auto`, so ``N`` is
        pulled from ``trial_source`` and is never a hard-coded literal (FINDINGS §4.1 cause (b)).
        Path-concatenated basis (the FINDINGS §3 convention) — read alongside :attr:`dedup_tstat`.
        """
        variance = (
            float(np.var(self.distribution.path_sharpes, ddof=1))
            if self.distribution.num_paths > 1
            else 0.0
        )
        return deflated_sharpe_auto(self.combined, variance, trial_source=trial_source)

    @property
    def dedup_tstat(self) -> float:
        """The honest de-duplicated t-stat of the edge (FINDINGS §3).

        The φ CPCV paths are overlapping reconstructions of the same events, so the
        path-concatenated t-stat over-counts by ≈ ``√φ``; dividing it out gives the independent,
        de-duplicated t-stat to read against the multiple-testing hurdle.
        """
        values = self.combined.to_numpy(dtype="float64")
        values = values[~np.isnan(values)]
        std = float(values.std(ddof=1)) if values.size > 1 else 0.0
        if std == 0.0 or values.size < 2:
            return 0.0
        t_concatenated = float(values.mean()) / std * math.sqrt(values.size)
        phi = max(self.distribution.num_paths, 1)
        return t_concatenated / math.sqrt(phi)


def evaluate_spec_under_cpcv(
    spec: StrategySpec,
    cpcv: CombinatorialPurgedCV,
    *,
    periods_per_year: float,
) -> MechanismEvaluation:
    """Run a mechanism through the **existing** CPCV engine; reconstruct its path distribution.

    Args:
        spec: the mechanism, exposing ``label_times`` + per-event net returns.
        cpcv: the configured combinatorial purged CV (its embargo must cover ≥ one label horizon).
        periods_per_year: annualisation factor for the path-Sharpe (e.g. 2 for semi-annual
            index-rebalance events, 252 for a daily pairs spread). Explicit, never a hidden
            default — the cadence differs by mechanism (Ground Rule 2).

    Returns:
        A :class:`MechanismEvaluation` (per-observation distribution + φ paths + concatenated nets).
    """
    paths, distribution = cpcv.run(spec.label_times, spec_backtest_fn(spec), periods_per_year=None)
    combined = pd.concat(list(paths)).dropna() if paths else pd.Series(dtype="float64")
    _logger.info(
        "mechanism evaluated under cpcv",
        extra={
            "mechanism": spec.name,
            "num_paths": distribution.num_paths,
            "median_path_sharpe": distribution.median,
        },
    )
    return MechanismEvaluation(
        name=spec.name,
        distribution=distribution,
        paths=tuple(paths),
        combined=combined,
        periods_per_year=periods_per_year,
    )


def mechanism_kill_gate_evidence(
    evaluation: MechanismEvaluation,
    *,
    trial_source: TrialCountSource,
    pbo: float,
    robustness_passed: bool,
    robustness_detail: str,
    regime_labels: npt.NDArray[np.intp] | pd.Series | None = None,
    n_regimes: int = 0,
) -> KillGateEvidence:
    """Assemble the seven-point :class:`~quant.research.reports.killgate.KillGateEvidence`.

    Bundles a mechanism's CPCV outcome with the auxiliary evidence the existing kill-gate judges
    — DSR at the **live cumulative** trial count (P6.2), PBO, the robustness battery verdict, and
    the per-regime net-return breakdown — into the primitive evidence
    :func:`~quant.research.reports.killgate.evaluate_kill_gate` consumes **unchanged**. Profit
    factor, trade concentration, and the regime breakdown are read from the representative
    full-timeline path (the same convention as the P2.9 pipeline).

    Args:
        evaluation: the mechanism's CPCV evaluation.
        trial_source: the cumulative trial-count source feeding the DSR (P6.2).
        pbo: Probability of Backtest Overfitting over the mechanism's candidate-config panel.
        robustness_passed: the P2.8 robustness battery's overall verdict (criterion 6).
        robustness_detail: a short human-readable battery summary (criterion 6 detail).
        regime_labels: per-event regime index aligned to the representative path (criterion 7);
            ``None`` leaves criterion 7 unjudged (it then cannot pass — the honest default).
        n_regimes: number of regimes the labels span (required when ``regime_labels`` is given).

    Returns:
        The :class:`KillGateEvidence` ready for ``evaluate_kill_gate``.
    """
    net = evaluation.representative_path.to_numpy(dtype="float64")
    regime_means: Mapping[int, float]
    regime_counts: Mapping[int, int]
    if regime_labels is None:
        regime_means, regime_counts = {}, {}
    else:
        labels = np.asarray(regime_labels, dtype=np.intp).ravel()
        if labels.shape[0] != net.shape[0]:
            raise SpecError(
                f"{evaluation.name}: regime_labels length {labels.shape[0]} != "
                f"representative path length {net.shape[0]}"
            )
        regime_means, regime_counts = regime_breakdown(labels, net, n_regimes)
    return KillGateEvidence(
        cpcv_median_path_sharpe=evaluation.annualised_median_sharpe,
        deflated_sharpe_ratio=evaluation.deflated_sharpe(trial_source),
        pbo=pbo,
        fraction_negative_paths=evaluation.fraction_negative,
        worst_path_sharpe=evaluation.worst_path_sharpe,
        profit_factor=profit_factor(net),
        trade_concentration=trade_concentration(net),
        robustness_passed=robustness_passed,
        robustness_detail=robustness_detail,
        regime_mean_returns=regime_means,
        regime_observation_counts=regime_counts,
    )


def validate_spec_timeline(spec: StrategySpec, *, min_groups: int) -> None:
    """Fail loudly if a spec's ``label_times`` violates the CPCV contract (Ground Rule 7).

    A thin guard around the shared
    :func:`~quant.research.validation.splits._validate_label_times` primitive so a malformed
    mechanism timeline (unsorted index, ``t1`` before ``t0``, too few events for the scheme) is
    rejected at the harness boundary with a mechanism-named error rather than deep in the engine.
    """
    _validate_label_times(spec.label_times, min_groups)
