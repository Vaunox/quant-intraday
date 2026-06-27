#!/usr/bin/env python
"""Phase 3X.8 — pre-committed gate run for the cross-sectional factor strategy.

Ties the whole Phase-3X pipeline together end-to-end:

    factors (P3X.2) -> sector-neutral composite (P3X.4) -> forward-return labels (P3X.3)
    -> top-quantile book + caps (P3X.7) -> CNC monthly backtest (P3X.6)
    -> active-IR CPCV + DSR (P3X.5) -> seven-point benchmark-relative kill-gate (P3X.8)

The default run is on **synthetic** GBM data — an INTEGRATION PROOF that the pipeline assembles and
the gate emits a verdict (the number itself is noise). ``--validated`` runs the **real** verdict on
the survivorship-free bhavcopy panel (P3X.1b-e) over a liquidity-defined top-N universe (the
operator's chosen Nifty-500-like proxy; see ``docs/iteration_log/p3x_data_sourcing.md``); it needs
``data/nifty_panel/`` built first and never fabricates a number from absent data.

Usage::

    python scripts/run_factor_gate.py                 # synthetic integration run
    python scripts/run_factor_gate.py --no-mlflow
    python scripts/build_nifty500_panel.py            # build the real panel first, then:
    python scripts/run_factor_gate.py --validated     # real liquidity-universe verdict
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
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
    back_adjust_for_splits,
    evaluate_factor_gate,
    liquidity_universe,
    load_sector_map,
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
VALIDATED_TOP_N = 500  # liquidity-universe size for the --validated run (Nifty-500-like)
_PANEL_DIR = _REPO_ROOT / "data" / "nifty_panel"
_NIFTY500_LIST_URL = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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
    """Run on synthetic GBM data (integration proof; the number is noise by construction)."""
    print("Phase 3X.8 — gate run (SYNTHETIC integration; the number is noise by construction).")
    bars_by_symbol, sectors = _synthetic_universe(seed=7)
    return _run_pipeline(
        bars_by_symbol,
        sectors,
        eligibility=None,
        mode="synthetic",
        use_mlflow=use_mlflow,
        extra_params={},
    )


def run_validated(use_mlflow: bool = True, *, top_n: int = VALIDATED_TOP_N) -> bool:
    """Run on the real survivorship-free bhavcopy panel over a liquidity-defined top-N universe."""
    close = pd.read_parquet(_PANEL_DIR / "close.parquet")
    volume = pd.read_parquet(_PANEL_DIR / "volume.parquet")
    value = pd.read_parquet(_PANEL_DIR / "value.parquet")
    print(
        f"Phase 3X — VALIDATED gate run (survivorship-free bhavcopy, liquidity top-{top_n}).\n"
        f"  panel: {close.shape[0]} dates x {close.shape[1]} names"
    )

    ca_path = _PANEL_DIR / "corporate_actions.csv"
    if ca_path.exists():
        ca = pd.read_csv(ca_path)
        events = list(zip(ca["symbol"].astype(str), ca["ex_date"].astype(str), strict=True))
        close, volume = back_adjust_for_splits(close, volume, events)
        print(f"  applied {len(events)} split/bonus back-adjustments")

    rebalance_dates = month_end_rebalance_dates(pd.DatetimeIndex(close.index))
    eligibility = liquidity_universe(
        value, rebalance_dates, top_n=top_n, adv_window=VOL_WINDOW, min_history_sessions=LOOKBACK
    )
    ever_eligible = [c for c in eligibility.columns if bool(eligibility[c].any())]
    close, volume, eligibility = (
        close[ever_eligible],
        volume[ever_eligible],
        eligibility[ever_eligible],
    )
    print(f"  ever-eligible names: {len(ever_eligible)}")

    sectors = _load_sectors(ever_eligible)
    bars_by_symbol = {
        sym: pd.DataFrame({"close": close[sym], "volume": volume[sym]}) for sym in ever_eligible
    }
    return _run_pipeline(
        bars_by_symbol,
        sectors,
        eligibility=eligibility,
        mode=f"validated-liquidity-top{top_n}",
        use_mlflow=use_mlflow,
        extra_params={"top_n": float(top_n), "ever_eligible": float(len(ever_eligible))},
    )


def _run_pipeline(
    bars_by_symbol: dict[str, pd.DataFrame],
    sectors: dict[str, str],
    *,
    eligibility: pd.DataFrame | None,
    mode: str,
    use_mlflow: bool,
    extra_params: dict[str, float],
) -> bool:
    """The shared assembly: factors -> composite -> book -> CNC backtest -> active CPCV -> gate."""
    close_panel = _panel(bars_by_symbol, "close")
    market_returns = close_panel.pct_change(fill_method=None).mean(axis=1)  # equal-weight proxy
    rebalance_dates = month_end_rebalance_dates(pd.DatetimeIndex(close_panel.index))

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
        eligible = scores.notna() & (vols > 0)  # composite and a positive vol both warmed up
        if eligibility is not None and date in eligibility.index:
            in_universe = cast("pd.Series", eligibility.loc[date]).reindex(scores.index)
            eligible = eligible & in_universe.fillna(False).astype(bool)
        if int(eligible.sum()) < MIN_NAMES:  # skip warm-up / thin rebalances
            continue
        books[date] = construct_book(
            scores.where(eligible),
            sectors,
            quantile=QUANTILE,
            volatility=vols,
            method="inverse_vol",
        )
    if not books:
        raise RuntimeError("no rebalance had enough warmed-up, eligible names to build a book")
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
    benchmark = _benchmark_returns(period_returns, eligibility, reb)
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
        robustness_passed=False,  # robustness battery not run in this baseline pass
    )
    verdict = evaluate_factor_gate(metrics, _load_kill_gate())

    print(
        f"  rebalances: {len(reb)} | universe: {len(close_panel.columns)} | "
        f"active IR {evaluation.annualised_ir:+.3f} | DSR {metrics.dsr:.3f} | "
        f"dedup t {evaluation.dedup_tstat:.2f} | max sector wt {max_sector_weight:.3f}"
    )
    print(verdict.render())
    if use_mlflow:
        _log_mlflow(metrics, verdict, mode=mode, extra_params=extra_params)
    return verdict.passed


def _benchmark_returns(
    period_returns: pd.DataFrame, eligibility: pd.DataFrame | None, reb: pd.DatetimeIndex
) -> pd.Series:
    """Equal-weight return of the eligible universe each month (the active-return benchmark)."""
    if eligibility is None:
        return period_returns.mean(axis=1)
    mask = eligibility.reindex(index=reb, columns=period_returns.columns).fillna(False)
    return period_returns.where(mask.astype(bool)).mean(axis=1)


def _load_sectors(symbols: list[str]) -> dict[str, str]:
    """Fetch the current Nifty-500 ``symbol -> sector`` map; names not on the list get ``Other``."""
    dest = _PANEL_DIR / "ind_nifty500list.csv"
    mapping: dict[str, str] = {}
    try:
        if not dest.exists():
            request = urllib.request.Request(
                _NIFTY500_LIST_URL,
                headers={"User-Agent": _USER_AGENT, "Referer": "https://www.niftyindices.com/"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                dest.write_bytes(response.read())
        mapping = load_sector_map(str(dest))
    except Exception as exc:  # sector map is best-effort; fall back to "Other"
        print(f"  [WARN] sector fetch failed ({exc}); using 'Other' for all names")
    return {sym: mapping.get(sym, "Other") for sym in symbols}


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


def _log_mlflow(
    metrics: GateMetrics,
    verdict: FactorGateVerdict,
    *,
    mode: str,
    extra_params: dict[str, float],
) -> None:
    try:
        import mlflow

        mlflow.set_tracking_uri(
            "sqlite:///C:/Users/vinay/Documents/quant-intraday/mlruns/mlflow.db"
        )
        mlflow.set_experiment("p3x-factor-gate")
        with mlflow.start_run(run_name=f"p3x-{mode}") as run:
            mlflow.log_params({"mode": mode, "n_trials": BASELINE_N_TRIALS, **extra_params})
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
    """Run the synthetic integration gate, or the validated run on the real bhavcopy panel."""
    parser = argparse.ArgumentParser(description="Phase 3X factor gate run.")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument(
        "--validated",
        action="store_true",
        help="run on the real survivorship-free bhavcopy panel (requires data/nifty_panel/)",
    )
    parser.add_argument("--top-n", type=int, default=VALIDATED_TOP_N)
    args = parser.parse_args()

    if args.validated:
        if not (_PANEL_DIR / "close.parquet").exists():
            print(
                f"VALIDATED run needs the panel at {_PANEL_DIR}. Build it first:\n"
                "  python scripts/build_nifty500_panel.py\n"
                "  python scripts/fetch_corporate_actions.py"
            )
            return 2
        run_validated(use_mlflow=not args.no_mlflow, top_n=args.top_n)
        return 0

    run_synthetic(use_mlflow=not args.no_mlflow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
