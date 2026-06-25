"""The seven-point kill-gate (Deep Dive #2, "The kill-gate" — the most important paragraph).

*"Before any capital — paper or real — a strategy must pass all of these, on honest,
cost-inclusive, point-in-time data."* This module is the gate itself: a pure function from
**evidence** (already computed by the validation engine) plus the **thresholds** (fixed in
config before the run, Inviolable Rule 1) to a pass/fail **verdict** on each of the seven
criteria and the overall trade/don't-trade decision.

The gate is an **AND**: the verdict is PASS only if all seven criteria pass; otherwise KILL.
There is no "tweak until it passes" — that inflates the trial count the Deflated Sharpe punishes
(criterion 2), and most candidates *should* fail here (Inviolable Rule 7). The seven criteria:

1. CPCV median path-Sharpe > threshold, annualised, **after** full Indian costs + slippage.
2. Deflated Sharpe Ratio positive and significant given the honest trial count.
3. PBO below the threshold.
4. Narrow, positive CPCV path distribution — few/no negative paths, none deeply negative.
5. P&L not concentrated in a handful of trades (profit factor + single-trade share).
6. Survives the robustness battery (P2.8).
7. Edge stable across regimes (every sufficiently-observed regime's mean net return clears the bar).

This module imports nothing from the model or pipeline layers — it is fed primitive evidence,
so it stays a small, exhaustively-testable decision function.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant.core.config import KillGateConfig
from quant.core.logging import get_logger

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KillGateEvidence:
    """The computed evidence the kill-gate judges (all net-of-cost, point-in-time).

    Assembled by the validation report (P2.9) from the CPCV path distribution, the DSR, the
    PBO, the per-trade net returns, the robustness battery, and the regime breakdown. Holding
    primitives (not the upstream report objects) keeps the gate decoupled and pure.
    """

    cpcv_median_path_sharpe: float  # (1) annualised, net of costs
    deflated_sharpe_ratio: float  # (2) a probability in [0, 1]
    pbo: float  # (3)
    fraction_negative_paths: float  # (4)
    worst_path_sharpe: float  # (4) annualised
    profit_factor: float  # (5) gross profit / gross loss
    trade_concentration: float  # (5) largest single trade's share of gross profit, in [0, 1]
    robustness_passed: bool  # (6) the P2.8 battery's overall verdict
    robustness_detail: str  # (6) a short human-readable summary of the battery flags
    regime_mean_returns: Mapping[int, float]  # (7) per-regime mean net strategy return
    regime_observation_counts: Mapping[int, int]  # (7) per-regime observation count


@dataclass(frozen=True, slots=True)
class KillGateCriterion:
    """One criterion's outcome: whether it passed, the observed value, and why."""

    number: int  # 1..7
    name: str
    passed: bool
    detail: str  # human-readable observed-vs-threshold explanation

    @property
    def mark(self) -> str:
        """A pass/fail glyph for the rendered report."""
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True, slots=True)
class KillGateVerdict:
    """The seven criteria + the overall trade/don't-trade decision."""

    criteria: tuple[KillGateCriterion, ...]

    @property
    def passed(self) -> bool:
        """Whether **all** seven criteria passed (the gate is an AND)."""
        return all(criterion.passed for criterion in self.criteria)

    @property
    def verdict(self) -> str:
        """``"PASS"`` (proceed toward capital) or ``"KILL"`` (the strategy dies here)."""
        return "PASS" if self.passed else "KILL"

    @property
    def failed_criteria(self) -> tuple[KillGateCriterion, ...]:
        """The criteria that failed (empty on a PASS)."""
        return tuple(c for c in self.criteria if not c.passed)

    def render(self) -> str:
        """Render the verdict as a fixed-width text block (the report's decision section)."""
        lines = [
            "SEVEN-POINT KILL-GATE",
            "=" * 72,
            *(f"  [{c.mark}] ({c.number}) {c.name}: {c.detail}" for c in self.criteria),
            "-" * 72,
            f"  VERDICT: {self.verdict}"
            + ("" if self.passed else f"  ({len(self.failed_criteria)} criteria failed)"),
        ]
        return "\n".join(lines)


def evaluate_kill_gate(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateVerdict:
    """Evaluate the seven criteria against ``evidence`` and the configured thresholds.

    Returns a :class:`KillGateVerdict`; ``verdict.passed`` is the AND of all seven. Logs the
    outcome (the audit substrate for the trade/don't-trade decision).
    """
    criteria = (
        _criterion_1(evidence, config),
        _criterion_2(evidence, config),
        _criterion_3(evidence, config),
        _criterion_4(evidence, config),
        _criterion_5(evidence, config),
        _criterion_6(evidence),
        _criterion_7(evidence, config),
    )
    verdict = KillGateVerdict(criteria=criteria)
    _logger.info(
        "kill-gate evaluated",
        extra={
            "verdict": verdict.verdict,
            "failed": [c.number for c in verdict.failed_criteria],
        },
    )
    return verdict


def _criterion_1(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(1) CPCV median path-Sharpe > threshold, annualised, after costs."""
    passed = evidence.cpcv_median_path_sharpe > config.cpcv_median_sharpe_min
    return KillGateCriterion(
        number=1,
        name="CPCV median path-Sharpe (annualised, after costs)",
        passed=passed,
        detail=f"{evidence.cpcv_median_path_sharpe:.3f} vs > {config.cpcv_median_sharpe_min:.3f}",
    )


def _criterion_2(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(2) Deflated Sharpe Ratio positive and significant given the trial count."""
    passed = evidence.deflated_sharpe_ratio >= config.dsr_min
    return KillGateCriterion(
        number=2,
        name="Deflated Sharpe Ratio (vs honest trial count)",
        passed=passed,
        detail=f"{evidence.deflated_sharpe_ratio:.3f} vs >= {config.dsr_min:.3f}",
    )


def _criterion_3(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(3) PBO below the threshold."""
    passed = evidence.pbo <= config.pbo_max
    return KillGateCriterion(
        number=3,
        name="Probability of Backtest Overfitting",
        passed=passed,
        detail=f"{evidence.pbo:.3f} vs <= {config.pbo_max:.3f}",
    )


def _criterion_4(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(4) Narrow, positive CPCV distribution: few negative paths and none deeply negative."""
    few_negative = evidence.fraction_negative_paths <= config.max_fraction_negative_paths
    none_deep = evidence.worst_path_sharpe >= config.min_path_sharpe
    passed = few_negative and none_deep
    return KillGateCriterion(
        number=4,
        name="Narrow, positive CPCV path distribution",
        passed=passed,
        detail=(
            f"neg-fraction {evidence.fraction_negative_paths:.3f} vs "
            f"<= {config.max_fraction_negative_paths:.3f}; "
            f"worst path-Sharpe {evidence.worst_path_sharpe:.3f} vs >= {config.min_path_sharpe:.3f}"
        ),
    )


def _criterion_5(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(5) P&L not concentrated: profit factor and single-trade share."""
    pf_ok = evidence.profit_factor >= config.min_profit_factor
    concentration_ok = evidence.trade_concentration <= config.max_trade_concentration
    passed = pf_ok and concentration_ok
    return KillGateCriterion(
        number=5,
        name="P&L not concentrated in a few trades",
        passed=passed,
        detail=(
            f"profit factor {evidence.profit_factor:.3f} vs >= {config.min_profit_factor:.3f}; "
            f"top-trade share {evidence.trade_concentration:.3f} vs "
            f"<= {config.max_trade_concentration:.3f}"
        ),
    )


def _criterion_6(evidence: KillGateEvidence) -> KillGateCriterion:
    """(6) Survives the robustness battery (the P2.8 verdict against its own thresholds)."""
    return KillGateCriterion(
        number=6,
        name="Survives the robustness battery",
        passed=evidence.robustness_passed,
        detail=evidence.robustness_detail,
    )


def _criterion_7(evidence: KillGateEvidence, config: KillGateConfig) -> KillGateCriterion:
    """(7) Edge stable across regimes: every sufficiently-observed regime clears the bar."""
    judged: list[int] = [
        regime
        for regime, count in evidence.regime_observation_counts.items()
        if count >= config.regime_min_observations
    ]
    offenders = [
        regime
        for regime in judged
        if evidence.regime_mean_returns.get(regime, float("-inf")) < config.min_regime_mean_return
    ]
    passed = len(judged) > 0 and not offenders
    return KillGateCriterion(
        number=7,
        name="Edge stable across regimes",
        passed=passed,
        detail=_regime_detail(evidence, config, judged, offenders),
    )


def _regime_detail(
    evidence: KillGateEvidence,
    config: KillGateConfig,
    judged: Sequence[int],
    offenders: Sequence[int],
) -> str:
    """Human-readable regime breakdown for criterion 7."""
    if not judged:
        return f"no regime reached the {config.regime_min_observations}-observation floor"
    means = ", ".join(
        f"r{regime}={evidence.regime_mean_returns.get(regime, float('nan')):+.4f}"
        for regime in sorted(judged)
    )
    if offenders:
        return f"loss-making regime(s) {sorted(offenders)} [{means}]"
    return f"all {len(judged)} judged regimes >= {config.min_regime_mean_return:+.4f} [{means}]"
