"""The robustness battery (Deep Dive #2 §4b.7 — "run before trusting anything").

A high CPCV path-Sharpe is necessary but not sufficient: it can still be a knife-edge fit, a
lucky trade ordering, or a methodology leak. §4b.7 stresses the edge from five angles, and the
kill-gate's criterion 6 is *"survives the robustness battery (parameter sensitivity, noise,
cross-symbol, synthetic)"*. This module implements those five stress tests:

* **Parameter sensitivity** — re-evaluate the strategy under small parameter perturbations.
  A robust edge survives; a *knife-edge* (the metric swings wildly, or flips sign) is overfit.
* **Monte Carlo trade shuffle** — randomise the order of the realised per-trade returns and ask
  whether the equity curve's *shape* (its drawdown) was robust or a lucky sequencing.
* **Noise injection** — add small Gaussian noise to the features and ask whether the edge
  persists or collapses.
* **Cross-symbol validation** — train on one set of names, evaluate on held-out names. A
  *universal* signal generalises; a *symbol-specific* one overfits.
* **Synthetic-data backtest** — run the *same* strategy recipe on simulated price paths that
  contain **no real historical luck** (López de Prado's complement to historical backtests).
  On pure-noise data the edge must centre near zero; a strong edge there is a methodology leak.

**Design (Ground Rule 1).** The model is injected, never imported here: every stress test takes
an :data:`EvaluateFn` — *"given the (possibly perturbed) point-in-time data, return the CPCV
path-Sharpe distribution"* — or a returns series. This keeps the battery a pure *validation*
utility with **no dependency on the model package** (and therefore none on LightGBM/XGBoost),
fully testable with fake evaluators; the concrete model evaluator is wired in by the pipeline
orchestration (:mod:`quant.research.pipeline.robustness`), the layer that already bridges the
model stack and the validation engine.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.logging import get_logger
from quant.research.validation.cpcv import PathDistribution
from quant.research.validation.errors import RobustnessError
from quant.research.validation.metrics import sharpe_ratio

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StrategyDataset:
    """The point-in-time inputs a strategy is evaluated (and stressed) on.

    Bundles the model feature matrix, the binary labels, the ``t0 -> t1`` label-resolution
    times (driving the purge/embargo), the realised per-event forward return of a unit long,
    and optionally the regime-gate features — all sharing **one** event-time index. This is the
    same shape :func:`~quant.research.models.evaluation.evaluate_ensemble_under_cpcv` consumes,
    expressed without importing the model package so the battery stays model-agnostic.
    """

    features: pd.DataFrame
    labels: pd.Series
    label_times: pd.Series
    forward_returns: pd.Series
    regime_features: pd.DataFrame | None = None

    def __post_init__(self) -> None:
        """Fail loud unless every component shares the features index (Ground Rule 7)."""
        index = self.features.index
        if not (index.equals(self.labels.index) and index.equals(self.label_times.index)):
            raise RobustnessError("features, labels, and label_times must share one index")
        if not index.equals(self.forward_returns.index):
            raise RobustnessError("forward_returns must share the features index")
        if self.regime_features is not None and not index.equals(self.regime_features.index):
            raise RobustnessError("regime_features must share the features index")

    def __len__(self) -> int:
        """Number of labelled events in the dataset."""
        return len(self.features)

    @property
    def feature_names(self) -> tuple[str, ...]:
        """The model feature columns (ordered)."""
        return tuple(str(column) for column in self.features.columns)

    def with_features(self, features: pd.DataFrame) -> "StrategyDataset":
        """Return a copy with ``features`` replaced (the rest shared) — used by noise injection."""
        return replace(self, features=features)


#: Evaluate a (possibly perturbed) dataset and return its CPCV path-Sharpe distribution. The
#: pipeline supplies the concrete ensemble + regime-gate evaluator; tests supply a fake.
EvaluateFn = Callable[[StrategyDataset], PathDistribution]

#: Score one held-out symbol's dataset after training on the others: return that symbol's
#: per-event out-of-sample strategy-return series (used by :func:`cross_symbol_validation`).
CrossSymbolScoreFn = Callable[[Sequence[StrategyDataset], StrategyDataset], pd.Series]

#: Generate one synthetic universe of bars (``{symbol -> canonical bars}``) from a seed.
UniverseGenerator = Callable[[int], Mapping[str, pd.DataFrame]]

#: Assemble a :class:`StrategyDataset` from a universe of bars (the feature/label pipeline).
DatasetBuilder = Callable[[Mapping[str, pd.DataFrame]], StrategyDataset]


# --------------------------------------------------------------------------------------------
# Equity-path helpers
# --------------------------------------------------------------------------------------------


def max_drawdown(returns: npt.NDArray[np.float64] | pd.Series) -> float:
    """Return the maximum peak-to-trough drawdown of the additive equity path of ``returns``.

    The equity path is the running **sum** of the per-observation strategy returns (additive
    P&L in return units); the drawdown at each point is ``running_max - equity``, and the result
    is the largest such gap (a non-negative magnitude). Drawdown is the canonical *order-dependent*
    risk statistic — re-ordering the same returns leaves the total unchanged but reshapes the
    path — which is exactly why the Monte Carlo shuffle measures it.

    Args:
        returns: Per-observation strategy returns (NaNs dropped). Fewer than one finite value
            yields ``0.0``.
    """
    clean = np.asarray(returns, dtype="float64").ravel()
    clean = clean[~np.isnan(clean)]
    if clean.size == 0:
        return 0.0
    equity = np.cumsum(clean)
    running_max = np.maximum.accumulate(equity)
    return float(np.max(running_max - equity))


# --------------------------------------------------------------------------------------------
# 1. Parameter sensitivity
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParameterSensitivityReport:
    """How the strategy's median path-Sharpe moves as parameters are perturbed (§4b.7).

    A robust edge is *insensitive*: the medians cluster near the baseline. A knife-edge swings
    (high coefficient of variation) or flips sign — overfit, and disqualified by kill-gate
    criterion 6.
    """

    baseline_key: str
    median_by_variant: Mapping[str, float]
    knife_edge_cv_threshold: float

    @property
    def baseline_median(self) -> float:
        """The unperturbed (baseline) median path-Sharpe."""
        return self.median_by_variant[self.baseline_key]

    @property
    def medians(self) -> npt.NDArray[np.float64]:
        """All variants' median path-Sharpes, as an array."""
        return np.asarray(list(self.median_by_variant.values()), dtype="float64")

    @property
    def spread(self) -> float:
        """Max minus min median across variants (the absolute swing)."""
        values = self.medians
        return float(values.max() - values.min())

    @property
    def coefficient_of_variation(self) -> float:
        """Std/|mean| of the variant medians (0 when the mean is ~0 to avoid a blow-up)."""
        values = self.medians
        mean = float(values.mean())
        if abs(mean) < 1e-12:
            return 0.0
        return float(values.std(ddof=0) / abs(mean))

    @property
    def flips_sign(self) -> bool:
        """Whether any perturbed variant flips the sign of a positive baseline edge."""
        return self.baseline_median > 0.0 and bool((self.medians < 0.0).any())

    @property
    def is_knife_edge(self) -> bool:
        """Whether the strategy looks overfit: the medians swing too much, or flip sign."""
        return self.flips_sign or self.coefficient_of_variation > self.knife_edge_cv_threshold


def parameter_sensitivity(
    variants: Mapping[str, EvaluateFn],
    dataset: StrategyDataset,
    *,
    baseline_key: str,
    knife_edge_cv_threshold: float,
) -> ParameterSensitivityReport:
    """Evaluate every parameter variant on ``dataset`` and report the sensitivity of the edge.

    Args:
        variants: Named evaluators, each a strategy with one parameter perturbed (the same data,
            a different recipe). Must include ``baseline_key`` and at least one perturbation.
        dataset: The point-in-time data every variant is evaluated on.
        baseline_key: The key in ``variants`` that is the unperturbed strategy.
        knife_edge_cv_threshold: Coefficient-of-variation above which the edge is flagged a
            knife-edge (config, not a literal — Ground Rule 2).

    Raises:
        RobustnessError: If ``variants`` has fewer than two entries or lacks ``baseline_key``.
    """
    if len(variants) < 2:
        raise RobustnessError("parameter sensitivity needs the baseline plus >= 1 perturbation")
    if baseline_key not in variants:
        raise RobustnessError(f"baseline_key {baseline_key!r} is not among the variants")
    median_by_variant = {name: evaluate(dataset).median for name, evaluate in variants.items()}
    report = ParameterSensitivityReport(
        baseline_key=baseline_key,
        median_by_variant=median_by_variant,
        knife_edge_cv_threshold=knife_edge_cv_threshold,
    )
    _logger.info(
        "parameter sensitivity",
        extra={
            "baseline_median": report.baseline_median,
            "spread": report.spread,
            "cv": report.coefficient_of_variation,
            "is_knife_edge": report.is_knife_edge,
        },
    )
    return report


# --------------------------------------------------------------------------------------------
# 2. Monte Carlo trade shuffle
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonteCarloShuffleReport:
    """The distribution of the equity path's max drawdown under random trade orderings (§4b.7).

    The total P&L is order-invariant, so the shuffle isolates the *sequencing*: if the observed
    ordering's drawdown sits far in the benign tail of the shuffled distribution, the smooth
    equity curve owed more to a lucky ordering than to a robust edge.
    """

    observed_max_drawdown: float
    shuffled_drawdowns: npt.NDArray[np.float64] = field(repr=False)
    n_shuffles: int

    @property
    def percentile_rank(self) -> float:
        """Fraction of shuffles whose drawdown is <= the observed (low => unusually benign)."""
        if self.shuffled_drawdowns.size == 0:
            return 0.0
        return float(np.mean(self.shuffled_drawdowns <= self.observed_max_drawdown))

    @property
    def shuffled_median(self) -> float:
        """Median max drawdown across the random orderings."""
        return float(np.median(self.shuffled_drawdowns)) if self.shuffled_drawdowns.size else 0.0

    @property
    def shuffled_p05(self) -> float:
        """5th-percentile (most benign) shuffled max drawdown."""
        if self.shuffled_drawdowns.size == 0:
            return 0.0
        return float(np.percentile(self.shuffled_drawdowns, 5))

    @property
    def shuffled_p95(self) -> float:
        """95th-percentile (worst) shuffled max drawdown."""
        if self.shuffled_drawdowns.size == 0:
            return 0.0
        return float(np.percentile(self.shuffled_drawdowns, 95))

    @property
    def order_robust(self) -> bool:
        """Whether the observed ordering is *not* an anomalously benign outlier (rank >= 0.05)."""
        return self.percentile_rank >= 0.05


def monte_carlo_shuffle(
    returns: npt.NDArray[np.float64] | pd.Series,
    *,
    n_shuffles: int,
    seed: int,
) -> MonteCarloShuffleReport:
    """Shuffle the order of ``returns`` ``n_shuffles`` times; report the max-drawdown distribution.

    Args:
        returns: The realised per-trade (per-observation) strategy returns to reorder.
        n_shuffles: Number of random orderings to draw (>= 1).
        seed: RNG seed (Ground Rule 7 — every shuffle is reproducible).

    Raises:
        RobustnessError: If ``n_shuffles < 1`` or there are fewer than two finite returns.
    """
    if n_shuffles < 1:
        raise RobustnessError(f"n_shuffles must be >= 1, got {n_shuffles}")
    clean = np.asarray(returns, dtype="float64").ravel()
    clean = clean[~np.isnan(clean)]
    if clean.size < 2:
        raise RobustnessError(f"need at least 2 finite returns to shuffle, got {clean.size}")
    rng = np.random.default_rng(seed)
    shuffled = np.empty(n_shuffles, dtype="float64")
    for i in range(n_shuffles):
        shuffled[i] = max_drawdown(rng.permutation(clean))
    report = MonteCarloShuffleReport(
        observed_max_drawdown=max_drawdown(clean),
        shuffled_drawdowns=shuffled,
        n_shuffles=n_shuffles,
    )
    _logger.info(
        "monte carlo shuffle",
        extra={
            "observed_max_drawdown": report.observed_max_drawdown,
            "shuffled_median": report.shuffled_median,
            "percentile_rank": report.percentile_rank,
        },
    )
    return report


# --------------------------------------------------------------------------------------------
# 3. Noise injection
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoiseInjectionReport:
    """How the median path-Sharpe decays as feature noise grows (§4b.7).

    A real edge degrades *gracefully* as noise is added; an overfit one collapses (or, worse,
    is unaffected because it was never using the features honestly). ``median_by_level`` maps
    each relative noise level to the median path-Sharpe averaged over the repeats at that level.
    """

    baseline_median: float
    median_by_level: Mapping[float, float]

    @property
    def levels(self) -> tuple[float, ...]:
        """The noise levels tested, ascending."""
        return tuple(sorted(self.median_by_level))

    @property
    def min_noise_median(self) -> float:
        """Median path-Sharpe at the smallest (gentlest) noise level."""
        return self.median_by_level[self.levels[0]]

    @property
    def edge_persists(self) -> bool:
        """Whether a positive baseline edge stays positive at the gentlest noise level."""
        return self.baseline_median <= 0.0 or self.min_noise_median > 0.0


def noise_injection(
    evaluate: EvaluateFn,
    dataset: StrategyDataset,
    *,
    noise_levels: Sequence[float],
    repeats: int,
    seed: int,
) -> NoiseInjectionReport:
    """Add Gaussian noise to the features at each level and report the edge's decay.

    At level ``L`` the noise added to feature column ``j`` is ``N(0, L * std_j)`` — scaled by
    that column's own standard deviation so every feature is perturbed comparably. Each level is
    evaluated ``repeats`` times (distinct seeds) and the medians are averaged, so a single noisy
    draw cannot swing the verdict.

    Args:
        evaluate: The strategy evaluator (returns a CPCV path distribution).
        dataset: The unperturbed point-in-time data.
        noise_levels: Relative noise magnitudes to test (each ``>= 0``; non-empty).
        repeats: Noisy evaluations averaged per level (>= 1).
        seed: Base RNG seed (each (level, repeat) derives a distinct stream).

    Raises:
        RobustnessError: If ``noise_levels`` is empty, any level is negative, or ``repeats < 1``.
    """
    if not noise_levels:
        raise RobustnessError("noise_injection needs at least one noise level")
    if any(level < 0.0 for level in noise_levels):
        raise RobustnessError("noise levels must be non-negative")
    if repeats < 1:
        raise RobustnessError(f"repeats must be >= 1, got {repeats}")

    baseline_median = evaluate(dataset).median
    column_std = dataset.features.std(ddof=0).to_numpy(dtype="float64")
    median_by_level: dict[float, float] = {}
    for level_index, level in enumerate(sorted(noise_levels)):
        repeat_medians = np.empty(repeats, dtype="float64")
        for repeat in range(repeats):
            rng = np.random.default_rng([seed, level_index, repeat])
            noisy = _add_feature_noise(dataset.features, column_std, level, rng)
            repeat_medians[repeat] = evaluate(dataset.with_features(noisy)).median
        median_by_level[float(level)] = float(repeat_medians.mean())

    report = NoiseInjectionReport(baseline_median=baseline_median, median_by_level=median_by_level)
    _logger.info(
        "noise injection",
        extra={
            "baseline_median": baseline_median,
            "median_by_level": dict(median_by_level),
            "edge_persists": report.edge_persists,
        },
    )
    return report


def _add_feature_noise(
    features: pd.DataFrame,
    column_std: npt.NDArray[np.float64],
    level: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Return ``features`` plus ``N(0, level * std_j)`` noise per column (a fresh frame)."""
    scale = column_std * level
    noise = rng.normal(0.0, 1.0, size=features.shape) * scale[np.newaxis, :]
    return pd.DataFrame(
        features.to_numpy(dtype="float64") + noise,
        index=features.index,
        columns=features.columns,
    )


# --------------------------------------------------------------------------------------------
# 4. Cross-symbol validation
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrossSymbolReport:
    """Held-out-symbol out-of-sample Sharpe per symbol (§4b.7 — does the signal generalise?).

    For each symbol the strategy is trained on *all the other* symbols and scored on the
    held-out one. A universal signal produces positive held-out Sharpes across most names; a
    symbol-specific (overfit) one collapses out of universe.
    """

    sharpe_by_symbol: Mapping[str, float]

    @property
    def symbols(self) -> tuple[str, ...]:
        """The held-out symbols, in evaluation order."""
        return tuple(self.sharpe_by_symbol)

    @property
    def sharpes(self) -> npt.NDArray[np.float64]:
        """The held-out Sharpes, as an array."""
        return np.asarray(list(self.sharpe_by_symbol.values()), dtype="float64")

    @property
    def median(self) -> float:
        """Median held-out Sharpe across symbols."""
        return float(np.median(self.sharpes)) if self.sharpes.size else 0.0

    @property
    def fraction_positive(self) -> float:
        """Fraction of held-out symbols with a positive Sharpe."""
        return float(np.mean(self.sharpes > 0.0)) if self.sharpes.size else 0.0

    @property
    def generalizes(self) -> bool:
        """Whether the edge generalises: a positive median across a majority of held-out names."""
        return self.median > 0.0 and self.fraction_positive >= 0.5


def cross_symbol_validation(
    datasets: Mapping[str, StrategyDataset],
    score: CrossSymbolScoreFn,
    *,
    periods_per_year: float | None = None,
) -> CrossSymbolReport:
    """Leave-one-symbol-out: train on the rest, score the held-out, report its Sharpe per symbol.

    Args:
        datasets: One :class:`StrategyDataset` per symbol (>= 2 symbols).
        score: Trains on the other symbols' datasets and returns the held-out symbol's
            per-event out-of-sample strategy-return series.
        periods_per_year: If given, annualise the held-out Sharpes.

    Raises:
        RobustnessError: If fewer than two symbols are supplied, or ``score`` returns an empty
            series for a held-out symbol.
    """
    if len(datasets) < 2:
        raise RobustnessError("cross-symbol validation needs at least two symbols")
    sharpe_by_symbol: dict[str, float] = {}
    for held_out, test_dataset in datasets.items():
        train_datasets = [ds for symbol, ds in datasets.items() if symbol != held_out]
        returns = score(train_datasets, test_dataset)
        if len(returns) == 0:
            raise RobustnessError(f"cross-symbol score returned no returns for {held_out!r}")
        sharpe_by_symbol[held_out] = sharpe_ratio(returns, periods_per_year)
    report = CrossSymbolReport(sharpe_by_symbol=sharpe_by_symbol)
    _logger.info(
        "cross-symbol validation",
        extra={
            "median": report.median,
            "fraction_positive": report.fraction_positive,
            "generalizes": report.generalizes,
        },
    )
    return report


# --------------------------------------------------------------------------------------------
# 5. Synthetic-data backtest
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyntheticDataReport:
    """Median path-Sharpe across synthetic, no-real-luck universes (§4b.7).

    On price paths simulated from a memory-less process the strategy *should* show **no** edge.
    A distribution of medians centred near zero is the healthy outcome; a strongly positive
    centre is evidence of a methodology leak (lookahead, an in-sample-fit combiner, etc.).
    """

    median_sharpes: npt.NDArray[np.float64] = field(repr=False)
    n_universes: int
    n_skipped: int
    edge_threshold: float

    @property
    def mean_median(self) -> float:
        """Mean of the per-universe median path-Sharpes (should be ~0 on no-signal data)."""
        return float(np.mean(self.median_sharpes)) if self.median_sharpes.size else 0.0

    @property
    def fraction_positive(self) -> float:
        """Fraction of synthetic universes with a positive median path-Sharpe."""
        return float(np.mean(self.median_sharpes > 0.0)) if self.median_sharpes.size else 0.0

    @property
    def edge_detected(self) -> bool:
        """Whether a spurious edge appears on no-signal data (mean median > the threshold)."""
        return self.mean_median > self.edge_threshold


def synthetic_data_backtest(
    generator: UniverseGenerator,
    builder: DatasetBuilder,
    evaluate: EvaluateFn,
    *,
    n_universes: int,
    seed: int,
    edge_threshold: float,
) -> SyntheticDataReport:
    """Run the strategy recipe on ``n_universes`` synthetic universes; report the edge distribution.

    Each universe is generated from a distinct seed, assembled into a :class:`StrategyDataset`
    by the same feature/label ``builder`` the real pipeline uses, and evaluated. A universe that
    produces no labellable events (e.g. a flat path with no CUSUM trigger) is skipped and counted.

    Args:
        generator: Builds one synthetic universe of bars from a seed.
        builder: Turns a universe of bars into a :class:`StrategyDataset` (the real pipeline).
        evaluate: The strategy evaluator.
        n_universes: Number of synthetic universes to simulate (>= 1).
        seed: Base seed; universe ``u`` is generated from ``seed + u``.
        edge_threshold: Mean-median above which a spurious edge is flagged (config, Rule 2).

    Raises:
        RobustnessError: If ``n_universes < 1`` or every universe was skipped (no events at all,
            so the test could not run).
    """
    if n_universes < 1:
        raise RobustnessError(f"n_universes must be >= 1, got {n_universes}")
    medians: list[float] = []
    skipped = 0
    for universe in range(n_universes):
        dataset = builder(generator(seed + universe))
        if len(dataset) == 0:
            skipped += 1
            continue
        medians.append(evaluate(dataset).median)
    if not medians:
        raise RobustnessError("every synthetic universe produced no events; cannot run the test")
    report = SyntheticDataReport(
        median_sharpes=np.asarray(medians, dtype="float64"),
        n_universes=n_universes,
        n_skipped=skipped,
        edge_threshold=edge_threshold,
    )
    _logger.info(
        "synthetic-data backtest",
        extra={
            "mean_median": report.mean_median,
            "fraction_positive": report.fraction_positive,
            "edge_detected": report.edge_detected,
            "n_skipped": skipped,
        },
    )
    return report


def geometric_brownian_bars(
    symbol: str,
    *,
    sessions: int,
    minutes_per_session: int,
    seed: int,
    mu: float = 0.0,
    sigma: float = 0.0015,
    start_price: float = 100.0,
    start_day: pd.Timestamp | None = None,
    tz: str = "Asia/Kolkata",
) -> pd.DataFrame:
    """Simulate canonical 1-minute bars from a geometric Brownian motion (no-real-luck data).

    Driftless by default (``mu = 0``), so the path carries **no** exploitable signal — the
    null case the synthetic-data backtest needs. Bars are laid out over ``sessions`` weekday
    sessions from 09:15 IST, with high/low jittered around the open/close so range estimators
    have something to consume. The result is in the canonical bars schema, ready for the same
    feature pipeline the real data flows through.

    Args:
        symbol: The instrument symbol stamped on every bar.
        sessions: Number of weekday sessions to generate (>= 1).
        minutes_per_session: Bars per session (>= 1).
        seed: RNG seed (reproducible — Ground Rule 7).
        mu: Per-minute log-drift (0 = no edge).
        sigma: Per-minute log-volatility (> 0).
        start_price: Opening price of the first bar (> 0).
        start_day: First session date (defaults to 2024-01-01); advanced over weekdays only.
        tz: Session timezone (IST).

    Raises:
        RobustnessError: If ``sessions`` or ``minutes_per_session`` is not positive, or
            ``sigma <= 0`` or ``start_price <= 0``.
    """
    if sessions < 1 or minutes_per_session < 1:
        raise RobustnessError("sessions and minutes_per_session must be positive")
    if sigma <= 0.0 or start_price <= 0.0:
        raise RobustnessError("sigma and start_price must be positive")

    rng = np.random.default_rng(seed)
    timestamps = _session_minute_index(sessions, minutes_per_session, start_day, tz)
    total = timestamps.shape[0]

    # GBM closes; each bar opens at the previous close (first opens at start_price). High/low
    # jitter around the open/close so range estimators have signal. All vectorised (no loop).
    closes = start_price * np.exp(np.cumsum(rng.normal(mu, sigma, size=total)))
    opens = np.concatenate(([start_price], closes[:-1]))
    body_high = np.maximum(opens, closes)
    body_low = np.minimum(opens, closes)
    highs = body_high * (1.0 + np.abs(rng.normal(0.0, sigma / 3.0, size=total)))
    lows = body_low * (1.0 - np.abs(rng.normal(0.0, sigma / 3.0, size=total)))
    volumes = rng.integers(100, 1000, size=total)

    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _session_minute_index(
    sessions: int, minutes_per_session: int, start_day: pd.Timestamp | None, tz: str
) -> pd.DatetimeIndex:
    """Build the 1-minute timestamp index over ``sessions`` weekday sessions from 09:15 IST."""
    day = pd.Timestamp("2024-01-01") if start_day is None else pd.Timestamp(start_day)
    offsets = pd.to_timedelta(np.arange(minutes_per_session), unit="m")
    blocks: list[pd.DatetimeIndex] = []
    placed = 0
    while placed < sessions:
        if day.weekday() < 5:  # weekday session only
            session_start = pd.Timestamp(day.year, day.month, day.day, 9, 15, tz=tz)
            blocks.append(pd.DatetimeIndex(session_start + offsets))
            placed += 1
        day = day + pd.Timedelta(days=1)
    combined = blocks[0] if len(blocks) == 1 else blocks[0].append(blocks[1:])
    return pd.DatetimeIndex(combined)
