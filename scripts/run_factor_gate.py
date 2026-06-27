#!/usr/bin/env python
"""Phase 3X.8 — pre-committed gate run for the cross-sectional factor strategy.

Ties the whole Phase-3X pipeline together end-to-end:

    factors (P3X.2) -> sector-neutral composite (P3X.4) -> forward-return labels (P3X.3)
    -> top-quantile book + caps (P3X.7) -> CNC monthly backtest (P3X.6)
    -> active-IR CPCV + DSR (P3X.5) -> seven-point benchmark-relative kill-gate (P3X.8)

It runs on **synthetic** GBM data (``--synthetic``, the default) as an INTEGRATION PROOF — it
demonstrates the pipeline assembles and the gate emits a verdict; the number itself is noise. The
**real** Nifty-500 verdict (``--validated``) is gated on the P3X.1 data decision (survivorship-
correct membership + delisted-name history); see ``docs/iteration_log/p3x_data_sourcing.md``. This
script never fabricates the real number.

Usage::

    python scripts/run_factor_gate.py                 # synthetic integration run
    python scripts/run_factor_gate.py --no-mlflow
    python scripts/run_factor_gate.py --validated     # raises until P3X.1 data exists
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# ruff: noqa: E402  (the quant.* imports follow the sys.path bootstrap above — research entry point)
from quant.capital.portfolio.construction import construct_book
from quant.core.calendar import IST
from quant.research.factors import (
    EqualWeightComposite,
    FactorGateVerdict,
    GateMetrics,
    evaluate_factor_gate,
)
from quant.research.factors.price_factors import (
    amihud_illiquidity,
    low_volatility,
    momentum_12_1,
    residual_momentum,
    short_term_reversal,
)
from quant.research.labeling.cross_sectional import (
    build_cross_sectional_labels,
    month_end_rebalance_dates,
)
from quant.research.validation.active import evaluate_active_under_cpcv
from quant.research.validation.cpcv import CombinatorialPurgedCV
from quant.research.validation.monthly_backtest import CncCostModel, monthly_backtest

N_SYMBOLS = 60
N_DAYS = 1300
N_SECTORS = 8
LOOKBACK = 252
SKIP = 21
VOL_WINDOW = 126
HORIZON = 21
QUANTILE = 0.2
NO_TRADE_BAND = 0.25
CPCV_GROUPS = 4
CPCV_TEST_GROUPS = 2
CPCV_EMBARGO = 0.02
BASELINE_N_TRIALS = 1  # the zero-parameter baseline is one configuration
MIN_NAMES = 20  # skip warm-up rebalances until this many names have a defined composite


def _synthetic_universe(seed: int) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Generate ``N_SYMBOLS`` GBM daily-bar frames + a sector map (no real signal)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=N_DAYS, freq="B", tz=IST)
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    sectors: dict[str, str] = {}
    for i in range(N_SYMBOLS):
        symbol = f"SYM{i:03d}"
        sectors[symbol] = f"SEC{i % N_SECTORS}"
        daily = rng.normal(0.0003, 0.018, size=N_DAYS)
        close = 100.0 * np.exp(np.cumsum(daily))
        opens = np.concatenate(([close[0]], close[:-1]))
        high = np.maximum(opens, close) * (1.0 + np.abs(rng.normal(0, 0.004, N_DAYS)))
        low = np.minimum(opens, close) * (1.0 - np.abs(rng.normal(0, 0.004, N_DAYS)))
        volume = rng.integers(50_000, 500_000, N_DAYS).astype("int64")
        bars_by_symbol[symbol] = pd.DataFrame(
            {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
            index=dates,  # DatetimeIndex so factor outputs align with the price panel
        )
    return bars_by_symbol, sectors


def _panel(bars_by_symbol: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    """Wide ``date x symbol`` panel of ``column`` from per-symbol bar frames."""
    return pd.DataFrame({sym: bars[column] for sym, bars in bars_by_symbol.items()})


def _factor_panels(
    bars_by_symbol: dict[str, pd.DataFrame], market_returns: pd.Series
) -> dict[str, pd.DataFrame]:
    """Compute each price factor for every symbol → ``{factor -> (date x symbol) panel}``."""
    return {
        "momentum": pd.DataFrame(
            {s: momentum_12_1(b, lookback=LOOKBACK, skip=SKIP) for s, b in bars_by_symbol.items()}
        ),
        "reversal": pd.DataFrame(
            {s: short_term_reversal(b, window=SKIP) for s, b in bars_by_symbol.items()}
        ),
        "low_vol": pd.DataFrame(
            {s: low_volatility(b, window=VOL_WINDOW) for s, b in bars_by_symbol.items()}
        ),
        "amihud": pd.DataFrame(
            {s: amihud_illiquidity(b, window=VOL_WINDOW) for s, b in bars_by_symbol.items()}
        ),
        "residual_mom": pd.DataFrame(
            {
                s: residual_momentum(
                    b, market_returns, lookback=LOOKBACK, skip=SKIP, beta_window=VOL_WINDOW
                )
                for s, b in bars_by_symbol.items()
            }
        ),
    }


def run_synthetic(use_mlflow: bool = True) -> bool:
    """Run the full pipeline on synthetic data; print + return the gate verdict (PASS bool)."""
    print("Phase 3X.8 — gate run (SYNTHETIC integration; the number is noise by construction).")
    bars_by_symbol, sectors = _synthetic_universe(seed=7)
    close_panel = _panel(bars_by_symbol, "close")
    market_returns = close_panel.pct_change(fill_method=None).mean(axis=1)  # equal-weight proxy
    trading_dates = pd.DatetimeIndex(close_panel.index)

    rebalance_dates = month_end_rebalance_dates(trading_dates)
    factor_panels = _factor_panels(bars_by_symbol, market_returns)
    at_reb = {name: panel.reindex(rebalance_dates) for name, panel in factor_panels.items()}
    composite = EqualWeightComposite(sectors).combine(at_reb)

    labels = build_cross_sectional_labels(close_panel, rebalance_dates, horizon=HORIZON)
    vol_panel = close_panel.pct_change(fill_method=None).rolling(VOL_WINDOW).std()
    composite_full = composite.reindex(columns=close_panel.columns)

    books: dict[pd.Timestamp, pd.Series] = {}
    for date in labels.rebalance_dates:
        scores = cast("pd.Series", composite_full.loc[date])
        vols = cast("pd.Series", vol_panel.loc[date])
        eligible = scores.notna() & (vols > 0)  # both the composite and a positive vol warmed up
        if int(eligible.sum()) < MIN_NAMES:  # skip warm-up rebalances
            continue
        books[date] = construct_book(
            scores.where(eligible),
            sectors,
            quantile=QUANTILE,
            volatility=vols,
            method="inverse_vol",
        )
    if not books:
        raise RuntimeError("no rebalance had enough warmed-up names to build a book")
    reb = pd.DatetimeIndex(sorted(books))
    target_weights = (
        pd.DataFrame(books).T.reindex(index=reb, columns=close_panel.columns).fillna(0.0)
    )
    period_returns = labels.forward_return.reindex(index=reb, columns=close_panel.columns)

    cost_model = CncCostModel()
    backtest = monthly_backtest(
        target_weights,
        period_returns.fillna(0.0),
        cost_model=cost_model,
        no_trade_band=NO_TRADE_BAND,
    )
    benchmark = period_returns.mean(axis=1)
    active = (backtest.net_return - benchmark).rename("active")
    active_values = active.to_numpy(dtype="float64")
    label_times = labels.label_times.loc[reb]

    def backtest_fn(train: npt.NDArray[np.intp], test: npt.NDArray[np.intp]) -> pd.Series:
        # Zero-parameter baseline: the active return per rebalance is precomputed (no fit).
        return pd.Series(active_values[test], index=label_times.index[test])

    cpcv = CombinatorialPurgedCV(CPCV_GROUPS, CPCV_TEST_GROUPS, embargo_pct=CPCV_EMBARGO)
    evaluation = evaluate_active_under_cpcv(label_times, backtest_fn, cpcv)

    max_sector_weight = _max_sector_weight(target_weights, sectors)
    metrics = GateMetrics(
        active_ir=evaluation.annualised_ir,
        dsr=evaluation.deflated_sharpe(n_trials=BASELINE_N_TRIALS),
        fraction_negative=evaluation.fraction_negative,
        worst_path_ir=evaluation.worst_path_ir,
        pbo=None,  # PBO needs the multi-config panel (computed when ML configs are tried)
        max_sector_weight=max_sector_weight,
        max_single_factor_share=None,  # factor attribution is a follow-on
        robustness_passed=False,  # battery not run on the synthetic integration
    )
    kill_gate = _load_kill_gate()
    verdict = evaluate_factor_gate(metrics, kill_gate)

    print(
        f"  rebalances: {len(reb)} | universe: {len(close_panel.columns)} | "
        f"active IR {evaluation.annualised_ir:+.3f} | DSR {metrics.dsr:.3f} | "
        f"dedup t {evaluation.dedup_tstat:.2f} | max sector wt {max_sector_weight:.3f}"
    )
    print(verdict.render())
    if use_mlflow:
        _log_mlflow(metrics, verdict)
    return verdict.passed


def _max_sector_weight(target_weights: pd.DataFrame, sectors: dict[str, str]) -> float:
    """The largest single-sector total weight across all rebalances."""
    sector_of = pd.Series(
        [sectors[s] for s in target_weights.columns], index=target_weights.columns
    )
    by_sector = target_weights.T.groupby(sector_of).sum().T  # (rebalance x sector)
    return float(by_sector.to_numpy().max()) if by_sector.size else 0.0


def _load_kill_gate() -> dict[str, float]:
    """Load the pre-committed kill-gate thresholds from config/factor_default.yaml."""
    path = _REPO_ROOT / "config" / "factor_default.yaml"
    with path.open() as handle:
        config = yaml.safe_load(handle)
    return {k: float(v) for k, v in config["kill_gate"].items() if isinstance(v, int | float)}


def _log_mlflow(metrics: GateMetrics, verdict: FactorGateVerdict) -> None:
    try:
        import mlflow

        mlflow.set_tracking_uri(
            "sqlite:///C:/Users/vinay/Documents/quant-intraday/mlruns/mlflow.db"
        )
        mlflow.set_experiment("p3x-factor-gate")
        with mlflow.start_run(run_name="p3x8-synthetic-integration") as run:
            mlflow.log_params({"mode": "synthetic", "n_trials": BASELINE_N_TRIALS})
            mlflow.log_metrics(
                {
                    "active_ir": metrics.active_ir,
                    "dsr": metrics.dsr,
                    "fraction_negative": metrics.fraction_negative,
                    "worst_path_ir": metrics.worst_path_ir,
                    "max_sector_weight": metrics.max_sector_weight or 0.0,
                    "gate_passed": float(verdict.passed),
                }
            )
            run_id = run.info.run_id
        print(f"  logged to MLflow 'p3x-factor-gate' run_id={run_id}")
    except Exception as exc:
        print(f"  [WARN] MLflow logging failed: {exc}")


def main() -> int:
    """Run the synthetic integration gate, or refuse the validated run until P3X.1 data exists."""
    parser = argparse.ArgumentParser(description="Phase 3X.8 factor gate run.")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--validated", action="store_true", help="run on real Nifty-500 data")
    args = parser.parse_args()

    if args.validated:
        print(
            "VALIDATED run is gated on P3X.1 — a survivorship-correct Nifty-500 panel "
            "(membership + delisted-name history) does not yet exist. Settle the data decision "
            "in docs/iteration_log/p3x_data_sourcing.md first. Refusing to fabricate a number."
        )
        return 2

    run_synthetic(use_mlflow=not args.no_mlflow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
