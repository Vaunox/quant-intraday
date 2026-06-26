"""Assemble the real backfilled bars into the pooled training matrix (P2A.6).

This is the orchestration that was explicitly deferred from P2.7 (*"materializing the
P1.6/P1.7 features + ... into the training matrix is pipeline orchestration"*) and is the
heart of the final registry-promotable run: it turns the immutable Parquet bars (P2A.3) into
the ``(features, labels, label_times, forward_returns, regime_features, weights)`` a single
cross-sectional :class:`~quant.research.models.ensemble.EnsembleTrainer` consumes.

Per symbol (:func:`build_symbol_dataset`):

1. **Resample** the minute archive to the 15-minute decision clock (:func:`resample_bars`,
   session-safe — overnight buckets are dropped, not merged).
2. **Features** — the P1.6 causal core vector (:func:`~quant.data.features.harness`'s
   ``compute_feature_frame``) plus the P1.7 regime descriptors that drive the gate.
3. **Events + labels** — CUSUM event sampling (P2.3) then triple-barrier labels
   (vol-scaled, vertical = session end). The binary target is *"did the long side win"*
   (``label > 0``); the realized barrier return is the per-event forward return.
4. **Weights** — average-uniqueness x time-decay (P2.4), the non-IID correction.

The eight symbols are then pooled into **one** cross-sectional dataset (:func:`pool_datasets`)
by concatenating each symbol's events onto a single synthetic timeline, separated by a gap
**strictly larger than the maximum label horizon** (one session). This is what lets the one
model train on the whole universe while satisfying the unique-sorted-timeline contract of
:class:`~quant.research.validation.splits.PurgedKFold`: intra-symbol time deltas are preserved
exactly (so the purge/embargo stay correct) and a label window can never span two symbols
(proven by :attr:`PooledDataset.segments` and asserted in the tests, per the operator
constraint). The pool gap is config, not a literal (Ground Rule 2): ``pipeline.pool_gap_days``.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from quant.core.config import Config, LabelingConfig
from quant.core.interfaces import Repository
from quant.core.logging import get_logger
from quant.data.features.harness import compute_feature_frame
from quant.data.features.regime import trend_strength, volatility_regime
from quant.data.features.volatility import realized_volatility
from quant.data.store import serde
from quant.research.labeling.cusum import cusum_events
from quant.research.labeling.triple_barrier import LABEL, RETURN, TripleBarrierLabeler
from quant.research.labeling.weights import SampleWeights, time_decay_weights
from quant.research.pipeline.errors import PipelineError

_logger = get_logger(__name__)

#: The regime-gate feature columns (kept stable for the registry/feature alignment).
REGIME_FEATURES = ("vol_regime", "trend_strength")


@dataclass(frozen=True, slots=True)
class SymbolDataset:
    """One symbol's labeled, point-in-time training rows (all aligned to the event time ``t0``)."""

    symbol: str
    features: pd.DataFrame  # P1.6 core features at each event
    labels: pd.Series  # binary {0, 1}: did the long side win (triple-barrier label > 0)
    label_times: pd.Series  # t0 -> t1 (drives the purge/embargo)
    forward_returns: pd.Series  # realized barrier return of a unit long position
    regime_features: pd.DataFrame  # P1.7 regime descriptors at each event (gate inputs)
    weights: pd.Series  # average-uniqueness x time-decay sample weights (P2.4)

    def __len__(self) -> int:
        """Number of labeled events for this symbol."""
        return len(self.features)


@dataclass(frozen=True, slots=True)
class PoolSegment:
    """Where one symbol's rows land on the pooled synthetic timeline (audit + overlap proof)."""

    symbol: str
    offset: pd.Timedelta  # synthetic_time = real_time + offset (preserves intra-symbol deltas)
    synthetic_start: pd.Timestamp  # earliest synthetic event time t0
    synthetic_end: pd.Timestamp  # latest synthetic resolution time t1
    n_obs: int


@dataclass(frozen=True, slots=True)
class PooledDataset:
    """The pooled cross-sectional training matrix on one synthetic, gap-separated timeline."""

    features: pd.DataFrame
    labels: pd.Series
    label_times: pd.Series
    forward_returns: pd.Series
    regime_features: pd.DataFrame
    weights: pd.Series
    segments: tuple[PoolSegment, ...]

    @property
    def n_obs(self) -> int:
        """Total pooled observations across all symbols."""
        return len(self.features)

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols contributing to the pool, in synthetic-timeline order."""
        return tuple(segment.symbol for segment in self.segments)

    @property
    def feature_names(self) -> tuple[str, ...]:
        """The model feature columns (ordered)."""
        return tuple(str(column) for column in self.features.columns)


def resample_bars(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample canonical bars to ``minutes``-minute bars, session-safe.

    OHLCV aggregation (open=first, high=max, low=min, close=last, volume=sum) over left-closed,
    left-labelled buckets, so a 15-minute bar is timestamped at its start (matching the minute
    archive's start-of-bar convention). Empty buckets — the overnight gap — are dropped rather
    than carried, so no bar ever straddles two sessions.

    Args:
        bars: A single symbol's canonical-schema bars (e.g. the minute archive).
        minutes: Target bar width in minutes (the decision frequency; > 0).

    Returns:
        Canonical-schema bars at the coarser interval (empty in, empty out).

    Raises:
        PipelineError: If ``minutes`` is not positive.
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    if minutes <= 0:
        raise PipelineError(f"resample interval must be positive minutes, got {minutes}")
    frame = serde.sort_bars(serde.ensure_bars_schema(bars))
    if frame.empty:
        return serde.empty_bars_frame()
    symbol = str(frame["symbol"].iloc[0])
    indexed = frame.set_index(serde.TIME_COLUMN)
    aggregated = indexed.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    aggregated = aggregated.dropna(subset=["open", "high", "low", "close"])
    aggregated.insert(0, "symbol", symbol)
    aggregated["volume"] = aggregated["volume"].astype("int64")
    return serde.ensure_bars_schema(aggregated.reset_index())


def build_symbol_dataset(symbol: str, bars: pd.DataFrame, config: Config) -> SymbolDataset:
    """Resample, feature, label, and weight one symbol's bars into training rows.

    Args:
        symbol: The instrument symbol (carried into the dataset for pooling/audit).
        bars: That symbol's canonical-schema bars (the minute archive over the run window).
        config: System config (decision frequency, feature windows, labeling barriers).

    Returns:
        A :class:`SymbolDataset` aligned to the labeled event times (empty if no event can be
        labeled — e.g. too little history to clear the feature/volatility warm-up).
    """
    resampled = resample_bars(bars, config.market.decision_frequency_minutes)
    times = pd.DatetimeIndex(resampled[serde.TIME_COLUMN], name=serde.TIME_COLUMN)
    features, regime = _feature_frames(bars, resampled, times, config)

    close = pd.Series(resampled["close"].to_numpy(dtype="float64"), index=times, name="close")
    if len(close) == 0:
        return _empty_symbol_dataset(symbol, features, regime)
    events = cusum_events(close, config.labeling.cusum_threshold)
    sigma = pd.Series(
        realized_volatility(resampled, config.features.volatility_window).to_numpy(dtype="float64"),
        index=times,
    )
    labels = TripleBarrierLabeler(config.labeling).label(resampled, events, sigma)
    if len(labels) == 0:
        return _empty_symbol_dataset(symbol, features, regime)

    event_times = labels.frame.index
    binary = (labels.frame[LABEL] > 0).astype("int64").rename("label")
    forward = labels.frame[RETURN].astype("float64").rename("forward_return")
    label_times = labels.label_times
    feature_rows = features.reindex(event_times)
    regime_rows = regime.reindex(event_times)

    # Drop warm-up events whose feature/regime vector is not yet fully defined (point-in-time:
    # an undefined trailing window is genuinely unknown, never back-filled).
    valid = feature_rows.notna().all(axis=1) & regime_rows.notna().all(axis=1)
    valid_events = event_times[valid.to_numpy()]
    if len(valid_events) == 0:
        return _empty_symbol_dataset(symbol, features, regime)

    weights = _sample_weights(times, label_times.loc[valid_events])
    _logger.info(
        "symbol dataset built",
        extra={
            "symbol": symbol,
            "resampled_bars": len(resampled),
            "events": len(events),
            "labeled": len(labels),
            "valid_rows": len(valid_events),
            "positive_rate": float(binary.loc[valid_events].mean()),
        },
    )
    return SymbolDataset(
        symbol=symbol,
        features=feature_rows.loc[valid_events],
        labels=binary.loc[valid_events],
        label_times=label_times.loc[valid_events],
        forward_returns=forward.loc[valid_events],
        regime_features=regime_rows.loc[valid_events],
        weights=weights,
    )


def pool_datasets(datasets: Sequence[SymbolDataset], *, gap: pd.Timedelta) -> PooledDataset:
    """Pool per-symbol datasets onto one synthetic, gap-separated timeline.

    Symbols are placed in deterministic (sorted-name) order; each is shifted by a constant
    timedelta so its first event begins one ``gap`` after the previous symbol's last label
    resolves. The shift is a single constant per symbol, so every intra-symbol time delta — and
    therefore the purge/embargo geometry — is preserved exactly, while the gap (strictly larger
    than the max label horizon) guarantees no label window crosses a symbol boundary.

    Args:
        datasets: The per-symbol datasets to pool (non-empty; empties should be filtered first).
        gap: The inter-symbol gap (``> 0``; from ``pipeline.pool_gap_days``).

    Returns:
        A :class:`PooledDataset` with a sorted, unique synthetic timeline.

    Raises:
        PipelineError: If ``datasets`` is empty or ``gap`` is not positive.
    """
    if not datasets:
        raise PipelineError("no symbol datasets to pool")
    if gap <= pd.Timedelta(0):
        raise PipelineError(f"pool gap must be positive, got {gap}")

    ordered = sorted(datasets, key=lambda dataset: dataset.symbol)
    feature_parts: list[pd.DataFrame] = []
    regime_parts: list[pd.DataFrame] = []
    label_parts: list[pd.Series] = []
    label_time_parts: list[pd.Series] = []
    forward_parts: list[pd.Series] = []
    weight_parts: list[pd.Series] = []
    segments: list[PoolSegment] = []
    cursor: pd.Timestamp | None = None

    for dataset in ordered:
        real_t0 = dataset.features.index
        offset = pd.Timedelta(0) if cursor is None else (cursor + gap) - real_t0.min()
        synthetic_t0 = pd.DatetimeIndex(real_t0 + offset, name="event_time")
        shifted_label_times = (dataset.label_times + offset).set_axis(synthetic_t0)

        feature_parts.append(dataset.features.set_axis(synthetic_t0))
        regime_parts.append(dataset.regime_features.set_axis(synthetic_t0))
        label_parts.append(dataset.labels.set_axis(synthetic_t0))
        label_time_parts.append(shifted_label_times)
        forward_parts.append(dataset.forward_returns.set_axis(synthetic_t0))
        weight_parts.append(dataset.weights.set_axis(synthetic_t0))

        synthetic_end = pd.Timestamp(shifted_label_times.max())
        segments.append(
            PoolSegment(
                symbol=dataset.symbol,
                offset=offset,
                synthetic_start=pd.Timestamp(synthetic_t0.min()),
                synthetic_end=synthetic_end,
                n_obs=len(dataset),
            )
        )
        cursor = synthetic_end

    pooled = PooledDataset(
        features=pd.concat(feature_parts),
        labels=pd.concat(label_parts),
        label_times=pd.concat(label_time_parts),
        forward_returns=pd.concat(forward_parts),
        regime_features=pd.concat(regime_parts),
        weights=pd.concat(weight_parts),
        segments=tuple(segments),
    )
    _logger.info(
        "pooled dataset built",
        extra={"symbols": list(pooled.symbols), "n_obs": pooled.n_obs, "gap_days": gap.days},
    )
    return pooled


def build_pooled_dataset(
    config: Config, repository: Repository, symbols: Sequence[str], start: datetime, end: datetime
) -> PooledDataset:
    """Read each symbol from the store and assemble the pooled cross-sectional training matrix.

    Args:
        config: System config.
        repository: The store to read bars from (Parquet archive, by default).
        symbols: The universe symbols to pool.
        start: Inclusive window start (tz-aware IST).
        end: Inclusive window end (tz-aware IST).

    Returns:
        The :class:`PooledDataset` ready for the
        :class:`~quant.research.models.ensemble.EnsembleTrainer`.

    Raises:
        PipelineError: If no symbol produced any labeled events.
    """
    datasets: list[SymbolDataset] = []
    for symbol in symbols:
        bars = repository.read_bars(symbol, start, end)
        if bars.empty:
            _logger.warning("no bars for symbol; skipping", extra={"symbol": symbol})
            continue
        dataset = build_symbol_dataset(symbol, bars, config)
        if len(dataset) == 0:
            _logger.warning("symbol produced no labeled events; skipping", extra={"symbol": symbol})
            continue
        datasets.append(dataset)
    if not datasets:
        raise PipelineError("no symbol produced any labeled events; cannot build a dataset")
    gap = pd.Timedelta(days=config.pipeline.pool_gap_days)
    return pool_datasets(datasets, gap=gap)


def data_version(symbols: Sequence[str], start: datetime, end: datetime, interval: str) -> str:
    """Return a deterministic data-version tag for the dataset (§4 reproducibility contract).

    Human-readable (interval, symbol count, date span) plus a short hash of the exact symbol
    set, so two runs over the same data get the same tag and a different universe gets a
    different one.
    """
    digest = hashlib.sha1("-".join(sorted(symbols)).encode("utf-8")).hexdigest()[:8]
    return f"{interval}-{len(symbols)}sym-{start:%Y%m%d}-{end:%Y%m%d}-{digest}"


def label_version(labeling: LabelingConfig) -> str:
    """Return a deterministic label-version tag from the triple-barrier parameters."""
    return (
        f"tb-cusum{labeling.cusum_threshold}-u{labeling.barrier_upper_multiple}"
        f"-d{labeling.barrier_lower_multiple}-min{labeling.barrier_min_return}"
        f"-vmax{labeling.vertical_max_hold_bars}"
    )


def _feature_frames(
    bars: pd.DataFrame, resampled: pd.DataFrame, times: pd.DatetimeIndex, config: Config
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute the (model features, regime features), optionally on a finer grid (cycle 3a).

    Default (``features.feature_frequency_minutes`` is ``None`` or equals the decision frequency):
    compute on the 15-min decision bars — the legacy P1.6/P2A.6 path, unchanged. When a finer
    frequency is configured, the same feature families are computed on the finer grid (e.g. 5-min)
    and **point-in-time aligned** to the decision rows: each decision bar takes the finer bar that
    closes at the *same instant* it does, so the data horizon is identical (no lookahead, Inviolable
    Rule 2) while the features see sub-15-min structure (Part II "features from finer data").

    Raises:
        PipelineError: If the finer frequency does not evenly divide the decision frequency.
    """
    decision = config.market.decision_frequency_minutes
    fine = config.features.feature_frequency_minutes
    if fine is None or fine == decision:
        return (
            compute_feature_frame(resampled, config.features),
            _regime_frame(resampled, times, config),
        )
    if fine > decision or decision % fine != 0:
        raise PipelineError(
            f"feature_frequency_minutes ({fine}) must be <= and evenly divide the decision "
            f"frequency ({decision})"
        )
    fine_bars = resample_bars(bars, fine)
    fine_times = pd.DatetimeIndex(fine_bars[serde.TIME_COLUMN], name=serde.TIME_COLUMN)
    features = _align_fine_to_decision(
        compute_feature_frame(fine_bars, config.features), times, decision, fine
    )
    regime = _align_fine_to_decision(
        _regime_frame(fine_bars, fine_times, config), times, decision, fine
    )
    return features, regime


def _align_fine_to_decision(
    fine_frame: pd.DataFrame, decision_times: pd.DatetimeIndex, decision: int, fine: int
) -> pd.DataFrame:
    """Align finer-grid features to the decision rows by matching bar-close instants.

    A decision bar ``[t, t+decision)`` closes at ``t + decision``; the finer bar that closes at the
    same instant starts at ``t + (decision - fine)``. Reindexing the finer frame at those starts
    and relabelling to ``decision_times`` gives each decision row the finer features with the
    identical point-in-time horizon. A missing finer bar (a data gap) yields a NaN row, which the
    caller drops as warm-up — never fabricated.
    """
    offset = pd.Timedelta(minutes=decision - fine)
    aligned = fine_frame.reindex(decision_times + offset)
    aligned.index = decision_times
    return aligned


def _regime_frame(resampled: pd.DataFrame, times: pd.DatetimeIndex, config: Config) -> pd.DataFrame:
    """Build the regime-gate feature frame (vol regime + trend strength) indexed by bar time."""
    features = config.features
    return pd.DataFrame(
        {
            "vol_regime": volatility_regime(
                resampled,
                vol_window=features.regime_vol_window,
                lookback=features.regime_vol_lookback,
            ).to_numpy(dtype="float64"),
            "trend_strength": trend_strength(resampled, window=features.trend_window).to_numpy(
                dtype="float64"
            ),
        },
        index=times,
    )


def _sample_weights(bar_times: pd.DatetimeIndex, label_times: pd.Series) -> pd.Series:
    """Average-uniqueness x time-decay weights for the labeled events (P2.4, AFML ch. 4)."""
    weighting = SampleWeights(bar_times, label_times)
    uniqueness = weighting.average_uniqueness()
    decay = time_decay_weights(uniqueness)
    return (uniqueness * decay).rename("weight")


def _empty_symbol_dataset(
    symbol: str, features: pd.DataFrame, regime: pd.DataFrame
) -> SymbolDataset:
    """A typed empty dataset (no labelable event), preserving the feature/regime column schema."""
    empty_index = pd.DatetimeIndex([], name="event_time")
    return SymbolDataset(
        symbol=symbol,
        features=features.iloc[0:0].set_axis(empty_index),
        labels=pd.Series(dtype="int64", index=empty_index, name="label"),
        label_times=pd.Series(
            dtype=features.index.dtype if len(features) else "datetime64[ns, Asia/Kolkata]",
            index=empty_index,
            name="t1",
        ),
        forward_returns=pd.Series(dtype="float64", index=empty_index, name="forward_return"),
        regime_features=regime.iloc[0:0].set_axis(empty_index),
        weights=pd.Series(dtype="float64", index=empty_index, name="weight"),
    )
