"""The classic breakout **Turtle** trend-following signal (Phase 3T · spec §1).

The strategy under test across all three Phase-3T rungs. This module is the *pure,
causal* decision layer: from hygiene-clean, corporate-action-**adjusted** bars it emits a
signed **position path** (the target the backtester executes at next-bar open, Inviolable
Rule 2) and the per-trade ``label_times`` (t0 = entry decision, t1 = exit/stop decision)
that feed the purged splitters (CPCV). It owns *no* execution fidelity — next-bar-open
fills, the cost model, and MIS-square-off vs CNC multi-day-hold live in the backtester
(P2.1 / P3T.3). Keeping the split here is what lets the *same* signal run unchanged across
intraday MIS, daily CNC, and monthly ETF regimes.

**Canonical contract (spec §1 — frozen authoritatively in ``config/turtle_default.yaml``
at P3T.6; the defaults here mirror it):**

* **Entry** — System 1 breaks the **20**-bar Donchian extreme; System 2 the **55**-bar.
* **Exit** — the opposite **10**-bar (S1) / **20**-bar (S2) extreme — a trend-reversal
  exit, never a profit target.
* **Volatility unit N** — the **20-period Wilder-smoothed ATR**, ``N=(19·N_prev+TR)/20``.
  The SMA-ATR in :func:`quant.data.features.volatility.atr` is the *variant* the spec
  names (§1); the canonical N is Wilder, implemented here as :func:`wilder_atr`.
* **Initial stop** — **2N** from entry.
* **Sizing** — ``1 unit = (0.01·equity)/N`` shares, but at ₹40k-₹1L with no leverage the
  book **binds on cash, not volatility** — :func:`unit_size` takes ``min(vol_unit,
  cash_affordable)`` and rounds *down* to whole shares (spec §1 "small-capital sizing
  reality"; §8.6). It records when the cash constraint bound.
* **Pyramiding** — OFF for the baseline; ON adds a unit every **+0.5N** favorable to a max
  of **4**, trailing every stop to 2N from the newest entry. A counted escalation (§6),
  and it degrades gracefully when cash is exhausted.
* **S1 last-breakout loser-filter** — skip an S1 entry if the *previous* S1 breakout would
  have been a **winner** (the original anti-whipsaw rule). S2 takes every breakout.

**Point-in-time correctness (Inviolable Rule 2; Deep Dive #1 §2.1).** The Donchian level
at bar *t* is the extreme of the *prior* ``window`` bars (``rolling(window).max().shift(1)``)
— it *excludes* bar *t*, so a breakout is ``high_t ≥ level_t`` decided at *t*'s close and
filled at *t+1*'s open. N is a trailing Wilder recursion. Every primitive is forward-shift
invariant (the P1.8 leakage suite) and identical on the vectorized and incremental paths
(the P1.7 dual-path guarantee). The loser-filter consults only *already-resolved* prior
breakouts, so it never peeks forward.

Reference: spec §1 (canonical params) & §8 (honesty notes); Faith, *Way of the Turtle*
(2007), ch. 5 (the S1/S2 rules, the 2N stop, unit sizing, the loser filter); Deep Dive #1
§2.1-2.2 (causal features); P1.7 harness; P1.8 leakage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.data.store import serde
from quant.research.signals.errors import SignalInputError

# --- trade-frame schema (kept stable for downstream consumers) ---------------------------
#: Index name and columns of the per-trade frame produced by :func:`generate_trades`.
ENTRY_TIME = "entry_time"
EXIT_TIME = "exit_time"
DIRECTION = "direction"
UNITS = "units"
SHARES = "shares"
ENTRY_PRICE = "entry_price"
EXIT_PRICE = "exit_price"
EXIT_REASON = "exit_reason"
RET = "ret"
CASH_BOUND = "cash_bound"
_TRADE_COLUMNS = (
    EXIT_TIME,
    DIRECTION,
    UNITS,
    SHARES,
    ENTRY_PRICE,
    EXIT_PRICE,
    EXIT_REASON,
    RET,
    CASH_BOUND,
)

#: Exit-reason tags recorded per trade.
STOP = "stop"  # the 2N (trailed) protective stop was hit
DONCHIAN_EXIT = "donchian_exit"  # the opposite N_exit-bar extreme was hit (trend reversal)
END = "end"  # the sample ended with the position still open (marked out at last close)


@dataclass(frozen=True, slots=True)
class TurtleConfig:
    """The frozen canonical Turtle contract (spec §1).

    The authoritative values are frozen in ``config/turtle_default.yaml`` at P3T.6; these
    defaults mirror the canonical System-1, pyramiding-OFF baseline so the module is usable
    (and testable) before that config exists. Any deviation from the canonical values is a
    **counted trial** (§6), never a silent per-regime tune.
    """

    entry_window: int = 20  # S1 Donchian entry (55 for S2)
    exit_window: int = 10  # opposite-extreme exit (20 for S2)
    atr_window: int = 20  # Wilder-N lookback
    stop_multiple: float = 2.0  # initial hard stop = 2N from entry
    risk_fraction: float = 0.01  # 1 unit risks 1% of equity at a 1N move
    pyramiding: bool = False  # OFF for baseline; ON is a counted escalation
    pyramid_step_fraction: float = 0.5  # add a unit every +0.5N favorable
    max_units: int = 4  # cap on pyramided units
    use_loser_filter: bool = True  # S1 anti-whipsaw filter (S2 sets False)
    allow_short: bool = True  # long+short where the product allows; long-only sets False

    def __post_init__(self) -> None:
        """Validate the contract (fail loud, Ground Rule 7)."""
        if self.entry_window < 1:
            raise SignalInputError(f"entry_window must be >= 1, got {self.entry_window!r}")
        if self.exit_window < 1:
            raise SignalInputError(f"exit_window must be >= 1, got {self.exit_window!r}")
        if self.atr_window <= 1:
            raise SignalInputError(f"atr_window must be > 1, got {self.atr_window!r}")
        if self.stop_multiple <= 0:
            raise SignalInputError(f"stop_multiple must be > 0, got {self.stop_multiple!r}")
        if self.risk_fraction <= 0:
            raise SignalInputError(f"risk_fraction must be > 0, got {self.risk_fraction!r}")
        if self.pyramid_step_fraction <= 0:
            raise SignalInputError(
                f"pyramid_step_fraction must be > 0, got {self.pyramid_step_fraction!r}"
            )
        if self.max_units < 1:
            raise SignalInputError(f"max_units must be >= 1, got {self.max_units!r}")

    @classmethod
    def system1(cls) -> TurtleConfig:
        """The canonical System 1 (20/10, loser-filter ON) — the baseline on every rung.

        Variants (a different risk fraction, pyramiding ON, …) are counted trials (§6);
        build them with :func:`dataclasses.replace` on this base so the deviation is explicit.
        """
        return cls(entry_window=20, exit_window=10, use_loser_filter=True)

    @classmethod
    def system2(cls) -> TurtleConfig:
        """The canonical System 2 (55/20, takes every breakout) — a counted escalation (§6)."""
        return cls(entry_window=55, exit_window=20, use_loser_filter=False)


# =========================================================================================
# Pure causal primitives (forward-shift invariant; skew-free on the dual-path harness)
# =========================================================================================


def donchian_high(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the **prior**-``window``-bar Donchian high (the long-breakout level).

    ``rolling(window).max().shift(1)`` — the highest high of the ``window`` bars *strictly
    before* the current bar, so it is known at the current bar's open and a breakout
    (``high_t ≥ level_t``) is decided causally at *t* and filled at *t+1*. The first
    ``window`` rows are ``NaN`` (insufficient history).
    """
    if window < 1:
        raise SignalInputError(f"window must be >= 1, got {window!r}")
    return bars["high"].rolling(window).max().shift(1).rename(f"donchian_high_{window}")


def donchian_low(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the **prior**-``window``-bar Donchian low (the short-breakout / long-exit level).

    The causal mirror of :func:`donchian_high` — ``rolling(window).min().shift(1)``.
    """
    if window < 1:
        raise SignalInputError(f"window must be >= 1, got {window!r}")
    return bars["low"].rolling(window).min().shift(1).rename(f"donchian_low_{window}")


def wilder_atr(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the canonical Turtle **N**: the ``window``-period Wilder-smoothed ATR.

    True range ``TR = max(high-low, |high-prev_close|, |low-prev_close|)``; N is seeded with
    the simple mean of the first ``window`` true ranges and then smoothed by Wilder's
    recursion ``N_t = ((window-1)·N_{t-1} + TR_t)/window`` (spec §1). This is a trailing
    recursion — the value at row *t* uses only bars at or before *t* — so it is point-in-time
    correct and forward-shift invariant. The first ``window`` rows are ``NaN`` (warm-up).

    Distinct from :func:`quant.data.features.volatility.atr`, which is the **SMA**-smoothed
    ATR the spec names as a non-canonical variant.
    """
    if window <= 1:
        raise SignalInputError(f"window must be > 1, got {window!r}")
    high = bars["high"].to_numpy(dtype="float64")
    low = bars["low"].to_numpy(dtype="float64")
    close = bars["close"].to_numpy(dtype="float64")
    n = len(high)

    true_range = np.full(n, np.nan, dtype="float64")
    for k in range(1, n):  # TR[0] undefined (no previous close) — Wilder starts at TR[1]
        prev_close = close[k - 1]
        true_range[k] = max(
            high[k] - low[k],
            abs(high[k] - prev_close),
            abs(low[k] - prev_close),
        )

    atr = np.full(n, np.nan, dtype="float64")
    if n > window:
        # Seed at index ``window`` with the SMA of TR[1..window] (window true ranges), then
        # apply Wilder smoothing. Seeding this way keeps a prefix of the series identical to
        # the full computation (the forward-shift-invariance guarantee).
        atr[window] = float(np.mean(true_range[1 : window + 1]))
        for k in range(window + 1, n):
            atr[k] = (atr[k - 1] * (window - 1) + true_range[k]) / window

    return pd.Series(atr, index=bars.index, name=f"wilder_atr_{window}")


@dataclass(frozen=True, slots=True)
class UnitSize:
    """The result of the Turtle volatility-unit sizer at a single entry.

    ``shares`` is the whole-share size actually taken; ``cash_bound`` records that the
    cash-affordable size was smaller than the volatility unit wanted — the "binds on cash,
    not on volatility" reality at retail scale (spec §1, §8.6). ``vol_unit_shares`` and
    ``affordable_shares`` are the two (fractional) candidates, kept for diagnostics.
    """

    shares: int
    cash_bound: bool
    vol_unit_shares: float
    affordable_shares: float


def unit_size(
    *,
    equity: float,
    atr_n: float,
    price: float,
    cash_available: float,
    risk_fraction: float = 0.01,
) -> UnitSize:
    """Return the Turtle volatility unit, capped by cash and rounded down to whole shares.

    ``vol_unit = (risk_fraction·equity)/N`` is the size at which a 1N adverse move costs
    ``risk_fraction`` of equity (a 2N stop ⇒ ~2%). With no leverage the position cannot
    exceed ``cash_available/price`` shares, so the taken size is
    ``floor(min(vol_unit, affordable))`` (spec §1). ``cash_bound`` is set when the cash cap
    is the binding one — itself a finding about whether the strategy is even expressible at
    ₹40k.

    Args:
        equity: Account equity (INR, > 0) — the base the 1% risk is measured against.
        atr_n: The volatility unit N (Wilder ATR) in **price** units (> 0).
        price: The entry price per share (INR, > 0).
        cash_available: Cash free for this unit (INR, >= 0); the no-leverage cap.
        risk_fraction: Fraction of equity risked at a 1N move (canonical 0.01).

    Raises:
        SignalInputError: If ``equity``/``atr_n``/``price`` <= 0, ``cash_available`` < 0, or
            ``risk_fraction`` <= 0 (fail loud, Ground Rule 7).
    """
    if equity <= 0:
        raise SignalInputError(f"equity must be > 0, got {equity!r}")
    if atr_n <= 0:
        raise SignalInputError(f"atr_n must be > 0, got {atr_n!r}")
    if price <= 0:
        raise SignalInputError(f"price must be > 0, got {price!r}")
    if cash_available < 0:
        raise SignalInputError(f"cash_available must be >= 0, got {cash_available!r}")
    if risk_fraction <= 0:
        raise SignalInputError(f"risk_fraction must be > 0, got {risk_fraction!r}")

    vol_unit_shares = (risk_fraction * equity) / atr_n
    affordable_shares = cash_available / price
    raw = min(vol_unit_shares, affordable_shares)
    shares = math.floor(raw) if raw > 0 else 0
    cash_bound = affordable_shares < vol_unit_shares
    return UnitSize(
        shares=shares,
        cash_bound=cash_bound,
        vol_unit_shares=vol_unit_shares,
        affordable_shares=affordable_shares,
    )


def initial_stop(
    *, entry_price: float, atr_n: float, direction: int, stop_multiple: float = 2.0
) -> float:
    """Return the initial hard stop price: ``stop_multiple``·N adverse to a fresh entry.

    Long (``direction=+1``): ``entry - 2N``; short (``direction=-1``): ``entry + 2N``.
    """
    if direction not in (1, -1):
        raise SignalInputError(f"direction must be +1 or -1, got {direction!r}")
    if atr_n <= 0:
        raise SignalInputError(f"atr_n must be > 0, got {atr_n!r}")
    if stop_multiple <= 0:
        raise SignalInputError(f"stop_multiple must be > 0, got {stop_multiple!r}")
    return entry_price - direction * stop_multiple * atr_n


# =========================================================================================
# Trade generation (the causal event state-machine)
# =========================================================================================


@dataclass(frozen=True, slots=True)
class TurtleTrades:
    """The Turtle signal's output for one instrument: the trade log and the position path.

    ``trades`` is one row per *taken* trade, indexed by entry time. ``positions`` is the
    signed **share** target per bar (positive long, negative short, 0 flat) that the
    backtester executes at next-bar open. ``label_times`` maps each entry to its exit for
    the purged splitters.
    """

    trades: pd.DataFrame
    positions: pd.Series

    @property
    def label_times(self) -> pd.Series:
        """The ``t0 -> t1`` Series (entry time -> exit time) for purged CV / CPCV."""
        return self.trades[EXIT_TIME].rename("t1")

    def __len__(self) -> int:
        """Number of taken trades."""
        return len(self.trades)


@dataclass(frozen=True, slots=True)
class _Book:
    """The resolution of one breakout: where/why it exited, its size, and its outcome."""

    exit_index: int
    exit_price: float
    reason: str
    total_shares: int
    units: int
    avg_entry: float
    cash_bound: bool
    #: ``(bar_index, cumulative_shares)`` steps — how the (pyramided) size grew over time.
    steps: list[tuple[int, int]] = field(default_factory=list)

    @property
    def winner(self) -> bool:
        """Whether the trade closed in profit (the loser-filter's winner/loser signal)."""
        return (self.exit_price - self.avg_entry) * self._sign > 0

    _sign: int = 1


def generate_trades(
    bars: pd.DataFrame,
    config: TurtleConfig,
    *,
    equity: float,
    cash: float,
) -> TurtleTrades:
    """Run the Turtle signal over one instrument's bars and return its trades + position path.

    A single left-to-right pass over the bars (so it is naturally causal and identical on
    the vectorized and incremental paths): detect a Donchian breakout at each flat bar,
    apply the S1 loser-filter, size the unit under the no-leverage cash cap, walk the trade
    to its 2N-stop or opposite-extreme exit (pyramiding in between if enabled), record it,
    and resume scanning after the exit.

    Args:
        bars: One symbol's canonical-schema, hygiene-clean, corporate-action **adjusted**
            bars (spec §1: adjusted series only — a raw split spike is a false breakout).
        config: The frozen Turtle contract (:class:`TurtleConfig`).
        equity: Account equity (INR, > 0) the 1%-risk unit is measured against.
        cash: Cash available to deploy (INR, >= 0); the no-leverage cap on every unit.

    Returns:
        A :class:`TurtleTrades` with the trade log, the signed-share position path, and the
        ``label_times`` for CPCV.

    Raises:
        SignalInputError: If ``equity`` <= 0 or ``cash`` < 0.
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    if equity <= 0:
        raise SignalInputError(f"equity must be > 0, got {equity!r}")
    if cash < 0:
        raise SignalInputError(f"cash must be >= 0, got {cash!r}")

    frame = serde.sort_bars(serde.ensure_bars_schema(bars))
    times = pd.DatetimeIndex(frame[serde.TIME_COLUMN])
    n = len(frame)
    if n == 0:
        empty_pos = pd.Series(np.zeros(0, dtype="int64"), index=times, name="position")
        return TurtleTrades(trades=_empty_trades(), positions=empty_pos)

    high = frame["high"].to_numpy(dtype="float64")
    low = frame["low"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    open_ = frame["open"].to_numpy(dtype="float64")
    entry_high = donchian_high(frame, config.entry_window).to_numpy(dtype="float64")
    entry_low = donchian_low(frame, config.entry_window).to_numpy(dtype="float64")
    exit_high = donchian_high(frame, config.exit_window).to_numpy(dtype="float64")
    exit_low = donchian_low(frame, config.exit_window).to_numpy(dtype="float64")
    n_atr = wilder_atr(frame, config.atr_window).to_numpy(dtype="float64")
    pos_arr = np.zeros(n, dtype="int64")  # the signed-share hold path, filled per taken trade

    def _resolve(start: int, direction: int, max_units: int) -> _Book:
        """Walk a breakout from bar ``start`` to its exit; size up to ``max_units`` units."""
        atr_n = float(n_atr[start])
        entry_level = float(entry_high[start] if direction > 0 else entry_low[start])
        first = unit_size(
            equity=equity,
            atr_n=atr_n,
            price=entry_level,
            cash_available=cash,
            risk_fraction=config.risk_fraction,
        )
        remaining_cash = cash - first.shares * entry_level
        total_shares = first.shares
        notional = first.shares * entry_level
        cash_bound = first.cash_bound
        units = 1
        stop = initial_stop(
            entry_price=entry_level,
            atr_n=atr_n,
            direction=direction,
            stop_multiple=config.stop_multiple,
        )
        next_add = entry_level + direction * config.pyramid_step_fraction * atr_n
        steps: list[tuple[int, int]] = [(start, total_shares)]

        exit_index: int | None = None
        exit_price = float("nan")
        reason = END
        j = start + 1
        while j < n:
            # Exit checks FIRST (conservative on a bar that both extends and reverses).
            if direction > 0:
                if low[j] <= stop:
                    exit_index, exit_price, reason = j, stop, STOP
                    break
                if not math.isnan(exit_low[j]) and low[j] <= exit_low[j]:
                    exit_index, exit_price, reason = j, float(exit_low[j]), DONCHIAN_EXIT
                    break
            else:
                if high[j] >= stop:
                    exit_index, exit_price, reason = j, stop, STOP
                    break
                if not math.isnan(exit_high[j]) and high[j] >= exit_high[j]:
                    exit_index, exit_price, reason = j, float(exit_high[j]), DONCHIAN_EXIT
                    break
            # Pyramiding: add a unit each further +step·N favorable, trailing the stop to
            # 2N from the newest entry. Degrade gracefully when cash is exhausted.
            while units < max_units:
                favorable = high[j] if direction > 0 else low[j]
                reached = favorable >= next_add if direction > 0 else favorable <= next_add
                if not reached:
                    break
                add = unit_size(
                    equity=equity,
                    atr_n=atr_n,
                    price=next_add,
                    cash_available=remaining_cash,
                    risk_fraction=config.risk_fraction,
                )
                if add.shares <= 0:
                    cash_bound = True  # cash exhausted before the vol unit — stop adding
                    break
                total_shares += add.shares
                remaining_cash -= add.shares * next_add
                notional += add.shares * next_add
                cash_bound = cash_bound or add.cash_bound
                units += 1
                stop = initial_stop(
                    entry_price=next_add,
                    atr_n=atr_n,
                    direction=direction,
                    stop_multiple=config.stop_multiple,
                )
                next_add = next_add + direction * config.pyramid_step_fraction * atr_n
                steps.append((j, total_shares))
            j += 1

        if exit_index is None:  # never exited — mark out at the last close
            exit_index, exit_price, reason = n - 1, float(close[n - 1]), END
        avg_entry = notional / total_shares if total_shares > 0 else entry_level
        return _Book(
            exit_index=exit_index,
            exit_price=exit_price,
            reason=reason,
            total_shares=total_shares,
            units=units,
            avg_entry=avg_entry,
            cash_bound=cash_bound,
            steps=steps,
            _sign=direction,
        )

    rows: list[dict[str, object]] = []
    index: list[pd.Timestamp] = []
    last_breakout_winner: bool | None = None
    i = 0
    while i < n:
        if math.isnan(entry_high[i]) or math.isnan(n_atr[i]) or n_atr[i] <= 0:
            i += 1
            continue
        direction = _detect_breakout(i, high, low, open_, close, entry_high, entry_low, config)
        if direction == 0:
            i += 1
            continue

        shadow = _resolve(i, direction, max_units=1)  # single-unit — the filter's signal
        take = not (config.use_loser_filter and last_breakout_winner is True)
        last_breakout_winner = shadow.winner

        if not take:
            i = shadow.exit_index + 1
            continue

        book = shadow if not config.pyramiding else _resolve(i, direction, config.max_units)
        _write_positions(pos_arr, book, direction)
        index.append(times[i])
        rows.append(
            {
                EXIT_TIME: times[book.exit_index],
                DIRECTION: direction,
                UNITS: book.units,
                SHARES: book.total_shares,
                ENTRY_PRICE: book.avg_entry,
                EXIT_PRICE: book.exit_price,
                EXIT_REASON: book.reason,
                RET: (book.exit_price / book.avg_entry - 1.0) * direction,
                CASH_BOUND: book.cash_bound,
            }
        )
        i = book.exit_index + 1

    positions = pd.Series(pos_arr, index=times, name="position")
    return TurtleTrades(trades=_build_trades(rows, index), positions=positions)


def _detect_breakout(
    i: int,
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    open_: npt.NDArray[np.float64],
    close: npt.NDArray[np.float64],
    entry_high: npt.NDArray[np.float64],
    entry_low: npt.NDArray[np.float64],
    config: TurtleConfig,
) -> int:
    """Return +1 (long breakout), -1 (short breakout), or 0 (none) at bar ``i``.

    Long when the bar's high reaches the prior Donchian high; short (only where shorting is
    allowed) when the low reaches the prior Donchian low. An outside bar that breaks both
    ways is resolved by the bar's own net direction (sign of close-open) — a rare tie broken
    deterministically rather than silently.
    """
    long_break = high[i] >= entry_high[i]
    short_break = config.allow_short and not math.isnan(entry_low[i]) and low[i] <= entry_low[i]
    if long_break and short_break:
        return 1 if close[i] >= open_[i] else -1
    if long_break:
        return 1
    if short_break:
        return -1
    return 0


def _write_positions(pos_arr: npt.NDArray[np.int64], book: _Book, direction: int) -> None:
    """Write the signed-share hold path for a taken trade into ``pos_arr`` in place.

    Between each size step the target is the running signed share count; at the exit
    decision bar the target returns to 0 (the exit is decided there and filled next open).
    """
    steps = book.steps
    for step_idx, (bar, shares) in enumerate(steps):
        end = steps[step_idx + 1][0] if step_idx + 1 < len(steps) else book.exit_index
        pos_arr[bar:end] = direction * shares
    pos_arr[book.exit_index] = 0


def _empty_trades() -> pd.DataFrame:
    """The well-typed empty trade frame (a tz-aware entry index, the standard columns)."""
    index = pd.DatetimeIndex([], name=ENTRY_TIME)
    return pd.DataFrame(
        {
            EXIT_TIME: pd.Series(dtype="datetime64[ns, Asia/Kolkata]"),
            DIRECTION: pd.Series(dtype="int64"),
            UNITS: pd.Series(dtype="int64"),
            SHARES: pd.Series(dtype="int64"),
            ENTRY_PRICE: pd.Series(dtype="float64"),
            EXIT_PRICE: pd.Series(dtype="float64"),
            EXIT_REASON: pd.Series(dtype="object"),
            RET: pd.Series(dtype="float64"),
            CASH_BOUND: pd.Series(dtype="bool"),
        },
        index=index,
    )


def _build_trades(rows: list[dict[str, object]], index: list[pd.Timestamp]) -> pd.DataFrame:
    """Assemble the trade frame from accumulated rows (empty-safe)."""
    if not rows:
        return _empty_trades()
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name=ENTRY_TIME))
    return frame.loc[:, list(_TRADE_COLUMNS)]
