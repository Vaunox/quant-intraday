"""Portfolio construction for the monthly factor book (Phase 3X.7 — Capital Layer).

Turns a per-name composite score (P3X.4) into a long-only book, conservatively and cheaply:
**top-quantile selection → weighting (inverse-vol, or HRP) → sector + per-name caps**. The
no-trade band and costing live in the monthly backtester (P3X.6); sizing (the vol-target scalar)
is in :mod:`quant.capital.sizing`.

Inverse-vol is the default weighting; **HRP** (Hierarchical Risk Parity, López de Prado) is the
graduation once the book is wide enough to validate it OOS — it never inverts the covariance, so
it runs on a singular/degenerate matrix without error. Caps that bind leave residual cash (the
book sums to ≤ 1) rather than forcing capital back into the same names — the conservative choice.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage  # type: ignore[import-untyped]
from scipy.spatial.distance import squareform  # type: ignore[import-untyped]

from quant.capital.errors import CapitalError


def select_top_quantile(scores: pd.Series, *, quantile: float) -> pd.Index:
    """Return the names in the top ``quantile`` fraction by score (within the non-NaN universe).

    Raises:
        CapitalError: If ``quantile`` is not in ``(0, 1]``.
    """
    if not 0.0 < quantile <= 1.0:
        raise CapitalError(f"quantile must be in (0, 1], got {quantile}")
    valid = scores.dropna()
    count = max(1, round(quantile * len(valid)))
    return valid.nlargest(count).index


def inverse_vol_weights(volatility: pd.Series) -> pd.Series:
    """Return inverse-volatility weights over ``volatility`` (positive vols), summing to 1.

    Raises:
        CapitalError: If no name has a positive, finite volatility.
    """
    inv = 1.0 / volatility.where(volatility > 0)
    total = float(inv.sum())
    if not np.isfinite(total) or total <= 0:
        raise CapitalError("no positive volatilities to weight by")
    normalized: pd.Series = (inv / total).fillna(0.0)
    return normalized.rename("weight")


def hrp_weights(cov: pd.DataFrame) -> pd.Series:
    """Return Hierarchical Risk Parity weights from a covariance matrix (López de Prado).

    Quasi-diagonalises via single-linkage clustering of the correlation distance, then allocates
    by recursive bisection using each cluster's inverse-variance. Uses only the covariance's
    diagonal for the cluster variance, so it is robust to a singular/degenerate ``cov``.

    Raises:
        CapitalError: If ``cov`` is not square.
    """
    symbols = list(cov.columns)
    if cov.shape[0] != cov.shape[1] or list(cov.index) != symbols:
        raise CapitalError("cov must be a square, symbol-aligned covariance matrix")
    matrix = cov.to_numpy(dtype="float64")
    if matrix.shape[0] == 1:
        return pd.Series([1.0], index=symbols, name="weight")

    condensed = squareform(_correlation_distance(matrix), checks=False)
    order = list(leaves_list(linkage(condensed, "single")))
    weights = np.ones(matrix.shape[0], dtype="float64")
    clusters: list[list[int]] = [order]
    while clusters:
        nxt: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            half = len(cluster) // 2
            left, right = cluster[:half], cluster[half:]
            var_left = _cluster_variance(matrix, left)
            var_right = _cluster_variance(matrix, right)
            total = var_left + var_right
            alpha = 1.0 - var_left / total if total > 0 else 0.5
            for i in left:
                weights[i] *= alpha
            for i in right:
                weights[i] *= 1.0 - alpha
            nxt += [left, right]
        clusters = nxt
    return pd.Series(weights / weights.sum(), index=symbols, name="weight")


def apply_caps(
    weights: pd.Series, sectors: dict[str, str], *, sector_cap: float, name_cap: float
) -> pd.Series:
    """Cap each name at ``name_cap`` and each sector's total at ``sector_cap``.

    Per-name excess and over-cap sector excess are dropped to cash (the book may sum to < 1 when
    caps bind) rather than redistributed into the same names — conservative and exact in one pass.

    Raises:
        CapitalError: If a weighted name has no sector, or a cap is not in ``(0, 1]``.
    """
    if not 0.0 < name_cap <= 1.0 or not 0.0 < sector_cap <= 1.0:
        raise CapitalError("caps must be in (0, 1]")
    missing = [s for s in weights.index if s not in sectors]
    if missing:
        raise CapitalError(f"names missing a sector mapping: {sorted(missing)}")
    capped = weights.clip(upper=name_cap)
    sector_of = pd.Series([sectors[s] for s in capped.index], index=capped.index)
    sector_total = capped.groupby(sector_of).transform("sum")
    scale = (sector_cap / sector_total.where(sector_total > 0)).clip(upper=1.0).fillna(1.0)
    return (capped * scale).rename("weight")


def construct_book(
    scores: pd.Series,
    sectors: dict[str, str],
    *,
    quantile: float = 0.2,
    sector_cap: float = 0.25,
    name_cap: float = 0.05,
    volatility: pd.Series | None = None,
    cov: pd.DataFrame | None = None,
    method: str = "inverse_vol",
) -> pd.Series:
    """Build a long-only book for one rebalance: select top-quantile, weight, cap.

    Args:
        scores: composite score per symbol (NaN = out of the point-in-time universe).
        sectors: ``symbol -> sector`` for the sector cap.
        quantile: top fraction of the universe to hold.
        sector_cap: maximum total weight per sector.
        name_cap: maximum weight per name.
        volatility: per-symbol vol (required for ``method="inverse_vol"``).
        cov: covariance of the selected names (required for ``method="hrp"``).
        method: ``"inverse_vol"`` (default) or ``"hrp"``.

    Returns:
        A weight Series over the full ``scores`` index (0 for unselected/capped-to-cash names).

    Raises:
        CapitalError: On a bad method or a missing volatility/cov for the chosen method.
    """
    selected = select_top_quantile(scores, quantile=quantile)
    if method == "inverse_vol":
        if volatility is None:
            raise CapitalError("method='inverse_vol' requires volatility")
        raw = inverse_vol_weights(volatility.reindex(selected))
    elif method == "hrp":
        if cov is None:
            raise CapitalError("method='hrp' requires cov")
        raw = hrp_weights(cov.reindex(index=selected, columns=selected))
    else:
        raise CapitalError(f"unknown method {method!r} (expected 'inverse_vol' or 'hrp')")

    capped = apply_caps(raw, sectors, sector_cap=sector_cap, name_cap=name_cap)
    return capped.reindex(scores.index).fillna(0.0).rename("weight")


def _correlation_distance(cov: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return the correlation-distance matrix ``sqrt((1 - corr) / 2)`` from a covariance matrix."""
    std = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    std_safe = np.where(std > 0, std, 1.0)
    corr = np.clip(cov / np.outer(std_safe, std_safe), -1.0, 1.0)
    distance: npt.NDArray[np.float64] = np.sqrt(np.maximum((1.0 - corr) / 2.0, 0.0))
    return distance


def _cluster_variance(cov: npt.NDArray[np.float64], items: list[int]) -> float:
    """Return a cluster's inverse-variance-weighted variance (uses only the diagonal for IVP)."""
    sub = cov[np.ix_(items, items)]
    diag = np.diag(sub)
    ivp = 1.0 / np.where(diag > 0, diag, 1e-12)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)
