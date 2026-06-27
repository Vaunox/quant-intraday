"""The benchmark-relative seven-point kill-gate for the factor strategy (Phase 3X.8).

A pure threshold-checker: given the computed metrics and the thresholds locked in
``config/factor_default.yaml`` (Inviolable Rule 1 — fixed before any run), it emits a per-criterion
PASS/KILL verdict. Computing the metrics (active IR, DSR, PBO, …) is the orchestration's job; this
module only judges them, so it is fully unit-testable. A criterion whose metric was *not computed*
(``None``) counts as **not passed** — the gate never passes on an unmeasured criterion.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GateMetrics:
    """The computed evidence the kill-gate judges (active-return basis)."""

    active_ir: float  # annualised CPCV median active IR vs benchmark (criterion 1)
    dsr: float  # Deflated Sharpe Ratio on active returns at the honest N (criterion 2)
    fraction_negative: float  # fraction of negative active CPCV paths (criteria 4 & 5)
    worst_path_ir: float  # worst path's annualised active IR (criterion 4)
    pbo: float | None = None  # Probability of Backtest Overfitting (criterion 3)
    max_sector_weight: float | None = None  # realised max sector weight (criterion 7)
    max_single_factor_share: float | None = None  # max share of active return from one factor (7)
    robustness_passed: bool = False  # survived the robustness battery (criterion 6)


@dataclass(frozen=True, slots=True)
class FactorGateVerdict:
    """The seven-point verdict: each criterion -> (passed, human-readable detail)."""

    results: dict[str, tuple[bool, str]]

    @property
    def passed(self) -> bool:
        """Whether ALL criteria passed (the gate is cleared)."""
        return all(ok for ok, _ in self.results.values())

    def render(self) -> str:
        """A one-line-per-criterion PASS/KILL report ending in the overall verdict."""
        lines = [
            f"  [{'PASS' if ok else 'KILL'}] {name}: {detail}"
            for name, (ok, detail) in self.results.items()
        ]
        lines.append(f"VERDICT: {'PASS' if self.passed else 'KILL'}")
        return "\n".join(lines)


def _at_most(value: float | None, threshold: float) -> tuple[bool, str]:
    if value is None:
        return False, f"not computed (<= {threshold})"
    return value <= threshold, f"{value:.4f} <= {threshold}"


def _at_least(value: float | None, threshold: float) -> tuple[bool, str]:
    if value is None:
        return False, f"not computed (>= {threshold})"
    return value >= threshold, f"{value:.4f} >= {threshold}"


def evaluate_factor_gate(metrics: GateMetrics, kill_gate: Mapping[str, float]) -> FactorGateVerdict:
    """Judge ``metrics`` against the ``kill_gate`` thresholds; return the seven-point verdict.

    Args:
        metrics: the computed evidence (active IR, DSR, PBO, path stats, diversification).
        kill_gate: the ``kill_gate`` section of ``config/factor_default.yaml``.
    """
    sector_ok: tuple[bool, str]
    if metrics.max_sector_weight is None:
        sector_ok = (False, "max sector weight not computed")
    else:
        sector_ok = _at_most(
            metrics.max_sector_weight, float(kill_gate["max_sector_weight_pct"]) / 100.0
        )
    factor_ok = _at_most(
        metrics.max_single_factor_share, float(kill_gate["max_single_factor_active_share"])
    )

    results: dict[str, tuple[bool, str]] = {
        "1. active IR (annualised, net)": _at_least(
            metrics.active_ir, float(kill_gate["active_ir_min"])
        ),
        "2. deflated Sharpe ratio": _at_least(metrics.dsr, float(kill_gate["dsr_min"])),
        "3. probability of backtest overfitting": _at_most(
            metrics.pbo, float(kill_gate["pbo_max"])
        ),
        "4a. fraction negative paths": _at_most(
            metrics.fraction_negative, float(kill_gate["max_fraction_negative_paths"])
        ),
        "4b. worst path IR": _at_least(
            metrics.worst_path_ir, float(kill_gate["min_active_path_ir"])
        ),
        "5. every active path net-positive": (
            metrics.fraction_negative == 0.0,
            f"fraction_negative={metrics.fraction_negative:.4f} == 0",
        ),
        "6. survives robustness battery": (
            metrics.robustness_passed,
            "passed" if metrics.robustness_passed else "not run / failed",
        ),
        "7a. max sector weight": sector_ok,
        "7b. max single-factor active share": factor_ok,
    }
    return FactorGateVerdict(results=results)
